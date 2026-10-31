"""End-to-end tests. Run:  python -m unittest -v test_app"""
import importlib
<<<<<<< HEAD
import hashlib
import hmac
import json
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
import os
import re
import tempfile
import unittest
<<<<<<< HEAD
from unittest.mock import Mock, patch

_tmp = tempfile.mkdtemp()
os.environ['ORDERFOOD_DB'] = os.path.join(_tmp, 'test.db')
os.environ['ORDERFOOD_WALLET'] = os.path.join(_tmp, 'legacy_wallet.json')
os.environ['ORDERFOOD_SECRET_KEY'] = 'test-key'
os.environ['ORDERFOOD_MAPS_OFFLINE'] = '1'      # tests never call Google; the offline estimator is used
os.environ['RAZORPAY_KEY_ID'] = 'rzp_test_unit_test'
os.environ['RAZORPAY_KEY_SECRET'] = 'unit-test-secret'
=======

_tmp = tempfile.mkdtemp()
os.environ['ORDERFOOD_DB'] = os.path.join(_tmp, 'test.db')
os.environ['ORDERFOOD_WALLET'] = os.path.join(_tmp, 'wallet.json')
os.environ['ORDERFOOD_SECRET_KEY'] = 'test-key'
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
app_module = importlib.import_module('orderfood_app')
app = app_module.app
wallet = app_module.wallet_service


<<<<<<< HEAD
HOME = (19.0596, 72.8295)          # test customer: Bandra West


=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
        if 'Where should we deliver' in r.get_data(as_text=True):      # customers confirm a location first
            r = self.post('/location', {'lat': str(HOME[0]), 'lon': str(HOME[1]), 'address': 'Flat 4'})
            assert r.status_code == 200
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
        return r


def text(r):
    return r.get_data(as_text=True)


class OrderFoodTests(unittest.TestCase):
    def setUp(self):
<<<<<<< HEAD
        if os.path.exists(app.config['DATABASE']):
            os.remove(app.config['DATABASE'])
        app_module.init_database()
        c = db()                                  # seeding is random: put everyone ~1 km from the customer
        c.execute("UPDATE restaurants SET lat = 19.0650, lon = 72.8300 WHERE name != 'Coastal Kitchen'")
        c.execute("UPDATE users SET lat = 19.0620, lon = 72.8310 WHERE role = 'delivery_agent'")
        c.commit()
        c.close()
=======
        for f in (app.config['DATABASE'], app.config['WALLET_FILE']):
            if os.path.exists(f):
                os.remove(f)
        app_module.init_database()
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
        self.cust, self.rest, self.agent = Client(), Client(), Client()
        self.cust.login('alice.customer@example.com', 'AlicePass123!')
        self.rest.login('anna.admin@example.com', 'AnnaAdmin123!')
        self.agent.login('david.agent@example.com', 'DavidAgent123!')

    def balance(self, key):
        return wallet.get_balance(key)['balance']

    def add(self, item_id, n=1):
        for _ in range(n):
            self.cust.post('/add_to_cart', {'item_id': item_id})

<<<<<<< HEAD
    def razorpay_order(self, customer=None, amount=18000):
        customer = customer or self.cust
        token = re.search(r'name="token" value="([^"]+)"',
                          text(customer.get('/checkout'))).group(1)
        fake = Mock()
        fake.order.create.return_value = {
            'id': 'order_test123', 'amount': amount, 'currency': 'INR'}
        with patch.object(app_module.razorpay, 'Client', return_value=fake):
            response = customer.c.post(
                '/api/create-order', json={'token': token, 'address': 'Flat 4'},
                headers={'X-CSRFToken': customer.token()})
        return response, fake

    # --- security ----------------------------------------------------------
    def test_production_requires_secret_and_development_key_is_private(self):
        with tempfile.TemporaryDirectory() as secret_dir:
            with patch.object(app_module, 'BASE_DIR', secret_dir):
                with patch.dict(os.environ, {'ORDERFOOD_ENV': 'production'}, clear=True):
                    with self.assertRaises(RuntimeError):
                        app_module._load_secret_key()
                    os.environ['ORDERFOOD_SECRET_KEY'] = 'short'
                    with self.assertRaises(RuntimeError):
                        app_module._load_secret_key()
                    os.environ['ORDERFOOD_SECRET_KEY'] = 'p' * 32
                    self.assertEqual(app_module._load_secret_key(), 'p' * 32)
                    self.assertFalse(os.path.exists(os.path.join(secret_dir, '.secret_key')))

                with patch.dict(os.environ, {'ORDERFOOD_ENV': 'development'}, clear=True):
                    generated = app_module._load_secret_key()
                    self.assertEqual(len(generated), 64)
                    self.assertEqual(
                        open(os.path.join(secret_dir, '.secret_key'), encoding='utf-8').read(),
                        generated)
                    if os.name == 'posix':
                        mode = os.stat(os.path.join(secret_dir, '.secret_key')).st_mode & 0o777
                        self.assertEqual(mode, 0o600)

=======
    # --- security ----------------------------------------------------------
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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

<<<<<<< HEAD
    def test_home_navigation_is_available_without_svg_for_all_roles(self):
        guest = Client()
        clients = (guest, self.cust, self.rest, self.agent)
        for client in clients:
            page = text(client.get('/'))
            self.assertIn('class="brand"', page)
            self.assertNotIn('<svg', page)

    def test_home_and_login_do_not_show_fake_reviews_or_demo_fillers(self):
        home_page = text(self.cust.get('/'))
        self.assertIn('No ratings yet', home_page)
        self.assertNotIn('Thane &middot; Mulund &middot; Vikhroli', home_page)
        login_page = text(Client().get('/login'))
        self.assertNotIn('Try a demo account', login_page)
        self.assertNotIn('ofFillDemo', login_page)
        invalid_demo = Client().post('/login', {'email': 'agent@test.com', 'password': 'agent123'})
        self.assertIn('Invalid email or password', text(invalid_demo))

=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
    def test_cart_prices_cannot_be_tampered(self):
        self.cust.post('/add_to_cart', {'item_id': 1, 'price': '0.01'})
        r = self.cust.get('/cart')
        self.assertIn('₹180', text(r))

    # --- ordering ----------------------------------------------------------
    def test_far_restaurant_cannot_be_ordered(self):
<<<<<<< HEAD
        r = self.cust.post('/add_to_cart', {'item_id': 16})       # Coastal Kitchen is outside the 30-minute radius
=======
        r = self.cust.post('/add_to_cart', {'item_id': 16})       # Coastal Kitchen item (42 min)
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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

<<<<<<< HEAD
    def test_razorpay_creates_server_priced_order_and_verifies_payment(self):
        self.add(1)
        self.add(7)
        response, fake = self.razorpay_order(amount=42000)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            'order_id': 'order_test123', 'amount': 42000, 'currency': 'INR'})
        request_data = fake.order.create.call_args.kwargs['data']
        self.assertEqual(request_data['amount'], 42000)
        self.assertEqual(request_data['currency'], 'INR')
        self.assertTrue(request_data['receipt'].startswith('of1'))

        payload = {'razorpay_order_id': 'order_test123',
                   'razorpay_payment_id': 'pay_test456',
                   'razorpay_signature': 'bad-signature'}
        headers = {'X-CSRFToken': self.cust.token()}
        invalid = self.cust.c.post('/api/verify-payment', json=payload, headers=headers)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(db().execute('SELECT COUNT(*) FROM orders').fetchone()[0], 0)

        payload['razorpay_signature'] = hmac.new(
            b'unit-test-secret', b'order_test123|pay_test456', hashlib.sha256).hexdigest()
        verified = self.cust.c.post('/api/verify-payment', json=payload, headers=headers)
        self.assertEqual(verified.status_code, 200)
        self.assertTrue(verified.get_json()['success'])
        self.assertEqual(db().execute('SELECT COUNT(*) FROM orders').fetchone()[0], 2)
        self.assertEqual(db().execute('SELECT COUNT(*) FROM transactions '
                                      'WHERE payment_method = ?', ('razorpay',)).fetchone()[0], 2)
        self.assertAlmostEqual(self.balance('1'), 650)

        duplicate = self.cust.c.post('/api/verify-payment', json=payload, headers=headers)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(db().execute('SELECT COUNT(*) FROM orders').fetchone()[0], 2)

        order_id = db().execute('SELECT MIN(id) FROM orders').fetchone()[0]
        refund_client = Mock()
        refund_client.payment.refund.side_effect = app_module.razorpay.errors.ServerError(
            'refund unavailable')
        with patch.object(app_module.razorpay, 'Client', return_value=refund_client):
            rejected = self.rest.post(f'/restaurant/order/{order_id}/reject')
        self.assertIn('could not refund', text(rejected))
        self.assertEqual(db().execute('SELECT status FROM orders WHERE id = ?',
                                      (order_id,)).fetchone()[0], 'pending')
        self.assertAlmostEqual(self.balance('1'), 650)

        refund_client = Mock()
        refund_client.payment.refund.return_value = {'id': 'rfnd_test123', 'status': 'pending'}
        with patch.object(app_module.razorpay, 'Client', return_value=refund_client):
            rejected = self.rest.post(f'/restaurant/order/{order_id}/reject')
        self.assertIn('refund initiated', text(rejected))
        self.assertEqual(db().execute('SELECT status FROM orders WHERE id = ?',
                                      (order_id,)).fetchone()[0], 'rejected')
        self.assertEqual(db().execute(
            "SELECT payment_method FROM transactions WHERE order_id = ? AND type = 'refund'",
            (order_id,)).fetchone()[0], 'razorpay')
        self.assertAlmostEqual(self.balance('1'), 650)

    def test_razorpay_rejects_missing_auth_and_small_amount(self):
        guest = Client()
        self.assertEqual(guest.c.post('/api/create-order', json={}).status_code, 401)
        self.assertEqual(guest.c.post('/api/verify-payment', json={}).status_code, 401)
        self.assertEqual(self.agent.c.post(
            '/api/create-order', json={}, headers={'X-CSRFToken': self.agent.token()}).status_code, 403)

        self.add(1)
        c = db()
        c.execute('UPDATE menu_items SET price = 0.5 WHERE id = 1')
        c.commit()
        c.close()
        token = re.search(r'name="token" value="([^"]+)"',
                          text(self.cust.get('/checkout'))).group(1)
        with patch.object(app_module.razorpay, 'Client') as client:
            response = self.cust.c.post(
                '/api/create-order', json={'token': token, 'address': 'Flat 4'},
                headers={'X-CSRFToken': self.cust.token()})
        self.assertEqual(response.status_code, 400)
        self.assertIn('at least ₹1.00', response.get_json()['error'])
        client.assert_not_called()

    def test_razorpay_sdk_failure_and_payment_page_configuration(self):
        self.add(1)
        page = text(self.cust.get('/checkout'))
        self.assertIn('https://checkout.razorpay.com/v1/checkout.js', page)
        self.assertIn('Pay ₹180 with Razorpay', page)
        self.assertIn('rzp_test_unit_test', page)
        self.assertNotIn('unit-test-secret', page)

        token = re.search(r'name="token" value="([^"]+)"', page).group(1)
        with patch.object(app_module.razorpay, 'Client') as client:
            client.return_value.order.create.side_effect = app_module.razorpay.errors.ServerError(
                'gateway unavailable')
            response = self.cust.c.post(
                '/api/create-order', json={'token': token, 'address': 'Flat 4'},
                headers={'X-CSRFToken': self.cust.token()})
        self.assertEqual(response.status_code, 500)
        self.assertIn('try again', response.get_json()['error'])

    def test_razorpay_missing_credentials_returns_service_unavailable(self):
        self.add(1)
        page = text(self.cust.get('/checkout'))
        token = re.search(r'name="token" value="([^"]+)"', page).group(1)
        with patch.dict(os.environ, {'RAZORPAY_KEY_ID': '', 'RAZORPAY_KEY_SECRET': ''}):
            response = self.cust.c.post(
                '/api/create-order', json={'token': token, 'address': 'Flat 4'},
                headers={'X-CSRFToken': self.cust.token()})
        self.assertEqual(response.status_code, 503)
        self.assertIn('not configured', response.get_json()['error'])

    def test_razorpay_rejects_malformed_verification_without_writing_orders(self):
        self.add(1)
        self.razorpay_order()
        headers = {'X-CSRFToken': self.cust.token()}
        malformed_payloads = [
            {},
            {'razorpay_order_id': 'bad', 'razorpay_payment_id': 'pay_test456',
             'razorpay_signature': 'a' * 64},
            {'razorpay_order_id': 'order_test123', 'razorpay_payment_id': 'bad',
             'razorpay_signature': 'a' * 64},
            {'razorpay_order_id': 'order_test123', 'razorpay_payment_id': 'pay_test456',
             'razorpay_signature': 'not-a-signature'},
        ]
        for payload in malformed_payloads:
            response = self.cust.c.post('/api/verify-payment', json=payload, headers=headers)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(db().execute('SELECT COUNT(*) FROM orders').fetchone()[0], 0)

    def test_razorpay_cart_change_after_payment_start_is_rejected(self):
        self.add(1)
        self.razorpay_order(amount=18000)
        self.add(7)  # mutate the cart after the gateway order has been created
        payload = {
            'razorpay_order_id': 'order_test123',
            'razorpay_payment_id': 'pay_test456',
            'razorpay_signature': hmac.new(
                b'unit-test-secret', b'order_test123|pay_test456', hashlib.sha256).hexdigest(),
        }
        response = self.cust.c.post(
            '/api/verify-payment', json=payload,
            headers={'X-CSRFToken': self.cust.token()})
        self.assertEqual(response.status_code, 409)
        self.assertIn('cart changed', response.get_json()['error'])
        self.assertEqual(db().execute('SELECT COUNT(*) FROM orders').fetchone()[0], 0)

    def test_razorpay_create_order_is_idempotent_for_same_checkout_intent(self):
        self.add(1)
        first, fake = self.razorpay_order()
        page = text(self.cust.get('/checkout'))
        token = re.search(r'name="token" value="([^"]+)"', page).group(1)
        second = self.cust.c.post(
            '/api/create-order', json={'token': token, 'address': 'Flat 4'},
            headers={'X-CSRFToken': self.cust.token()})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()['order_id'], first.get_json()['order_id'])
        fake.order.create.assert_called_once()

    def test_razorpay_invalid_gateway_order_response_is_rejected(self):
        self.add(1)
        page = text(self.cust.get('/checkout'))
        token = re.search(r'name="token" value="([^"]+)"', page).group(1)
        fake = Mock()
        fake.order.create.return_value = {'id': 'order_test123', 'amount': 1, 'currency': 'INR'}
        with patch.object(app_module.razorpay, 'Client', return_value=fake):
            response = self.cust.c.post(
                '/api/create-order', json={'token': token, 'address': 'Flat 4'},
                headers={'X-CSRFToken': self.cust.token()})
        self.assertEqual(response.status_code, 500)
        self.assertIn('invalid payment order', response.get_json()['error'])
        with self.cust.c.session_transaction() as browser_session:
            self.assertNotIn('razorpay_intent', browser_session)

    def test_razorpay_pending_order_can_be_cancelled(self):
        self.add(1)
        response, _ = self.razorpay_order()
        self.assertEqual(response.status_code, 200)
        cancelled = self.cust.c.post(
            '/api/cancel-order', json={'order_id': 'order_test123'},
            headers={'X-CSRFToken': self.cust.token()})
        self.assertEqual(cancelled.status_code, 200)
        with self.cust.c.session_transaction() as browser_session:
            self.assertNotIn('razorpay_intent', browser_session)

    def test_burger_joint_end_to_end(self):
        burger_owner = Client()
        burger_owner.login('admin@test.com', 'admin123')
=======
    def test_burger_joint_end_to_end(self):
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
        self.assertIn('New order', text(burger_owner.get('/notifications')))
        burger_owner.post(f'/restaurant/order/{oid}/accept')
        burger_owner.post(f'/restaurant/order/{oid}/request_agent')
=======
        self.assertIn('New order', text(self.rest.get('/notifications')))
        self.rest.post(f'/restaurant/order/{oid}/accept')
        self.rest.post(f'/restaurant/order/{oid}/request_agent')
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
        burger_owner.post(f'/restaurant/order/{oid}/ready')
=======
        self.rest.post(f'/restaurant/order/{oid}/ready')
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
        self.agent.post('/agent/active/pickup')
        self.agent.post('/agent/active/onway')
        r = self.agent.post('/agent/active/delivered')
        self.assertIn('Delivery completed', text(r))

        self.assertEqual(db().execute('SELECT status FROM orders').fetchone()[0], 'delivered')
        self.assertAlmostEqual(self.balance('3'), 40)             # agent default: per order
<<<<<<< HEAD
        self.assertAlmostEqual(self.balance('5'), total)          # restaurant owner paid on delivery
=======
        self.assertAlmostEqual(self.balance('rest_5'), total)     # restaurant paid on delivery
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5

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

<<<<<<< HEAD
    def test_agent_delivery_offers_are_sequential_and_ranked(self):
        self.add(1)
        token = re.search(r'name="token" value="([^"]+)"',
                          text(self.cust.get('/checkout'))).group(1)
        self.cust.post('/checkout', {'token': token, 'address': 'Flat 4'})
        order_id = db().execute('SELECT id FROM orders').fetchone()[0]

        other = Client()
        other.post('/register', {
            'name': 'Far Driver', 'email': 'far.agent@test.com',
            'password': 'faragent123', 'role': 'delivery_agent'})
        other.login('far.agent@test.com', 'faragent123')
        other_id = db().execute(
            "SELECT id FROM users WHERE email = 'far.agent@test.com'").fetchone()[0]
        c = db()
        c.execute('UPDATE users SET lat = 19.10, lon = 72.90 WHERE id = ?', (other_id,))
        c.commit()
        c.close()

        self.rest.post(f'/restaurant/order/{order_id}/accept')
        self.rest.post(f'/restaurant/order/{order_id}/request_agent')
        did = db().execute('SELECT id FROM deliveries WHERE order_id = ?', (order_id,)).fetchone()[0]
        self.assertEqual(db().execute(
            'SELECT offer_agent_id FROM deliveries WHERE id = ?', (did,)).fetchone()[0], 3)
        self.assertIn(f'/agent/request/{did}', text(self.agent.get('/dashboard/delivery-agent')))
        self.assertNotIn(f'/agent/request/{did}', text(other.get('/dashboard/delivery-agent')))

        self.agent.post(f'/agent/request/{did}/reject')
        self.assertEqual(db().execute(
            'SELECT offer_agent_id FROM deliveries WHERE id = ?', (did,)).fetchone()[0], other_id)
        self.assertIn(f'/agent/request/{did}', text(other.get('/dashboard/delivery-agent')))
        other.post(f'/agent/request/{did}/reject')
        self.assertEqual(db().execute(
            'SELECT status FROM deliveries WHERE id = ?', (did,)).fetchone()[0], 'restaurant_fallback')
        self.assertIn('no available delivery agent remains', text(self.rest.get('/notifications')))

    def test_customer_feedback_requires_completed_order_and_notifies_restaurant(self):
        self.add(1)
        token = re.search(r'name="token" value="([^"]+)"',
                          text(self.cust.get('/checkout'))).group(1)
        self.cust.post('/checkout', {'token': token, 'address': 'Flat 4'})
        order_id = db().execute('SELECT id FROM orders').fetchone()[0]

        early = self.cust.post(f'/orders/{order_id}/feedback', {'rating': '5', 'feedback': 'Great'})
        self.assertEqual(early.status_code, 404)
        self.rest.post(f'/restaurant/order/{order_id}/accept')
        self.rest.post(f'/restaurant/order/{order_id}/ready')
        self.rest.post(f'/restaurant/order/{order_id}/self_deliver')
        self.rest.post(f'/restaurant/order/{order_id}/self_delivered')
        self.cust.post(f'/orders/{order_id}/confirm')
        submitted = self.cust.post(
            f'/orders/{order_id}/feedback', {'rating': '5', 'feedback': 'Fresh and delicious'})
        self.assertIn('shared with the restaurant', text(submitted))
        c = db()
        review = c.execute('SELECT rating, feedback FROM reviews WHERE order_id = ?',
                           (order_id,)).fetchone()
        self.assertEqual((review['rating'], review['feedback']), (5, 'Fresh and delicious'))
        self.assertIn('New 5-star feedback', c.execute(
            'SELECT message FROM notifications WHERE user_id = 2 ORDER BY id DESC LIMIT 1').fetchone()[0])
        c.close()
        detail = text(self.cust.get('/restaurant/1'))
        self.assertIn('5.0 from 1 reviews', detail)
        self.assertIn('Fresh and delicious', detail)
        self.assertIn('Fresh and delicious', text(self.rest.get('/dashboard/restaurant')))

        duplicate = self.cust.post(
            f'/orders/{order_id}/feedback', {'rating': '4', 'feedback': 'Changed my mind'})
        self.assertIn('already been submitted', text(duplicate))

    def test_razorpay_route_settles_platform_payment_without_wallet_credits(self):
        self.add(1)
        response, _ = self.razorpay_order(amount=18000)
        self.assertEqual(response.status_code, 200)
        payment_payload = {
            'razorpay_order_id': 'order_test123',
            'razorpay_payment_id': 'pay_test456',
            'razorpay_signature': hmac.new(
                b'unit-test-secret', b'order_test123|pay_test456', hashlib.sha256).hexdigest(),
        }
        verified = self.cust.c.post(
            '/api/verify-payment', json=payment_payload,
            headers={'X-CSRFToken': self.cust.token()})
        self.assertEqual(verified.status_code, 200)
        order_id = verified.get_json()['order_ids'][0]

        self.rest.post(f'/restaurant/order/{order_id}/accept')
        self.rest.post(f'/restaurant/order/{order_id}/request_agent')
        did = db().execute('SELECT id FROM deliveries WHERE order_id = ?', (order_id,)).fetchone()[0]
        self.agent.post(f'/agent/request/{did}/accept')
        self.rest.post(f'/restaurant/order/{order_id}/ready')
        self.agent.post('/agent/active/arrive')
        self.agent.post('/agent/active/pickup')
        self.agent.post('/agent/active/delivered')
        self.assertEqual(db().execute(
            "SELECT COUNT(*) FROM settlements WHERE order_id = ? AND status = 'pending_setup'",
            (order_id,)).fetchone()[0], 2)
        self.assertEqual(self.balance('2'), 0)
        self.assertEqual(self.balance('3'), 0)

        self.rest.post('/restaurant/payout', {'payout_account_id': 'acc_restaurant123'})
        with patch.dict(os.environ, {'RAZORPAY_ROUTE_ENABLED': 'false'}):
            self.agent.post('/agent/settings', {'payout_account_id': 'acc_agent123'})
        fake = Mock()
        fake.payment.transfer.return_value = {'items': [
            {'id': 'trf_rest', 'status': 'created'},
            {'id': 'trf_agent', 'status': 'created'},
        ]}
        with patch.dict(os.environ, {'RAZORPAY_ROUTE_ENABLED': 'true'}):
            with patch.object(app_module.razorpay, 'Client', return_value=fake):
                self.agent.post('/agent/settings', {'process_pending': '1'})

        transfers = fake.payment.transfer.call_args.args[1]['transfers']
        self.assertEqual([transfer['amount'] for transfer in transfers], [14000, 4000])
        statuses = db().execute(
            'SELECT recipient_role, status, transfer_id FROM settlements WHERE order_id = ? '
            'ORDER BY recipient_role', (order_id,)).fetchall()
        self.assertTrue(all(row['status'] == 'submitted' for row in statuses))
        self.assertEqual({row['transfer_id'] for row in statuses}, {'trf_rest', 'trf_agent'})
        self.assertEqual(self.balance('2'), 0)
        self.assertEqual(self.balance('3'), 0)
        with patch.dict(os.environ, {'RAZORPAY_ROUTE_ENABLED': 'true'}):
            with patch.object(app_module.razorpay, 'Client', return_value=fake):
                self.agent.post('/agent/settings', {'process_pending': '1'})
        fake.payment.transfer.assert_called_once()

    def test_reject_refunds_and_cancel_refunds(self):
        burger_owner = Client()
        burger_owner.login('admin@test.com', 'admin123')
=======
    def test_reject_refunds_and_cancel_refunds(self):
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
        item = db().execute('SELECT id, price FROM menu_items WHERE restaurant_id = 5 LIMIT 1').fetchone()
        for action in ('reject', 'cancel'):
            self.add(item['id'])
            token = re.search(r'name="token" value="([^"]+)"', text(self.cust.get('/checkout'))).group(1)
            self.cust.post('/checkout', {'token': token, 'address': 'Flat 4'})
            oid = db().execute('SELECT MAX(id) FROM orders').fetchone()[0]
            self.assertAlmostEqual(self.balance('1'), 650 - item['price'])
            if action == 'reject':
<<<<<<< HEAD
                burger_owner.post(f'/restaurant/order/{oid}/reject')
=======
                self.rest.post(f'/restaurant/order/{oid}/reject')
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
        burger_owner = Client()
        item = db().execute('SELECT id, price FROM menu_items WHERE restaurant_id = 5 LIMIT 1').fetchone()
        burger_owner.login('admin@test.com', 'admin123')
=======
        item = db().execute('SELECT id, price FROM menu_items WHERE restaurant_id = 5 LIMIT 1').fetchone()
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
        self.add(item['id'])
        token = re.search(r'name="token" value="([^"]+)"', text(self.cust.get('/checkout'))).group(1)
        self.cust.post('/checkout', {'token': token, 'address': 'Flat 4'})
        oid = db().execute('SELECT id FROM orders').fetchone()[0]
<<<<<<< HEAD
        burger_owner.post(f'/restaurant/order/{oid}/accept')
        burger_owner.post(f'/restaurant/order/{oid}/request_agent')
=======
        self.rest.post(f'/restaurant/order/{oid}/accept')
        self.rest.post(f'/restaurant/order/{oid}/request_agent')
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
        did = db().execute('SELECT id FROM deliveries').fetchone()[0]
        self.agent.post(f'/agent/request/{did}/accept')
        r = self.agent.post('/agent/active/fail', {'reason': 'Wrong address'})
        self.assertIn('will not be marked as delivered', text(r))
        self.assertEqual(db().execute('SELECT status FROM orders').fetchone()[0], 'delivery_failed')
        self.assertAlmostEqual(self.balance('1'), 650)

    def test_all_agents_reject_falls_back_to_restaurant(self):
<<<<<<< HEAD
        burger_owner = Client()
        item = db().execute('SELECT id FROM menu_items WHERE restaurant_id = 5 LIMIT 1').fetchone()
        burger_owner.login('admin@test.com', 'admin123')
=======
        item = db().execute('SELECT id FROM menu_items WHERE restaurant_id = 5 LIMIT 1').fetchone()
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
        self.add(item['id'])
        token = re.search(r'name="token" value="([^"]+)"', text(self.cust.get('/checkout'))).group(1)
        self.cust.post('/checkout', {'token': token, 'address': 'Flat 4'})
        oid = db().execute('SELECT id FROM orders').fetchone()[0]
<<<<<<< HEAD
        burger_owner.post(f'/restaurant/order/{oid}/accept')
        burger_owner.post(f'/restaurant/order/{oid}/request_agent')
        did = db().execute('SELECT id FROM deliveries').fetchone()[0]
        self.agent.post(f'/agent/request/{did}/reject')          # only one agent exists
        self.assertEqual(db().execute('SELECT status FROM deliveries').fetchone()[0], 'restaurant_fallback')
        burger_owner.post(f'/restaurant/order/{oid}/ready')
        burger_owner.post(f'/restaurant/order/{oid}/self_deliver')
        burger_owner.post(f'/restaurant/order/{oid}/self_delivered')
=======
        self.rest.post(f'/restaurant/order/{oid}/accept')
        self.rest.post(f'/restaurant/order/{oid}/request_agent')
        did = db().execute('SELECT id FROM deliveries').fetchone()[0]
        self.agent.post(f'/agent/request/{did}/reject')          # only one agent exists
        self.assertEqual(db().execute('SELECT status FROM deliveries').fetchone()[0], 'restaurant_fallback')
        self.rest.post(f'/restaurant/order/{oid}/ready')
        self.rest.post(f'/restaurant/order/{oid}/self_deliver')
        self.rest.post(f'/restaurant/order/{oid}/self_delivered')
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
        self.assertEqual(db().execute('SELECT status FROM orders').fetchone()[0], 'delivered')

    def test_restaurant_cannot_touch_other_restaurants(self):
        # Find a restaurant that is NOT the one this admin owns
        c = db()
        owned_id = c.execute('SELECT restaurant_id FROM users WHERE email=?', ('anna.admin@example.com',)).fetchone()[0]
        other_id = c.execute('SELECT id FROM restaurants WHERE id != ? LIMIT 1', (owned_id,)).fetchone()[0]

        # Try to toggle an item from that other restaurant
        item_id = c.execute('SELECT id FROM menu_items WHERE restaurant_id = ? LIMIT 1', (other_id,)).fetchone()[0]
        self.assertEqual(self.rest.post(f'/restaurant/menu/{item_id}/toggle').status_code, 404)

        # Try to accept an order for another restaurant
        order_id = c.execute('SELECT id FROM orders WHERE restaurant_id != ? LIMIT 1', (owned_id,)).fetchone()
        if order_id:
            self.assertEqual(self.rest.post(f'/restaurant/order/{order_id[0]}/accept').status_code, 404)

    def test_register_ignores_bad_role_and_wallet_is_idempotent(self):
        r = Client().post('/register', {'name': 'X', 'email': 'x@test.com', 'password': 'xxxxxxxx', 'role': 'superadmin'})
        self.assertEqual(r.status_code, 400)
        wallet.credit('1', 10, 'same-ref')
        wallet.credit('1', 10, 'same-ref')
        self.assertAlmostEqual(self.balance('1'), 660)
<<<<<<< HEAD
        c = db()
        self.assertEqual(c.execute('SELECT COUNT(*) FROM wallet_operations WHERE operation = ? AND reference = ?',
                                   ('credit', 'same-ref')).fetchone()[0], 1)
        self.assertEqual(c.execute('SELECT COUNT(*) FROM wallets WHERE user_id = 1').fetchone()[0], 1)
        c.close()

    def test_legacy_wallet_file_migrates_into_user_wallets_once(self):
        legacy_path = app.config['LEGACY_WALLET_FILE']
        c = db()
        c.execute('DELETE FROM wallet_operations')
        c.execute('DELETE FROM wallets')
        c.execute("DELETE FROM app_metadata WHERE key = 'legacy_wallet_migrated'")
        c.commit()
        c.close()
        with open(legacy_path, 'w', encoding='utf-8') as fh:
            json.dump({
                '1': {'balance': 25, 'currency': 'INR'},
                '2': {'balance': 5, 'currency': 'INR'},
                'rest_1': {'balance': 30, 'currency': 'INR'},
                '_processed': {'credit:legacy-ref': {'wallet': '1', 'amount': 10}},
            }, fh)

        app_module.init_database()
        self.assertFalse(os.path.exists(legacy_path))
        self.assertAlmostEqual(self.balance('1'), 25)
        self.assertAlmostEqual(self.balance('2'), 35)
        wallet.credit('1', 10, 'legacy-ref')
        self.assertAlmostEqual(self.balance('1'), 25)

    def test_home_search_matches_restaurants_and_food_items(self):
        self.assertIn('Annapurna Meals', text(self.cust.get('/?q=Veg+Thali')))
        page = text(self.cust.get('/?q=Chicken+Biryani'))
        self.assertIn('Spice Route Biryani', page)
        self.assertIn('Chicken Biryani', page)
        self.assertIn('Coastal Kitchen', text(self.cust.get('/?q=Coastal')))

    def test_menu_categories_are_validated_and_editable(self):
        c = db()
        self.assertEqual(c.execute(
            "SELECT category FROM menu_items WHERE name = 'Chicken Biryani'").fetchone()[0], 'Rice & Biryani')
        self.assertEqual(c.execute(
            "SELECT category FROM menu_items WHERE name = 'Masala Chaas'").fetchone()[0], 'Drinks')
        self.assertEqual(c.execute(
            "SELECT category FROM menu_items WHERE name = 'Prawn Fry'").fetchone()[0], 'Appetizers')
        c.close()
        item = db().execute('SELECT id FROM menu_items WHERE restaurant_id = 1 LIMIT 1').fetchone()
        response = self.rest.post(f"/restaurant/menu/{item['id']}/category", {'category': 'Invalid'})
        self.assertIn('valid menu category', text(response))
        response = self.rest.post(f"/restaurant/menu/{item['id']}/category", {'category': 'Rice & Biryani'})
        self.assertIn('Menu updated.', text(response))
        category = db().execute('SELECT category FROM menu_items WHERE id = ?', (item['id'],)).fetchone()[0]
        self.assertEqual(category, 'Rice & Biryani')
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5

    def test_every_page_renders(self):
        for url in ('/', '/restaurant/1', '/restaurant/4', '/cart', '/orders', '/notifications'):
            self.assertEqual(self.cust.get(url).status_code, 200, url)
        self.assertEqual(self.rest.get('/dashboard/restaurant').status_code, 200)
        self.assertEqual(self.agent.get('/dashboard/delivery-agent').status_code, 200)


<<<<<<< HEAD
# ----------------------------------------------------------------------------------------------
# Google Maps: location gate, 30-minute rule from real coordinates, live tracking
# ----------------------------------------------------------------------------------------------
maps_service = importlib.import_module('maps_service')


class GoogleMapsTests(unittest.TestCase):
    def setUp(self):
        if os.path.exists(app.config['DATABASE']):
            os.remove(app.config['DATABASE'])
        app_module.init_database()
        c = db()
        self.seeded_restaurant_locations = c.execute(
            'SELECT id, lat, lon FROM restaurants ORDER BY id').fetchall()
        c.execute("UPDATE restaurants SET lat = 19.0650, lon = 72.8300 WHERE name != 'Coastal Kitchen'")
        c.execute("UPDATE users SET lat = 19.0620, lon = 72.8310 WHERE role = 'delivery_agent'")
        c.commit()
        c.close()
        self.svc = app_module.map_service
        self._saved = (self.svc.offline, self.svc.server_key, self.svc._call, self.svc.last_error)
        self.svc._cache.clear()
        self.calls = []

    def tearDown(self):
        self.svc.offline, self.svc.server_key, self.svc._call, self.svc.last_error = self._saved
        self.svc._cache.clear()

    def go_online(self, handler):
        self.svc.offline, self.svc.server_key = False, 'test-key'
        def fake(url, payload=None, headers=None):
            self.calls.append((url, payload, headers))
            return handler(url, payload)
        self.svc._call = fake

    def new_customer(self):
        c = Client()
        r = c.post('/login', {'email': 'alice.customer@example.com', 'password': 'AlicePass123!'})
        return c, r

    # --- location gate -------------------------------------------------------------------------
    def test_customer_is_asked_for_location_on_every_login(self):
        c, r = self.new_customer()
        self.assertIn('Where should we deliver', text(r))
        self.assertIn('Where should we deliver', text(c.get('/')))          # browsing is blocked until confirmed
        self.assertIn('Where should we deliver', text(c.get('/cart')))
        r = c.post('/location', {'lat': HOME[0], 'lon': HOME[1], 'address': 'Linking Road'})
        self.assertIn('Delivers to you in 30 minutes', text(r))
        saved = db().execute("SELECT lat, lon, location_address FROM users WHERE email = 'alice.customer@example.com'").fetchone()
        self.assertEqual((saved['lat'], saved['location_address']), (HOME[0], 'Linking Road'))
        c2, r2 = self.new_customer()                                        # a new login asks again, pre-filled
        self.assertIn('Where should we deliver', text(r2))
        self.assertIn('Confirm this location', text(r2))

    def test_location_validation_and_area_fallback(self):
        c, _ = self.new_customer()
        for bad in ({'lat': '999', 'lon': '10'}, {'lat': 'abc', 'lon': '1'}, {'lat': '', 'lon': ''}):
            r = c.post('/location', bad)
            self.assertIn('Please choose your delivery location', text(r))
        r = c.post('/location', {'area': 'Dadar'})                           # no-JS / no-key path
        self.assertIn('Delivers to you in 30 minutes', text(r))
        self.assertEqual(c.get('/').status_code, 200)
        c.post('/location', {'area': 'Thane West, Thane'})
        with c.c.session_transaction() as session:
            self.assertEqual(session['address'], 'Thane West, Thane')

    def test_staff_are_not_asked_for_location(self):
        r = Client().post('/login', {'email': 'anna.admin@example.com', 'password': 'AnnaAdmin123!'})
        self.assertIn('Owner dashboard', text(r))

    # --- seeding ---------------------------------------------------------------------------------
    def test_every_restaurant_and_driver_has_a_location(self):
        c = db()
        self.assertEqual(c.execute('SELECT COUNT(*) FROM restaurants WHERE lat IS NULL OR lon IS NULL').fetchone()[0], 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM users WHERE role = 'delivery_agent' AND lat IS NULL").fetchone()[0], 0)
        centers = [(area[1], area[2]) for area in maps_service.RESTAURANT_AREAS]
        restaurants = self.seeded_restaurant_locations
        self.assertTrue(all(
            min(maps_service.haversine_km((r['lat'], r['lon']), center) for center in centers) < 1
            for r in restaurants
        ))
        self.assertTrue(any(
            min(maps_service.haversine_km((r['lat'], r['lon']), center)
                for center in (area[1:] for area in maps_service.RESTAURANT_AREAS[4:6])) < 1
            for r in restaurants
        ))
        self.assertTrue(any(
            maps_service.haversine_km((r['lat'], r['lon']), maps_service.RESTAURANT_AREAS[6][1:]) < 1
            for r in restaurants
        ))
        # backfill only touches rows without a location
        c.execute("UPDATE restaurants SET lat = NULL, lon = NULL WHERE id = 1")
        c.commit()
        app_module.init_database()
        self.assertIsNotNone(db().execute('SELECT lat FROM restaurants WHERE id = 1').fetchone()[0])

    # --- 30-minute rule --------------------------------------------------------------------------
    def test_thirty_minute_rule_uses_customer_and_restaurant_coordinates(self):
        c, _ = self.new_customer()
        c.post('/location', {'lat': HOME[0], 'lon': HOME[1], 'address': 'Bandra'})
        home = text(c.get('/'))
        self.assertIn('Annapurna Meals', home.split('Over 30 minutes away')[0])
        self.assertIn('Coastal Kitchen', home.split('Over 30 minutes away')[1])
        # move the customer 40 km north: the nearby restaurants are now out of range
        c.post('/location', {'lat': 19.45, 'lon': 72.85, 'address': 'Far north'})
        page = text(c.get('/'))
        self.assertNotIn('Annapurna Meals', page.split('Over 30 minutes away')[0])
        self.assertIn('too far', text(c.post('/add_to_cart', {'item_id': 1})))

    def test_google_matrix_is_batched_cached_and_parsed(self):
        def handler(url, payload):
            n = len(payload['origins'])
            return [{'originIndex': i, 'destinationIndex': 0, 'status': {}, 'condition': 'ROUTE_EXISTS',
                     'distanceMeters': 3000 + i * 100, 'duration': '600s'} for i in range(n)]
        self.go_online(handler)
        c, _ = self.new_customer()
        c.post('/location', {'lat': HOME[0], 'lon': HOME[1], 'address': 'Bandra'})
        page = text(c.get('/'))
        matrix_calls = [x for x in self.calls if 'computeRouteMatrix' in x[0]]
        self.assertEqual(len(matrix_calls), 1)                              # one request for all restaurants
        self.assertEqual(matrix_calls[0][2]['X-Goog-Api-Key'], 'test-key')
        self.assertIn('20 min', page)                                       # 10 min drive + 10 min pickup buffer
        text(c.get('/'))
        self.assertEqual(len([x for x in self.calls if 'computeRouteMatrix' in x[0]]), 1)   # second view: cached

    def test_google_failure_falls_back_to_estimates_and_warns(self):
        def boom(url, payload):
            raise maps_service.MapsError('HTTP 403: Routes API has not been enabled')
        self.go_online(boom)
        c, _ = self.new_customer()
        r = c.post('/location', {'lat': HOME[0], 'lon': HOME[1], 'address': 'Bandra'})
        self.assertIn('approximate', text(r))
        self.assertIn('Annapurna Meals', text(r).split('Over 30 minutes away')[0])

    def test_polyline_decoder_rejects_malformed_data(self):
        with self.assertRaises(ValueError):
            app_module.maps_service.decode_polyline('abc')
        with self.assertRaises(ValueError):
            app_module.maps_service.decode_polyline(None)

    def test_polyline_decoder(self):
        pts = maps_service.decode_polyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@')   # Google's documented example
        self.assertEqual(pts, [[38.5, -120.2], [40.7, -120.95], [43.252, -126.453]])

    # --- live tracking ---------------------------------------------------------------------------
    def place_and_assign(self):
        cust = Client(); cust.login('alice.customer@example.com', 'AlicePass123!')
        rest, agent = Client(), Client()
        rest.login('anna.admin@example.com', 'AnnaAdmin123!')
        agent.login('david.agent@example.com', 'DavidAgent123!')
        cust.post('/add_to_cart', {'item_id': 1})
        token = re.search(r'name="token" value="([^"]+)"', text(cust.get('/checkout'))).group(1)
        cust.post('/checkout', {'token': token, 'address': 'Flat 4'})
        oid = db().execute('SELECT id FROM orders ORDER BY id DESC').fetchone()[0]
        for action in ('accept', 'ready', 'request_agent'):
            rest.post(f'/restaurant/order/{oid}/{action}')
        did = db().execute('SELECT id FROM deliveries WHERE order_id = ?', (oid,)).fetchone()[0]
        agent.post(f'/agent/request/{did}/accept')
        return cust, rest, agent, oid

    def test_everyone_can_track_and_only_the_right_people(self):
        cust, rest, agent, oid = self.place_and_assign()
        hdr = {'X-CSRFToken': agent.token()}
        # agent reports a position; customer and restaurant both see it
        r = agent.c.post('/api/agent/location', json={'lat': 19.0612, 'lon': 72.8305}, headers=hdr)
        self.assertEqual(r.get_json(), {'ok': True})
        for who in (cust, rest, agent):
            d = who.c.get(f'/api/orders/{oid}/tracking?path=1').get_json()
            self.assertEqual(d['stage'], 'to_restaurant')
            self.assertAlmostEqual(d['agent']['lat'], 19.0612)
            self.assertEqual(d['restaurant']['lat'], 19.0650)
            self.assertTrue(d['restaurant']['address'])
            self.assertEqual(d['destination']['lat'], HOME[0])             # the customer's confirmed pin
            self.assertGreater(len(d['path']), 1)
            self.assertIsNotNone(d['eta_customer_min'])
            self.assertEqual(who.get(f'/track/{oid}').status_code, 200)
        rest_address = db().execute(
            'SELECT address FROM restaurants WHERE id = '
            '(SELECT restaurant_id FROM orders WHERE id = ?)', (oid,)).fetchone()['address']
        self.assertIn(rest_address, text(cust.get(f'/orders?order={oid}')))
        self.assertIn(rest_address, text(cust.get('/')))
        active_agent_page = text(agent.get('/agent/active'))
        self.assertIn(rest_address, active_agent_page)
        self.assertIn('id="t-agent-navigation"', active_agent_page)
        # after pickup the target switches to the customer
        for action in ('arrive', 'pickup'):
            agent.post(f'/agent/active/{action}')
        d = cust.c.get(f'/api/orders/{oid}/tracking').get_json()
        self.assertEqual(d['stage'], 'to_customer')
        self.assertEqual(d['destination']['address'], 'Flat 4')
        active_agent_page = text(agent.get('/agent/active'))
        self.assertIn('id="t-agent-navigation"', active_agent_page)
        c = db()
        c.execute('UPDATE restaurants SET lat = NULL, lon = NULL WHERE id = '
                  '(SELECT restaurant_id FROM orders WHERE id = ?)', (oid,))
        c.execute('UPDATE orders SET dest_lat = NULL, dest_lon = NULL WHERE id = ?', (oid,))
        c.execute('UPDATE users SET lat = NULL, lon = NULL WHERE id = '
                  '(SELECT user_id FROM orders WHERE id = ?)', (oid,))
        c.commit()
        c.close()
        d = agent.c.get(f'/api/orders/{oid}/tracking').get_json()
        self.assertEqual(d['restaurant']['address'], rest_address)
        self.assertIsNone(d['restaurant']['lat'])
        self.assertEqual(d['destination']['address'], 'Flat 4')
        self.assertIsNone(d['destination']['lat'])
        self.assertIsNone(d['path'])                                       # path only when asked for
        # outsiders get a 404, not someone else's live location
        other = Client()
        other.post('/register', {'name': 'Eve', 'email': 'eve@example.com', 'password': 'EvePass12345!', 'role': 'customer'})
        other.login('eve@example.com', 'EvePass12345!')
        self.assertEqual(other.c.get(f'/api/orders/{oid}/tracking').status_code, 404)
        self.assertEqual(other.get(f'/track/{oid}').status_code, 404)
        rest2 = Client(); rest2.login('anna.admin@example.com', 'AnnaAdmin123!')
        self.assertEqual(rest2.c.get(f'/api/orders/{oid}/tracking').status_code, 200)

    def test_agent_location_endpoint_is_protected_and_validated(self):
        agent = Client(); agent.login('david.agent@example.com', 'DavidAgent123!')
        self.assertEqual(agent.c.post('/api/agent/location', json={'lat': 1, 'lon': 2}).status_code, 400)   # no CSRF
        hdr = {'X-CSRFToken': agent.token()}
        for bad in ({'lat': 'x', 'lon': 1}, {'lat': 95, 'lon': 1}, {}):
            self.assertEqual(agent.c.post('/api/agent/location', json=bad, headers=hdr).status_code, 400)
        cust, _ = self.new_customer()
        cust.post('/location', {'lat': HOME[0], 'lon': HOME[1]})
        self.assertNotEqual(cust.c.post('/api/agent/location', json={'lat': 1, 'lon': 2},
                                        headers={'X-CSRFToken': cust.token()}).status_code, 200)

    def test_agent_sees_nearest_pickup_first_and_request_map(self):
        cust, rest, agent, oid = self.place_and_assign()
        d = db().execute('SELECT status FROM deliveries WHERE order_id = ?', (oid,)).fetchone()
        self.assertEqual(d['status'], 'accepted')
        page = text(agent.get('/agent/active'))
        self.assertIn('id="track-root"', page)
        self.assertIn('data-locurl', page)

    def test_request_preview_and_pages_with_and_without_key(self):
        cust = Client(); cust.login('alice.customer@example.com', 'AlicePass123!')
        rest, agent = Client(), Client()
        rest.login('anna.admin@example.com', 'AnnaAdmin123!')
        agent.login('david.agent@example.com', 'DavidAgent123!')
        cust.post('/add_to_cart', {'item_id': 1})
        token = re.search(r'name="token" value="([^"]+)"', text(cust.get('/checkout'))).group(1)
        cust.post('/checkout', {'token': token, 'address': 'Flat 4'})
        oid = db().execute('SELECT id FROM orders').fetchone()[0]
        for action in ('accept', 'ready', 'request_agent'):
            rest.post(f'/restaurant/order/{oid}/{action}')
        did = db().execute('SELECT id FROM deliveries').fetchone()[0]
        dash = text(agent.get('/dashboard/delivery-agent'))
        self.assertIn('pickup', dash)                                       # distance from the agent to the restaurant
        offline = text(agent.get(f'/agent/request/{did}'))
        self.assertIn('data-static=', offline)
        self.assertIn('Map unavailable', offline)                           # no key: explains how to enable maps
        self.assertNotIn('maps.googleapis.com', offline)
        # with a key: the browser gets the key, never the server-only key
        self.svc.offline, self.svc.browser_key, self.svc.server_key = False, 'BROWSER-KEY', 'SERVER-KEY'
        self.svc._call = lambda url, payload=None, headers=None: {'routes': [{'distanceMeters': 2000, 'duration': '300s',
                              'polyline': {'encodedPolyline': '_p~iF~ps|U_ulLnnqC'}}]}
        page = text(agent.get(f'/agent/request/{did}'))
        self.assertIn('BROWSER-KEY', page)
        self.assertNotIn('SERVER-KEY', page)
        self.assertIn('[38.5, -120.2]', page)                               # real route path embedded for the map
        loc = text(cust.get('/location'))
        self.assertIn('location_picker.js', loc)
        self.assertEqual(cust.get('/orders').status_code, 200)
        self.svc.browser_key = ''


=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
if __name__ == '__main__':
    unittest.main()
