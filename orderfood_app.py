"""
OrderFood - Flask-based food ordering platform.

Roles: customer, restaurant_admin, delivery_agent.
Run:   python orderfood_app.py      (http://127.0.0.1:9000)
Reset: delete orderfood.db and wallet.json, then start again.
"""

import functools
import hmac
import json
import os
import secrets
import sqlite3
import threading
from urllib.parse import quote_plus

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config['DATABASE'] = os.environ.get('ORDERFOOD_DB', os.path.join(BASE_DIR, 'orderfood.db'))
app.config['WALLET_FILE'] = os.environ.get('ORDERFOOD_WALLET', os.path.join(BASE_DIR, 'wallet.json'))
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')


def _load_secret_key():
    """Secret key comes from the environment, otherwise a random key kept in .secret_key."""
    key = os.environ.get('ORDERFOOD_SECRET_KEY')
    if key:
        return key
    path = os.path.join(BASE_DIR, '.secret_key')
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(path, 'w') as f:
        f.write(key)
    return key


app.secret_key = _load_secret_key()

MAX_DELIVERY_MINUTES = 30
STARTING_CUSTOMER_BALANCE = 650.0
PAY_RATES = {'per_order': 40, 'per_km': 10, 'per_min': 2}      # rupees
PAY_LABELS = {'per_order': 'Per order', 'per_km': 'Per kilometre', 'per_min': 'Per minute'}
OPEN_ORDER_STATES = ('pending', 'preparing', 'ready', 'out_for_delivery', 'delivered')
ACTIVE_DELIVERY_STATES = ('accepted', 'at_restaurant', 'picked_up', 'on_the_way')
FAIL_REASONS = ['Customer not reachable', 'Wrong address', 'Order damaged', 'Other']
ROLES = {'customer', 'restaurant_admin', 'delivery_agent'}


# ---------------------------------------------------------------------------
# Third-party service mocks
# ---------------------------------------------------------------------------

class ExternalWalletService:
    """Mock payment gateway / wallet provider (JSON file).

    Every deduct/credit may carry a `ref`. Repeating a ref is ignored, so a retried
    request can never charge or refund twice.
    """

    def __init__(self, storage_file):
        self.storage_file = storage_file
        self._lock = threading.RLock()

    def _load(self):
        try:
            with open(self.storage_file) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, data):
        tmp = self.storage_file + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.storage_file)

    def ensure(self, key, initial=0.0):
        with self._lock:
            data = self._load()
            if key not in data:
                data[key] = {'balance': float(initial), 'currency': 'INR'}
                self._save(data)

    def get_balance(self, key):
        with self._lock:
            wallet = self._load().get(str(key))
        return wallet or {'balance': 0.0, 'currency': 'INR'}

    def _apply(self, key, amount, sign, ref, op):
        amount = round(float(amount), 2)
        if amount <= 0:
            return False, 'Invalid amount'
        key = str(key)
        with self._lock:
            data = self._load()
            processed = data.setdefault('_processed', {})
            ref_key = f'{op}:{ref}' if ref else None
            if ref_key and ref_key in processed:
                return True, 'Duplicate request ignored'
            wallet = data.get(key)
            if wallet is None:
                return False, 'Wallet not found'
            if sign < 0 and wallet['balance'] + 1e-9 < amount:
                return False, 'Insufficient Funds'
            wallet['balance'] = round(wallet['balance'] + sign * amount, 2)
            if ref_key:
                processed[ref_key] = {'wallet': key, 'amount': amount}
            self._save(data)
        return True, 'Success'

    def deduct(self, key, amount, ref=None):
        return self._apply(key, amount, -1, ref, 'deduct')

    def credit(self, key, amount, ref=None):
        return self._apply(key, amount, +1, ref, 'credit')


class ExternalMapService:
    """Mock maps/geocoding provider. Delivery times are a deterministic estimate, not a real
    routing calculation -- this app never calls a real maps API (see README).

    An earlier version of this class geocoded addresses for real via Nominatim and ran Haversine
    on the result. That broke the product's core 30-minute rule: free-text addresses like
    "Hostel Block B" geocode to arbitrary, often distant real-world places, so a nearby restaurant
    could suddenly read as thousands of minutes away once a customer typed a delivery address. It
    also meant checkout depended on a third-party network call with no offline fallback. Kept
    fully mocked and deterministic instead, matching what the UI tells the customer.
    """

    def calculate_delivery_time(self, restaurant_id, restaurant_address, customer_address=None):
        # Simulate a map service failure for SOP 2 testing
        if (customer_address or "").lower() == "fail_map":
            raise RuntimeError("Maps API service is currently unavailable.")

        if 'far away' in (restaurant_address or '').lower():
            return 42

        if not customer_address:
            # Stable mock for listings where no delivery address is known yet (e.g. home page).
            return 10 + (int(restaurant_id) * 7) % 16

        # Deterministic mock once a delivery address is known: same two addresses always produce
        # the same estimate, varied by how different the addresses look.
        diff = abs(len(restaurant_address or "") - len(customer_address or ""))
        return 10 + (diff % 20)

    @staticmethod
    def distance_km(minutes):
        # Reverse the logic: 20 km/h avg speed
        return round((minutes - 10) * 0.33, 1) if minutes > 10 else 0.5

    def get_navigation_url(self, address):
        return 'https://www.openstreetmap.org/search?query=' + quote_plus(address)


wallet_service = ExternalWalletService(app.config['WALLET_FILE'])
map_service = ExternalMapService()


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def _ensure_column(cursor, table, column, ddl):
    cols = [r[1] for r in cursor.execute(f'PRAGMA table_info({table})')]
    if column not in cols:
        cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')


MENU_SEED = {
    1: [('Veg Thali', 'Main Course', 180, 1), ('Paneer Thali', 'Main Course', 220, 1),
        ('Rajma Chawal', 'Main Course', 140, 1), ('Chole Bhature', 'Main Course', 120, 0),
        ('Masala Chaas', 'Drinks', 40, 1), ('Gulab Jamun', 'Desserts', 60, 1)],
    2: [('Chicken Biryani', 'Main Course', 240, 1), ('Veg Biryani', 'Main Course', 200, 1),
        ('Egg Biryani', 'Main Course', 210, 1), ('Raita', 'Appetizers', 30, 1),
        ('Phirni', 'Desserts', 70, 1)],
    3: [('Paneer Wrap', 'Main Course', 160, 1), ('Greek Salad', 'Appetizers', 190, 1),
        ('Quinoa Bowl', 'Main Course', 220, 1), ('Cold Coffee', 'Drinks', 110, 1)],
    4: [('Fish Curry Rice', 'Main Course', 260, 1), ('Prawn Fry', 'Appetizers', 320, 1)],
}
GENERIC_MENU = [('Signature Starter', 'Appetizers', 120), ('House Special', 'Main Course', 240),
                ('Sweet Treat', 'Desserts', 100), ('Fresh Drink', 'Drinks', 80)]

RESTAURANTS = [
    ('Annapurna Meals', 'Mumbai', 'Authentic North Indian Thalis', 4.5),
    ('Spice Route Biryani', 'Mumbai', 'Hyderabadi and Lucknowi Biryanis', 4.3),
    ('Green Bowl Salads', 'Mumbai', 'Fresh organic salads and wraps', 4.7),
    ('Coastal Kitchen', 'Far Away', 'Premium Seafood and Coastal Delicacies', 4.0),
    ('The Burger Joint', 'Mumbai', 'Gourmet burgers and loaded fries', 4.2),
    ('Pizza Planet', 'Mumbai', 'Authentic Neapolitan style pizzas', 4.4),
    ('Sushi Zen', 'Mumbai', 'Fresh premium sushi and sashimi', 4.8),
    ('Taco Town', 'Mumbai', 'Street style Mexican tacos', 4.1),
    ('Wok Express', 'Mumbai', 'Fast and fiery Asian stir-fry', 4.3),
    ('Pasta Palace', 'Mumbai', 'Handmade Italian pasta', 4.5),
    ('Desert Delight', 'Mumbai', 'Exotic Middle Eastern sweets', 4.6),
    ('Kebab Kingdom', 'Mumbai', 'Char-grilled tandoori specialties', 4.4),
    ('The Pancake House', 'Mumbai', 'Fluffy pancakes and waffles', 4.2),
    ('Dim Sum Dynasty', 'Mumbai', 'Hand-crafted dumplings', 4.7),
    ('Mediterranean Magic', 'Mumbai', 'Hummus, Pita and Falafel', 4.3),
    ('Juice Junction', 'Mumbai', 'Fresh cold-pressed juices', 4.5),
    ('The Steakhouse', 'Mumbai', 'Premium cuts and grilled sides', 4.6),
    ('Noodle Nation', 'Mumbai', 'Authentic Ramen and Udon', 4.4),
    ('Bake Street', 'Mumbai', 'Artisan breads and pastries', 4.7),
    ('Curry Corner', 'Mumbai', 'Homestyle Indian curries', 4.1),
    ('Samosa Station', 'Mumbai', 'Crispy samosas and chai', 4.3),
    ('The Vegan Hub', 'Mumbai', '100% plant-based delicacies', 4.5),
]

# Presentation-only: a curated photo + cuisine icon + colour tone per restaurant, so cards never
# fall back to a generic placeholder. Purely decorative -- no business logic reads this.
CUISINE_LABELS = {'grain': 'Rice & grains', 'leaf': 'Salads & veg', 'fish': 'Seafood',
                   'flame': 'Grilled & spicy', 'sweet': 'Desserts', 'drink': 'Drinks', 'spice': 'Curries & spice'}
RESTAURANT_STYLE = {
    'Annapurna Meals': ('photo-1546833999-b9f581a1996d', 'grain', 1),
    'Spice Route Biryani': ('photo-1589302168068-964664d93dc0', 'grain', 2),
    'Green Bowl Salads': ('photo-1512621776951-a57141f2eefd', 'leaf', 3),
    'Coastal Kitchen': ('photo-1565557623262-b51c2513a641', 'fish', 4),
    'The Burger Joint': ('photo-1568901346375-23c9450c58cd', 'flame', 5),
    'Pizza Planet': ('photo-1565299624946-b28f40a0ae38', 'flame', 1),
    'Sushi Zen': ('photo-1579871494447-9811cf80d66c', 'fish', 2),
    'Taco Town': ('photo-1551504734-5ee1c4a1479b', 'flame', 3),
    'Wok Express': ('photo-1512058564366-18510be2db19', 'flame', 4),
    'Pasta Palace': ('photo-1551183053-bf91a1d81141', 'grain', 5),
    'Desert Delight': ('photo-1519676867240-f03562e64548', 'sweet', 1),
    'Kebab Kingdom': ('photo-1529006557810-274b9b2fc783', 'flame', 2),
    'The Pancake House': ('photo-1528207776546-365bb710ee93', 'sweet', 3),
    'Dim Sum Dynasty': ('photo-1496116218417-1a781b1c416c', 'grain', 4),
    'Mediterranean Magic': ('photo-1540420773420-3366772f4999', 'leaf', 5),
    'Juice Junction': ('photo-1600271886742-f049cd451bba', 'drink', 1),
    'The Steakhouse': ('photo-1600891964599-f61ba0e24092', 'flame', 2),
    'Noodle Nation': ('photo-1569718212165-3a8278d5f624', 'grain', 3),
    'Bake Street': ('photo-1509440159596-0249088772ff', 'grain', 4),
    'Curry Corner': ('photo-1585937421612-70a008356fbe', 'spice', 5),
    'Samosa Station': ('photo-1601050690597-df0568f70950', 'spice', 1),
    'The Vegan Hub': ('photo-1604908176997-125f25cc6f3d', 'leaf', 2),
}


def restaurant_style(name):
    photo, icon, tone = RESTAURANT_STYLE.get(name, (None, 'grain', 1))
    url = f'https://images.unsplash.com/{photo}?auto=format&fit=crop&w=640&h=480&q=70' if photo else None
    return {'photo_url': url, 'icon': icon, 'tone': tone, 'cuisine': CUISINE_LABELS[icon]}


def init_database():
    conn = sqlite3.connect(app.config['DATABASE'])
    cur = conn.cursor()
    cur.execute('PRAGMA foreign_keys = ON')
    cur.executescript('''
    CREATE TABLE IF NOT EXISTS restaurants (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, address TEXT NOT NULL,
        description TEXT, rating REAL DEFAULT 0.0, is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS menu_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, restaurant_id INTEGER NOT NULL, name TEXT NOT NULL,
        description TEXT, price REAL NOT NULL, category TEXT, is_available INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, name TEXT,
        password TEXT NOT NULL, role TEXT DEFAULT 'customer',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, restaurant_id INTEGER NOT NULL,
        customer_email TEXT NOT NULL, delivery_address TEXT NOT NULL, total_amount REAL NOT NULL,
        status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        estimated_delivery_time REAL,
        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, item_id INTEGER,
        name TEXT NOT NULL, price REAL NOT NULL, qty INTEGER NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS deliveries (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
        delivery_agent_name TEXT NOT NULL, driver_address TEXT, status TEXT DEFAULT 'pending',
        completed_at TIMESTAMP,
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS delivery_rejections (
        delivery_id INTEGER NOT NULL, agent_id INTEGER NOT NULL,
        PRIMARY KEY (delivery_id, agent_id));
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, restaurant_id INTEGER NOT NULL,
        amount REAL NOT NULL, type TEXT DEFAULT 'revenue', payment_method TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, message TEXT NOT NULL,
        is_read INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    ''')
    # Upgrade databases created by the older version of the app.
    for table, column, ddl in [
        ('restaurants', 'is_open', 'INTEGER DEFAULT 1'),
        ('users', 'restaurant_id', 'INTEGER'),
        ('users', 'payment_method', "TEXT DEFAULT 'per_order'"),
        ('users', 'is_available', 'INTEGER DEFAULT 1'),
        ('users', 'accessibility_note', 'TEXT'),
        ('orders', 'user_id', 'INTEGER'),
        ('orders', 'payment_ref', 'TEXT'),
        ('deliveries', 'delivery_agent_id', 'INTEGER'),
        ('deliveries', 'distance_km', 'REAL'),
        ('deliveries', 'payout', 'REAL'),
        ('deliveries', 'payment_method', 'TEXT'),
        ('deliveries', 'fail_reason', 'TEXT'),
        ('transactions', 'user_id', 'INTEGER'),
    ]:
        _ensure_column(cur, table, column, ddl)

    if cur.execute('SELECT COUNT(*) FROM restaurants').fetchone()[0] == 0:
        cur.executemany('INSERT INTO restaurants (name, address, description, rating) VALUES (?,?,?,?)',
                        RESTAURANTS)
        for rid, (name, *_rest) in enumerate(RESTAURANTS, start=1):
            if rid in MENU_SEED:
                items = MENU_SEED[rid]
            else:
                items = [(f'{n}', c, p, 1) for n, c, p in GENERIC_MENU]
            cur.executemany(
                'INSERT INTO menu_items (restaurant_id, name, price, category, is_available) VALUES (?,?,?,?,?)',
                [(rid, n, p, c, a) for n, c, p, a in items])

    if cur.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0:
        demo = [
            ('alice.customer@example.com', 'Alice Wonderland', 'AlicePass123!', 'customer', None),
            ('bob.customer@example.com', 'Bob Builder', 'BobPass456!', 'customer', None),
            ('charlie.customer@example.com', 'Charlie Brown', 'CharliePass789!', 'customer', None),
            ('anna.admin@example.com', 'Anna Apple', 'AnnaAdmin123!', 'restaurant_admin', 1),
            ('ben.admin@example.com', 'Ben Banana', 'BenAdmin456!', 'restaurant_admin', 2),
            ('cat.admin@example.com', 'Cat Cherry', 'CatAdmin789!', 'restaurant_admin', 3),
            ('david.agent@example.com', 'David Driver', 'DavidAgent123!', 'delivery_agent', None),
            ('elena.agent@example.com', 'Elena Express', 'ElenaAgent456!', 'delivery_agent', None),
            ('frank.agent@example.com', 'Frank Fast', 'FrankAgent789!', 'delivery_agent', None),
        ]
        cur.executemany('INSERT INTO users (email, name, password, role, restaurant_id) VALUES (?,?,?,?,?)',
                        [(e, n, generate_password_hash(p), r, rid) for e, n, p, r, rid in demo])
    # Removed specific manual update for admin@test.com
    conn.commit()

    # Make sure every user has a wallet (older databases never created them).
    for uid, role, rid in cur.execute('SELECT id, role, restaurant_id FROM users').fetchall():
        wallet_service.ensure(str(uid), STARTING_CUSTOMER_BALANCE if role == 'customer' else 0.0)
        if role == 'restaurant_admin' and rid:
            wallet_service.ensure(f'rest_{rid}', 0.0)
    conn.close()


# ---------------------------------------------------------------------------
# Security helpers (CSRF, auth)
# ---------------------------------------------------------------------------

def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_hex(16)
    return session['_csrf']


@app.before_request
def csrf_protect():
    if request.method == 'POST':
        sent = request.form.get('_csrf') or request.headers.get('X-CSRFToken') or ''
        expected = session.get('_csrf')
        if not expected or not hmac.compare_digest(sent, expected):
            abort(400, 'Your session expired or the form was invalid. Please go back and try again.')


app.jinja_env.globals['csrf_token'] = csrf_token
app.jinja_env.globals['csrf_input'] = lambda: Markup(
    f'<input type="hidden" name="_csrf" value="{csrf_token()}">')
app.jinja_env.globals['PAY_LABELS'] = PAY_LABELS
app.jinja_env.globals['PAY_RATES'] = PAY_RATES
app.jinja_env.globals['restaurant_style'] = restaurant_style


@app.template_filter('money')
def money(value):
    value = float(value or 0)
    text = f'{value:,.0f}' if abs(value - round(value)) < 0.005 else f'{value:,.2f}'
    return f'₹{text}'


@app.template_filter('label')
def label(status):
    return (status or '').replace('_', ' ').capitalize()


def role_home(role):
    return {'restaurant_admin': 'restaurant_dashboard',
            'delivery_agent': 'delivery_agent_dashboard'}.get(role, 'home')


def login_required(role=None):
    def wrapper(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                flash('Authentication required. Please log in.', 'error')
                return redirect(url_for('login'))
            if role and session.get('role') != role:
                flash('That page is not available for your account type.', 'error')
                return redirect(url_for(role_home(session.get('role'))))
            return f(*args, **kwargs)
        return decorated
    return wrapper


def safe_next(default):
    nxt = request.form.get('next', '')
    return nxt if nxt.startswith('/') and not nxt.startswith('//') else default


def wallet_key():
    if session.get('role') == 'restaurant_admin':
        return f"rest_{session.get('restaurant_id')}"
    return str(session.get('user_id'))


def notify(db, user_id, message):
    db.execute('INSERT INTO notifications (user_id, message) VALUES (?, ?)', (user_id, message))


def notify_restaurant(db, restaurant_id, message):
    for row in db.execute('SELECT id FROM users WHERE restaurant_id = ?', (restaurant_id,)):
        notify(db, row['id'], message)


def notify_agents(db, message, exclude=()):
    for row in db.execute("SELECT id FROM users WHERE role = 'delivery_agent' AND is_available = 1"):
        if row['id'] not in exclude:
            notify(db, row['id'], message)


@app.context_processor
def inject_globals():
    uid = session.get('user_id')
    if not uid:
        return {'wallet': {'balance': 0, 'currency': 'INR'}, 'current_user': 'Guest',
                'cart_count': 0, 'unread': 0}
    db = get_db()
    unread = db.execute('SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0',
                        (uid,)).fetchone()[0]
    return {
        'wallet': wallet_service.get_balance(wallet_key()),
        'current_user': session.get('user_name', 'Guest'),
        'cart_count': sum(session.get('cart', {}).values()),
        'unread': unread,
    }


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
def http_error(err):
    return render_template('error.html', code=err.code, message=err.description), err.code


@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        name = (request.form.get('name') or '').strip()
        password = request.form.get('password') or ''
        role = request.form.get('role', 'customer')
        note = (request.form.get('accessibility_note') or '').strip()[:200]
        rest_name = (request.form.get('restaurant_name') or '').strip()
        rest_addr = (request.form.get('restaurant_address') or '').strip()

        error = None
        if role not in ROLES:
            error = 'Invalid account type.'
        elif not email or not name:
            error = 'Name and email are required.'
        elif len(password) < 8:
            error = 'Password must be at least 8 characters.'
        elif role == 'restaurant_admin' and not (rest_name and rest_addr):
            error = 'Restaurant name and address are required for restaurant accounts.'
        if error:
            flash(error, 'error')
            return render_template('register.html'), 400

        db = get_db()
        try:
            rest_id = None
            if role == 'restaurant_admin':
                rest_id = db.execute('INSERT INTO restaurants (name, address, description) VALUES (?,?,?)',
                                     (rest_name, rest_addr, 'New restaurant')).lastrowid
            user_id = db.execute(
                'INSERT INTO users (email, name, password, role, restaurant_id, accessibility_note) '
                'VALUES (?,?,?,?,?,?)',
                (email, name, generate_password_hash(password), role, rest_id, note)).lastrowid
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            flash('Email already registered.', 'error')
            return render_template('register.html'), 400

        wallet_service.ensure(str(user_id), STARTING_CUSTOMER_BALANCE if role == 'customer' else 0.0)
        if rest_id:
            wallet_service.ensure(f'rest_{rest_id}', 0.0)
        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()

        valid = False
        if user:
            stored = user['password']
            if stored.startswith(('scrypt:', 'pbkdf2:')):
                valid = check_password_hash(stored, password)
            elif hmac.compare_digest(stored, password):          # legacy plain-text row: upgrade it
                valid = True
                db.execute('UPDATE users SET password = ? WHERE id = ?',
                           (generate_password_hash(password), user['id']))
                db.commit()
        if valid:
            session.clear()
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['user_name'] = user['name']
            session['email'] = user['email']
            session['restaurant_id'] = user['restaurant_id']
            wallet_service.ensure(str(user['id']),
                                  STARTING_CUSTOMER_BALANCE if user['role'] == 'customer' else 0.0)
            return redirect(url_for(role_home(user['role'])))
        flash('Invalid email or password.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Customer: browsing
# ---------------------------------------------------------------------------

def restaurant_with_time(row):
    try:
        # In a real app, we'd use session['address'] if available
        customer_addr = session.get('address')
        return map_service.calculate_delivery_time(row['id'], row['address'], customer_addr)
    except Exception as e:
        # SOP 2: Handle map service failures gracefully
        flash(f"Map service error: {str(e)}. Using estimated defaults.", "warning")
        return 20 # Fallback default


@app.route('/')
@login_required('customer')
def home():
    db = get_db()
    q = (request.args.get('q') or '').strip()
    sql, params = 'SELECT * FROM restaurants WHERE is_active = 1', []
    if q:
        sql += ' AND (name LIKE ? OR description LIKE ?)'
        params += [f'%{q}%', f'%{q}%']
    reachable, too_far = [], []
    for r in db.execute(sql + ' ORDER BY rating DESC', params):
        minutes = restaurant_with_time(r)
        (reachable if minutes <= MAX_DELIVERY_MINUTES else too_far).append((r, minutes))
    reachable.sort(key=lambda x: x[1])

    awaiting = db.execute(
        "SELECT o.*, r.name AS rest_name, "
        "(SELECT group_concat(name || ' x' || qty, ', ') FROM order_items WHERE order_id = o.id) AS summary "
        "FROM orders o JOIN restaurants r ON r.id = o.restaurant_id "
        "WHERE o.user_id = ? AND o.status = 'delivered'", (session['user_id'],)).fetchall()
    return render_template('home.html', reachable=reachable, too_far=too_far, q=q, awaiting=awaiting)


@app.route('/restaurant/<int:rest_id>')
@login_required('customer')
def restaurant_detail(rest_id):
    db = get_db()
    rest = db.execute('SELECT * FROM restaurants WHERE id = ? AND is_active = 1', (rest_id,)).fetchone()
    if not rest:
        abort(404, 'Restaurant not found.')
    items = db.execute('SELECT * FROM menu_items WHERE restaurant_id = ? ORDER BY category, id',
                       (rest_id,)).fetchall()
    minutes = restaurant_with_time(rest)
    return render_template('restaurant_detail.html', restaurant=rest, menu_items=items,
                           delivery_time=minutes, too_far=minutes > MAX_DELIVERY_MINUTES,
                           cart=session.get('cart', {}))


# ---------------------------------------------------------------------------
# Customer: cart
# ---------------------------------------------------------------------------

def cart_groups(db):
    """Cart grouped per restaurant (one group == one separate order / transaction).
    Prices always come from the database, never from the browser."""
    cart = session.get('cart', {})
    if not cart:
        return []
    ids = [int(i) for i in cart]
    marks = ','.join('?' * len(ids))
    rows = db.execute(
        f'SELECT m.*, r.name AS rest_name, r.address AS rest_address, r.is_open, r.is_active '
        f'FROM menu_items m JOIN restaurants r ON r.id = m.restaurant_id WHERE m.id IN ({marks})', ids).fetchall()
    found = {str(r['id']) for r in rows}
    if found != set(cart):                       # item was deleted by the restaurant
        session['cart'] = {k: v for k, v in cart.items() if k in found}
    groups = {}
    for r in rows:
        qty = cart[str(r['id'])]
        grp = groups.setdefault(r['restaurant_id'], {
            'restaurant_id': r['restaurant_id'], 'name': r['rest_name'], 'items': [], 'subtotal': 0,
            'minutes': map_service.calculate_delivery_time(r['restaurant_id'], r['rest_address'], session.get('address')),
            'is_open': bool(r['is_open']) and bool(r['is_active']), 'problems': []})
        line = qty * r['price']
        grp['items'].append({'id': r['id'], 'name': r['name'], 'price': r['price'], 'qty': qty,
                             'line': line, 'available': bool(r['is_available'])})
        grp['subtotal'] += line
    for grp in groups.values():
        if not grp['is_open']:
            grp['problems'].append('This restaurant is currently closed.')
        if grp['minutes'] > MAX_DELIVERY_MINUTES:
            grp['problems'].append('This restaurant is too far to deliver to you.')
        if any(not i['available'] for i in grp['items']):
            grp['problems'].append('Some items are sold out.')
    return list(groups.values())


@app.route('/add_to_cart', methods=['POST'])
@login_required('customer')
def add_to_cart():
    db = get_db()
    item = db.execute(
        'SELECT m.*, r.address, r.is_open, r.is_active FROM menu_items m '
        'JOIN restaurants r ON r.id = m.restaurant_id WHERE m.id = ?',
        (request.form.get('item_id', type=int),)).fetchone()
    back = safe_next(url_for('view_cart'))
    if not item or not item['is_active']:
        flash('That item does not exist.', 'error')
    elif not item['is_available']:
        flash(f"{item['name']} is sold out.", 'error')
    elif not item['is_open']:
        flash('That restaurant is currently closed.', 'error')
    elif map_service.calculate_delivery_time(item['restaurant_id'], item['address'], session.get('address')) > MAX_DELIVERY_MINUTES:
        flash('That restaurant is too far to deliver to you.', 'error')
    else:
        cart = dict(session.get('cart', {}))
        key = str(item['id'])
        cart[key] = min(cart.get(key, 0) + 1, 20)
        session['cart'] = cart
        flash(f"{item['name'].upper()} added to cart.", 'success')
    return redirect(back)


@app.route('/cart/update', methods=['POST'])
@login_required('customer')
def cart_update():
    key = str(request.form.get('item_id', type=int))
    action = request.form.get('action')
    cart = dict(session.get('cart', {}))
    if key in cart:
        if action == 'inc':
            cart[key] = min(cart[key] + 1, 20)
        elif action == 'dec':
            cart[key] -= 1
        elif action == 'remove':
            cart[key] = 0
        if cart[key] <= 0:
            del cart[key]
    session['cart'] = cart
    return redirect(safe_next(url_for('view_cart')))


@app.route('/cart/replace', methods=['POST'])
@login_required('customer')
def cart_replace():
    db = get_db()
    old_id, new_id = request.form.get('old_id', type=int), request.form.get('new_id', type=int)
    cart = dict(session.get('cart', {}))
    old = db.execute('SELECT restaurant_id FROM menu_items WHERE id = ?', (old_id,)).fetchone()
    new = db.execute('SELECT restaurant_id, is_available, name FROM menu_items WHERE id = ?', (new_id,)).fetchone()
    if (str(old_id) in cart and old and new and new['is_available']
            and old['restaurant_id'] == new['restaurant_id']):       # replacement must be from the same restaurant
        qty = cart.pop(str(old_id))
        cart[str(new_id)] = min(cart.get(str(new_id), 0) + qty, 20)
        session['cart'] = cart
        flash(f"Replaced with {new['name']}.", 'success')
    else:
        flash('That replacement is not available.', 'error')
    return redirect(url_for('view_cart'))


@app.route('/cart')
@login_required('customer')
def view_cart():
    db = get_db()
    groups = cart_groups(db)
    replacements = {}
    for grp in groups:
        if any(not i['available'] for i in grp['items']):
            replacements[grp['restaurant_id']] = db.execute(
                'SELECT id, name, price FROM menu_items WHERE restaurant_id = ? AND is_available = 1',
                (grp['restaurant_id'],)).fetchall()
    total = sum(g_['subtotal'] for g_ in groups)
    blocked = any(g_['problems'] for g_ in groups)
    return render_template('cart.html', groups=groups, total=total, replacements=replacements,
                           blocked=blocked)


# ---------------------------------------------------------------------------
# Customer: checkout (one separate payment per restaurant)
# ---------------------------------------------------------------------------

def open_orders_for(db, user_id):
    marks = ','.join('?' * len(OPEN_ORDER_STATES))
    return db.execute(
        f'SELECT o.id, o.status, r.name AS rest_name FROM orders o JOIN restaurants r ON r.id = o.restaurant_id '
        f'WHERE o.user_id = ? AND o.status IN ({marks})', (user_id, *OPEN_ORDER_STATES)).fetchall()


@app.route('/checkout', methods=['GET'])
@login_required('customer')
def checkout_review():
    db = get_db()
    groups = cart_groups(db)
    if not groups:
        flash('Your cart is empty.', 'error')
        return redirect(url_for('home'))
    if any(g_['problems'] for g_ in groups):
        flash('Fix the problems in your cart before paying.', 'error')
        return redirect(url_for('view_cart'))
    pending = open_orders_for(db, session['user_id'])
    if pending:
        return render_template('confirm_last.html', pending=pending)
    total = sum(g_['subtotal'] for g_ in groups)
    balance = wallet_service.get_balance(str(session['user_id']))['balance']
    token = secrets.token_hex(8)
    session['checkout_token'] = token
    return render_template('checkout.html', groups=groups, total=total, balance=balance, token=token,
                           address=session.get('address', ''))


def place_order(db, user_id, email, group, address, ref):
    """Create one order and take its payment. Returns (ok, message, order_id)."""
    try:
        cur = db.execute(
            "INSERT INTO orders (restaurant_id, user_id, customer_email, delivery_address, total_amount, "
            "status, estimated_delivery_time, payment_ref) VALUES (?,?,?,?,?,'pending',?,?)",
            (group['restaurant_id'], user_id, email, address, group['subtotal'], group['minutes'], ref))
        order_id = cur.lastrowid
        db.executemany('INSERT INTO order_items (order_id, item_id, name, price, qty) VALUES (?,?,?,?,?)',
                       [(order_id, i['id'], i['name'], i['price'], i['qty']) for i in group['items']])
        db.execute("INSERT INTO transactions (order_id, restaurant_id, amount, type, payment_method, user_id) "
                   "VALUES (?,?,?,'payment','wallet',?)", (order_id, group['restaurant_id'], group['subtotal'], user_id))
        db.execute("INSERT INTO deliveries (order_id, delivery_agent_name, status, distance_km) "
                   "VALUES (?, 'Unassigned', 'not_requested', ?)",
                   (order_id, map_service.distance_km(group['minutes'])))
    except sqlite3.Error as exc:
        db.rollback()
        return False, f'System error: {exc}', None

    ok, msg = wallet_service.deduct(str(user_id), group['subtotal'], ref)
    if not ok:
        db.rollback()                                   # nothing saved, nothing charged
        return False, msg, None
    try:
        db.commit()
    except sqlite3.Error as exc:
        db.rollback()
        wallet_service.credit(str(user_id), group['subtotal'], f'refund:{ref}')   # money back
        return False, f'System error, you were not charged: {exc}', None
    notify_restaurant(db, group['restaurant_id'], f"New order #{order_id} - {group['subtotal']:.0f} paid.")
    db.commit()
    return True, 'Paid, order placed', order_id


@app.route('/checkout', methods=['POST'])
@login_required('customer')
def checkout():
    db = get_db()
    token = request.form.get('token', '')
    if not token or token != session.pop('checkout_token', None):
        flash('This checkout was already submitted or has expired. Check My orders before paying again.', 'error')
        return redirect(url_for('orders'))
    groups = cart_groups(db)
    if not groups:
        return redirect(url_for('home'))

    address = (request.form.get('address') or '').strip()
    if not address:
        flash('Please enter a delivery address.', 'error')
        return redirect(url_for('checkout_review'))
    session['address'] = address

    if open_orders_for(db, session['user_id']):
        return redirect(url_for('checkout_review'))             # shows the "confirm last order" screen

    results, cart = [], dict(session.get('cart', {}))
    for n, grp in enumerate(groups, start=1):
        if grp['problems']:
            ok, msg, order_id = False, ' '.join(grp['problems']), None
        else:
            ok, msg, order_id = place_order(db, session['user_id'], session['email'], grp, address,
                                            f"{token}-{grp['restaurant_id']}")
        if ok:
            for it in grp['items']:
                cart.pop(str(it['id']), None)
        results.append({'n': n, 'name': grp['name'], 'amount': grp['subtotal'], 'ok': ok,
                        'message': msg, 'order_id': order_id})
    session['cart'] = cart

    if all(r['ok'] for r in results):
        paid = sum(r['amount'] for r in results)
        balance = wallet_service.get_balance(str(session['user_id']))['balance']
        flash(f'{money(paid)} paid from your wallet. Balance: {money(balance)}', 'success')
        return redirect(url_for('orders', order=results[0]['order_id']))
    return render_template('checkout_result.html', results=results)


# ---------------------------------------------------------------------------
# Customer: orders
# ---------------------------------------------------------------------------

TRACK_STEPS = ['Order placed', 'Restaurant confirmed', 'Preparing', 'Delivery agent assigned',
               'Out for delivery', 'Delivered']


def progress_level(order, delivery):
    status = order['status']
    level = {'pending': 1, 'preparing': 3, 'ready': 3, 'out_for_delivery': 5,
             'delivered': 6, 'completed': 6, 'disputed': 6}.get(status, 0)
    if status in ('preparing', 'ready') and delivery and delivery['status'] in ACTIVE_DELIVERY_STATES:
        level = 4
    return level


@app.route('/orders')
@login_required('customer')
def orders():
    db = get_db()
    rows = db.execute(
        "SELECT o.*, r.name AS rest_name FROM orders o JOIN restaurants r ON r.id = o.restaurant_id "
        "WHERE o.user_id = ? ORDER BY o.id DESC LIMIT 12", (session['user_id'],)).fetchall()
    selected = None
    wanted = request.args.get('order', type=int)
    for r in rows:
        if r['id'] == wanted:
            selected = r
    selected = selected or (rows[0] if rows else None)
    detail = None
    if selected:
        items = db.execute('SELECT * FROM order_items WHERE order_id = ?', (selected['id'],)).fetchall()
        delivery = db.execute(
            'SELECT d.*, u.accessibility_note AS agent_note FROM deliveries d '
            'LEFT JOIN users u ON u.id = d.delivery_agent_id WHERE d.order_id = ?', (selected['id'],)).fetchone()
        level = progress_level(selected, delivery)
        detail = {'order': selected, 'items': items, 'delivery': delivery, 'level': level,
                  'steps': [(s, i + 1 <= level) for i, s in enumerate(TRACK_STEPS)]}
    return render_template('orders.html', rows=rows, detail=detail)


def _own_order_update(sql, order_id):
    db = get_db()
    cur = db.execute(sql, (order_id, session['user_id']))
    db.commit()
    return cur.rowcount == 1


def refund_order(db, order, reason):
    ref = f"refund:order:{order['id']}"
    ok, _ = wallet_service.credit(str(order['user_id']), order['total_amount'], ref)
    if ok:
        db.execute("INSERT INTO transactions (order_id, restaurant_id, amount, type, payment_method, user_id) "
                   "VALUES (?,?,?,'refund','wallet',?)",
                   (order['id'], order['restaurant_id'], order['total_amount'], order['user_id']))
        notify(db, order['user_id'], f"Order #{order['id']}: {reason}. {money(order['total_amount'])} refunded.")


@app.route('/orders/<int:order_id>/confirm', methods=['POST'])
@login_required('customer')
def confirm_delivery(order_id):
    # Only the owner can confirm, and only after the agent/restaurant marked it delivered.
    if _own_order_update("UPDATE orders SET status = 'completed' WHERE id = ? AND user_id = ? "
                         "AND status = 'delivered'", order_id):
        flash('Thanks! Order confirmed as received.', 'success')
    else:
        flash('This order cannot be confirmed yet. It must be marked delivered first.', 'error')
    return redirect(safe_next(url_for('home')))


@app.route('/orders/<int:order_id>/report', methods=['POST'])
@login_required('customer')
def report_problem(order_id):
    if _own_order_update("UPDATE orders SET status = 'disputed' WHERE id = ? AND user_id = ? "
                         "AND status = 'delivered'", order_id):
        db = get_db()
        order = db.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        notify_restaurant(db, order['restaurant_id'], f'Order #{order_id}: customer reported a problem.')
        db.commit()
        flash('Problem reported. We will look into it.', 'success')
    else:
        flash('Only delivered orders can be reported.', 'error')
    return redirect(url_for('orders', order=order_id))


@app.route('/orders/<int:order_id>/cancel', methods=['POST'])
@login_required('customer')
def cancel_order(order_id):
    db = get_db()
    if _own_order_update("UPDATE orders SET status = 'cancelled' WHERE id = ? AND user_id = ? "
                         "AND status = 'pending'", order_id):
        order = db.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        db.execute("UPDATE deliveries SET status = 'cancelled' WHERE order_id = ?", (order_id,))
        refund_order(db, order, 'cancelled by you')
        notify_restaurant(db, order['restaurant_id'], f'Order #{order_id} was cancelled by the customer.')
        db.commit()
        flash('Order cancelled and refunded.', 'success')
    else:
        flash('Only orders the restaurant has not accepted yet can be cancelled.', 'error')
    return redirect(url_for('orders', order=order_id))


@app.route('/notifications')
@login_required()
def notifications():
    db = get_db()
    rows = db.execute('SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 50',
                      (session['user_id'],)).fetchall()
    db.execute('UPDATE notifications SET is_read = 1 WHERE user_id = ?', (session['user_id'],))
    db.commit()
    return render_template('notifications.html', rows=rows)


# ---------------------------------------------------------------------------
# Restaurant dashboard
# ---------------------------------------------------------------------------

def my_restaurant(db):
    rest = db.execute('SELECT * FROM restaurants WHERE id = ?', (session.get('restaurant_id'),)).fetchone()
    if not rest:
        abort(403, 'No restaurant is linked to this account.')
    return rest


@app.route('/dashboard/restaurant')
@login_required('restaurant_admin')
def restaurant_dashboard():
    db = get_db()
    rest = my_restaurant(db)
    orders_ = db.execute(
        'SELECT o.*, d.status AS del_status, d.delivery_agent_name, d.id AS delivery_id, '
        "(SELECT group_concat(name || ' x' || qty, ', ') FROM order_items WHERE order_id = o.id) AS summary "
        'FROM orders o JOIN deliveries d ON d.order_id = o.id WHERE o.restaurant_id = ? '
        'ORDER BY o.id DESC', (rest['id'],)).fetchall()
    menu = db.execute('SELECT * FROM menu_items WHERE restaurant_id = ? ORDER BY category, id', (rest['id'],)).fetchall()
    revenue_states = ('preparing', 'ready', 'out_for_delivery', 'delivered', 'completed', 'disputed')
    revenue = sum(o['total_amount'] for o in orders_
                  if o['status'] in revenue_states and (o['created_at'] or '')[:10] == _today(db))
    stats = {'new': sum(o['status'] == 'pending' for o in orders_),
             'active': sum(o['status'] in ('preparing', 'ready', 'out_for_delivery') for o in orders_),
             'revenue': revenue}
    return render_template('dashboard_restaurant.html', rest=rest, orders=orders_, menu=menu, stats=stats)


def _today(db):
    return db.execute("SELECT date('now')").fetchone()[0]


@app.route('/restaurant/order/<int:order_id>/<action>', methods=['POST'])
@login_required('restaurant_admin')
def restaurant_order_action(order_id, action):
    db = get_db()
    rest = my_restaurant(db)
    order = db.execute('SELECT * FROM orders WHERE id = ? AND restaurant_id = ?', (order_id, rest['id'])).fetchone()
    delivery = db.execute('SELECT * FROM deliveries WHERE order_id = ?', (order_id,)).fetchone()
    if not order or not delivery:
        abort(404, 'Order not found.')

    def set_status(new, *allowed):
        cur = db.execute(f"UPDATE orders SET status = ? WHERE id = ? AND status IN ({','.join('?' * len(allowed))})",
                         (new, order_id, *allowed))
        return cur.rowcount == 1

    msg = None
    if action == 'accept' and set_status('preparing', 'pending'):
        notify(db, order['user_id'], f"Order #{order_id}: {rest['name']} accepted your order.")
        msg = 'Order accepted.'
    elif action == 'reject' and set_status('rejected', 'pending'):
        db.execute("UPDATE deliveries SET status = 'cancelled' WHERE order_id = ?", (order_id,))
        refund_order(db, order, f"{rest['name']} could not take your order")
        msg = 'Order rejected and customer refunded.'
    elif action == 'ready' and set_status('ready', 'preparing'):
        if delivery['delivery_agent_id']:
            notify(db, delivery['delivery_agent_id'], f'Order #{order_id} is ready for pickup.')
        notify(db, order['user_id'], f'Order #{order_id} is ready.')
        msg = 'Marked as ready.'
    elif action == 'request_agent' and order['status'] in ('preparing', 'ready') and db.execute(
            "UPDATE deliveries SET status = 'pending' WHERE order_id = ? AND status = 'not_requested'",
            (order_id,)).rowcount == 1:
        db.execute('DELETE FROM delivery_rejections WHERE delivery_id = ?', (delivery['id'],))
        notify_agents(db, f"New delivery request: {rest['name']} (order #{order_id}).")
        msg = 'Delivery agents have been notified.'
    elif action == 'self_deliver' and order['status'] == 'ready' and db.execute(
            "UPDATE deliveries SET status = 'self', delivery_agent_name = 'Restaurant' WHERE order_id = ? "
            "AND status IN ('not_requested', 'pending', 'restaurant_fallback')", (order_id,)).rowcount == 1:
        set_status('out_for_delivery', 'ready')
        notify(db, order['user_id'], f'Order #{order_id} is out for delivery from {rest["name"]}.')
        msg = 'You are delivering this order yourself.'
    elif action == 'self_delivered' and order['status'] == 'out_for_delivery' and delivery['status'] == 'self':
        db.execute("UPDATE deliveries SET status = 'delivered', completed_at = CURRENT_TIMESTAMP WHERE order_id = ?",
                   (order_id,))
        set_status('delivered', 'out_for_delivery')
        pay_restaurant(db, order)
        notify(db, order['user_id'], f'Order #{order_id} was delivered. Please confirm you received it.')
        msg = 'Marked as delivered.'
    if msg:
        db.commit()
        flash(msg, 'success')
    else:
        db.rollback()
        flash('That action is not possible for this order right now.', 'error')
    return redirect(url_for('restaurant_dashboard') + '#orders')


def pay_restaurant(db, order):
    ok, _ = wallet_service.credit(f"rest_{order['restaurant_id']}", order['total_amount'],
                                  f"restaurant:{order['id']}")
    if ok:
        db.execute("INSERT INTO transactions (order_id, restaurant_id, amount, type, payment_method) "
                   "VALUES (?,?,?,'restaurant_payout','wallet')",
                   (order['id'], order['restaurant_id'], order['total_amount']))


@app.route('/restaurant/menu/add', methods=['POST'])
@login_required('restaurant_admin')
def menu_add():
    db = get_db()
    rest = my_restaurant(db)
    name = (request.form.get('name') or '').strip()
    price = request.form.get('price', type=float)
    category = request.form.get('category') or 'Main Course'
    if not name or price is None or price <= 0:
        flash('Enter an item name and a price above zero.', 'error')
    else:
        db.execute('INSERT INTO menu_items (restaurant_id, name, price, category) VALUES (?,?,?,?)',
                   (rest['id'], name, price, category))
        db.commit()
        flash(f'{name} added to the menu.', 'success')
    return redirect(url_for('restaurant_dashboard') + '#menu')


@app.route('/restaurant/menu/<int:item_id>/<action>', methods=['POST'])
@login_required('restaurant_admin')
def menu_edit(item_id, action):
    db = get_db()
    rest = my_restaurant(db)
    owned = db.execute('SELECT id FROM menu_items WHERE id = ? AND restaurant_id = ?', (item_id, rest['id'])).fetchone()
    if not owned:
        abort(404, 'Menu item not found.')
    if action == 'toggle':
        db.execute('UPDATE menu_items SET is_available = 1 - is_available WHERE id = ?', (item_id,))
    elif action == 'price':
        price = request.form.get('price', type=float)
        if price is None or price <= 0:
            flash('Enter a price above zero.', 'error')
            return redirect(url_for('restaurant_dashboard') + '#menu')
        db.execute('UPDATE menu_items SET price = ? WHERE id = ?', (price, item_id))
    elif action == 'delete':
        db.execute('DELETE FROM menu_items WHERE id = ?', (item_id,))
    else:
        abort(404)
    db.commit()
    flash('Menu updated.', 'success')
    return redirect(url_for('restaurant_dashboard') + '#menu')


@app.route('/restaurant/info', methods=['POST'])
@login_required('restaurant_admin')
def restaurant_info():
    db = get_db()
    rest = my_restaurant(db)
    if request.form.get('toggle_open'):
        db.execute('UPDATE restaurants SET is_open = 1 - is_open WHERE id = ?', (rest['id'],))
    else:
        name, address = (request.form.get('name') or '').strip(), (request.form.get('address') or '').strip()
        if not name or not address:
            flash('Name and address are required.', 'error')
            return redirect(url_for('restaurant_dashboard') + '#info')
        db.execute('UPDATE restaurants SET name = ?, address = ?, description = ? WHERE id = ?',
                   (name, address, (request.form.get('description') or '').strip(), rest['id']))
    db.commit()
    flash('Restaurant updated.', 'success')
    return redirect(url_for('restaurant_dashboard') + '#info')


# ---------------------------------------------------------------------------
# Delivery agent dashboard
# ---------------------------------------------------------------------------

def payout_for(method, distance_km, minutes):
    if method == 'per_km':
        return round(distance_km * PAY_RATES['per_km'])
    if method == 'per_min':
        return round(minutes * PAY_RATES['per_min'])
    return PAY_RATES['per_order']


def current_agent(db):
    return db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()


def active_delivery(db, agent_id):
    marks = ','.join('?' * len(ACTIVE_DELIVERY_STATES))
    return db.execute(
        f'SELECT d.*, o.id AS order_id, o.status AS order_status, o.delivery_address, o.estimated_delivery_time, '
        f'r.name AS rest_name, r.address AS rest_address, u.name AS customer_name, '
        f'u.accessibility_note AS customer_note, '
        f"(SELECT group_concat(name || ' x' || qty, ', ') FROM order_items WHERE order_id = o.id) AS summary "
        f'FROM deliveries d JOIN orders o ON o.id = d.order_id JOIN restaurants r ON r.id = o.restaurant_id '
        f'LEFT JOIN users u ON u.id = o.user_id '
        f'WHERE d.delivery_agent_id = ? AND d.status IN ({marks}) LIMIT 1', (agent_id, *ACTIVE_DELIVERY_STATES)).fetchone()


def pending_requests(db, agent_id):
    return db.execute(
        "SELECT d.*, o.delivery_address, o.estimated_delivery_time, o.total_amount, r.name AS rest_name, "
        "r.address AS rest_address, u.accessibility_note AS customer_note, "
        "(SELECT COUNT(*) FROM order_items WHERE order_id = o.id) AS n_items "
        "FROM deliveries d JOIN orders o ON o.id = d.order_id JOIN restaurants r ON r.id = o.restaurant_id "
        "LEFT JOIN users u ON u.id = o.user_id "
        "WHERE d.status = 'pending' AND d.id NOT IN (SELECT delivery_id FROM delivery_rejections WHERE agent_id = ?) "
        "ORDER BY d.id", (agent_id,)).fetchall()


@app.route('/dashboard/delivery-agent')
@login_required('delivery_agent')
def delivery_agent_dashboard():
    db = get_db()
    agent = current_agent(db)
    reqs = []
    if agent['is_available']:
        for r in pending_requests(db, agent['id']):
            reqs.append({'row': r, 'payout': payout_for(agent['payment_method'], r['distance_km'] or 0,
                                                        r['estimated_delivery_time'] or 0)})
    earned = db.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE type = 'agent_payout' "
                        "AND user_id = ? AND date(created_at) = date('now')", (agent['id'],)).fetchone()[0]
    history = db.execute(
        "SELECT d.*, r.name AS rest_name FROM deliveries d JOIN orders o ON o.id = d.order_id "
        "JOIN restaurants r ON r.id = o.restaurant_id WHERE d.delivery_agent_id = ? "
        "AND d.status IN ('delivered', 'failed') ORDER BY d.id DESC LIMIT 10", (agent['id'],)).fetchall()
    return render_template('dashboard_delivery.html', agent=agent, requests=reqs, earned=earned,
                           active=active_delivery(db, agent['id']), history=history)


@app.route('/agent/settings', methods=['POST'])
@login_required('delivery_agent')
def agent_settings():
    db = get_db()
    method = request.form.get('payment_method')
    if method in PAY_RATES:
        db.execute('UPDATE users SET payment_method = ? WHERE id = ?', (method, session['user_id']))
        flash(f'Payment method set to: {PAY_LABELS[method].lower()}.', 'success')
    if request.form.get('toggle_available'):
        db.execute('UPDATE users SET is_available = 1 - is_available WHERE id = ?', (session['user_id'],))
    db.commit()
    return redirect(url_for('delivery_agent_dashboard'))


@app.route('/agent/request/<int:delivery_id>')
@login_required('delivery_agent')
def agent_request(delivery_id):
    db = get_db()
    agent = current_agent(db)
    req = next((r for r in pending_requests(db, agent['id']) if r['id'] == delivery_id), None)
    if not req:
        return render_template('agent_request.html', req=None)
    payout = payout_for(agent['payment_method'], req['distance_km'] or 0, req['estimated_delivery_time'] or 0)
    return render_template('agent_request.html', req=req, payout=payout, agent=agent,
                           map_url=map_service.get_navigation_url(req['rest_address']))


@app.route('/agent/request/<int:delivery_id>/accept', methods=['POST'])
@login_required('delivery_agent')
def agent_accept(delivery_id):
    db = get_db()
    agent = current_agent(db)
    if active_delivery(db, agent['id']):
        flash('Finish your current delivery before accepting another one.', 'error')
        return redirect(url_for('delivery_agent_dashboard'))
    row = db.execute('SELECT d.*, o.estimated_delivery_time, o.user_id, o.id AS oid, o.restaurant_id '
                     'FROM deliveries d JOIN orders o ON o.id = d.order_id WHERE d.id = ?', (delivery_id,)).fetchone()
    if not row:
        abort(404)
    payout = payout_for(agent['payment_method'], row['distance_km'] or 0, row['estimated_delivery_time'] or 0)
    # Atomic claim: only one agent can win, everyone else sees "request is gone".
    cur = db.execute(
        "UPDATE deliveries SET status = 'accepted', delivery_agent_id = ?, delivery_agent_name = ?, payout = ?, "
        "payment_method = ? WHERE id = ? AND status = 'pending' AND delivery_agent_id IS NULL",
        (agent['id'], agent['name'], payout, agent['payment_method'], delivery_id))
    if cur.rowcount != 1:
        db.rollback()
        return render_template('agent_request.html', req=None)
    notify(db, row['user_id'], f"Order #{row['oid']}: {agent['name']} will deliver your order.")
    notify_restaurant(db, row['restaurant_id'], f"Order #{row['oid']}: {agent['name']} accepted the delivery.")
    db.commit()
    flash('Delivery accepted.', 'success')
    return redirect(url_for('agent_active'))


@app.route('/agent/request/<int:delivery_id>/reject', methods=['POST'])
@login_required('delivery_agent')
def agent_reject(delivery_id):
    db = get_db()
    row = db.execute("SELECT d.*, o.restaurant_id, o.id AS oid FROM deliveries d JOIN orders o ON o.id = d.order_id "
                     "WHERE d.id = ? AND d.status = 'pending'", (delivery_id,)).fetchone()
    if row:
        db.execute('INSERT OR IGNORE INTO delivery_rejections (delivery_id, agent_id) VALUES (?,?)',
                   (delivery_id, session['user_id']))
        agents = db.execute("SELECT COUNT(*) FROM users WHERE role = 'delivery_agent'").fetchone()[0]
        rejected = db.execute('SELECT COUNT(*) FROM delivery_rejections WHERE delivery_id = ?', (delivery_id,)).fetchone()[0]
        if rejected >= agents:               # every agent said no: the restaurant must deliver itself
            db.execute("UPDATE deliveries SET status = 'restaurant_fallback' WHERE id = ?", (delivery_id,))
            notify_restaurant(db, row['restaurant_id'],
                              f"Order #{row['oid']}: no delivery agent is available. Please deliver it yourself.")
        db.commit()
    flash('Request rejected. Other agents will get it instead.', 'success')
    return redirect(url_for('delivery_agent_dashboard'))


@app.route('/agent/active')
@login_required('delivery_agent')
def agent_active():
    db = get_db()
    active = active_delivery(db, session['user_id'])
    if not active:
        flash('You have no active delivery.', 'error')
        return redirect(url_for('delivery_agent_dashboard'))
    return render_template('agent_active.html', d=active, reasons=FAIL_REASONS,
                           map_url=map_service.get_navigation_url(active['rest_address']))


STEP_FLOW = {'arrive': ('accepted', 'at_restaurant'), 'pickup': ('at_restaurant', 'picked_up'),
             'onway': ('picked_up', 'on_the_way')}


@app.route('/agent/active/<action>', methods=['POST'])
@login_required('delivery_agent')
def agent_step(action):
    db = get_db()
    d = active_delivery(db, session['user_id'])
    if not d:
        abort(404, 'No active delivery.')
    order = db.execute('SELECT * FROM orders WHERE id = ?', (d['order_id'],)).fetchone()

    if action in STEP_FLOW and d['status'] == STEP_FLOW[action][0]:
        if action == 'pickup':
            if d['order_status'] != 'ready':
                flash('The order is not ready yet. Wait for the restaurant to mark it ready.', 'error')
                return redirect(url_for('agent_active'))
            db.execute("UPDATE orders SET status = 'out_for_delivery' WHERE id = ?", (d['order_id'],))
            notify(db, order['user_id'], f"Order #{d['order_id']} is out for delivery.")
        db.execute('UPDATE deliveries SET status = ? WHERE id = ?', (STEP_FLOW[action][1], d['id']))
        db.commit()
        return redirect(url_for('agent_active'))

    if action == 'delivered' and d['status'] in ('picked_up', 'on_the_way'):
        db.execute("UPDATE deliveries SET status = 'delivered', completed_at = CURRENT_TIMESTAMP WHERE id = ?", (d['id'],))
        db.execute("UPDATE orders SET status = 'delivered' WHERE id = ?", (d['order_id'],))
        pay_restaurant(db, order)
        ok, _ = wallet_service.credit(str(session['user_id']), d['payout'], f"agent:{d['id']}")
        if ok:
            db.execute("INSERT INTO transactions (order_id, restaurant_id, amount, type, payment_method, user_id) "
                       "VALUES (?,?,?,'agent_payout','wallet',?)",
                       (d['order_id'], order['restaurant_id'], d['payout'], session['user_id']))
        notify(db, order['user_id'], f"Order #{d['order_id']} was delivered. Please confirm you received it.")
        db.commit()
        return redirect(url_for('agent_done', delivery_id=d['id']))

    flash('That step is not possible right now.', 'error')
    return redirect(url_for('agent_active'))


@app.route('/agent/active/fail', methods=['POST'])
@login_required('delivery_agent')
def agent_fail():
    db = get_db()
    d = active_delivery(db, session['user_id'])
    if not d:
        abort(404, 'No active delivery.')
    reason = request.form.get('reason')
    if reason not in FAIL_REASONS:
        flash('Pick a reason.', 'error')
        return redirect(url_for('agent_active'))
    detail = (request.form.get('details') or '').strip()[:200]
    order = db.execute('SELECT * FROM orders WHERE id = ?', (d['order_id'],)).fetchone()
    db.execute("UPDATE deliveries SET status = 'failed', fail_reason = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?",
               (f'{reason}. {detail}'.strip(), d['id']))
    db.execute("UPDATE orders SET status = 'delivery_failed' WHERE id = ?", (d['order_id'],))   # never marked delivered
    refund_order(db, order, f'could not be delivered ({reason.lower()})')
    notify_restaurant(db, order['restaurant_id'], f"Order #{order['id']} could not be delivered: {reason}.")
    db.commit()
    flash('Problem reported. This order will not be marked as delivered.', 'success')
    return redirect(url_for('delivery_agent_dashboard'))


@app.route('/agent/done/<int:delivery_id>')
@login_required('delivery_agent')
def agent_done(delivery_id):
    db = get_db()
    d = db.execute(
        "SELECT d.*, r.name AS rest_name, o.delivery_address FROM deliveries d JOIN orders o ON o.id = d.order_id "
        "JOIN restaurants r ON r.id = o.restaurant_id WHERE d.id = ? AND d.delivery_agent_id = ? "
        "AND d.status = 'delivered'", (delivery_id, session['user_id'])).fetchone()
    if not d:
        abort(404)
    return render_template('agent_done.html', d=d)


init_database()

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1',
            host=os.environ.get('ORDERFOOD_HOST', '127.0.0.1'),
            port=int(os.environ.get('ORDERFOOD_PORT', 9000)))
