"""End-to-end tests. Run:  python -m unittest -v test_app"""
import importlib
import os
import re
import tempfile
import unittest

_tmp = tempfile.mkdtemp()
os.environ['ORDERFOOD_DB'] = os.path.join(_tmp, 'test.db')
os.environ['ORDERFOOD_WALLET'] = os.path.join(_tmp, 'wallet.json')
os.environ['ORDERFOOD_SECRET_KEY'] = 'test-key'
app_module = importlib.import_module('orderfood_app')
app = app_module.app
wallet = app_module.wallet_service


def db():
    import sqlite3
    c = sqlite3.connect(app.config['DATABASE'])
    c.row_factory = sqlite3.Row
    return c


class Client:
    def __init__(self):
        self.c = app.test_client()

    def token(self):
        html = self.c.get('/login').get_data(as_text=True)
        return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)

    def post(self, url, data=None, follow=True, csrf=True):
        data = dict(data or {})
        if csrf:
            data['_csrf'] = self.token()
        return self.c.post(url, data=data, follow_redirects=follow)

    def get(self, url, follow=True):
        return self.c.get(url, follow_redirects=follow)

    def login(self, email, password):
        r = self.post('/login', {'email': email, 'password': password})
        assert r.status_code == 200
        return r


def text(r):
    return r.get_data(as_text=True)


class OrderFoodTests(unittest.TestCase):
    def setUp(self):
        for f in (app.config['DATABASE'], app.config['WALLET_FILE']):
            if os.path.exists(f):
                os.remove(f)
        app_module.init_database()
        self.cust, self.rest, self.agent = Client(), Client(), Client()
        self.cust.login('customer@test.com', 'password123')
        self.rest.login('admin@test.com', 'admin123')
        self.agent.login('agent@test.com', 'agent123')

    def balance(self, key):
        return wallet.get_balance(key)['balance']

    def add(self, item_id, n=1):
        for _ in range(n):
            self.cust.post('/add_to_cart', {'item_id': item_id})

    # --- security ----------------------------------------------------------
    def test_csrf_blocks_post_without_token(self):
        r = self.cust.post('/add_to_cart', {'item_id': 1}, csrf=False)
        self.assertEqual(r.status_code, 400)

    def test_passwords_are_hashed_and_legacy_upgraded(self):
        c = db()
        pw = c.execute("SELECT password FROM users WHERE email='customer@test.com'").fetchone()[0]
        self.assertNotEqual(pw, 'password123')
        c.execute("UPDATE users SET password='plain1234' WHERE email='customer@test.com'")
        c.commit()
        Client().login('customer@test.com', 'plain1234')
        pw = c.execute("SELECT password FROM users WHERE email='customer@test.com'").fetchone()[0]
        self.assertTrue(pw.startswith(('scrypt:', 'pbkdf2:')))

    def test_roles_cannot_open_other_dashboards(self):
        r = self.cust.get('/dashboard/restaurant')
        self.assertIn('not available for your account type', text(r))
        r = self.rest.get('/')
        self.assertIn('Dashboard', text(r))
        self.assertIn('not available', text(r))

    def test_cart_prices_cannot_be_tampered(self):
        self.cust.post('/add_to_cart', {'item_id': 1, 'price': '0.01'})
        r = self.cust.get('/cart')
        self.assertIn('₹180', text(r))

    # --- ordering ----------------------------------------------------------
    def test_far_restaurant_cannot_be_ordered(self):
        r = self.cust.post('/add_to_cart', {'item_id': 16})       # Coastal Kitchen item (42 min)
        self.assertIn('too far', text(r))
        self.assertIn('Your cart is empty', text(self.cust.get('/cart')))

    def test_sold_out_item_rejected_and_replaceable(self):
        r = self.cust.post('/add_to_cart', {'item_id': 4})          # Chole Bhature, sold out
        self.assertIn('sold out', text(r))
        self.add(1)
        c = db()
        c.execute('UPDATE menu_items SET is_available = 0 WHERE id = 1')
        c.commit()
        page = text(self.cust.get('/cart'))
        self.assertIn('sold out', page)
        r = self.cust.post('/cart/replace', {'old_id': 1, 'new_id': 2})
        self.assertIn('Paneer Thali', text(r))
        r = self.cust.post('/cart/replace', {'old_id': 2, 'new_id': 7})   # different restaurant
        self.assertIn('not available', text(r))

    def test_multi_restaurant_checkout_and_full_lifecycle(self):
        self.add(1)               # Veg Thali 180 (Annapurna)
        self.add(5, 2)            # Masala Chaas 40 x2
        self.add(7)               # Chicken Biryani 240 (Spice Route)
        r = self.cust.get('/checkout')
        self.assertIn('₹500', text(r))
        token = re.search(r'name="token" value="([^"]+)"', text(r)).group(1)
        r = self.cust.post('/checkout', {'token': token, 'address': 'Hostel Block B'})
        self.assertIn('paid from your wallet', text(r))
        self.assertAlmostEqual(self.balance('1'), 650 - 500)
        c = db()
        orders = c.execute('SELECT * FROM orders ORDER BY id').fetchall()
        self.assertEqual(len(orders), 2)                          # one order per restaurant
        self.assertEqual(sorted(o['total_amount'] for o in orders), [240, 260])

        # replaying the same checkout form does not charge again
        r = self.cust.post('/checkout', {'token': token, 'address': 'Hostel Block B'})
        self.assertIn('already submitted', text(r))
        self.assertAlmostEqual(self.balance('1'), 150)

        # delivery gate: cannot place a new order while one is open
        self.add(3)
        self.assertIn('Finish your last order', text(self.cust.get('/checkout')))

    def test_burger_joint_end_to_end(self):
        item = db().execute('SELECT id, price FROM menu_items WHERE restaurant_id = 5 LIMIT 1').fetchone()
        self.add(item['id'], 2)
        total = item['price'] * 2
        token = re.search(r'name="token" value="([^"]+)"', text(self.cust.get('/checkout'))).group(1)
        self.cust.post('/checkout', {'token': token, 'address': 'Flat 4'})
        oid = db().execute('SELECT id FROM orders').fetchone()[0]

        # customer cannot confirm before delivery
        r = self.cust.post(f'/orders/{oid}/confirm')
        self.assertIn('cannot be confirmed yet', text(r))

        # restaurant: accept, request agent, mark ready
        self.assertIn('New order', text(self.rest.get('/notifications')))
        self.rest.post(f'/restaurant/order/{oid}/accept')
        self.rest.post(f'/restaurant/order/{oid}/request_agent')
        self.assertIn('New delivery request', text(self.agent.get('/notifications')))
        r = self.agent.get('/dashboard/delivery-agent')
        self.assertIn('The Burger Joint', text(r))

        # second agent races for the same request: only one wins
        other = Client()
        other.post('/register', {'name': 'Eve', 'email': 'eve@test.com', 'password': 'evepass123', 'role': 'delivery_agent'})
        other.login('eve@test.com', 'evepass123')
        did = db().execute('SELECT id FROM deliveries').fetchone()[0]
        self.assertIn('Delivery accepted', text(self.agent.post(f'/agent/request/{did}/accept')))
        self.assertIn('this request is gone', text(other.post(f'/agent/request/{did}/accept')))

        # pickup is blocked until restaurant marks ready
        self.agent.post('/agent/active/arrive')
        r = self.agent.post('/agent/active/pickup')
        self.assertIn('not ready yet', text(r))
        self.rest.post(f'/restaurant/order/{oid}/ready')
        self.agent.post('/agent/active/pickup')
        self.agent.post('/agent/active/onway')
        r = self.agent.post('/agent/active/delivered')
        self.assertIn('Delivery completed', text(r))

        self.assertEqual(db().execute('SELECT status FROM orders').fetchone()[0], 'delivered')
        self.assertAlmostEqual(self.balance('3'), 40)             # agent default: per order
        self.assertAlmostEqual(self.balance('rest_5'), total)     # restaurant paid on delivery

        # only now the customer may confirm; another customer cannot
        self.assertIn('Did you receive your last order', text(self.cust.get('/')))
        stranger = Client()
        stranger.post('/register', {'name': 'Sam', 'email': 'sam@test.com', 'password': 'sampass123'})
        stranger.login('sam@test.com', 'sampass123')
        self.assertIn('cannot be confirmed', text(stranger.post(f'/orders/{oid}/confirm')))
        self.assertIn('Thanks', text(self.cust.post(f'/orders/{oid}/confirm')))
        self.assertEqual(db().execute('SELECT status FROM orders').fetchone()[0], 'completed')

        # gate is open again
        self.add(item['id'])
        self.assertIn('Payment', text(self.cust.get('/checkout')))

    def test_reject_refunds_and_cancel_refunds(self):
        item = db().execute('SELECT id, price FROM menu_items WHERE restaurant_id = 5 LIMIT 1').fetchone()
        for action in ('reject', 'cancel'):
            self.add(item['id'])
            token = re.search(r'name="token" value="([^"]+)"', text(self.cust.get('/checkout'))).group(1)
            self.cust.post('/checkout', {'token': token, 'address': 'Flat 4'})
            oid = db().execute('SELECT MAX(id) FROM orders').fetchone()[0]
            self.assertAlmostEqual(self.balance('1'), 650 - item['price'])
            if action == 'reject':
                self.rest.post(f'/restaurant/order/{oid}/reject')
            else:
                self.cust.post(f'/orders/{oid}/cancel')
            self.assertAlmostEqual(self.balance('1'), 650)

    def test_partial_payment_failure_keeps_failed_items_in_cart(self):
        self.add(1, 3)            # 540 -> Annapurna (paid first)
        self.add(7, 1)            # 240 -> would exceed the 650 balance (540 + 240 = 780)
        token = re.search(r'name="token" value="([^"]+)"', text(self.cust.get('/checkout'))).group(1)
        r = self.cust.post('/checkout', {'token': token, 'address': 'Flat 4'})
        page = text(r)
        self.assertIn('did not go through', page)
        self.assertIn('Insufficient Funds', page)
        self.assertAlmostEqual(self.balance('1'), 110)
        self.assertEqual(db().execute('SELECT COUNT(*) FROM orders').fetchone()[0], 1)
        self.assertIn('Chicken Biryani', text(self.cust.get('/cart')))

    def test_failed_delivery_not_marked_delivered_and_refunded(self):
        item = db().execute('SELECT id, price FROM menu_items WHERE restaurant_id = 5 LIMIT 1').fetchone()
        self.add(item['id'])
        token = re.search(r'name="token" value="([^"]+)"', text(self.cust.get('/checkout'))).group(1)
        self.cust.post('/checkout', {'token': token, 'address': 'Flat 4'})
        oid = db().execute('SELECT id FROM orders').fetchone()[0]
        self.rest.post(f'/restaurant/order/{oid}/accept')
        self.rest.post(f'/restaurant/order/{oid}/request_agent')
        did = db().execute('SELECT id FROM deliveries').fetchone()[0]
        self.agent.post(f'/agent/request/{did}/accept')
        r = self.agent.post('/agent/active/fail', {'reason': 'Wrong address'})
        self.assertIn('will not be marked as delivered', text(r))
        self.assertEqual(db().execute('SELECT status FROM orders').fetchone()[0], 'delivery_failed')
        self.assertAlmostEqual(self.balance('1'), 650)

    def test_all_agents_reject_falls_back_to_restaurant(self):
        item = db().execute('SELECT id FROM menu_items WHERE restaurant_id = 5 LIMIT 1').fetchone()
        self.add(item['id'])
        token = re.search(r'name="token" value="([^"]+)"', text(self.cust.get('/checkout'))).group(1)
        self.cust.post('/checkout', {'token': token, 'address': 'Flat 4'})
        oid = db().execute('SELECT id FROM orders').fetchone()[0]
        self.rest.post(f'/restaurant/order/{oid}/accept')
        self.rest.post(f'/restaurant/order/{oid}/request_agent')
        did = db().execute('SELECT id FROM deliveries').fetchone()[0]
        self.agent.post(f'/agent/request/{did}/reject')          # only one agent exists
        self.assertEqual(db().execute('SELECT status FROM deliveries').fetchone()[0], 'restaurant_fallback')
        self.rest.post(f'/restaurant/order/{oid}/ready')
        self.rest.post(f'/restaurant/order/{oid}/self_deliver')
        self.rest.post(f'/restaurant/order/{oid}/self_delivered')
        self.assertEqual(db().execute('SELECT status FROM orders').fetchone()[0], 'delivered')

    def test_restaurant_cannot_touch_other_restaurants(self):
        self.assertEqual(self.rest.post('/restaurant/menu/1/toggle').status_code, 404)
        self.assertEqual(self.rest.post('/restaurant/order/999/accept').status_code, 404)

    def test_register_ignores_bad_role_and_wallet_is_idempotent(self):
        r = Client().post('/register', {'name': 'X', 'email': 'x@test.com', 'password': 'xxxxxxxx', 'role': 'superadmin'})
        self.assertEqual(r.status_code, 400)
        wallet.credit('1', 10, 'same-ref')
        wallet.credit('1', 10, 'same-ref')
        self.assertAlmostEqual(self.balance('1'), 660)

    def test_every_page_renders(self):
        for url in ('/', '/restaurant/1', '/restaurant/4', '/cart', '/orders', '/notifications'):
            self.assertEqual(self.cust.get(url).status_code, 200, url)
        self.assertEqual(self.rest.get('/dashboard/restaurant').status_code, 200)
        self.assertEqual(self.agent.get('/dashboard/delivery-agent').status_code, 200)


if __name__ == '__main__':
    unittest.main()
