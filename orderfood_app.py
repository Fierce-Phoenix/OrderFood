"""
OrderFood - Flask-based food ordering platform.

Roles: customer, restaurant_admin, delivery_agent.
Run:   python orderfood_app.py      (http://127.0.0.1:9000)
<<<<<<< HEAD
Reset: delete orderfood.db, then start again.
"""

import functools
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import random

import razorpay
import requests
from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
=======
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
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
                   session, url_for)
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

<<<<<<< HEAD
import maps_service                                    # Google Maps Platform (see maps_service.py)
maps_service.load_dotenv(os.path.join(BASE_DIR, '.env'))   # GOOGLE_MAPS_API_KEY etc.

app = Flask(__name__)
app.config['DATABASE'] = os.environ.get('ORDERFOOD_DB', os.path.join(BASE_DIR, 'orderfood.db'))
app.config['LEGACY_WALLET_FILE'] = os.environ.get('ORDERFOOD_WALLET', os.path.join(BASE_DIR, 'wallet.json'))
_deployment_environment = (os.environ.get('ORDERFOOD_ENV') or 'development').strip().lower()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=_deployment_environment in {'production', 'prod'},
)


def _load_secret_key():
    """Load the session-signing key without silently creating one in production.

    Local development gets a persistent, owner-readable-only key file. Deployments must
    provide ORDERFOOD_SECRET_KEY through their secret manager or process environment.
    """
    key = (os.environ.get('ORDERFOOD_SECRET_KEY') or '').strip()
    environment = (os.environ.get('ORDERFOOD_ENV') or 'development').strip().lower()
    if key:
        if environment in {'production', 'prod'} and len(key) < 32:
            raise RuntimeError('ORDERFOOD_SECRET_KEY must contain at least 32 characters in production.')
        return key

    if environment in {'production', 'prod'}:
        raise RuntimeError('Set ORDERFOOD_SECRET_KEY before starting OrderFood in production.')

    path = os.path.join(BASE_DIR, '.secret_key')
    try:
        # Exclusive creation avoids two first-start processes overwriting each other's key.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with open(path, encoding='utf-8') as f:
            key = f.read().strip()
        if not key:
            raise RuntimeError(f'The development secret-key file is empty: {path}')
        return key
    else:
        key = secrets.token_hex(32)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(key)
        return key
=======
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
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5


app.secret_key = _load_secret_key()

MAX_DELIVERY_MINUTES = 30
<<<<<<< HEAD
PICKUP_BUFFER_MIN = 10          # restaurant prep / handover time added to the drive time
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
STARTING_CUSTOMER_BALANCE = 650.0
PAY_RATES = {'per_order': 40, 'per_km': 10, 'per_min': 2}      # rupees
PAY_LABELS = {'per_order': 'Per order', 'per_km': 'Per kilometre', 'per_min': 'Per minute'}
OPEN_ORDER_STATES = ('pending', 'preparing', 'ready', 'out_for_delivery', 'delivered')
ACTIVE_DELIVERY_STATES = ('accepted', 'at_restaurant', 'picked_up', 'on_the_way')
FAIL_REASONS = ['Customer not reachable', 'Wrong address', 'Order damaged', 'Other']
ROLES = {'customer', 'restaurant_admin', 'delivery_agent'}
<<<<<<< HEAD
FOOD_CATEGORIES = [
    'Appetizers', 'Main Course', 'Rice & Biryani', 'Breads', 'Sides',
    'Breakfast', 'Desserts', 'Drinks',
]
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5


# ---------------------------------------------------------------------------
# Third-party service mocks
# ---------------------------------------------------------------------------

<<<<<<< HEAD
class SqlWalletService:
    """SQLite-backed wallet balances and idempotent wallet operations."""

    def __init__(self, database):
        self.database = database

    def _connect(self):
        conn = sqlite3.connect(self.database, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        return conn

    def ensure(self, key, initial=0.0):
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    'INSERT OR IGNORE INTO wallets (user_id, balance, currency) VALUES (?,?,?)',
                    (int(key), round(float(initial), 2), 'INR'))
        finally:
            conn.close()

    def get_balance(self, key):
        conn = self._connect()
        try:
            wallet = conn.execute('SELECT balance, currency FROM wallets WHERE user_id = ?',
                                  (int(key),)).fetchone()
            return dict(wallet) if wallet else {'balance': 0.0, 'currency': 'INR'}
        finally:
            conn.close()

    def _apply(self, key, amount, sign, ref, op, db=None):
        try:
            amount = round(float(amount), 2)
            user_id = int(key)
        except (TypeError, ValueError):
            return False, 'Invalid amount or user'
        if not math.isfinite(amount) or amount <= 0:
            return False, 'Invalid amount'
        owns_connection = db is None
        conn = db or self._connect()
        try:
            if owns_connection:
                conn.execute('BEGIN IMMEDIATE')
            conn.execute('SAVEPOINT wallet_change')
            if ref and conn.execute(
                    'SELECT 1 FROM wallet_operations WHERE operation = ? AND reference = ?',
                    (op, ref)).fetchone():
                conn.execute('ROLLBACK TO wallet_change')
                conn.execute('RELEASE wallet_change')
                if owns_connection:
                    conn.commit()
                return True, 'Duplicate request ignored'
            wallet = conn.execute('SELECT balance FROM wallets WHERE user_id = ?',
                                  (user_id,)).fetchone()
            if wallet is None:
                conn.execute('ROLLBACK TO wallet_change')
                conn.execute('RELEASE wallet_change')
                if owns_connection:
                    conn.rollback()
                return False, 'Wallet not found'
            if sign < 0 and wallet['balance'] + 1e-9 < amount:
                conn.execute('ROLLBACK TO wallet_change')
                conn.execute('RELEASE wallet_change')
                if owns_connection:
                    conn.rollback()
                return False, 'Insufficient Funds'
            balance = round(wallet['balance'] + sign * amount, 2)
            conn.execute('UPDATE wallets SET balance = ? WHERE user_id = ?', (balance, user_id))
            conn.execute('INSERT INTO wallet_operations (user_id, operation, reference, amount) '
                         'VALUES (?,?,?,?)', (user_id, op, ref, amount))
            conn.execute('RELEASE wallet_change')
            if owns_connection:
                conn.commit()
            return True, 'Success'
        except sqlite3.IntegrityError:
            conn.execute('ROLLBACK TO wallet_change')
            conn.execute('RELEASE wallet_change')
            if owns_connection:
                conn.rollback()
            if ref and conn.execute(
                    'SELECT 1 FROM wallet_operations WHERE operation = ? AND reference = ?',
                    (op, ref)).fetchone():
                return True, 'Duplicate request ignored'
            raise
        finally:
            if owns_connection:
                conn.close()

    def deduct(self, key, amount, ref=None, db=None):
        return self._apply(key, amount, -1, ref, 'deduct', db)

    def credit(self, key, amount, ref=None, db=None):
        return self._apply(key, amount, +1, ref, 'credit', db)


wallet_service = SqlWalletService(app.config['DATABASE'])
map_service = maps_service.GoogleMapsService()
=======
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
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5


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
<<<<<<< HEAD
    ('Annapurna Meals', 'Mumbai', 'Authentic North Indian Thalis', 0),
    ('Spice Route Biryani', 'Mumbai', 'Hyderabadi and Lucknowi Biryanis', 0),
    ('Green Bowl Salads', 'Mumbai', 'Fresh organic salads and wraps', 0),
    ('Coastal Kitchen', 'Far Away', 'Premium Seafood and Coastal Delicacies', 0),
    ('The Burger Joint', 'Mumbai', 'Gourmet burgers and loaded fries', 0),
    ('Pizza Planet', 'Mumbai', 'Authentic Neapolitan style pizzas', 0),
    ('Sushi Zen', 'Mumbai', 'Fresh premium sushi and sashimi', 0),
    ('Taco Town', 'Mumbai', 'Street style Mexican tacos', 0),
    ('Wok Express', 'Mumbai', 'Fast and fiery Asian stir-fry', 0),
    ('Pasta Palace', 'Mumbai', 'Handmade Italian pasta', 0),
    ('Desert Delight', 'Mumbai', 'Exotic Middle Eastern sweets', 0),
    ('Kebab Kingdom', 'Mumbai', 'Char-grilled tandoori specialties', 0),
    ('The Pancake House', 'Mumbai', 'Fluffy pancakes and waffles', 0),
    ('Dim Sum Dynasty', 'Mumbai', 'Hand-crafted dumplings', 0),
    ('Mediterranean Magic', 'Mumbai', 'Hummus, Pita and Falafel', 0),
    ('Juice Junction', 'Mumbai', 'Fresh cold-pressed juices', 0),
    ('The Steakhouse', 'Mumbai', 'Premium cuts and grilled sides', 0),
    ('Noodle Nation', 'Mumbai', 'Authentic Ramen and Udon', 0),
    ('Bake Street', 'Mumbai', 'Artisan breads and pastries', 0),
    ('Curry Corner', 'Mumbai', 'Homestyle Indian curries', 0),
    ('Samosa Station', 'Mumbai', 'Crispy samosas and chai', 0),
    ('The Vegan Hub', 'Mumbai', '100% plant-based delicacies', 0),
=======
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
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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


<<<<<<< HEAD
def restaurant_area_plan(rng):
    areas = [
        *[maps_service.RESTAURANT_AREAS[0]] * 7,
        *[maps_service.RESTAURANT_AREAS[1]] * 4,
        *[maps_service.RESTAURANT_AREAS[2]] * 4,
        *[maps_service.RESTAURANT_AREAS[3]] * 3,
        *[maps_service.RESTAURANT_AREAS[4]] * 2,
        maps_service.RESTAURANT_AREAS[5],
        maps_service.RESTAURANT_AREAS[6],
    ]
    rng.shuffle(areas)
    return areas


def migrate_restaurant_locations(cur):
    """Relocate the existing catalog once; later owner-edited locations remain untouched."""
    version = cur.execute(
        "SELECT value FROM app_metadata WHERE key = 'restaurant_locations_thane_mulund_v1'").fetchone()
    if version:
        return
    rng = random.Random()
    areas = restaurant_area_plan(rng)
    restaurants = cur.execute('SELECT id FROM restaurants ORDER BY id').fetchall()
    for index, (restaurant_id,) in enumerate(restaurants):
        label, lat, lon = map_service.random_spot(areas[index % len(areas)], rng)
        cur.execute('UPDATE restaurants SET lat = ?, lon = ?, address = ? WHERE id = ?',
                    (lat, lon, label, restaurant_id))
    cur.execute("INSERT INTO app_metadata (key, value) "
                "VALUES ('restaurant_locations_thane_mulund_v1', '1')")


def backfill_locations(cur):
    """Give restaurants and delivery drivers without a location a random regional spot."""
    rng = random.Random()
    areas = restaurant_area_plan(rng)
    rests = cur.execute('SELECT id, name, address FROM restaurants WHERE lat IS NULL OR lon IS NULL').fetchall()
    for n, (rid, _name, addr) in enumerate(rests):
        label, lat, lon = map_service.random_spot(areas[n % len(areas)], rng)
        pretty = map_service.reverse_geocode(lat, lon)
        generic = (addr or '').strip().lower() in ('', 'mumbai', 'far away')
        cur.execute('UPDATE restaurants SET lat = ?, lon = ?, address = ? WHERE id = ?',
                    (lat, lon, (pretty or label) if generic else addr, rid))
    for (uid,) in cur.execute("SELECT id FROM users WHERE role = 'delivery_agent' AND (lat IS NULL OR lon IS NULL)").fetchall():
        label, lat, lon = map_service.random_spot(rng=rng)
        cur.execute('UPDATE users SET lat = ?, lon = ?, location_address = ?, location_updated_at = CURRENT_TIMESTAMP '
                    'WHERE id = ?', (lat, lon, map_service.reverse_geocode(lat, lon) or label, uid))


def migrate_legacy_wallet_file(cur):
    """Import balances and idempotency records from the former JSON wallet store."""
    path = app.config['LEGACY_WALLET_FILE']
    if not os.path.exists(path):
        return False
    if cur.execute("SELECT 1 FROM app_metadata WHERE key = 'legacy_wallet_migrated'").fetchone():
        return True
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'Legacy wallet file is not valid JSON: {path}') from exc
    if not isinstance(data, dict):
        raise RuntimeError(f'Legacy wallet file has an invalid format: {path}')

    restaurant_users = {}
    for row in cur.execute(
            "SELECT restaurant_id, id FROM users WHERE role = 'restaurant_admin' ORDER BY id"):
        restaurant_users.setdefault(row[0], row[1])

    def account_id(wallet_key):
        if wallet_key == '_processed':
            return None
        if wallet_key.startswith('rest_'):
            try:
                rid = int(wallet_key[5:])
            except ValueError as exc:
                raise RuntimeError(f'Invalid legacy restaurant wallet identity: {wallet_key}') from exc
            user_id = restaurant_users.get(rid)
        else:
            try:
                user_id = int(wallet_key)
            except ValueError as exc:
                raise RuntimeError(f'Invalid legacy wallet identity: {wallet_key}') from exc
            exists = cur.execute('SELECT 1 FROM users WHERE id = ?', (user_id,)).fetchone()
            if not exists:
                user_id = None
        if user_id is None:
            raise RuntimeError(f'No user account exists for legacy wallet identity: {wallet_key}')
        return user_id

    for wallet_key, wallet in data.items():
        if wallet_key == '_processed':
            continue
        if not isinstance(wallet, dict):
            raise RuntimeError(f'Legacy wallet entry is invalid: {wallet_key}')
        try:
            balance = float(wallet['balance'])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f'Legacy wallet balance is invalid: {wallet_key}') from exc
        if not math.isfinite(balance) or balance < 0:
            raise RuntimeError(f'Legacy wallet balance is invalid: {wallet_key}')
        cur.execute('INSERT INTO wallets (user_id, balance, currency) VALUES (?,?,?) '
                    'ON CONFLICT(user_id) DO UPDATE SET '
                    'balance = wallets.balance + excluded.balance, currency = excluded.currency',
                    (account_id(wallet_key), balance, wallet.get('currency') or 'INR'))

    processed = data.get('_processed', {})
    if not isinstance(processed, dict):
        raise RuntimeError('Legacy wallet operation history has an invalid format.')
    for operation_ref, details in processed.items():
        operation, separator, reference = operation_ref.partition(':')
        if not separator or operation not in ('credit', 'deduct') or not reference:
            raise RuntimeError(f'Invalid legacy wallet operation reference: {operation_ref}')
        if not isinstance(details, dict):
            raise RuntimeError(f'Invalid legacy wallet operation: {operation_ref}')
        try:
            amount = float(details['amount'])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f'Invalid legacy wallet operation amount: {operation_ref}') from exc
        if not math.isfinite(amount) or amount <= 0:
            raise RuntimeError(f'Invalid legacy wallet operation amount: {operation_ref}')
        user_id = account_id(str(details.get('wallet', '')))
        cur.execute('INSERT OR IGNORE INTO wallet_operations (user_id, operation, reference, amount) '
                    'VALUES (?,?,?,?)', (user_id, operation, reference, amount))
    cur.execute("INSERT INTO app_metadata (key, value) VALUES ('legacy_wallet_migrated', '1')")
    return True


def migrate_menu_categories(cur):
    """Normalize old menu labels once, leaving future restaurant edits untouched."""
    version = cur.execute("SELECT value FROM app_metadata WHERE key = 'menu_categories_v3'").fetchone()
    if version:
        return

    rules = [
        ('Breakfast', ('pancake', 'waffle', 'breakfast', 'omelette')),
        ('Drinks', ('drink', 'coffee', 'tea', 'chai', 'juice', 'lassi', 'chaas',
                    'lemonade', 'milkshake', 'smoothie', 'soda')),
        ('Desserts', ('dessert', 'sweet', 'cake', 'pastry', 'brownie', 'ice cream',
                      'kulfi', 'gulab', 'phirni', 'halwa', 'treat')),
        ('Rice & Biryani', ('biryani', 'rice', 'pulao')),
        ('Breads', ('naan', 'roti', 'paratha', 'pita', 'bread')),
        ('Sides', ('raita', 'fries', 'side', 'dip', 'chutney', 'sauce')),
        ('Appetizers', ('starter', 'appetizer', 'salad', 'soup', 'samosa',
                        'dumpling', 'dim sum', 'spring roll', 'prawn fry', 'fish fry', 'kebab')),
    ]
    for item_id, name, category in cur.execute(
            'SELECT id, name, category FROM menu_items').fetchall():
        normalized = (name or '').casefold()
        revised = next((category_name for category_name, terms in rules
                        if any(term in normalized for term in terms)), category)
        if revised not in FOOD_CATEGORIES:
            revised = 'Main Course'
        if revised != category:
            cur.execute('UPDATE menu_items SET category = ? WHERE id = ?', (revised, item_id))
    cur.execute("INSERT INTO app_metadata (key, value) VALUES ('menu_categories_v3', '1')")


=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
    CREATE TABLE IF NOT EXISTS wallets (
        user_id INTEGER PRIMARY KEY, balance REAL NOT NULL DEFAULT 0 CHECK (balance >= 0),
        currency TEXT NOT NULL DEFAULT 'INR',
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS wallet_operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        operation TEXT NOT NULL CHECK (operation IN ('credit', 'deduct')),
        reference TEXT, amount REAL NOT NULL CHECK (amount > 0),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (operation, reference),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS app_metadata (
        key TEXT PRIMARY KEY, value TEXT NOT NULL);
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
    CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL UNIQUE,
        restaurant_id INTEGER NOT NULL, user_id INTEGER NOT NULL, rating INTEGER NOT NULL,
        feedback TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS settlements (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        recipient_role TEXT NOT NULL CHECK (recipient_role IN ('restaurant', 'delivery_agent')),
        amount_paise INTEGER NOT NULL CHECK (amount_paise >= 0),
        status TEXT NOT NULL DEFAULT 'pending_setup', transfer_id TEXT, message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (order_id, recipient_role),
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE);
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
    ''')
    # Upgrade databases created by the older version of the app.
    for table, column, ddl in [
        ('restaurants', 'is_open', 'INTEGER DEFAULT 1'),
<<<<<<< HEAD
        ('restaurants', 'lat', 'REAL'),
        ('restaurants', 'lon', 'REAL'),
        ('restaurants', 'payout_account_id', 'TEXT'),
        ('users', 'lat', 'REAL'),
        ('users', 'lon', 'REAL'),
        ('users', 'location_address', 'TEXT'),
        ('users', 'location_updated_at', 'TIMESTAMP'),
        ('orders', 'dest_lat', 'REAL'),
        ('orders', 'dest_lon', 'REAL'),
        ('users', 'restaurant_id', 'INTEGER'),
        ('users', 'payment_method', "TEXT DEFAULT 'per_order'"),
        ('users', 'payout_account_id', 'TEXT'),
=======
        ('users', 'restaurant_id', 'INTEGER'),
        ('users', 'payment_method', "TEXT DEFAULT 'per_order'"),
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
        ('users', 'is_available', 'INTEGER DEFAULT 1'),
        ('users', 'accessibility_note', 'TEXT'),
        ('orders', 'user_id', 'INTEGER'),
        ('orders', 'payment_ref', 'TEXT'),
        ('deliveries', 'delivery_agent_id', 'INTEGER'),
        ('deliveries', 'distance_km', 'REAL'),
        ('deliveries', 'payout', 'REAL'),
        ('deliveries', 'payment_method', 'TEXT'),
        ('deliveries', 'fail_reason', 'TEXT'),
<<<<<<< HEAD
        ('deliveries', 'offer_agent_id', 'INTEGER'),
        ('deliveries', 'offer_expires_at', 'TIMESTAMP'),
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
        ('transactions', 'user_id', 'INTEGER'),
    ]:
        _ensure_column(cur, table, column, ddl)

<<<<<<< HEAD
    # Ratings on earlier versions were seeded sample values, not customer feedback.
    cur.execute('UPDATE restaurants SET rating = 0')

=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
            ('anna.admin@example.com', 'Anna Apple', 'AnnaAdmin123!', 'restaurant_admin', 1),
            ('david.agent@example.com', 'David Driver', 'DavidAgent123!', 'delivery_agent', None),
            ('customer@test.com', 'Demo Customer', 'password123', 'customer', None),
            ('admin@test.com', 'Burger Joint Owner', 'admin123', 'restaurant_admin', 5),
        ]
        cur.executemany('INSERT INTO users (email, name, password, role, restaurant_id) VALUES (?,?,?,?,?)',
                        [(e, n, generate_password_hash(p), r, rid) for e, n, p, r, rid in demo])
    cur.execute('DROP TABLE IF EXISTS geocode_cache')          # leftover from an older experiment
    migrate_restaurant_locations(cur)
    backfill_locations(cur)
    migrate_menu_categories(cur)
    legacy_wallet_file = migrate_legacy_wallet_file(cur)
    conn.commit()
    for uid, role in cur.execute('SELECT id, role FROM users').fetchall():
        wallet_service.ensure(uid, STARTING_CUSTOMER_BALANCE if role == 'customer' else 0.0)
    conn.close()
    if legacy_wallet_file:
        try:
            os.remove(app.config['LEGACY_WALLET_FILE'])
        except FileNotFoundError:
            pass
=======
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
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5


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
<<<<<<< HEAD
        if request.endpoint in {'api_create_order', 'api_verify_payment', 'api_cancel_order'} \
                and 'user_id' not in session:
            return
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
app.jinja_env.globals['FOOD_CATEGORIES'] = FOOD_CATEGORIES
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5


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


<<<<<<< HEAD
def login_required(role=None, need_location=True):
=======
def login_required(role=None):
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
    def wrapper(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                flash('Authentication required. Please log in.', 'error')
                return redirect(url_for('login'))
            if role and session.get('role') != role:
                flash('That page is not available for your account type.', 'error')
                return redirect(url_for(role_home(session.get('role'))))
<<<<<<< HEAD
            if need_location and session.get('role') == 'customer' and not session.get('loc_ok'):
                # Like Zomato/Swiggy: a customer must confirm where to deliver before browsing.
                return redirect(url_for('location', next=request.path) if request.method == 'GET'
                                else url_for('location'))
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
            return f(*args, **kwargs)
        return decorated
    return wrapper


def safe_next(default):
    nxt = request.form.get('next', '')
    return nxt if nxt.startswith('/') and not nxt.startswith('//') else default


def wallet_key():
<<<<<<< HEAD
    return session.get('user_id')
=======
    if session.get('role') == 'restaurant_admin':
        return f"rest_{session.get('restaurant_id')}"
    return str(session.get('user_id'))
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5


def notify(db, user_id, message):
    db.execute('INSERT INTO notifications (user_id, message) VALUES (?, ?)', (user_id, message))


def notify_restaurant(db, restaurant_id, message):
    for row in db.execute('SELECT id FROM users WHERE restaurant_id = ?', (restaurant_id,)):
        notify(db, row['id'], message)


<<<<<<< HEAD
=======
def notify_agents(db, message, exclude=()):
    for row in db.execute("SELECT id FROM users WHERE role = 'delivery_agent' AND is_available = 1"):
        if row['id'] not in exclude:
            notify(db, row['id'], message)


>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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


<<<<<<< HEAD
@app.context_processor
def inject_maps():
    return {'maps_cfg': map_service.browser_config(), 'maps_enabled': map_service.enabled}


=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
                _label, rlat, rlon = map_service.random_spot()      # adjustable later on the dashboard map
                rest_id = db.execute('INSERT INTO restaurants (name, address, description, lat, lon) VALUES (?,?,?,?,?)',
                                     (rest_name, rest_addr, 'New restaurant', rlat, rlon)).lastrowid
=======
                rest_id = db.execute('INSERT INTO restaurants (name, address, description) VALUES (?,?,?)',
                                     (rest_name, rest_addr, 'New restaurant')).lastrowid
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
            user_id = db.execute(
                'INSERT INTO users (email, name, password, role, restaurant_id, accessibility_note) '
                'VALUES (?,?,?,?,?,?)',
                (email, name, generate_password_hash(password), role, rest_id, note)).lastrowid
<<<<<<< HEAD
            if role == 'delivery_agent':
                label, alat, alon = map_service.random_spot()
                db.execute('UPDATE users SET lat = ?, lon = ?, location_address = ?, '
                           'location_updated_at = CURRENT_TIMESTAMP WHERE id = ?', (alat, alon, label, user_id))
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            flash('Email already registered.', 'error')
            return render_template('register.html'), 400

<<<<<<< HEAD
        wallet_service.ensure(user_id, STARTING_CUSTOMER_BALANCE if role == 'customer' else 0.0)
=======
        wallet_service.ensure(str(user_id), STARTING_CUSTOMER_BALANCE if role == 'customer' else 0.0)
        if rest_id:
            wallet_service.ensure(f'rest_{rest_id}', 0.0)
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
            if user['role'] == 'customer':
                session['loc_ok'] = False                    # must (re)confirm the location every login
                if user['lat'] is not None and user['lon'] is not None:
                    session['loc'] = [user['lat'], user['lon']]
                    session['address'] = user['location_address'] or ''
                return redirect(url_for('location'))
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
            return redirect(url_for(role_home(user['role'])))
        flash('Invalid email or password.', 'error')
    return render_template('login.html')


<<<<<<< HEAD
@app.route('/location', methods=['GET', 'POST'])
@login_required('customer', need_location=False)
def location():
    """Ask the customer where to deliver (search box, 'use my location', or drag the pin)."""
    db = get_db()
    if request.method == 'POST':
        point = maps_service.valid_point(request.form.get('lat'), request.form.get('lon'))
        address = (request.form.get('address') or '').strip()[:200]
        if not point:                                            # no-JS / no-key fallback: pick an area
            area = map_service.area_by_name(request.form.get('area', ''))
            if area:
                point = (area[1], area[2])
                address = address or (area[0] if ', ' in area[0] else f'{area[0]}, Mumbai')
        if not point:
            flash('Please choose your delivery location on the map or pick an area.', 'error')
            return redirect(url_for('location'))
        address = address or f'Pinned location ({point[0]:.4f}, {point[1]:.4f})'
        db.execute('UPDATE users SET lat = ?, lon = ?, location_address = ?, location_updated_at = CURRENT_TIMESTAMP '
                   'WHERE id = ?', (point[0], point[1], address, session['user_id']))
        db.commit()
        session['loc'], session['address'], session['loc_ok'] = [point[0], point[1]], address, True
        return redirect(safe_next(url_for('home')))
    saved = session.get('loc')
    nxt = request.args.get('next', '')
    return render_template('location.html', saved=saved, address=session.get('address', ''),
                           areas=maps_service.AREAS, next=nxt if nxt.startswith('/') and not nxt.startswith('//') else '')


=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Customer: browsing
# ---------------------------------------------------------------------------

<<<<<<< HEAD
def customer_point():
    loc = session.get('loc')
    return (loc[0], loc[1]) if loc else None


def eta_for_restaurants(rows):
    """{restaurant_id: {'minutes', 'km', 'source'}} from each restaurant to the customer's confirmed
    location. 'minutes' is the whole promise: drive time + PICKUP_BUFFER_MIN. Rows need id/lat/lon."""
    dest = customer_point()
    points = {r['id']: (r['lat'], r['lon']) for r in rows if r['lat'] is not None and r['lon'] is not None}
    drive = map_service.deliveries_eta(points, dest) if dest and points else {}
    out = {}
    for r in rows:
        e = drive.get(r['id'])
        out[r['id']] = ({'minutes': math.ceil(e['minutes']) + PICKUP_BUFFER_MIN, 'km': e['km'], 'source': e['source']}
                        if e else {'minutes': 999, 'km': None, 'source': 'none'})   # no location -> unreachable
    if map_service.enabled and map_service.last_error and not session.get('maps_warned'):
        session['maps_warned'] = True
        flash('Live Google Maps data is unavailable right now, so delivery times are approximate.', 'warning')
    return out
=======
def restaurant_with_time(row):
    try:
        # In a real app, we'd use session['address'] if available
        customer_addr = session.get('address')
        return map_service.calculate_delivery_time(row['id'], row['address'], customer_addr)
    except Exception as e:
        # SOP 2: Handle map service failures gracefully
        flash(f"Map service error: {str(e)}. Using estimated defaults.", "warning")
        return 20 # Fallback default
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5


@app.route('/')
@login_required('customer')
def home():
    db = get_db()
    q = (request.args.get('q') or '').strip()
<<<<<<< HEAD
    review_fields = (
        "(SELECT COALESCE(AVG(rv.rating), 0) FROM reviews rv WHERE rv.restaurant_id = r.id) "
        "AS feedback_rating, (SELECT COUNT(*) FROM reviews rv WHERE rv.restaurant_id = r.id) "
        "AS review_count"
    )
    sql, params = (
        f'SELECT r.*, {review_fields}, NULL AS matched_items FROM restaurants r WHERE r.is_active = 1', [])
    if q:
        like = f'%{q}%'
        item_match = "(m.name LIKE ? OR COALESCE(m.description, '') LIKE ? OR COALESCE(m.category, '') LIKE ?)"
        sql = (
            f"SELECT r.*, {review_fields}, (SELECT group_concat(m.name, ', ') FROM menu_items m "
            f"WHERE m.restaurant_id = r.id AND {item_match}) AS matched_items "
            f"FROM restaurants r WHERE r.is_active = 1 AND "
            f"(r.name LIKE ? OR COALESCE(r.description, '') LIKE ? OR EXISTS "
            f"(SELECT 1 FROM menu_items m WHERE m.restaurant_id = r.id AND {item_match}))"
        )
        params = [like] * 8
    reachable, too_far = [], []
    rows = db.execute(sql + ' ORDER BY feedback_rating DESC, r.name', params).fetchall()
    etas = eta_for_restaurants(rows)
    for r in rows:
        e = etas[r['id']]
        (reachable if e['minutes'] <= MAX_DELIVERY_MINUTES else too_far).append((r, e['minutes'], e['km']))
=======
    sql, params = 'SELECT * FROM restaurants WHERE is_active = 1', []
    if q:
        sql += ' AND (name LIKE ? OR description LIKE ?)'
        params += [f'%{q}%', f'%{q}%']
    reachable, too_far = [], []
    for r in db.execute(sql + ' ORDER BY rating DESC', params):
        minutes = restaurant_with_time(r)
        (reachable if minutes <= MAX_DELIVERY_MINUTES else too_far).append((r, minutes))
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
    rating = db.execute(
        'SELECT COALESCE(AVG(rating), 0) AS average, COUNT(*) AS count FROM reviews WHERE restaurant_id = ?',
        (rest_id,)).fetchone()
    reviews = db.execute(
        'SELECT rv.*, u.name AS customer_name FROM reviews rv JOIN users u ON u.id = rv.user_id '
        'WHERE rv.restaurant_id = ? ORDER BY rv.id DESC LIMIT 20', (rest_id,)).fetchall()
    items = db.execute('SELECT * FROM menu_items WHERE restaurant_id = ? ORDER BY category, id',
                       (rest_id,)).fetchall()
    est = eta_for_restaurants([rest])[rest['id']]
    minutes = est['minutes']
    return render_template('restaurant_detail.html', restaurant=rest, menu_items=items,
                           feedback_rating=rating['average'], review_count=rating['count'], reviews=reviews,
                           delivery_time=minutes, distance_km=est['km'], too_far=minutes > MAX_DELIVERY_MINUTES,
=======
    items = db.execute('SELECT * FROM menu_items WHERE restaurant_id = ? ORDER BY category, id',
                       (rest_id,)).fetchall()
    minutes = restaurant_with_time(rest)
    return render_template('restaurant_detail.html', restaurant=rest, menu_items=items,
                           delivery_time=minutes, too_far=minutes > MAX_DELIVERY_MINUTES,
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
        f'SELECT m.*, r.name AS rest_name, r.address AS rest_address, r.lat AS rest_lat, r.lon AS rest_lon, r.is_open, r.is_active '
=======
        f'SELECT m.*, r.name AS rest_name, r.address AS rest_address, r.is_open, r.is_active '
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
        f'FROM menu_items m JOIN restaurants r ON r.id = m.restaurant_id WHERE m.id IN ({marks})', ids).fetchall()
    found = {str(r['id']) for r in rows}
    if found != set(cart):                       # item was deleted by the restaurant
        session['cart'] = {k: v for k, v in cart.items() if k in found}
<<<<<<< HEAD
    etas = eta_for_restaurants([{'id': r['restaurant_id'], 'lat': r['rest_lat'], 'lon': r['rest_lon']} for r in rows])
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
    groups = {}
    for r in rows:
        qty = cart[str(r['id'])]
        grp = groups.setdefault(r['restaurant_id'], {
            'restaurant_id': r['restaurant_id'], 'name': r['rest_name'], 'items': [], 'subtotal': 0,
<<<<<<< HEAD
            'minutes': etas[r['restaurant_id']]['minutes'], 'km': etas[r['restaurant_id']]['km'],
=======
            'minutes': map_service.calculate_delivery_time(r['restaurant_id'], r['rest_address'], session.get('address')),
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
        'SELECT m.*, r.address, r.lat, r.lon, r.is_open, r.is_active FROM menu_items m '
=======
        'SELECT m.*, r.address, r.is_open, r.is_active FROM menu_items m '
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
        'JOIN restaurants r ON r.id = m.restaurant_id WHERE m.id = ?',
        (request.form.get('item_id', type=int),)).fetchone()
    back = safe_next(url_for('view_cart'))
    if not item or not item['is_active']:
        flash('That item does not exist.', 'error')
    elif not item['is_available']:
        flash(f"{item['name']} is sold out.", 'error')
    elif not item['is_open']:
        flash('That restaurant is currently closed.', 'error')
<<<<<<< HEAD
    elif eta_for_restaurants([{'id': item['restaurant_id'], 'lat': item['lat'], 'lon': item['lon']}])[
            item['restaurant_id']]['minutes'] > MAX_DELIVERY_MINUTES:
=======
    elif map_service.calculate_delivery_time(item['restaurant_id'], item['address'], session.get('address')) > MAX_DELIVERY_MINUTES:
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
    intent = session.get('razorpay_intent')
    token = session.get('checkout_token') if intent else None
    if not token:
        token = secrets.token_hex(8)
        session['checkout_token'] = token
    return render_template('checkout.html', groups=groups, total=total, balance=balance, token=token,
                           address=session.get('address', ''),
                           razorpay_key_id=os.environ.get('RAZORPAY_KEY_ID', '').strip(),
                           customer_email=session.get('email', ''),
                           pending_razorpay_order_id=intent.get('order_id') if intent else '')


def place_order(db, user_id, email, group, address, ref, point=None, payment_method='wallet',
                charge_wallet=True, commit=True):
=======
    token = secrets.token_hex(8)
    session['checkout_token'] = token
    return render_template('checkout.html', groups=groups, total=total, balance=balance, token=token,
                           address=session.get('address', ''))


def place_order(db, user_id, email, group, address, ref):
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
    """Create one order and take its payment. Returns (ok, message, order_id)."""
    try:
        cur = db.execute(
            "INSERT INTO orders (restaurant_id, user_id, customer_email, delivery_address, total_amount, "
<<<<<<< HEAD
            "status, estimated_delivery_time, payment_ref, dest_lat, dest_lon) VALUES (?,?,?,?,?,'pending',?,?,?,?)",
            (group['restaurant_id'], user_id, email, address, group['subtotal'], group['minutes'], ref,
             point[0] if point else None, point[1] if point else None))
=======
            "status, estimated_delivery_time, payment_ref) VALUES (?,?,?,?,?,'pending',?,?)",
            (group['restaurant_id'], user_id, email, address, group['subtotal'], group['minutes'], ref))
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
        order_id = cur.lastrowid
        db.executemany('INSERT INTO order_items (order_id, item_id, name, price, qty) VALUES (?,?,?,?,?)',
                       [(order_id, i['id'], i['name'], i['price'], i['qty']) for i in group['items']])
        db.execute("INSERT INTO transactions (order_id, restaurant_id, amount, type, payment_method, user_id) "
<<<<<<< HEAD
                   "VALUES (?,?,?,'payment',?,?)",
                   (order_id, group['restaurant_id'], group['subtotal'], payment_method, user_id))
        db.execute("INSERT INTO deliveries (order_id, delivery_agent_name, status, distance_km) "
                   "VALUES (?, 'Unassigned', 'not_requested', ?)",
                   (order_id, group.get('km') or 0.5))
=======
                   "VALUES (?,?,?,'payment','wallet',?)", (order_id, group['restaurant_id'], group['subtotal'], user_id))
        db.execute("INSERT INTO deliveries (order_id, delivery_agent_name, status, distance_km) "
                   "VALUES (?, 'Unassigned', 'not_requested', ?)",
                   (order_id, map_service.distance_km(group['minutes'])))
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
    except sqlite3.Error as exc:
        db.rollback()
        return False, f'System error: {exc}', None

<<<<<<< HEAD
    if charge_wallet:
        ok, msg = wallet_service.deduct(user_id, group['subtotal'], ref, db=db)
        if not ok:
            db.rollback()                               # nothing saved, nothing charged
            return False, msg, None
    try:
        notify_restaurant(db, group['restaurant_id'],
                          f"New order #{order_id} - {group['subtotal']:.0f} paid.")
        if commit:
            db.commit()
    except sqlite3.Error as exc:
        db.rollback()
        return False, f'System error, payment was not recorded: {exc}', None
    return True, 'Paid, order placed', order_id


def razorpay_credentials():
    return (os.environ.get('RAZORPAY_KEY_ID', '').strip(),
            os.environ.get('RAZORPAY_KEY_SECRET', '').strip())


def api_customer_error():
    if 'user_id' not in session:
        return jsonify(error='Authentication required. Please log in.'), 401
    if session.get('role') != 'customer':
        return jsonify(error='Only customers can make payments.'), 403
    return None


def checkout_fingerprint(cart):
    encoded = json.dumps(cart, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def razorpay_payment_response(order_id, payment_id, existing=None):
    """Create the restaurant orders for one verified Razorpay payment."""
    db = get_db()
    uid = session['user_id']
    if existing is not None:
        session.pop('razorpay_intent', None)
        return jsonify(success=True, order_ids=[row['id'] for row in existing],
                       redirect_url=url_for('orders', order=existing[0]['id']))

    intent = session.get('razorpay_intent')
    if not intent or intent.get('order_id') != order_id or intent.get('user_id') != uid:
        return jsonify(error='This payment session has expired. Check your orders before retrying.'), 400

    cart = dict(session.get('cart', {}))
    groups = cart_groups(db)
    if not groups or any(group['problems'] for group in groups):
        return jsonify(error='Your cart has changed or is no longer available. Contact support if payment was captured.'), 409
    amount_paise = int(round(sum(group['subtotal'] for group in groups) * 100))
    if (amount_paise != intent['amount'] or
            checkout_fingerprint(cart) != intent['cart_fingerprint']):
        return jsonify(error='Your cart changed after payment started. Contact support if payment was captured.'), 409
    if open_orders_for(db, uid):
        return jsonify(error='An order is already active. Contact support if payment was captured.'), 409

    address = intent['address']
    point = intent['point']
    results = []
    for group in groups:
        payment_ref = f'razorpay:{order_id}:{payment_id}:{group["restaurant_id"]}'
        ok, message, new_order_id = place_order(
            db, uid, session['email'], group, address, payment_ref, point,
            payment_method='razorpay', charge_wallet=False, commit=False)
        if not ok:
            db.rollback()
            app.logger.error('Could not record Razorpay-paid order for user %s: %s', uid, message)
            return jsonify(error='Payment was verified, but the order could not be recorded. Contact support.'), 500
        results.append(new_order_id)
    try:
        db.commit()
    except sqlite3.Error:
        db.rollback()
        app.logger.exception('Could not commit orders for verified Razorpay payment %s', payment_id)
        return jsonify(error='Payment was verified, but the order could not be recorded. Contact support.'), 500

    for group in groups:
        for item in group['items']:
            cart.pop(str(item['id']), None)
    session['cart'] = cart
    session.pop('checkout_token', None)
    session.pop('razorpay_intent', None)
    return jsonify(success=True, order_ids=results,
                   redirect_url=url_for('orders', order=results[0]))


@app.route('/api/create-order', methods=['POST'])
def api_create_order():
    auth_error = api_customer_error()
    if auth_error:
        return auth_error
    key_id, key_secret = razorpay_credentials()
    if not key_id or not key_secret:
        return jsonify(error='Razorpay is not configured on the server.'), 503

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='A JSON payment request is required.'), 400
    token = data.get('token')
    address_value = data.get('address')
    address = address_value.strip() if isinstance(address_value, str) else ''
    if not token or token != session.get('checkout_token'):
        return jsonify(error='Checkout session expired. Reload checkout and try again.'), 400
    if not address:
        return jsonify(error='Please enter a delivery address.'), 400
    groups = cart_groups(get_db())
    if not groups or any(group['problems'] for group in groups):
        return jsonify(error='Fix the problems in your cart before paying.'), 400
    if open_orders_for(get_db(), session['user_id']):
        return jsonify(error='Finish your active order before placing another.'), 409
    point = customer_point()
    if not point:
        return jsonify(error='Confirm your delivery location before paying.'), 400
    amount = int(round(sum(group['subtotal'] for group in groups) * 100))
    if amount < 100:
        return jsonify(error='Payment amount must be at least ₹1.00.'), 400

    fingerprint = checkout_fingerprint(dict(session.get('cart', {})))
    intent = session.get('razorpay_intent')
    if intent:
        if (intent.get('user_id') == session['user_id'] and intent.get('amount') == amount and
                intent.get('cart_fingerprint') == fingerprint):
            return jsonify(order_id=intent['order_id'], amount=amount, currency='INR')
        return jsonify(error='A payment is already in progress. Cancel it before changing your cart.'), 409

    receipt = f"of{session['user_id']}{secrets.token_hex(8)}"
    try:
        created = razorpay.Client(auth=(key_id, key_secret)).order.create(data={
            'amount': amount, 'currency': 'INR', 'receipt': receipt})
    except (razorpay.errors.BadRequestError, razorpay.errors.GatewayError,
            razorpay.errors.ServerError) as exc:
        app.logger.warning('Razorpay order creation failed: %s', exc)
        return jsonify(error='Razorpay could not create the payment order. Please try again.'), 500
    except (requests.exceptions.RequestException, OSError, TimeoutError) as exc:
        app.logger.warning('Razorpay connection failed: %s', exc)
        return jsonify(error='Could not connect to Razorpay. Please try again.'), 500

    if (not isinstance(created, dict) or not created.get('id') or
            created.get('amount') != amount or created.get('currency') != 'INR'):
        app.logger.error('Razorpay returned an incomplete order response.')
        return jsonify(error='Razorpay returned an invalid payment order.'), 500
    session['address'] = address
    session['razorpay_intent'] = {
        'order_id': created['id'], 'amount': amount, 'user_id': session['user_id'],
        'address': address, 'point': point,
        'cart_fingerprint': fingerprint,
    }
    return jsonify(order_id=created['id'], amount=amount, currency='INR')


@app.route('/api/verify-payment', methods=['POST'])
def api_verify_payment():
    auth_error = api_customer_error()
    if auth_error:
        return auth_error
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='A JSON payment request is required.'), 400
    order_id = data.get('razorpay_order_id')
    payment_id = data.get('razorpay_payment_id')
    signature = data.get('razorpay_signature')
    if not all(isinstance(value, str) and value for value in (order_id, payment_id, signature)):
        return jsonify(error='razorpay_order_id, razorpay_payment_id and razorpay_signature are required.'), 400
    if (not re.fullmatch(r'order_[A-Za-z0-9]+', order_id) or
            not re.fullmatch(r'pay_[A-Za-z0-9]+', payment_id)):
        return jsonify(error='Invalid Razorpay order or payment ID.'), 400
    if not re.fullmatch(r'[A-Fa-f0-9]{64}', signature):
        return jsonify(error='Invalid Razorpay payment signature.'), 400

    _, key_secret = razorpay_credentials()
    if not key_secret:
        return jsonify(error='Razorpay is not configured on the server.'), 503
    expected = hmac.new(key_secret.encode('utf-8'), f'{order_id}|{payment_id}'.encode('utf-8'),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return jsonify(error='Payment signature verification failed.'), 400

    db = get_db()
    prefix = f'razorpay:{order_id}:{payment_id}:'
    existing = db.execute(
        'SELECT id, total_amount FROM orders WHERE user_id = ? '
        'AND substr(payment_ref, 1, ?) = ? ORDER BY id',
        (session['user_id'], len(prefix), prefix)).fetchall()
    if existing:
        intent = session.get('razorpay_intent')
        if intent and intent.get('order_id') == order_id:
            expected_amount = intent.get('amount', 0) / 100
            if abs(sum(row['total_amount'] for row in existing) - expected_amount) > 0.01:
                return jsonify(error='Recorded orders do not match this payment amount.'), 409
        return razorpay_payment_response(order_id, payment_id, existing)

    return razorpay_payment_response(order_id, payment_id)


@app.route('/api/cancel-order', methods=['POST'])
def api_cancel_order():
    auth_error = api_customer_error()
    if auth_error:
        return auth_error
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='A JSON payment request is required.'), 400
    intent = session.get('razorpay_intent')
    if intent and data.get('order_id') == intent.get('order_id'):
        session.pop('razorpay_intent', None)
    return jsonify(success=True)
=======
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
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5


@app.route('/checkout', methods=['POST'])
@login_required('customer')
def checkout():
    db = get_db()
<<<<<<< HEAD
    if session.get('razorpay_intent'):
        flash('Finish or cancel the Razorpay payment already in progress before paying from your wallet.',
              'error')
        return redirect(url_for('checkout_review'))
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
    point = customer_point()
    if not point:
        return redirect(url_for('location'))
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5

    if open_orders_for(db, session['user_id']):
        return redirect(url_for('checkout_review'))             # shows the "confirm last order" screen

    results, cart = [], dict(session.get('cart', {}))
    for n, grp in enumerate(groups, start=1):
        if grp['problems']:
            ok, msg, order_id = False, ' '.join(grp['problems']), None
        else:
            ok, msg, order_id = place_order(db, session['user_id'], session['email'], grp, address,
<<<<<<< HEAD
                                            f"{token}-{grp['restaurant_id']}", point)
=======
                                            f"{token}-{grp['restaurant_id']}")
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
        "SELECT o.*, r.name AS rest_name, r.address AS rest_address FROM orders o "
        "JOIN restaurants r ON r.id = o.restaurant_id "
=======
        "SELECT o.*, r.name AS rest_name FROM orders o JOIN restaurants r ON r.id = o.restaurant_id "
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
        review = db.execute('SELECT rating, feedback FROM reviews WHERE order_id = ?',
                            (selected['id'],)).fetchone()
        level = progress_level(selected, delivery)
        detail = {'order': selected, 'items': items, 'delivery': delivery, 'level': level,
                  'review': review, 'steps': [(s, i + 1 <= level) for i, s in enumerate(TRACK_STEPS)]}
=======
        level = progress_level(selected, delivery)
        detail = {'order': selected, 'items': items, 'delivery': delivery, 'level': level,
                  'steps': [(s, i + 1 <= level) for i, s in enumerate(TRACK_STEPS)]}
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
    return render_template('orders.html', rows=rows, detail=detail)


def _own_order_update(sql, order_id):
    db = get_db()
    cur = db.execute(sql, (order_id, session['user_id']))
    db.commit()
    return cur.rowcount == 1


def refund_order(db, order, reason):
    ref = f"refund:order:{order['id']}"
<<<<<<< HEAD
    payment_ref = order['payment_ref'] or ''
    if payment_ref.startswith('razorpay:'):
        if db.execute("SELECT 1 FROM transactions WHERE order_id = ? AND type = 'refund'",
                      (order['id'],)).fetchone():
            return True, ''
        parts = payment_ref.split(':')
        key_id, key_secret = razorpay_credentials()
        if len(parts) != 4 or not parts[2] or not key_id or not key_secret:
            return False, 'Razorpay refund is not configured. The order was not changed.'
        amount = int(round(order['total_amount'] * 100))
        try:
            result = razorpay.Client(auth=(key_id, key_secret)).payment.refund(
                parts[2], data={'amount': amount})
        except (razorpay.errors.BadRequestError, razorpay.errors.GatewayError,
                razorpay.errors.ServerError, requests.exceptions.RequestException,
                OSError, TimeoutError) as exc:
            app.logger.warning('Razorpay refund failed for order %s: %s', order['id'], exc)
            return False, 'Razorpay could not refund this payment. The order was not changed.'
        if not isinstance(result, dict) or not result.get('id'):
            app.logger.error('Razorpay returned an incomplete refund response for order %s', order['id'])
            return False, 'Razorpay returned an invalid refund response. The order was not changed.'
        db.execute("INSERT INTO transactions (order_id, restaurant_id, amount, type, payment_method, user_id) "
                   "VALUES (?,?,?,'refund','razorpay',?)",
                   (order['id'], order['restaurant_id'], order['total_amount'], order['user_id']))
        notify(db, order['user_id'],
               f"Order #{order['id']}: {reason}. A Razorpay refund has been initiated.")
        return True, ''

    ok, _ = wallet_service.credit(order['user_id'], order['total_amount'], ref, db=db)
=======
    ok, _ = wallet_service.credit(str(order['user_id']), order['total_amount'], ref)
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
    if ok:
        db.execute("INSERT INTO transactions (order_id, restaurant_id, amount, type, payment_method, user_id) "
                   "VALUES (?,?,?,'refund','wallet',?)",
                   (order['id'], order['restaurant_id'], order['total_amount'], order['user_id']))
        notify(db, order['user_id'], f"Order #{order['id']}: {reason}. {money(order['total_amount'])} refunded.")
<<<<<<< HEAD
        return True, ''
    return False, 'The wallet refund could not be recorded. The order was not changed.'
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5


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


<<<<<<< HEAD
@app.route('/orders/<int:order_id>/feedback', methods=['POST'])
@login_required('customer')
def submit_feedback(order_id):
    db = get_db()
    order = db.execute(
        "SELECT id, restaurant_id FROM orders WHERE id = ? AND user_id = ? AND status = 'completed'",
        (order_id, session['user_id'])).fetchone()
    if not order:
        abort(404, 'Completed order not found.')
    rating = request.form.get('rating', type=int)
    feedback = (request.form.get('feedback') or '').strip()
    if rating not in range(1, 6) or not feedback or len(feedback) > 1000:
        flash('Choose a rating from 1 to 5 and enter feedback (up to 1,000 characters).', 'error')
        return redirect(url_for('orders', order=order_id))
    try:
        inserted = db.execute(
            'INSERT OR IGNORE INTO reviews (order_id, restaurant_id, user_id, rating, feedback) '
            'VALUES (?,?,?,?,?)',
            (order_id, order['restaurant_id'], session['user_id'], rating, feedback))
        if inserted.rowcount != 1:
            db.rollback()
            flash('Feedback has already been submitted for this order.', 'error')
            return redirect(url_for('orders', order=order_id))
        notify_restaurant(
            db, order['restaurant_id'],
            f"New {rating}-star feedback for order #{order_id}: {feedback[:180]}")
        db.commit()
    except sqlite3.Error:
        db.rollback()
        app.logger.exception('Could not save feedback for order %s', order_id)
        flash('Feedback could not be saved. Please try again.', 'error')
        return redirect(url_for('orders', order=order_id))
    flash('Thank you. Your feedback was shared with the restaurant.', 'success')
    return redirect(url_for('orders', order=order_id))


=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
    order = db.execute('SELECT * FROM orders WHERE id = ? AND user_id = ?',
                       (order_id, session['user_id'])).fetchone()
    if order and order['status'] == 'pending':
        changed = db.execute("UPDATE orders SET status = 'cancelled' WHERE id = ? AND user_id = ? "
                             "AND status = 'pending'", (order_id, session['user_id'])).rowcount == 1
        if not changed:
            db.rollback()
            flash('Only orders the restaurant has not accepted yet can be cancelled.', 'error')
            return redirect(url_for('orders', order=order_id))
        db.execute("UPDATE deliveries SET status = 'cancelled' WHERE order_id = ?", (order_id,))
        refunded, error = refund_order(db, order, 'cancelled by you')
        if not refunded:
            db.rollback()
            flash(error, 'error')
            return redirect(url_for('orders', order=order_id))
        notify_restaurant(db, order['restaurant_id'], f'Order #{order_id} was cancelled by the customer.')
        db.commit()
        flash('Order cancelled; Razorpay refund initiated.' if
              (order['payment_ref'] or '').startswith('razorpay:') else
              'Order cancelled and refunded.', 'success')
=======
    if _own_order_update("UPDATE orders SET status = 'cancelled' WHERE id = ? AND user_id = ? "
                         "AND status = 'pending'", order_id):
        order = db.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        db.execute("UPDATE deliveries SET status = 'cancelled' WHERE order_id = ?", (order_id,))
        refund_order(db, order, 'cancelled by you')
        notify_restaurant(db, order['restaurant_id'], f'Order #{order_id} was cancelled by the customer.')
        db.commit()
        flash('Order cancelled and refunded.', 'success')
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
    advance_expired_offers(db)
    db.commit()
    rest = my_restaurant(db)
    orders_ = db.execute(
        'SELECT o.*, d.status AS del_status, d.delivery_agent_name, d.id AS delivery_id, '
        "(SELECT status FROM settlements s WHERE s.order_id = o.id AND s.recipient_role = 'restaurant') "
        'AS restaurant_settlement_status, '
        "(SELECT status FROM settlements s WHERE s.order_id = o.id AND s.recipient_role = 'delivery_agent') "
        'AS agent_settlement_status, '
        "(SELECT message FROM settlements s WHERE s.order_id = o.id AND s.recipient_role = 'restaurant') "
        'AS restaurant_settlement_message, '
=======
    rest = my_restaurant(db)
    orders_ = db.execute(
        'SELECT o.*, d.status AS del_status, d.delivery_agent_name, d.id AS delivery_id, '
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
        "(SELECT group_concat(name || ' x' || qty, ', ') FROM order_items WHERE order_id = o.id) AS summary "
        'FROM orders o JOIN deliveries d ON d.order_id = o.id WHERE o.restaurant_id = ? '
        'ORDER BY o.id DESC', (rest['id'],)).fetchall()
    menu = db.execute('SELECT * FROM menu_items WHERE restaurant_id = ? ORDER BY category, id', (rest['id'],)).fetchall()
<<<<<<< HEAD
    reviews = db.execute(
        'SELECT rv.*, u.name AS customer_name, o.id AS order_id FROM reviews rv '
        'JOIN users u ON u.id = rv.user_id JOIN orders o ON o.id = rv.order_id '
        'WHERE rv.restaurant_id = ? ORDER BY rv.id DESC LIMIT 20', (rest['id'],)).fetchall()
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
    revenue_states = ('preparing', 'ready', 'out_for_delivery', 'delivered', 'completed', 'disputed')
    revenue = sum(o['total_amount'] for o in orders_
                  if o['status'] in revenue_states and (o['created_at'] or '')[:10] == _today(db))
    stats = {'new': sum(o['status'] == 'pending' for o in orders_),
             'active': sum(o['status'] in ('preparing', 'ready', 'out_for_delivery') for o in orders_),
             'revenue': revenue}
<<<<<<< HEAD
    return render_template('dashboard_restaurant.html', rest=rest, orders=orders_, menu=menu,
                           reviews=reviews, stats=stats)
=======
    return render_template('dashboard_restaurant.html', rest=rest, orders=orders_, menu=menu, stats=stats)
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5


def _today(db):
    return db.execute("SELECT date('now')").fetchone()[0]


@app.route('/restaurant/order/<int:order_id>/<action>', methods=['POST'])
@login_required('restaurant_admin')
def restaurant_order_action(order_id, action):
    db = get_db()
    rest = my_restaurant(db)
<<<<<<< HEAD
    order = db.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    delivery = db.execute('SELECT * FROM deliveries WHERE order_id = ?', (order_id,)).fetchone()
    if not order or not delivery:
        abort(404, 'Order not found.')
    if order['restaurant_id'] != rest['id']:
        abort(404, 'Order not found.')
=======
    order = db.execute('SELECT * FROM orders WHERE id = ? AND restaurant_id = ?', (order_id, rest['id'])).fetchone()
    delivery = db.execute('SELECT * FROM deliveries WHERE order_id = ?', (order_id,)).fetchone()
    if not order or not delivery:
        abort(404, 'Order not found.')
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5

    def set_status(new, *allowed):
        cur = db.execute(f"UPDATE orders SET status = ? WHERE id = ? AND status IN ({','.join('?' * len(allowed))})",
                         (new, order_id, *allowed))
        return cur.rowcount == 1

    msg = None
<<<<<<< HEAD
    settle_order_id = None
    if action == 'accept' and set_status('preparing', 'pending'):
        notify(db, order['user_id'], f"Order #{order_id}: {rest['name']} accepted your order.")
        msg = 'Order accepted.'
    elif action == 'reject' and order['status'] == 'pending' and set_status('rejected', 'pending'):
        db.execute("UPDATE deliveries SET status = 'cancelled' WHERE order_id = ?", (order_id,))
        refunded, error = refund_order(db, order, f"{rest['name']} could not take your order")
        if not refunded:
            db.rollback()
            flash(error, 'error')
            return redirect(url_for('restaurant_dashboard') + '#orders')
        msg = ('Order rejected; Razorpay refund initiated.' if
               (order['payment_ref'] or '').startswith('razorpay:') else
               'Order rejected and customer refunded.')
=======
    if action == 'accept' and set_status('preparing', 'pending'):
        notify(db, order['user_id'], f"Order #{order_id}: {rest['name']} accepted your order.")
        msg = 'Order accepted.'
    elif action == 'reject' and set_status('rejected', 'pending'):
        db.execute("UPDATE deliveries SET status = 'cancelled' WHERE order_id = ?", (order_id,))
        refund_order(db, order, f"{rest['name']} could not take your order")
        msg = 'Order rejected and customer refunded.'
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
    elif action == 'ready' and set_status('ready', 'preparing'):
        if delivery['delivery_agent_id']:
            notify(db, delivery['delivery_agent_id'], f'Order #{order_id} is ready for pickup.')
        notify(db, order['user_id'], f'Order #{order_id} is ready.')
        msg = 'Marked as ready.'
    elif action == 'request_agent' and order['status'] in ('preparing', 'ready') and db.execute(
            "UPDATE deliveries SET status = 'pending' WHERE order_id = ? AND status = 'not_requested'",
            (order_id,)).rowcount == 1:
        db.execute('DELETE FROM delivery_rejections WHERE delivery_id = ?', (delivery['id'],))
<<<<<<< HEAD
        advance_expired_offers(db)
        assigned = assign_next_agent(db, delivery['id'])
        msg = ('A delivery request was sent to the best-ranked available agent.'
               if assigned else 'No available delivery agent; please self-deliver this order.')
=======
        notify_agents(db, f"New delivery request: {rest['name']} (order #{order_id}).")
        msg = 'Delivery agents have been notified.'
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
        settle_order_id = order_id
        msg = 'Marked as delivered.'
    if msg:
        db.commit()
        if settle_order_id:
            settle_razorpay_order(db, settle_order_id)
=======
        msg = 'Marked as delivered.'
    if msg:
        db.commit()
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
        flash(msg, 'success')
    else:
        db.rollback()
        flash('That action is not possible for this order right now.', 'error')
    return redirect(url_for('restaurant_dashboard') + '#orders')


def pay_restaurant(db, order):
<<<<<<< HEAD
    if (order['payment_ref'] or '').startswith('razorpay:'):
        return
    owner = db.execute(
        "SELECT id FROM users WHERE restaurant_id = ? AND role = 'restaurant_admin' ORDER BY id LIMIT 1",
        (order['restaurant_id'],)).fetchone()
    if not owner:
        return
    ok, _ = wallet_service.credit(owner['id'], order['total_amount'], f"restaurant:{order['id']}", db=db)
    if ok:
        db.execute("INSERT INTO transactions (order_id, restaurant_id, amount, type, payment_method, user_id) "
                   "VALUES (?, ?, ?, 'restaurant_payout', 'wallet', ?)",
                   (order['id'], order['restaurant_id'], order['total_amount'], owner['id']))


def settle_razorpay_order(db, order_id):
    order = db.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    delivery = db.execute('SELECT * FROM deliveries WHERE order_id = ?', (order_id,)).fetchone()
    if not order or not delivery or not (order['payment_ref'] or '').startswith('razorpay:'):
        return
    payment_parts = order['payment_ref'].split(':')
    if len(payment_parts) != 4 or not payment_parts[2]:
        app.logger.error('Invalid Razorpay reference for delivered order %s', order_id)
        return
    owner = db.execute(
        "SELECT id FROM users WHERE restaurant_id = ? AND role = 'restaurant_admin' ORDER BY id LIMIT 1",
        (order['restaurant_id'],)).fetchone()
    if not owner:
        app.logger.error('No restaurant payout owner found for order %s', order_id)
        return

    recipients = []
    gross_paise = int(round(order['total_amount'] * 100))
    try:
        fee_bps = int(os.environ.get('RAZORPAY_ROUTE_PLATFORM_FEE_BPS', '0'))
    except ValueError:
        fee_bps = -1
    if fee_bps < 0 or fee_bps > 10000:
        app.logger.error('RAZORPAY_ROUTE_PLATFORM_FEE_BPS must be between 0 and 10000')
        fee_bps = -1
    fee_paise = gross_paise * fee_bps // 10000 if fee_bps >= 0 else gross_paise
    agent_paise = int(round((delivery['payout'] or 0) * 100)) if delivery['delivery_agent_id'] else 0
    restaurant_paise = gross_paise - fee_paise - agent_paise
    agent = (db.execute('SELECT id, payout_account_id FROM users WHERE id = ?',
                        (delivery['delivery_agent_id'],)).fetchone()
             if delivery['delivery_agent_id'] else None)
    restaurant = db.execute(
        'SELECT payout_account_id FROM restaurants WHERE id = ?', (order['restaurant_id'],)).fetchone()
    if (restaurant_paise < 100 or agent_paise < 0 or
            (agent_paise and agent_paise < 100)):
        app.logger.error('Invalid payout split for delivered order %s', order_id)
        invalid_recipients = [{
            'role': 'restaurant', 'user_id': owner['id'],
            'amount': max(0, restaurant_paise),
        }]
        if agent:
            invalid_recipients.append({
                'role': 'delivery_agent', 'user_id': agent['id'],
                'amount': max(0, agent_paise),
            })
        for recipient in invalid_recipients:
            db.execute(
                "INSERT OR IGNORE INTO settlements "
                "(order_id, user_id, recipient_role, amount_paise, status, message) "
                "VALUES (?,?,?,?, 'review', ?)",
                (order_id, recipient['user_id'], recipient['role'], recipient['amount'],
                 'Payout split is outside provider limits or exceeds the captured payment. '
                 'Review this order before sending a transfer.'))
            notify(db, recipient['user_id'],
                   f"Order #{order_id} payout needs manual review because the split exceeds provider limits.")
        db.commit()
        return

    recipients.append({
        'role': 'restaurant', 'user_id': owner['id'],
        'account': restaurant['payout_account_id'] if restaurant else None,
        'amount': restaurant_paise,
    })
    if agent and agent_paise > 0:
        recipients.append({
            'role': 'delivery_agent', 'user_id': agent['id'],
            'account': agent['payout_account_id'], 'amount': agent_paise,
        })

    pending_created = False
    for recipient in recipients:
        inserted = db.execute(
            "INSERT OR IGNORE INTO settlements (order_id, user_id, recipient_role, amount_paise) "
            "VALUES (?,?,?,?)",
            (order_id, recipient['user_id'], recipient['role'], recipient['amount']))
        pending_created = pending_created or inserted.rowcount == 1
        db.execute(
            "UPDATE settlements SET user_id = ?, amount_paise = ?, message = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE order_id = ? AND recipient_role = ? "
            "AND status = 'pending_setup'",
            (recipient['user_id'], recipient['amount'],
             'Configure an approved Razorpay Route linked account and enable Route to receive this payout.',
             order_id, recipient['role']))

    # Route transfers require platform activation and verified linked accounts. Never
    # mark an unsettled payout as paid or silently credit the local wallet instead.
    key_id, key_secret = razorpay_credentials()
    route_enabled = os.environ.get('RAZORPAY_ROUTE_ENABLED', '').strip().lower() in ('1', 'true', 'yes')
    if (fee_bps < 0 or not route_enabled or not key_id or not key_secret or
            any(not r['account'] or not re.fullmatch(r'acc_[A-Za-z0-9]+', r['account'])
                for r in recipients)):
        db.commit()
        if pending_created:
            for recipient in recipients:
                notify(db, recipient['user_id'],
                       f"Order #{order_id} payout is pending setup. Add your approved linked account; "
                       'Route must be enabled by the platform.')
            db.commit()
        return

    current = db.execute(
        'SELECT recipient_role, status FROM settlements WHERE order_id = ?', (order_id,)).fetchall()
    if any(row['status'] != 'pending_setup' for row in current):
        return
    db.execute(
        "UPDATE settlements SET status = 'processing', message = 'Transfer request sent to Razorpay.', "
        'updated_at = CURRENT_TIMESTAMP WHERE order_id = ? AND status = ?',
        (order_id, 'pending_setup'))
    db.commit()
    transfers = [{
        'account': recipient['account'],
        'amount': recipient['amount'],
        'currency': 'INR',
        'notes': {'order_id': str(order_id), 'recipient': recipient['role']},
    } for recipient in recipients if recipient['amount'] > 0]
    try:
        result = razorpay.Client(auth=(key_id, key_secret)).payment.transfer(
            payment_parts[2], {'transfers': transfers})
    except (razorpay.errors.BadRequestError, razorpay.errors.GatewayError,
            razorpay.errors.ServerError, requests.exceptions.RequestException,
            OSError, TimeoutError) as exc:
        app.logger.warning('Razorpay Route transfer needs reconciliation for order %s: %s', order_id, exc)
        db.execute(
            "UPDATE settlements SET status = 'review', message = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE order_id = ? AND status = 'processing'",
            ('Razorpay transfer could not be confirmed. Reconcile this payment in the Razorpay Dashboard.',
             order_id))
        db.commit()
        return

    items = result.get('items') if isinstance(result, dict) else result
    if isinstance(result, dict) and result.get('id') and not items and len(recipients) == 1:
        items = [result]
    if not isinstance(items, list) or len(items) != len(transfers) or any(
            not isinstance(item, dict) or not item.get('id') for item in items):
        app.logger.error('Razorpay returned an incomplete transfer response for order %s', order_id)
        db.execute(
            "UPDATE settlements SET status = 'review', message = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE order_id = ? AND status = 'processing'",
            ('Razorpay returned an incomplete transfer response. Reconcile in the Razorpay Dashboard.',
             order_id))
        db.commit()
        return
    for recipient, item in zip((r for r in recipients if r['amount'] > 0), items):
        status = 'paid' if item.get('status') == 'processed' else 'submitted'
        db.execute(
            'UPDATE settlements SET status = ?, transfer_id = ?, message = ?, updated_at = CURRENT_TIMESTAMP '
            'WHERE order_id = ? AND recipient_role = ?',
            (status, item['id'], f"Razorpay transfer status: {item.get('status', 'created')}.",
             order_id, recipient['role']))
        notify(db, recipient['user_id'],
               f"Order #{order_id} payout was submitted to Razorpay. "
               f"Transfer status: {item.get('status', 'created')}.")
    db.commit()


def settle_pending_for_user(db, user_id, role):
    rows = db.execute(
        'SELECT DISTINCT order_id FROM settlements WHERE user_id = ? AND recipient_role = ? '
        "AND status = 'pending_setup' ORDER BY order_id", (user_id, role)).fetchall()
    for row in rows:
        settle_razorpay_order(db, row['order_id'])


@app.route('/restaurant/payout', methods=['POST'])
@login_required('restaurant_admin')
def restaurant_payout_settings():
    db = get_db()
    rest = my_restaurant(db)
    if request.form.get('process_pending'):
        if not rest['payout_account_id']:
            flash('Add an approved Razorpay linked account before processing payouts.', 'error')
            return redirect(url_for('restaurant_dashboard') + '#payout')
        settle_pending_for_user(db, session['user_id'], 'restaurant')
        flash('Pending setup payouts were checked. Review the settlement status on each order.', 'success')
        return redirect(url_for('restaurant_dashboard') + '#payout')
    account_id = (request.form.get('payout_account_id') or '').strip()
    if account_id and not re.fullmatch(r'acc_[A-Za-z0-9]+', account_id):
        flash('Enter a valid Razorpay linked-account ID (acc_...).', 'error')
        return redirect(url_for('restaurant_dashboard') + '#payout')
    db.execute('UPDATE restaurants SET payout_account_id = ? WHERE id = ?',
               (account_id or None, rest['id']))
    db.commit()
    if account_id:
        settle_pending_for_user(db, session['user_id'], 'restaurant')
    flash('Payout account saved. Only the Razorpay linked-account ID is stored.', 'success')
    return redirect(url_for('restaurant_dashboard') + '#payout')
=======
    ok, _ = wallet_service.credit(f"rest_{order['restaurant_id']}", order['total_amount'],
                                  f"restaurant:{order['id']}")
    if ok:
        db.execute("INSERT INTO transactions (order_id, restaurant_id, amount, type, payment_method) "
                   "VALUES (?,?,?,'restaurant_payout','wallet')",
                   (order['id'], order['restaurant_id'], order['total_amount']))
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5


@app.route('/restaurant/menu/add', methods=['POST'])
@login_required('restaurant_admin')
def menu_add():
    db = get_db()
    rest = my_restaurant(db)
    name = (request.form.get('name') or '').strip()
    price = request.form.get('price', type=float)
    category = request.form.get('category') or 'Main Course'
<<<<<<< HEAD
    if not name or price is None or price <= 0 or category not in FOOD_CATEGORIES:
        flash('Enter an item name, a valid category, and a price above zero.', 'error')
=======
    if not name or price is None or price <= 0:
        flash('Enter an item name and a price above zero.', 'error')
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
    elif action == 'category':
        category = request.form.get('category') or ''
        if category not in FOOD_CATEGORIES:
            flash('Choose a valid menu category.', 'error')
            return redirect(url_for('restaurant_dashboard') + '#menu')
        db.execute('UPDATE menu_items SET category = ? WHERE id = ?', (category, item_id))
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
        point = maps_service.valid_point(request.form.get('lat'), request.form.get('lon'))
        if point:
            db.execute('UPDATE restaurants SET lat = ?, lon = ? WHERE id = ?', (point[0], point[1], rest['id']))
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
        f'r.name AS rest_name, r.address AS rest_address, r.lat AS rest_lat, r.lon AS rest_lon, o.dest_lat, o.dest_lon, u.name AS customer_name, '
=======
        f'r.name AS rest_name, r.address AS rest_address, u.name AS customer_name, '
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
        f'u.accessibility_note AS customer_note, '
        f"(SELECT group_concat(name || ' x' || qty, ', ') FROM order_items WHERE order_id = o.id) AS summary "
        f'FROM deliveries d JOIN orders o ON o.id = d.order_id JOIN restaurants r ON r.id = o.restaurant_id '
        f'LEFT JOIN users u ON u.id = o.user_id '
        f'WHERE d.delivery_agent_id = ? AND d.status IN ({marks}) LIMIT 1', (agent_id, *ACTIVE_DELIVERY_STATES)).fetchone()


def pending_requests(db, agent_id):
    return db.execute(
<<<<<<< HEAD
        "SELECT d.*, o.delivery_address, o.estimated_delivery_time, o.total_amount, "
        "r.name AS rest_name, r.address AS rest_address, r.lat AS rest_lat, r.lon AS rest_lon, "
        "o.dest_lat, o.dest_lon, u.accessibility_note AS customer_note, "
        "(SELECT COUNT(*) FROM order_items WHERE order_id = o.id) AS n_items "
        "FROM deliveries d JOIN orders o ON o.id = d.order_id JOIN restaurants r ON r.id = o.restaurant_id "
        "LEFT JOIN users u ON u.id = o.user_id "
        "WHERE d.status = 'pending' AND d.offer_agent_id = ? "
        "AND d.offer_expires_at > CURRENT_TIMESTAMP ORDER BY d.id", (agent_id,)).fetchall()


def pickup_distance_km(agent, restaurant):
    if (agent['lat'] is None or agent['lon'] is None or
            restaurant['lat'] is None or restaurant['lon'] is None):
        return None
    return maps_service.haversine_km(
        (agent['lat'], agent['lon']), (restaurant['lat'], restaurant['lon'])) * maps_service.ROAD_FACTOR


def assign_next_agent(db, delivery_id):
    delivery = db.execute(
        "SELECT d.*, o.id AS oid, o.restaurant_id, o.estimated_delivery_time, "
        "r.name AS rest_name, r.lat AS lat, r.lon AS lon "
        "FROM deliveries d JOIN orders o ON o.id = d.order_id "
        "JOIN restaurants r ON r.id = o.restaurant_id "
        "WHERE d.id = ? AND d.status = 'pending' AND d.delivery_agent_id IS NULL",
        (delivery_id,)).fetchone()
    if not delivery:
        return False
    agents = db.execute(
        "SELECT u.* FROM users u WHERE u.role = 'delivery_agent' AND u.is_available = 1 "
        "AND NOT EXISTS (SELECT 1 FROM delivery_rejections x WHERE x.delivery_id = ? AND x.agent_id = u.id) "
        "AND NOT EXISTS (SELECT 1 FROM deliveries active WHERE active.delivery_agent_id = u.id "
        "AND active.status IN ('accepted', 'at_restaurant', 'picked_up', 'on_the_way')) "
        "AND NOT EXISTS (SELECT 1 FROM deliveries offered WHERE offered.offer_agent_id = u.id "
        "AND offered.status = 'pending')", (delivery_id,)).fetchall()
    candidates = []
    for agent in agents:
        distance = pickup_distance_km(agent, delivery)
        payout = payout_for(agent['payment_method'], delivery['distance_km'] or 0,
                           delivery['estimated_delivery_time'] or 0)
        candidates.append((agent, distance, payout))
    strategy = os.environ.get('DELIVERY_ASSIGNMENT_STRATEGY', 'nearest').strip().lower()
    if strategy not in ('nearest', 'cheapest'):
        strategy = 'nearest'
    if strategy == 'cheapest':
        candidates.sort(key=lambda c: (c[2], c[1] is None, c[1] or 0, c[0]['id']))
    else:
        candidates.sort(key=lambda c: (c[1] is None, c[1] if c[1] is not None else math.inf,
                                       c[2], c[0]['id']))
    if not candidates:
        db.execute(
            "UPDATE deliveries SET status = 'restaurant_fallback', offer_agent_id = NULL, "
            'offer_expires_at = NULL WHERE id = ? AND status = ?',
            (delivery_id, 'pending'))
        notify_restaurant(
            db, delivery['restaurant_id'],
            f"Order #{delivery['oid']}: no available delivery agent remains. Please deliver it yourself.")
        return False
    agent = candidates[0][0]
    cur = db.execute(
        "UPDATE deliveries SET offer_agent_id = ?, "
        "offer_expires_at = datetime('now', '+2 minutes') "
        "WHERE id = ? AND status = 'pending' AND delivery_agent_id IS NULL AND offer_agent_id IS NULL",
        (agent['id'], delivery_id))
    if cur.rowcount != 1:
        return False
    notify(db, agent['id'],
           f"New delivery request: {delivery['rest_name']} (order #{delivery['oid']}). "
           f"You have the first offer based on {strategy} ranking.")
    return True


def advance_expired_offers(db):
    expired = db.execute(
        "SELECT d.id, d.offer_agent_id FROM deliveries d LEFT JOIN users u ON u.id = d.offer_agent_id "
        "WHERE d.status = 'pending' AND d.offer_agent_id IS NOT NULL "
        "AND (d.offer_expires_at <= CURRENT_TIMESTAMP OR u.is_available != 1)").fetchall()
    for row in expired:
        db.execute('INSERT OR IGNORE INTO delivery_rejections (delivery_id, agent_id) VALUES (?,?)',
                   (row['id'], row['offer_agent_id']))
        db.execute('UPDATE deliveries SET offer_agent_id = NULL, offer_expires_at = NULL '
                   'WHERE id = ? AND offer_agent_id = ?', (row['id'], row['offer_agent_id']))
        assign_next_agent(db, row['id'])
=======
        "SELECT d.*, o.delivery_address, o.estimated_delivery_time, o.total_amount, r.name AS rest_name, "
        "r.address AS rest_address, u.accessibility_note AS customer_note, "
        "(SELECT COUNT(*) FROM order_items WHERE order_id = o.id) AS n_items "
        "FROM deliveries d JOIN orders o ON o.id = d.order_id JOIN restaurants r ON r.id = o.restaurant_id "
        "LEFT JOIN users u ON u.id = o.user_id "
        "WHERE d.status = 'pending' AND d.id NOT IN (SELECT delivery_id FROM delivery_rejections WHERE agent_id = ?) "
        "ORDER BY d.id", (agent_id,)).fetchall()
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5


@app.route('/dashboard/delivery-agent')
@login_required('delivery_agent')
def delivery_agent_dashboard():
    db = get_db()
    agent = current_agent(db)
<<<<<<< HEAD
    advance_expired_offers(db)
    db.commit()
    reqs = []
    if agent['is_available']:
        for r in pending_requests(db, agent['id']):
            pickup = None                              # how far the agent is from the restaurant right now
            if agent['lat'] is not None and r['rest_lat'] is not None:
                pickup = round(maps_service.haversine_km((agent['lat'], agent['lon']), (r['rest_lat'], r['rest_lon']))
                               * maps_service.ROAD_FACTOR, 1)
            reqs.append({'row': r, 'pickup_km': pickup,
                         'payout': payout_for(agent['payment_method'], r['distance_km'] or 0,
                                              r['estimated_delivery_time'] or 0)})
    earned = db.execute(
        "SELECT COALESCE((SELECT SUM(amount) FROM transactions WHERE type = 'agent_payout' "
        "AND user_id = ? AND date(created_at) = date('now')), 0) + "
        "COALESCE((SELECT SUM(amount_paise / 100.0) FROM settlements WHERE user_id = ? "
        "AND recipient_role = 'delivery_agent' AND status IN ('submitted', 'paid') "
        "AND date(created_at) = date('now')), 0)",
        (agent['id'], agent['id'])).fetchone()[0]
=======
    reqs = []
    if agent['is_available']:
        for r in pending_requests(db, agent['id']):
            reqs.append({'row': r, 'payout': payout_for(agent['payment_method'], r['distance_km'] or 0,
                                                        r['estimated_delivery_time'] or 0)})
    earned = db.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE type = 'agent_payout' "
                        "AND user_id = ? AND date(created_at) = date('now')", (agent['id'],)).fetchone()[0]
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
    history = db.execute(
        "SELECT d.*, r.name AS rest_name FROM deliveries d JOIN orders o ON o.id = d.order_id "
        "JOIN restaurants r ON r.id = o.restaurant_id WHERE d.delivery_agent_id = ? "
        "AND d.status IN ('delivered', 'failed') ORDER BY d.id DESC LIMIT 10", (agent['id'],)).fetchall()
<<<<<<< HEAD
    settlements = db.execute(
        "SELECT s.*, o.id AS oid FROM settlements s JOIN orders o ON o.id = s.order_id "
        "WHERE s.user_id = ? AND s.recipient_role = 'delivery_agent' "
        "ORDER BY s.id DESC LIMIT 10", (agent['id'],)).fetchall()
    return render_template('dashboard_delivery.html', agent=agent, requests=reqs, earned=earned,
                           active=active_delivery(db, agent['id']), history=history,
                           settlements=settlements)
=======
    return render_template('dashboard_delivery.html', agent=agent, requests=reqs, earned=earned,
                           active=active_delivery(db, agent['id']), history=history)
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5


@app.route('/agent/settings', methods=['POST'])
@login_required('delivery_agent')
def agent_settings():
    db = get_db()
<<<<<<< HEAD
    if request.form.get('process_pending'):
        agent = current_agent(db)
        if not agent['payout_account_id']:
            flash('Add an approved Razorpay linked account before processing payouts.', 'error')
            return redirect(url_for('delivery_agent_dashboard') + '#payout')
        settle_pending_for_user(db, session['user_id'], 'delivery_agent')
        flash('Pending setup payouts were checked. Review the settlement status below.', 'success')
        return redirect(url_for('delivery_agent_dashboard') + '#payout')
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
    method = request.form.get('payment_method')
    if method in PAY_RATES:
        db.execute('UPDATE users SET payment_method = ? WHERE id = ?', (method, session['user_id']))
        flash(f'Payment method set to: {PAY_LABELS[method].lower()}.', 'success')
    if request.form.get('toggle_available'):
        db.execute('UPDATE users SET is_available = 1 - is_available WHERE id = ?', (session['user_id'],))
<<<<<<< HEAD
        db.commit()
        advance_expired_offers(db)
        db.commit()
        return redirect(url_for('delivery_agent_dashboard'))
    if 'payout_account_id' in request.form:
        account_id = (request.form.get('payout_account_id') or '').strip()
        if account_id and not re.fullmatch(r'acc_[A-Za-z0-9]+', account_id):
            db.rollback()
            flash('Enter a valid Razorpay linked-account ID (acc_...).', 'error')
            return redirect(url_for('delivery_agent_dashboard') + '#payout')
        db.execute('UPDATE users SET payout_account_id = ? WHERE id = ?',
                   (account_id or None, session['user_id']))
        db.commit()
        if account_id:
            settle_pending_for_user(db, session['user_id'], 'delivery_agent')
        flash('Payout account saved. Only the Razorpay linked-account ID is stored.', 'success')
        return redirect(url_for('delivery_agent_dashboard') + '#payout')
=======
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
                           preview=request_preview(agent, req))
=======
                           map_url=map_service.get_navigation_url(req['rest_address']))
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5


@app.route('/agent/request/<int:delivery_id>/accept', methods=['POST'])
@login_required('delivery_agent')
def agent_accept(delivery_id):
    db = get_db()
    agent = current_agent(db)
    if active_delivery(db, agent['id']):
        flash('Finish your current delivery before accepting another one.', 'error')
        return redirect(url_for('delivery_agent_dashboard'))
<<<<<<< HEAD
    advance_expired_offers(db)
    row = db.execute('SELECT d.*, o.estimated_delivery_time, o.user_id, o.id AS oid, o.restaurant_id '
                     'FROM deliveries d JOIN orders o ON o.id = d.order_id WHERE d.id = ?', (delivery_id,)).fetchone()
    if not row or not agent['is_available']:
        db.commit()
        return render_template('agent_request.html', req=None)
    payout = payout_for(agent['payment_method'], row['distance_km'] or 0, row['estimated_delivery_time'] or 0)
    cur = db.execute(
        "UPDATE deliveries SET status = 'accepted', delivery_agent_id = ?, delivery_agent_name = ?, payout = ?, "
        "payment_method = ?, offer_expires_at = NULL WHERE id = ? AND status = 'pending' "
        "AND delivery_agent_id IS NULL AND offer_agent_id = ? AND offer_expires_at > CURRENT_TIMESTAMP",
        (agent['id'], agent['name'], payout, agent['payment_method'], delivery_id, agent['id']))
=======
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
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
                     "WHERE d.id = ? AND d.status = 'pending' AND d.offer_agent_id = ?",
                     (delivery_id, session['user_id'])).fetchone()
    if row:
        db.execute('INSERT OR IGNORE INTO delivery_rejections (delivery_id, agent_id) VALUES (?,?)',
                   (delivery_id, session['user_id']))
        db.execute('UPDATE deliveries SET offer_agent_id = NULL, offer_expires_at = NULL '
                   'WHERE id = ? AND offer_agent_id = ?', (delivery_id, session['user_id']))
        assigned = assign_next_agent(db, delivery_id)
        db.commit()
        flash('Request rejected. The next ranked available agent has been offered the delivery.'
              if assigned else 'Request rejected. No other agent is available; the restaurant was notified.',
              'success')
    else:
        flash('This delivery offer is no longer assigned to you.', 'error')
=======
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
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
    return redirect(url_for('delivery_agent_dashboard'))


@app.route('/agent/active')
@login_required('delivery_agent')
def agent_active():
    db = get_db()
    active = active_delivery(db, session['user_id'])
    if not active:
        flash('You have no active delivery.', 'error')
        return redirect(url_for('delivery_agent_dashboard'))
<<<<<<< HEAD
    return render_template('agent_active.html', d=active, reasons=FAIL_REASONS)


# ---------------------------------------------------------------------------
# Live tracking (Zomato/Swiggy style): agent position in, everyone's map out
# ---------------------------------------------------------------------------

TERMINAL_ORDER_STATES = ('delivered', 'completed', 'disputed', 'rejected', 'cancelled', 'delivery_failed')


def request_preview(agent, req):
    """Static map data for a delivery request the agent has not accepted yet."""
    if req['rest_lat'] is None or req['dest_lat'] is None:
        return None
    rest, dest = (req['rest_lat'], req['rest_lon']), (req['dest_lat'], req['dest_lon'])
    me = (agent['lat'], agent['lon']) if agent['lat'] is not None else None
    to_rest = map_service.route(me, rest, with_path=True, ttl=120) if me else None
    to_cust = map_service.route(rest, dest, with_path=True, ttl=600)
    return {'restaurant': {'name': req['rest_name'], 'lat': rest[0], 'lon': rest[1]},
            'destination': {'lat': dest[0], 'lon': dest[1]},
            'agent': {'name': 'You', 'lat': me[0], 'lon': me[1]} if me else None,
            'path': to_rest['path'] if to_rest else None, 'path_next': to_cust['path'],
            'pickup_km': to_rest['km'] if to_rest else None,
            'pickup_min': math.ceil(to_rest['minutes']) if to_rest else None}


def tracked_order(db, order_id):
    """The order row, only if the logged-in user is the customer, the restaurant, or the agent on it."""
    o = db.execute(
        'SELECT o.*, r.name AS rest_name, r.address AS rest_address, r.lat AS rest_lat, r.lon AS rest_lon, '
        'u.lat AS cust_lat, u.lon AS cust_lon FROM orders o JOIN restaurants r ON r.id = o.restaurant_id '
        'LEFT JOIN users u ON u.id = o.user_id WHERE o.id = ?', (order_id,)).fetchone()
    role, uid = session.get('role'), session.get('user_id')
    allowed = bool(o) and (
        (role == 'customer' and o['user_id'] == uid)
        or (role == 'restaurant_admin' and o['restaurant_id'] == session.get('restaurant_id'))
        or (role == 'delivery_agent' and db.execute(
            'SELECT 1 FROM deliveries WHERE order_id = ? AND delivery_agent_id = ?', (order_id, uid)).fetchone()))
    if not allowed:
        abort(404, 'Order not found.')
    return o


def tracking_payload(db, order_id, with_path=False):
    o = tracked_order(db, order_id)
    d = db.execute(
        "SELECT d.*, a.name AS agent_name, a.lat AS agent_lat, a.lon AS agent_lon, "
        "CAST((julianday('now') - julianday(a.location_updated_at)) * 86400 AS INTEGER) AS agent_age "
        "FROM deliveries d LEFT JOIN users a ON a.id = d.delivery_agent_id WHERE d.order_id = ?", (order_id,)).fetchone()
    rest = (o['rest_lat'], o['rest_lon']) if o['rest_lat'] is not None else None
    if o['dest_lat'] is not None:
        dest = (o['dest_lat'], o['dest_lon'])
    else:
        dest = (o['cust_lat'], o['cust_lon']) if o['cust_lat'] is not None else None
    dstatus = d['status'] if d else None
    if o['status'] in TERMINAL_ORDER_STATES:
        stage = 'done'
    elif dstatus in ('picked_up', 'on_the_way'):
        stage = 'to_customer'
    elif dstatus in ('accepted', 'at_restaurant'):
        stage = 'to_restaurant'
    elif dstatus == 'self':
        stage = 'self'
    else:
        stage = 'preparing'

    agent = pos = None
    if stage in ('to_restaurant', 'to_customer') and d['agent_lat'] is not None:
        pos = (d['agent_lat'], d['agent_lon'])
        agent = {'name': d['agent_name'], 'lat': pos[0], 'lon': pos[1], 'age_s': d['agent_age']}

    eta_stop = eta_customer = km = path = path_next = source = None
    if stage == 'to_restaurant' and pos and rest and dest:
        leg1 = map_service.route(pos, rest, with_path=with_path, ttl=30)
        leg2 = map_service.route(rest, dest, with_path=with_path, ttl=600)
        eta_stop, km, source = math.ceil(leg1['minutes']), leg1['km'], leg1['source']
        eta_customer = math.ceil(leg1['minutes'] + leg2['minutes'])
        path, path_next = leg1['path'], leg2['path']
    elif stage == 'to_customer' and pos and dest:
        leg = map_service.route(pos, dest, with_path=with_path, ttl=30)
        eta_stop = eta_customer = math.ceil(leg['minutes'])
        km, source, path = leg['km'], leg['source'], leg['path']
    elif stage in ('preparing', 'self') and rest and dest:
        leg = map_service.route(rest, dest, with_path=with_path, ttl=600)
        km, source, path = leg['km'], leg['source'], leg['path']
        eta_customer = int(o['estimated_delivery_time'] or 0) or None
    return {
        'order_id': o['id'], 'order_status': o['status'], 'delivery_status': dstatus, 'stage': stage,
        'restaurant': {'name': o['rest_name'], 'address': o['rest_address'],
                       'lat': rest[0] if rest else None, 'lon': rest[1] if rest else None},
        'destination': {'address': o['delivery_address'], 'lat': dest[0] if dest else None,
                        'lon': dest[1] if dest else None},
        'agent': agent, 'eta_stop_min': eta_stop, 'eta_customer_min': eta_customer, 'distance_km': km,
        'source': source, 'path': path if with_path else None, 'path_next': path_next if with_path else None,
    }


@app.route('/track/<int:order_id>')
@login_required()
def track_order(order_id):
    o = tracked_order(get_db(), order_id)
    return render_template('track.html', o=o)


@app.route('/api/orders/<int:order_id>/tracking')
@login_required()
def api_tracking(order_id):
    return jsonify(tracking_payload(get_db(), order_id, with_path=request.args.get('path') == '1'))


@app.route('/api/agent/location', methods=['POST'])
@login_required('delivery_agent')
def api_agent_location():
    """The agent's phone (or the demo simulator) reports its position every few seconds."""
    data = request.get_json(silent=True) or {}
    point = maps_service.valid_point(data.get('lat'), data.get('lon'))
    if not point:
        return jsonify(error='lat and lon are required numbers'), 400
    db = get_db()
    db.execute('UPDATE users SET lat = ?, lon = ?, location_updated_at = CURRENT_TIMESTAMP WHERE id = ?',
               (point[0], point[1], session['user_id']))
    db.commit()
    return jsonify(ok=True)

=======
    return render_template('agent_active.html', d=active, reasons=FAIL_REASONS,
                           map_url=map_service.get_navigation_url(active['rest_address']))
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5


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
<<<<<<< HEAD
        if not (order['payment_ref'] or '').startswith('razorpay:'):
            ok, _ = wallet_service.credit(session['user_id'], d['payout'], f"agent:{d['id']}", db=db)
            if ok:
                db.execute("INSERT INTO transactions (order_id, restaurant_id, amount, type, payment_method, user_id) "
                           "VALUES (?,?,?,'agent_payout','wallet',?)",
                           (d['order_id'], order['restaurant_id'], d['payout'], session['user_id']))
        notify(db, order['user_id'], f"Order #{d['order_id']} was delivered. Please confirm you received it.")
        db.commit()
        settle_razorpay_order(db, d['order_id'])
=======
        ok, _ = wallet_service.credit(str(session['user_id']), d['payout'], f"agent:{d['id']}")
        if ok:
            db.execute("INSERT INTO transactions (order_id, restaurant_id, amount, type, payment_method, user_id) "
                       "VALUES (?,?,?,'agent_payout','wallet',?)",
                       (d['order_id'], order['restaurant_id'], d['payout'], session['user_id']))
        notify(db, order['user_id'], f"Order #{d['order_id']} was delivered. Please confirm you received it.")
        db.commit()
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
    refunded, error = refund_order(db, order, f'could not be delivered ({reason.lower()})')
    if not refunded:
        db.rollback()
        flash(error, 'error')
        return redirect(url_for('agent_active'))
=======
    refund_order(db, order, f'could not be delivered ({reason.lower()})')
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
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
<<<<<<< HEAD
    print('Google Maps: ' + ('enabled (key loaded)' if map_service.enabled else
          'NOT configured - add GOOGLE_MAPS_API_KEY to .env (see README). Using offline estimates.'))
    debug_enabled = (os.environ.get('FLASK_DEBUG') == '1' and
                     _deployment_environment not in {'production', 'prod'})
    app.run(debug=debug_enabled,
=======
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1',
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
            host=os.environ.get('ORDERFOOD_HOST', '127.0.0.1'),
            port=int(os.environ.get('ORDERFOOD_PORT', 9000)))
