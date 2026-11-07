"""
OrderFood - Flask-based food ordering platform.

Roles: customer, restaurant_admin, delivery_agent.
Run:   python orderfood_app.py      (http://127.0.0.1:9000)
Reset: delete orderfood.db, then start again.
"""

import functools
import csv
import hashlib
import hmac
import io
import json
import math
import os
import re
import secrets
import sqlite3
import random
import threading
import tempfile
import time

import razorpay
import requests
from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_CONFIG_BYTES = 5 * 1024 * 1024
SCHEMA_VERSION = 4
_DATABASE_INIT_LOCK = threading.Lock()
_INITIALIZED_DATABASE = None


def _reject_duplicate_json_keys(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError(f'Duplicate JSON key: {key}')
        data[key] = value
    return data


def _reject_json_constant(value):
    raise ValueError(f'Non-standard JSON number is not allowed: {value}')


def _load_json(path, description):
    try:
        if os.path.getsize(path) > MAX_CONFIG_BYTES:
            raise RuntimeError(f'{description} exceeds the {MAX_CONFIG_BYTES}-byte size limit: {path}')
        with open(path, encoding='utf-8') as fh:
            return json.load(fh, object_pairs_hook=_reject_duplicate_json_keys)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f'{description} is unreadable or invalid: {path}') from exc


def load_catalog(path=None):
    path = path or os.path.join(BASE_DIR, 'data', 'catalog.json')
    data = _load_json(path, 'Catalog configuration')
    schema_version = data.get('schema_version') if isinstance(data, dict) else None
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version != 1:
        raise RuntimeError(f'Catalog configuration has an invalid shape: {path}')
    categories = data.get('categories')
    restaurants = data.get('restaurants')
    default_menu = data.get('default_menu')
    rules = data.get('category_normalization_rules')
    if (not isinstance(categories, list) or not categories or
            any(not isinstance(category, str) or not category.strip() for category in categories) or
            len(categories) != len(set(categories)) or not isinstance(restaurants, list) or
            not restaurants or not isinstance(default_menu, list) or not default_menu or
            not isinstance(rules, list)):
        raise RuntimeError(f'Catalog configuration has an invalid shape: {path}')
    if any(not isinstance(category, str) or not category.strip() for category in categories):
        raise RuntimeError(f'Catalog categories must be non-empty strings: {path}')

    def valid_menu(menu):
        if not isinstance(menu, list) or not menu:
            return False
        for item in menu:
            if not isinstance(item, dict):
                return False
            price = item.get('price')
            if isinstance(price, bool) or not isinstance(price, (int, float)):
                return False
            try:
                price = float(price)
            except (TypeError, ValueError, OverflowError):
                return False
            if (not isinstance(item.get('name'), str) or not item['name'].strip() or
                    item.get('category') not in categories or
                    not math.isfinite(price) or price <= 0 or
                    not isinstance(item.get('available', True), bool)):
                return False
        return True

    if not valid_menu(default_menu):
        raise RuntimeError(f'Catalog default menu has invalid entries: {path}')
    slugs = []
    for restaurant in restaurants:
        if not isinstance(restaurant, dict):
            raise RuntimeError(f'Catalog restaurant entries must be objects: {path}')
        slug = restaurant.get('slug')
        if (not isinstance(slug, str) or
                not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug)):
            raise RuntimeError(f'Catalog restaurant slugs must be lowercase kebab-case: {path}')
        if any(not isinstance(restaurant.get(field), str) or not restaurant[field].strip()
               for field in ('name', 'address', 'description')):
            raise RuntimeError(f'Catalog restaurant name, address, and description are required: {path}')
        if 'menu' in restaurant and not valid_menu(restaurant['menu']):
            raise RuntimeError(f'Catalog menu entries are invalid for {slug}: {path}')
        style = restaurant.get('style', {})
        if not isinstance(style, dict):
            raise RuntimeError(f'Catalog presentation style is invalid for {slug}: {path}')
        tone = style.get('tone', 1)
        if isinstance(tone, bool) or not isinstance(tone, int) or tone not in range(1, 6):
            raise RuntimeError(f'Catalog presentation tone is invalid for {slug}: {path}')
        for field in ('photo', 'icon', 'cuisine'):
            value = style.get(field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise RuntimeError(f'Catalog presentation field {field} is invalid for {slug}: {path}')
        photo = style.get('photo')
        if photo and not re.fullmatch(r'photo-[A-Za-z0-9-]+', photo):
            raise RuntimeError(f'Catalog photo identifier is invalid for {slug}: {path}')
        slugs.append(slug)
    if len(slugs) != len(set(slugs)):
        raise RuntimeError(f'Catalog restaurant slugs must be present and unique: {path}')
    for rule in rules:
        if (not isinstance(rule, dict) or rule.get('category') not in categories or
                not isinstance(rule.get('keywords'), list) or not rule['keywords'] or
                any(not isinstance(term, str) or not term.strip() for term in rule['keywords'])):
            raise RuntimeError(f'Catalog category-normalization rules are invalid: {path}')
    return data


def load_platform_settings(path=None):
    path = path or os.path.join(BASE_DIR, 'data', 'platform.json')
    data = _load_json(path, 'Platform settings')
    schema_version = data.get('schema_version') if isinstance(data, dict) else None
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version != 1:
        raise RuntimeError(f'Platform settings have an invalid shape: {path}')
    delivery = data.get('delivery')
    wallet = data.get('wallet')
    payout = data.get('agent_payout')
    reasons = data.get('delivery_failure_reasons')
    if (not isinstance(delivery, dict) or not isinstance(wallet, dict) or
            not isinstance(payout, dict) or not isinstance(payout.get('rates'), dict) or
            not isinstance(payout.get('labels'), dict) or not isinstance(reasons, list) or
            not reasons or any(not isinstance(reason, str) or not reason.strip() for reason in reasons) or
            len(reasons) != len(set(reasons))):
        raise RuntimeError(f'Platform settings have an invalid shape: {path}')
    try:
        pickup_buffer = delivery['pickup_buffer_minutes']
        demo_balance = wallet['demo_customer_balance']
        rates = payout['rates']
        labels = payout['labels']
        if (isinstance(pickup_buffer, bool) or not isinstance(pickup_buffer, int) or pickup_buffer < 0 or
                isinstance(demo_balance, bool) or not isinstance(demo_balance, (int, float)) or
                not math.isfinite(float(demo_balance)) or demo_balance < 0 or
                set(rates) != set(labels) or
                any(isinstance(rate, bool) or not isinstance(rate, (int, float)) or
                    not math.isfinite(float(rate)) or rate < 0
                    for rate in rates.values()) or
                any(not isinstance(label, str) or not label.strip() for label in labels.values())):
            raise ValueError
    except (KeyError, OverflowError, TypeError, ValueError) as exc:
        raise RuntimeError(f'Platform settings have invalid values: {path}') from exc
    return data


CATALOG = load_catalog()
PLATFORM_SETTINGS = load_platform_settings()

import maps_service                                    # Google Maps Platform (see maps_service.py)
maps_service.load_dotenv(os.path.join(BASE_DIR, '.env'))   # GOOGLE_MAPS_API_KEY etc.

app = Flask(__name__)
app.config['DATABASE'] = os.environ.get('ORDERFOOD_DB', os.path.join(BASE_DIR, 'orderfood.db'))
app.config['LEGACY_WALLET_FILE'] = os.environ.get('ORDERFOOD_WALLET', os.path.join(BASE_DIR, 'wallet.json'))
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
try:
    app.config['DATABASE_BUSY_TIMEOUT_MS'] = int(os.environ.get('ORDERFOOD_DB_BUSY_TIMEOUT_MS', '5000'))
except ValueError as exc:
    raise RuntimeError('ORDERFOOD_DB_BUSY_TIMEOUT_MS must be an integer between 1 and 60000.') from exc
if not 1 <= app.config['DATABASE_BUSY_TIMEOUT_MS'] <= 60000:
    raise RuntimeError('ORDERFOOD_DB_BUSY_TIMEOUT_MS must be an integer between 1 and 60000.')
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


app.secret_key = _load_secret_key()


def connect_database(path=None):
    """Open a consistently configured SQLite connection for app and wallet operations."""
    database = os.fspath(path or app.config['DATABASE'])
    if database != ':memory:' and not database.startswith('file:'):
        absolute_path = os.path.abspath(database)
        os.makedirs(os.path.dirname(absolute_path), mode=0o700, exist_ok=True)
        try:
            descriptor = os.open(absolute_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        if os.name == 'posix':
            os.chmod(absolute_path, 0o600)

    timeout_ms = app.config['DATABASE_BUSY_TIMEOUT_MS']
    conn = sqlite3.connect(database, timeout=timeout_ms / 1000, uri=database.startswith('file:'))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute(f'PRAGMA busy_timeout = {timeout_ms}')
    conn.execute('PRAGMA synchronous = NORMAL')
    conn.execute('PRAGMA trusted_schema = OFF')
    return conn

PICKUP_BUFFER_MIN = PLATFORM_SETTINGS['delivery']['pickup_buffer_minutes']
DEMO_CUSTOMER_BALANCE = PLATFORM_SETTINGS['wallet']['demo_customer_balance']
PAY_RATES = PLATFORM_SETTINGS['agent_payout']['rates']
PAY_LABELS = PLATFORM_SETTINGS['agent_payout']['labels']
OPEN_ORDER_STATES = ('pending', 'preparing', 'ready', 'out_for_delivery', 'delivered')
ACTIVE_DELIVERY_STATES = ('accepted', 'at_restaurant', 'picked_up', 'on_the_way')
FAIL_REASONS = PLATFORM_SETTINGS['delivery_failure_reasons']
DEMO_USERS = (
    ('alice.customer@example.com', 'Alice Wonderland', 'AlicePass123!', 'customer', None),
    ('anna.admin@example.com', 'Anna Apple', 'AnnaAdmin123!', 'restaurant_admin', 1),
    ('david.agent@example.com', 'David Driver', 'DavidAgent123!', 'delivery_agent', None),
    ('customer@test.com', 'Demo Customer', 'password123', 'customer', None),
    ('admin@test.com', 'Burger Joint Owner', 'admin123', 'restaurant_admin', 5),
)
DEMO_USER_EMAILS = frozenset(user[0] for user in DEMO_USERS)


# ---------------------------------------------------------------------------
# Third-party service mocks
# ---------------------------------------------------------------------------

class SqlWalletService:
    """SQLite-backed wallet balances and idempotent wallet operations."""

    def __init__(self, database):
        self.database = database

    def _connect(self):
        return connect_database(self.database)

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


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    if 'db' not in g:
        g.db = connect_database()
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


def restaurant_slug(name, cur=None):
    base = re.sub(r'[^a-z0-9]+', '-', name.casefold()).strip('-') or 'restaurant'
    if cur is None:
        return base
    slug = base
    suffix = 2
    while cur.execute('SELECT 1 FROM restaurants WHERE slug = ?', (slug,)).fetchone():
        slug = f'{base}-{suffix}'
        suffix += 1
    return slug


def restaurant_style(slug):
    restaurant = next((item for item in CATALOG['restaurants'] if item['slug'] == slug), None)
    style = restaurant.get('style', {}) if restaurant else {}
    photo = style.get('photo')
    url = f'https://images.unsplash.com/{photo}?auto=format&fit=crop&w=640&h=480&q=70' if photo else None
    return {
        'photo_url': url,
        'icon': style.get('icon', 'grain'),
        'tone': style.get('tone', 1),
        'cuisine': style.get('cuisine', 'Restaurant'),
    }


def migrate_legacy_wallet_file(cur):
    """Import balances and idempotency records from the former JSON wallet store."""
    path = app.config['LEGACY_WALLET_FILE']
    if not os.path.exists(path):
        return False
    if cur.execute("SELECT 1 FROM app_metadata WHERE key = 'legacy_wallet_migrated'").fetchone():
        return True
    data = _load_json(path, 'Legacy wallet file')
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


def menu_category_names(db):
    return [row[0] for row in db.execute(
        'SELECT name FROM menu_categories ORDER BY sort_order, name')]


def disable_default_demo_credentials(cur):
    for email, _name, password, _role, _restaurant_id in DEMO_USERS:
        row = cur.execute('SELECT id, password FROM users WHERE email = ?', (email,)).fetchone()
        if not row:
            continue
        stored = row[1]
        try:
            matches = stored == password or check_password_hash(stored, password)
        except (TypeError, ValueError):
            matches = False
        if matches:
            cur.execute('UPDATE users SET password = ? WHERE id = ?',
                        (generate_password_hash(secrets.token_urlsafe(48)), row[0]))


def migrate_menu_categories(cur):
    """Normalize old menu labels once, leaving future restaurant edits untouched."""
    version = cur.execute("SELECT value FROM app_metadata WHERE key = 'menu_categories_v3'").fetchone()
    if version:
        return

    rules = CATALOG['category_normalization_rules']
    categories = set(menu_category_names(cur))
    for item_id, name, category in cur.execute(
            'SELECT id, name, category FROM menu_items').fetchall():
        normalized = (name or '').casefold()
        revised = next((rule['category'] for rule in rules
                        if any(term in normalized for term in rule['keywords'])), category)
        if revised not in categories:
            revised = 'Main Course'
        if revised != category:
            cur.execute('UPDATE menu_items SET category = ? WHERE id = ?', (revised, item_id))
    cur.execute("INSERT INTO app_metadata (key, value) VALUES ('menu_categories_v3', '1')")


def _enable_wal(conn):
    deadline = time.monotonic() + app.config['DATABASE_BUSY_TIMEOUT_MS'] / 1000
    while True:
        try:
            mode = conn.execute('PRAGMA journal_mode = WAL').fetchone()[0].lower()
            if mode not in {'wal', 'memory'}:
                raise RuntimeError(f'SQLite refused WAL mode and selected {mode!r}.')
            return
        except sqlite3.OperationalError as exc:
            if 'locked' not in str(exc).lower() or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def _initialize_database(conn):
    cur = conn.cursor()
    demo_customer_ids = []
    _enable_wal(conn)
    cur.executescript('''
    BEGIN IMMEDIATE;
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS restaurants (
        id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT, name TEXT NOT NULL, address TEXT NOT NULL,
        description TEXT, rating REAL DEFAULT 0.0, is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS menu_categories (
        name TEXT PRIMARY KEY, sort_order INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS menu_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, restaurant_id INTEGER NOT NULL, name TEXT NOT NULL,
        description TEXT, price REAL NOT NULL, category TEXT, is_available INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE,
        FOREIGN KEY (category) REFERENCES menu_categories(name));
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, name TEXT,
        password TEXT NOT NULL, role TEXT DEFAULT 'customer',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS account_applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, name TEXT NOT NULL,
        requested_role TEXT NOT NULL CHECK (requested_role IN ('restaurant_admin', 'delivery_agent')),
        restaurant_name TEXT, restaurant_address TEXT, password_hash TEXT, restaurant_id INTEGER,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'approved', 'rejected')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_account_applications_email
        ON account_applications(email) WHERE status = 'pending';
    CREATE TABLE IF NOT EXISTS restaurant_intake (
        id INTEGER PRIMARY KEY AUTOINCREMENT, restaurant_name TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE, address TEXT NOT NULL, description TEXT NOT NULL,
        owner_name TEXT NOT NULL, owner_email TEXT NOT NULL,
        menu_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'approved', 'rejected')),
        restaurant_id INTEGER UNIQUE, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id));
    CREATE TABLE IF NOT EXISTS restaurant_intake_menu_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, intake_id INTEGER NOT NULL,
        name TEXT NOT NULL, description TEXT, price REAL NOT NULL CHECK (price > 0),
        category TEXT NOT NULL, is_available INTEGER NOT NULL DEFAULT 1,
        item_order INTEGER NOT NULL,
        UNIQUE (intake_id, item_order),
        FOREIGN KEY (intake_id) REFERENCES restaurant_intake(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS admin_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER NOT NULL,
        action TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
        details_json TEXT NOT NULL DEFAULT '{}',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (actor_id) REFERENCES users(id));
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
    CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL UNIQUE,
        restaurant_id INTEGER NOT NULL, user_id INTEGER NOT NULL, rating INTEGER NOT NULL,
        feedback TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS delivery_tips (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL UNIQUE,
        customer_id INTEGER NOT NULL, agent_id INTEGER NOT NULL,
        amount REAL NOT NULL CHECK (amount > 0),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
        FOREIGN KEY (customer_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (agent_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS settlements (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        recipient_role TEXT NOT NULL CHECK (recipient_role IN ('restaurant', 'delivery_agent')),
        amount_paise INTEGER NOT NULL CHECK (amount_paise >= 0),
        status TEXT NOT NULL DEFAULT 'pending_setup', transfer_id TEXT, message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (order_id, recipient_role),
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE);
    ''')
    current_version = cur.execute('PRAGMA user_version').fetchone()[0]
    if current_version > SCHEMA_VERSION:
        raise RuntimeError(
            f'Database schema version {current_version} is newer than this application supports '
            f'({SCHEMA_VERSION}).')
    # Upgrade databases created by the older version of the app.
    for table, column, ddl in [
        ('restaurants', 'is_open', 'INTEGER DEFAULT 1'),
        ('restaurants', 'slug', 'TEXT'),
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
        ('users', 'is_available', 'INTEGER DEFAULT 1'),
        ('users', 'accessibility_note', 'TEXT'),
        ('orders', 'user_id', 'INTEGER'),
        ('orders', 'payment_ref', 'TEXT'),
        ('deliveries', 'delivery_agent_id', 'INTEGER'),
        ('deliveries', 'distance_km', 'REAL'),
        ('deliveries', 'payout', 'REAL'),
        ('deliveries', 'payment_method', 'TEXT'),
        ('deliveries', 'fail_reason', 'TEXT'),
        ('deliveries', 'offer_agent_id', 'INTEGER'),
        ('deliveries', 'offer_expires_at', 'TIMESTAMP'),
        ('transactions', 'user_id', 'INTEGER'),
    ]:
        _ensure_column(cur, table, column, ddl)
    _ensure_column(cur, 'account_applications', 'password_hash', 'TEXT')
    _ensure_column(cur, 'account_applications', 'restaurant_id', 'INTEGER')
    _ensure_column(cur, 'restaurant_intake', 'menu_json', "TEXT NOT NULL DEFAULT '[]'")

    seeded_slugs = {restaurant['name']: restaurant['slug'] for restaurant in CATALOG['restaurants']}
    for restaurant_id, name, slug in cur.execute(
            'SELECT id, name, slug FROM restaurants ORDER BY id').fetchall():
        if not slug:
            seeded_slug = seeded_slugs.get(name)
            if seeded_slug and cur.execute(
                    'SELECT 1 FROM restaurants WHERE slug = ?', (seeded_slug,)).fetchone():
                seeded_slug = None
            cur.execute('UPDATE restaurants SET slug = ? WHERE id = ?',
                        (seeded_slug or restaurant_slug(name, cur), restaurant_id))
    cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_restaurants_slug '
                'ON restaurants(slug) WHERE slug IS NOT NULL')

    for index, category in enumerate(CATALOG['categories']):
        cur.execute('INSERT INTO menu_categories (name, sort_order) VALUES (?,?) '
                    'ON CONFLICT(name) DO UPDATE SET sort_order = excluded.sort_order',
                    (category, index))
    cur.execute('''
    CREATE TRIGGER IF NOT EXISTS menu_category_insert_guard
    BEFORE INSERT ON menu_items
    WHEN NOT EXISTS (SELECT 1 FROM menu_categories WHERE name = NEW.category)
    BEGIN
        SELECT RAISE(ABORT, 'Unknown menu category');
    END
    ''')
    cur.execute('''
    CREATE TRIGGER IF NOT EXISTS menu_category_update_guard
    BEFORE UPDATE OF category ON menu_items
    WHEN NOT EXISTS (SELECT 1 FROM menu_categories WHERE name = NEW.category)
    BEGIN
        SELECT RAISE(ABORT, 'Unknown menu category');
    END
    ''')

    # Ratings on earlier versions were seeded sample values, not customer feedback.
    if not cur.execute(
            "SELECT 1 FROM app_metadata WHERE key = 'sample_ratings_cleared_v1'").fetchone():
        cur.execute('UPDATE restaurants SET rating = 0')
        cur.execute(
            "INSERT INTO app_metadata (key, value) VALUES ('sample_ratings_cleared_v1', '1')")

    if cur.execute('SELECT COUNT(*) FROM restaurants').fetchone()[0] == 0:
        known_categories = set(menu_category_names(cur))
        rng = random.Random()
        for restaurant in CATALOG['restaurants']:
            _label, lat, lon = map_service.random_spot(rng=rng)
            rid = cur.execute(
                'INSERT INTO restaurants (slug, name, address, description, rating, lat, lon) '
                'VALUES (?,?,?,?,?,?,?)',
                (restaurant['slug'], restaurant['name'], restaurant['address'],
                 restaurant['description'], 0, lat, lon)).lastrowid
            items = restaurant.get('menu', CATALOG['default_menu'])
            for item in items:
                if item['category'] not in known_categories:
                    raise RuntimeError(
                        f"Unknown menu category {item['category']!r} in catalog for {restaurant['slug']}.")
            cur.executemany(
                'INSERT INTO menu_items (restaurant_id, name, price, category, is_available) '
                'VALUES (?,?,?,?,?)',
                [(rid, item['name'], item['price'], item['category'], int(item['available']))
                 for item in items])

    seed_demo_users = (
        os.environ.get('ORDERFOOD_SEED_DEMO_USERS', '').strip().lower() in {'1', 'true', 'yes'} and
        _deployment_environment not in {'production', 'prod'})
    if cur.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0 and seed_demo_users:
        cur.executemany('INSERT INTO users (email, name, password, role, restaurant_id) VALUES (?,?,?,?,?)',
                        [(e, n, generate_password_hash(p), r, rid) for e, n, p, r, rid in DEMO_USERS])
        demo_customer_ids = [row[0] for row in cur.execute(
            "SELECT id FROM users WHERE email IN ('alice.customer@example.com', 'customer@test.com')")]
    if _deployment_environment in {'production', 'prod'}:
        disable_default_demo_credentials(cur)
    cur.execute('DROP TABLE IF EXISTS geocode_cache')          # leftover from an older experiment
    migrate_menu_categories(cur)
    legacy_wallet_file = migrate_legacy_wallet_file(cur)
    if current_version < 1:
        cur.execute("INSERT INTO schema_migrations (version, name) VALUES (1, 'baseline schema')")
    if current_version < 2:
        indexes = (
            'CREATE INDEX IF NOT EXISTS idx_orders_user_id_id ON orders(user_id, id DESC)',
            'CREATE INDEX IF NOT EXISTS idx_orders_restaurant_id_id ON orders(restaurant_id, id DESC)',
            'CREATE INDEX IF NOT EXISTS idx_orders_status_id ON orders(status, id)',
            'CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id)',
            'CREATE INDEX IF NOT EXISTS idx_deliveries_order_id ON deliveries(order_id)',
            'CREATE INDEX IF NOT EXISTS idx_deliveries_agent_status ON deliveries(delivery_agent_id, status)',
            'CREATE INDEX IF NOT EXISTS idx_deliveries_offer_status_expiry '
            'ON deliveries(offer_agent_id, status, offer_expires_at)',
            'CREATE INDEX IF NOT EXISTS idx_delivery_rejections_agent_delivery '
            'ON delivery_rejections(agent_id, delivery_id)',
            'CREATE INDEX IF NOT EXISTS idx_notifications_user_unread '
            'ON notifications(user_id, is_read, id DESC)',
            'CREATE INDEX IF NOT EXISTS idx_transactions_user_type_created '
            'ON transactions(user_id, type, created_at)',
            'CREATE INDEX IF NOT EXISTS idx_settlements_user_role_status '
            'ON settlements(user_id, recipient_role, status)',
            'CREATE INDEX IF NOT EXISTS idx_reviews_restaurant_id '
            'ON reviews(restaurant_id, id DESC)',
            'CREATE INDEX IF NOT EXISTS idx_menu_items_restaurant_category '
            'ON menu_items(restaurant_id, category, id)',
            'CREATE INDEX IF NOT EXISTS idx_applications_status_created '
            'ON account_applications(status, created_at DESC)',
        )
        for statement in indexes:
            cur.execute(statement)
        cur.execute("INSERT INTO schema_migrations (version, name) "
                    "VALUES (2, 'operational query indexes')")
    if current_version < 3:
        cur.execute('CREATE INDEX IF NOT EXISTS idx_restaurant_intake_status_created '
                    'ON restaurant_intake(status, created_at DESC)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_restaurant_intake_owner_email_status '
                    'ON restaurant_intake(owner_email, status)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_admin_audit_created '
                    'ON admin_audit_log(created_at DESC)')
        cur.execute("INSERT INTO schema_migrations (version, name) "
                    "VALUES (3, 'restaurant onboarding and audit')")
    if current_version < 4:
        cur.execute('CREATE INDEX IF NOT EXISTS idx_restaurant_intake_menu_items '
                    'ON restaurant_intake_menu_items(intake_id, item_order)')
        cur.execute("INSERT INTO schema_migrations (version, name) "
                    "VALUES (4, 'bulk restaurant menu staging')")
    cur.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
    user_ids = [row[0] for row in cur.execute('SELECT id FROM users').fetchall()]
    conn.commit()
    return user_ids, demo_customer_ids, legacy_wallet_file


def init_database():
    global _INITIALIZED_DATABASE
    conn = connect_database()
    try:
        user_ids, demo_customer_ids, legacy_wallet_file = _initialize_database(conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    for uid in user_ids:
        initial_balance = DEMO_CUSTOMER_BALANCE if uid in demo_customer_ids else 0.0
        wallet_service.ensure(uid, initial_balance)
    if legacy_wallet_file:
        try:
            os.remove(app.config['LEGACY_WALLET_FILE'])
        except OSError as exc:
            app.logger.warning('Legacy wallet data was imported but could not be removed: %s', exc)
    _INITIALIZED_DATABASE = _database_identity()


def _database_identity():
    path = os.fspath(app.config['DATABASE'])
    return path if path.startswith('file:') else os.path.abspath(path)


def ensure_database_initialized():
    if _INITIALIZED_DATABASE == _database_identity():
        return
    with _DATABASE_INIT_LOCK:
        if _INITIALIZED_DATABASE != _database_identity():
            init_database()


def database_health(path=None):
    database = os.fspath(path or app.config['DATABASE'])
    if database != ':memory:' and not database.startswith('file:') and not os.path.isfile(database):
        raise FileNotFoundError(f'SQLite database does not exist: {database}')
    conn = connect_database(database)
    try:
        integrity = [row[0] for row in conn.execute('PRAGMA integrity_check')]
        foreign_keys = [tuple(row) for row in conn.execute('PRAGMA foreign_key_check')]
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        return {'schema_version': version, 'integrity': integrity, 'foreign_key_violations': foreign_keys}
    finally:
        conn.close()


def backup_database(destination, source=None):
    source_path = os.fspath(source or app.config['DATABASE'])
    if source_path != ':memory:' and not source_path.startswith('file:') and not os.path.isfile(source_path):
        raise FileNotFoundError(f'SQLite database does not exist: {source_path}')
    destination_path = os.path.abspath(os.fspath(destination))
    if destination_path == os.path.abspath(source_path):
        raise ValueError('Backup destination must not be the live database file.')
    if os.path.exists(destination_path):
        raise FileExistsError(f'Backup destination already exists: {destination_path}')

    parent = os.path.dirname(destination_path)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix='.orderfood-backup-', suffix='.tmp', dir=parent)
    os.close(fd)
    if os.name == 'posix':
        os.chmod(temporary_path, 0o600)
    source_conn = destination_conn = None
    try:
        source_conn = connect_database(source_path)
        destination_conn = sqlite3.connect(temporary_path)
        source_conn.backup(destination_conn)
        check = [row[0] for row in destination_conn.execute('PRAGMA integrity_check')]
        if check != ['ok']:
            raise RuntimeError(f'Backup failed SQLite integrity validation: {check}')
        violations = [tuple(row) for row in destination_conn.execute('PRAGMA foreign_key_check')]
        if violations:
            raise RuntimeError(f'Backup contains foreign-key violations: {violations}')
        destination_conn.close()
        destination_conn = None
        source_conn.close()
        source_conn = None
        with open(temporary_path, 'rb+') as backup_file:
            os.fsync(backup_file.fileno())
        try:
            os.link(temporary_path, destination_path)
        except FileExistsError:
            raise FileExistsError(f'Backup destination already exists: {destination_path}') from None
        os.remove(temporary_path)
        return destination_path
    finally:
        if destination_conn is not None:
            destination_conn.close()
        if source_conn is not None:
            source_conn.close()
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


def create_platform_admin(email, name, password):
    email = email.strip().lower()
    name = name.strip()
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email) or len(email) > 254:
        raise ValueError('Enter a valid platform administrator email address.')
    if not name or len(name) > 120:
        raise ValueError('Administrator name must contain 1-120 characters.')
    if len(password) < 16:
        raise ValueError('Platform administrator passwords must be at least 16 characters.')
    conn = connect_database()
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM users WHERE email = ?', (email,)).fetchone():
            raise ValueError('That email already belongs to an account; no role was changed.')
        user_id = conn.execute(
            'INSERT INTO users (email, name, password, role) VALUES (?,?,?,?)',
            (email, name, generate_password_hash(password), 'platform_admin')).lastrowid
        conn.execute(
            'INSERT INTO admin_audit_log (actor_id, action, target_type, target_id, details_json) '
            'VALUES (?,?,?,?,?)',
            (user_id, 'platform_admin_create', 'user', str(user_id),
             json.dumps({'provisioning': 'trusted_cli'}, separators=(',', ':'))))
        conn.commit()
        return user_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Security helpers (CSRF, auth)
# ---------------------------------------------------------------------------

def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_hex(16)
    return session['_csrf']


@app.before_request
def initialize_database_before_request():
    ensure_database_initialized()


@app.before_request
def block_production_demo_sessions():
    if (_deployment_environment in {'production', 'prod'} and
            session.get('email') in DEMO_USER_EMAILS):
        session.clear()


@app.before_request
def csrf_protect():
    if request.method == 'POST':
        if request.endpoint in {'api_create_order', 'api_verify_payment', 'api_cancel_order'} \
                and 'user_id' not in session:
            return
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
            'delivery_agent': 'delivery_agent_dashboard',
            'platform_admin': 'admin_restaurants'}.get(role, 'home')


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


def record_admin_action(db, actor_id, action, target_type, target_id, details=None):
    db.execute(
        'INSERT INTO admin_audit_log (actor_id, action, target_type, target_id, details_json) '
        'VALUES (?,?,?,?,?)',
        (actor_id, action, target_type, str(target_id),
         json.dumps(details or {}, sort_keys=True, separators=(',', ':'))))


def create_staged_restaurant(db, intake):
    restaurant_id = db.execute(
        'INSERT INTO restaurants (slug, name, address, description, rating, is_active) '
        'VALUES (?,?,?,?,0,0)',
        (intake['slug'], intake['restaurant_name'], intake['address'],
         intake['description'])).lastrowid
    db.execute(
        'INSERT INTO menu_items (restaurant_id, name, description, price, category, is_available) '
        'SELECT ?, name, description, price, category, is_available '
        'FROM restaurant_intake_menu_items WHERE intake_id = ? ORDER BY item_order',
        (restaurant_id, intake['id']))
    return restaurant_id


def wallet_key():
    return session.get('user_id')


def notify(db, user_id, message):
    db.execute('INSERT INTO notifications (user_id, message) VALUES (?, ?)', (user_id, message))


def notify_restaurant(db, restaurant_id, message):
    for row in db.execute('SELECT id FROM users WHERE restaurant_id = ?', (restaurant_id,)):
        notify(db, row['id'], message)


@app.context_processor
def inject_globals():
    uid = session.get('user_id')
    if not uid:
        return {'wallet': {'balance': 0, 'currency': 'INR'}, 'current_user': 'Guest',
                'cart_count': 0, 'unread': 0, 'FOOD_CATEGORIES': [], 'can_order': False}
    db = get_db()
    unread = db.execute('SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0',
                        (uid,)).fetchone()[0]
    return {
        'wallet': wallet_service.get_balance(wallet_key()),
        'current_user': session.get('user_name', 'Guest'),
        'cart_count': sum(session.get('cart', {}).values()),
        'unread': unread,
        'FOOD_CATEGORIES': menu_category_names(db),
        'can_order': session.get('role') == 'customer' and session.get('loc_ok') is True
                     and bool(session.get('loc')),
    }


@app.context_processor
def inject_maps():
    return {'maps_cfg': map_service.browser_config(), 'maps_enabled': map_service.enabled}


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
        account_type = request.form.get('account_type', 'customer')
        password_field = 'password' if account_type == 'customer' else 'staff_password'
        password = request.form.get(password_field) or ''
        note = (request.form.get('accessibility_note') or '').strip()[:200]
        restaurant_name = (request.form.get('restaurant_name') or '').strip()
        restaurant_address = (request.form.get('restaurant_address') or '').strip()

        error = None
        if account_type not in {'customer', 'restaurant_admin', 'delivery_agent'}:
            error = 'Choose a valid account type.'
        elif not email or not name:
            error = 'Name and email are required.'
        elif len(name) > 120 or len(password) > 1024:
            error = 'Name or password is longer than allowed.'
        elif len(email) > 254 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
            error = 'Enter a valid email address.'
        elif account_type == 'customer' and len(password) < 8:
            error = 'Password must be at least 8 characters.'
        elif account_type != 'customer' and len(password) < 12:
            error = 'Staff application passwords must be at least 12 characters.'
        elif account_type == 'restaurant_admin' and (not restaurant_name or not restaurant_address):
            error = 'Restaurant name and address are required for a restaurant application.'
        elif account_type == 'restaurant_admin' and (
                len(restaurant_name) > 120 or len(restaurant_address) > 300):
            error = 'Restaurant name or address is longer than allowed.'
        if error:
            flash(error, 'error')
            return render_template('register.html'), 400

        db = get_db()
        if account_type != 'customer':
            if db.execute('SELECT 1 FROM users WHERE email = ?', (email,)).fetchone():
                flash('This email is already registered.', 'error')
                return render_template('register.html'), 400
            claimed_restaurant = None
            if account_type == 'restaurant_admin':
                pending_intake = db.execute(
                    "SELECT 1 FROM restaurant_intake WHERE owner_email = ? AND status = 'pending'",
                    (email,)).fetchone()
                if pending_intake:
                    flash('A platform administrator must review the imported restaurant before you apply.',
                          'error')
                    return render_template('register.html'), 400
                claimed_restaurant = db.execute(
                    "SELECT ri.restaurant_id, r.name, r.address FROM restaurant_intake ri "
                    "JOIN restaurants r ON r.id = ri.restaurant_id "
                    "WHERE ri.owner_email = ? AND ri.status = 'approved' AND r.is_active = 0 "
                    "AND NOT EXISTS (SELECT 1 FROM users u WHERE u.restaurant_id = r.id)",
                    (email,)).fetchone()
                if claimed_restaurant:
                    restaurant_name = claimed_restaurant['name']
                    restaurant_address = claimed_restaurant['address']
            try:
                db.execute(
                    'INSERT INTO account_applications '
                    '(email, name, requested_role, restaurant_name, restaurant_address, password_hash, restaurant_id) '
                    'VALUES (?,?,?,?,?,?,?)',
                    (email, name, account_type,
                     restaurant_name if account_type == 'restaurant_admin' else None,
                     restaurant_address if account_type == 'restaurant_admin' else None,
                     generate_password_hash(password),
                     claimed_restaurant['restaurant_id'] if claimed_restaurant else None))
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                flash('An application for this email is already awaiting review.', 'error')
                return render_template('register.html'), 400
            flash(
                'Application submitted. A platform administrator must verify and provision '
                'your account before you can log in.',
                'success')
            return redirect(url_for('register'))

        try:
            user_id = db.execute(
                'INSERT INTO users (email, name, password, role, restaurant_id, accessibility_note) '
                'VALUES (?,?,?,?,?,?)',
                (email, name, generate_password_hash(password), 'customer', None, note)).lastrowid
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            flash('Email already registered.', 'error')
            return render_template('register.html'), 400

        wallet_service.ensure(user_id, 0.0)
        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/admin/restaurants')
@login_required('platform_admin')
def admin_restaurants():
    db = get_db()
    applications = db.execute(
        "SELECT * FROM account_applications WHERE status = 'pending' ORDER BY created_at, id "
        "LIMIT 200").fetchall()
    intake_rows = db.execute(
        "SELECT * FROM restaurant_intake WHERE status = 'pending' ORDER BY created_at, id "
        "LIMIT 500").fetchall()
    intake_rows = [dict(row, menu_preview=json.loads(row['menu_json'])) for row in intake_rows]
    audit_rows = db.execute(
        'SELECT a.*, u.name AS actor_name FROM admin_audit_log a '
        'JOIN users u ON u.id = a.actor_id ORDER BY a.id DESC LIMIT 50').fetchall()
    return render_template('admin_restaurants.html', applications=applications,
                           intake_rows=intake_rows, audit_rows=audit_rows)


@app.route('/admin/restaurants/import', methods=['POST'])
@login_required('platform_admin')
def admin_import_restaurants():
    upload = request.files.get('csv_file')
    if not upload or not upload.filename:
        flash('Choose a CSV file to import.', 'error')
        return redirect(url_for('admin_restaurants'))
    content = upload.stream.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        flash('CSV file exceeds the 2 MiB limit.', 'error')
        return redirect(url_for('admin_restaurants'))
    try:
        text_content = content.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text_content, newline=''), strict=True)
        required_headers = {
            'restaurant_name', 'restaurant_slug', 'address', 'description',
            'owner_name', 'owner_email', 'menu_json',
        }
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)) or \
                set(reader.fieldnames) != required_headers:
            raise ValueError('CSV must contain exactly the required onboarding headers.')
        rows = []
        seen_slugs = set()
        seen_emails = set()
        db = get_db()
        known_categories = set(menu_category_names(db))
        for line_number, raw in enumerate(reader, start=2):
            if line_number > 502:
                raise ValueError('A single import may contain at most 500 restaurants.')
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError(f'CSV row {line_number} has missing or extra columns.')
            row = {key: (value or '').strip() for key, value in raw.items()}
            for key, maximum in (
                    ('restaurant_name', 120), ('restaurant_slug', 80), ('address', 300),
                    ('description', 1000), ('owner_name', 120), ('owner_email', 254)):
                if not row[key] or len(row[key]) > maximum:
                    raise ValueError(f'CSV row {line_number} has an empty or oversized {key}.')
            slug = row['restaurant_slug'].lower()
            email = row['owner_email'].lower()
            if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
                raise ValueError(f'CSV row {line_number} has an invalid restaurant_slug.')
            if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
                raise ValueError(f'CSV row {line_number} has an invalid owner_email.')
            if len(row['menu_json']) > 500000:
                raise ValueError(f'CSV row {line_number} has menu_json over 500,000 characters.')
            try:
                menu = json.loads(row['menu_json'], object_pairs_hook=_reject_duplicate_json_keys,
                                  parse_constant=_reject_json_constant)
            except (json.JSONDecodeError, RecursionError, ValueError) as exc:
                raise ValueError(f'CSV row {line_number} has invalid menu_json: {exc}') from exc
            if not isinstance(menu, list) or not menu or len(menu) > 200:
                raise ValueError(f'CSV row {line_number} must provide 1-200 menu items.')
            validated_menu = []
            for item in menu:
                if not isinstance(item, dict) or not {'name', 'price', 'category'} <= set(item) or \
                        set(item) - {'name', 'description', 'price', 'category', 'available'}:
                    raise ValueError(f'CSV row {line_number} has an invalid menu item shape.')
                name = item['name'].strip() if isinstance(item['name'], str) else ''
                description = item.get('description', '')
                category = item['category']
                price = item['price']
                available = item.get('available', True)
                try:
                    numeric_price = float(price)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError(f'CSV row {line_number} has a nonnumeric menu price.') from exc
                if (not name or len(name) > 120 or isinstance(price, bool) or
                        not math.isfinite(numeric_price) or not 0.01 <= round(numeric_price, 2) <= 1_000_000 or
                        not isinstance(category, str) or category not in known_categories or
                        not isinstance(description, str) or len(description) > 500 or
                        not isinstance(available, bool)):
                    raise ValueError(f'CSV row {line_number} has an invalid menu item.')
                validated_menu.append({
                    'name': name, 'description': description.strip(),
                    'price': round(numeric_price, 2), 'category': category,
                    'available': available,
                })
            if slug in seen_slugs or email in seen_emails:
                raise ValueError(f'CSV row {line_number} duplicates a slug or owner email in this file.')
            seen_slugs.add(slug)
            seen_emails.add(email)
            rows.append((row['restaurant_name'], slug, row['address'], row['description'],
                         row['owner_name'], email, validated_menu))
        if not rows:
            raise ValueError('CSV contains no restaurant rows.')
    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        flash(f'Import rejected: {exc}', 'error')
        return redirect(url_for('admin_restaurants'))

    try:
        db.execute('BEGIN IMMEDIATE')
        pending_count = db.execute(
            "SELECT COUNT(*) FROM restaurant_intake WHERE status = 'pending'").fetchone()[0]
        inserted = 0
        skipped = 0
        for row in rows:
            existing_slug = db.execute(
                'SELECT id, owner_email, status FROM restaurant_intake WHERE slug = ?',
                (row[1],)).fetchone()
            existing_restaurant = db.execute(
                'SELECT 1 FROM restaurants WHERE slug = ?', (row[1],)).fetchone()
            existing_email = db.execute(
                "SELECT slug FROM restaurant_intake WHERE owner_email = ? AND status != 'rejected'",
                (row[5],)).fetchone()
            if existing_slug:
                if existing_slug['owner_email'] != row[5]:
                    raise ValueError(f"Slug {row[1]!r} is already assigned to another owner.")
                if existing_slug['status'] == 'rejected':
                    if pending_count >= 500:
                        raise ValueError('The review queue is full; review staged restaurants first.')
                    db.execute(
                        "UPDATE restaurant_intake SET restaurant_name = ?, address = ?, description = ?, "
                        "owner_name = ?, menu_json = ?, status = 'pending', restaurant_id = NULL WHERE id = ?",
                        (row[0], row[2], row[3], row[4],
                         json.dumps(row[6], separators=(',', ':')), existing_slug['id']))
                    db.execute('DELETE FROM restaurant_intake_menu_items WHERE intake_id = ?',
                               (existing_slug['id'],))
                    db.executemany(
                        'INSERT INTO restaurant_intake_menu_items '
                        '(intake_id, name, description, price, category, is_available, item_order) '
                        'VALUES (?,?,?,?,?,?,?)',
                        [(existing_slug['id'], item['name'], item['description'], item['price'],
                          item['category'], int(item['available']), index)
                         for index, item in enumerate(row[6])])
                    inserted += 1
                    pending_count += 1
                    continue
                skipped += 1
                continue
            if existing_restaurant:
                raise ValueError(f"Slug {row[1]!r} is already used by a restaurant.")
            if existing_email:
                raise ValueError(f"Owner email {row[5]!r} is already assigned to an imported restaurant.")
            if db.execute('SELECT 1 FROM users WHERE email = ?', (row[5],)).fetchone():
                raise ValueError(f'Owner email {row[5]!r} already belongs to an account.')
            if db.execute(
                    "SELECT 1 FROM account_applications WHERE email = ? AND status = 'pending'",
                    (row[5],)).fetchone():
                raise ValueError(f'Owner email {row[5]!r} already has a pending application.')
            if pending_count >= 500:
                raise ValueError('The review queue is full; review staged restaurants first.')
            inserted_row = db.execute(
                'INSERT INTO restaurant_intake '
                '(restaurant_name, slug, address, description, owner_name, owner_email, menu_json) '
                'VALUES (?,?,?,?,?,?,?)',
                (*row[:6], json.dumps(row[6], separators=(',', ':'))))
            intake_id = inserted_row.lastrowid
            db.executemany(
                'INSERT INTO restaurant_intake_menu_items '
                '(intake_id, name, description, price, category, is_available, item_order) '
                'VALUES (?,?,?,?,?,?,?)',
                [(intake_id, item['name'], item['description'], item['price'],
                  item['category'], int(item['available']), index)
                 for index, item in enumerate(row[6])])
            inserted += 1
            pending_count += 1
        record_admin_action(db, session['user_id'], 'bulk_import', 'restaurant_intake',
                            f'batch-{secrets.token_hex(8)}',
                            {'inserted': inserted, 'skipped': skipped})
        db.commit()
    except (sqlite3.IntegrityError, ValueError) as exc:
        db.rollback()
        flash(f'Import rejected; no rows were staged: {exc}', 'error')
        return redirect(url_for('admin_restaurants'))
    flash(f'Import staged {inserted} restaurant(s); {skipped} idempotent row(s) were skipped. '
          'Imported restaurants remain inactive until approved and claimed.', 'success')
    return redirect(url_for('admin_restaurants'))


@app.route('/admin/restaurants/intake/<int:intake_id>/<action>', methods=['POST'])
@login_required('platform_admin')
def admin_review_intake(intake_id, action):
    if action not in {'approve', 'reject'}:
        abort(404)
    db = get_db()
    intake = db.execute(
        "SELECT * FROM restaurant_intake WHERE id = ? AND status = 'pending'", (intake_id,)).fetchone()
    if not intake:
        abort(404, 'Pending restaurant import was not found.')
    try:
        db.execute('BEGIN IMMEDIATE')
        if action == 'approve':
            if db.execute('SELECT 1 FROM restaurants WHERE slug = ?', (intake['slug'],)).fetchone():
                db.rollback()
                flash('That restaurant slug is already in use; resolve the conflict before approval.', 'error')
                return redirect(url_for('admin_restaurants'))
            restaurant_id = create_staged_restaurant(db, intake)
            db.execute("UPDATE restaurant_intake SET status = 'approved', restaurant_id = ? WHERE id = ?",
                       (restaurant_id, intake_id))
        else:
            db.execute("UPDATE restaurant_intake SET status = 'rejected' WHERE id = ?", (intake_id,))
        record_admin_action(db, session['user_id'], f'intake_{action}', 'restaurant_intake',
                            intake_id, {'slug': intake['slug'], 'owner_email': intake['owner_email']})
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        flash('The review could not be saved because of a data conflict.', 'error')
        return redirect(url_for('admin_restaurants'))
    flash('Restaurant intake approved. It remains hidden until its owner account is approved.'
          if action == 'approve' else 'Restaurant intake rejected.', 'success')
    return redirect(url_for('admin_restaurants'))


@app.route('/admin/restaurants/intake/bulk', methods=['POST'])
@login_required('platform_admin')
def admin_review_intake_bulk():
    action = request.form.get('action')
    raw_ids = request.form.getlist('intake_ids')
    if action not in {'approve', 'reject'} or not raw_ids or len(raw_ids) > 500:
        flash('Select between 1 and 500 restaurant intakes and choose an action.', 'error')
        return redirect(url_for('admin_restaurants'))
    try:
        intake_ids = [int(value) for value in raw_ids]
    except ValueError:
        flash('The selected restaurant intake IDs are invalid.', 'error')
        return redirect(url_for('admin_restaurants'))
    if any(value < 1 for value in intake_ids) or len(intake_ids) != len(set(intake_ids)):
        flash('The selected restaurant intake IDs are invalid or duplicated.', 'error')
        return redirect(url_for('admin_restaurants'))

    db = get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        for intake_id in intake_ids:
            intake = db.execute(
                "SELECT * FROM restaurant_intake WHERE id = ? AND status = 'pending'",
                (intake_id,)).fetchone()
            if not intake:
                raise ValueError(f'Intake {intake_id} is no longer pending.')
            if action == 'approve':
                if db.execute('SELECT 1 FROM restaurants WHERE slug = ?', (intake['slug'],)).fetchone():
                    raise ValueError(f"Restaurant slug {intake['slug']!r} is already in use.")
                restaurant_id = create_staged_restaurant(db, intake)
                db.execute(
                    "UPDATE restaurant_intake SET status = 'approved', restaurant_id = ? WHERE id = ?",
                    (restaurant_id, intake_id))
            else:
                db.execute("UPDATE restaurant_intake SET status = 'rejected' WHERE id = ?",
                           (intake_id,))
            record_admin_action(db, session['user_id'], f'intake_{action}',
                                'restaurant_intake', intake_id,
                                {'slug': intake['slug'], 'owner_email': intake['owner_email']})
        record_admin_action(db, session['user_id'], f'bulk_intake_{action}',
                            'restaurant_intake_batch', secrets.token_hex(8),
                            {'count': len(intake_ids), 'intake_ids': intake_ids})
        db.commit()
    except (sqlite3.IntegrityError, ValueError) as exc:
        db.rollback()
        flash(f'Bulk review was not applied: {exc}', 'error')
        return redirect(url_for('admin_restaurants'))
    outcome = 'approved' if action == 'approve' else 'rejected'
    flash(f'{len(intake_ids)} restaurant intake(s) {outcome}. '
          'Approved listings remain inactive until owner accounts are approved.', 'success')
    return redirect(url_for('admin_restaurants'))


@app.route('/admin/applications/<int:application_id>/<action>', methods=['POST'])
@login_required('platform_admin')
def admin_review_application(application_id, action):
    if action not in {'approve', 'reject'}:
        abort(404)
    db = get_db()
    application = db.execute(
        "SELECT * FROM account_applications WHERE id = ? AND status = 'pending'",
        (application_id,)).fetchone()
    if not application:
        abort(404, 'Pending application was not found.')
    if action == 'approve' and not application['password_hash']:
        flash('This legacy application has no stored password. Ask the applicant to submit a new application.',
              'error')
        return redirect(url_for('admin_restaurants'))
    try:
        db.execute('BEGIN IMMEDIATE')
        if action == 'approve':
            restaurant_id = None
            if application['requested_role'] == 'restaurant_admin':
                restaurant_id = application['restaurant_id']
                if restaurant_id:
                    restaurant = db.execute(
                        'SELECT is_active FROM restaurants WHERE id = ?', (restaurant_id,)).fetchone()
                    if not restaurant or restaurant['is_active']:
                        raise ValueError('The imported restaurant is unavailable or already claimed.')
                    if db.execute('SELECT 1 FROM users WHERE restaurant_id = ?', (restaurant_id,)).fetchone():
                        raise ValueError('The imported restaurant already has an owner account.')
                    db.execute('UPDATE restaurants SET is_active = 1 WHERE id = ?', (restaurant_id,))
                else:
                    slug = restaurant_slug(application['restaurant_name'], db)
                    restaurant_id = db.execute(
                        'INSERT INTO restaurants (slug, name, address, description, rating, is_active) '
                        'VALUES (?,?,?,?,0,1)',
                        (slug, application['restaurant_name'], application['restaurant_address'],
                         'New restaurant partner')).lastrowid
            user_id = db.execute(
                'INSERT INTO users (email, name, password, role, restaurant_id) VALUES (?,?,?,?,?)',
                (application['email'], application['name'], application['password_hash'],
                 application['requested_role'], restaurant_id)).lastrowid
            db.execute(
                "UPDATE account_applications SET status = 'approved', password_hash = NULL WHERE id = ?",
                (application_id,))
            record_admin_action(db, session['user_id'], 'application_approve',
                                'account_application', application_id,
                                {'email': application['email'], 'created_user_id': user_id,
                                 'restaurant_id': restaurant_id})
        else:
            db.execute("UPDATE account_applications SET status = 'rejected', password_hash = NULL WHERE id = ?",
                       (application_id,))
            record_admin_action(db, session['user_id'], 'application_reject',
                                'account_application', application_id,
                                {'email': application['email']})
        db.commit()
    except (sqlite3.IntegrityError, ValueError) as exc:
        db.rollback()
        flash(f'Application could not be reviewed: {exc}', 'error')
        return redirect(url_for('admin_restaurants'))
    flash('Application approved; the account is now available for login.'
          if action == 'approve' else 'Application rejected.', 'success')
    return redirect(url_for('admin_restaurants'))


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
                                  0.0)
            if user['role'] == 'customer':
                session['loc_ok'] = False
                session['loc'] = [user['lat'], user['lon']] if user['lat'] is not None and user['lon'] is not None else None
                session['address'] = user['location_address'] or ''
                return redirect(url_for('home'))
            return redirect(url_for(role_home(user['role'])))
        flash('Invalid email or password.', 'error')
    return render_template('login.html')


@app.route('/location', methods=['GET', 'POST'])
@login_required('customer')
def location():
    """Optionally confirm a delivery pin; customers can browse without a location."""
    db = get_db()
    if request.method == 'POST':
        if request.form.get('action') == 'skip':
            session['loc_ok'] = False
            session['loc'] = None
            session['address'] = ''
            return redirect(safe_next(url_for('home')))
        point = maps_service.valid_point(request.form.get('lat'), request.form.get('lon'))
        address = (request.form.get('address') or '').strip()[:200]
        if not point:
            flash('Choose a precise location to place orders, or continue browsing read-only.', 'error')
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
                           next=nxt if nxt.startswith('/') and not nxt.startswith('//') else '')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Customer: browsing
# ---------------------------------------------------------------------------

def customer_point():
    loc = session.get('loc') if session.get('loc_ok') else None
    return (loc[0], loc[1]) if loc else None


def eta_for_restaurants(rows):
    """Return optional route estimates from restaurants to the confirmed customer location."""
    dest = customer_point()
    points = {r['id']: (r['lat'], r['lon']) for r in rows if r['lat'] is not None and r['lon'] is not None}
    drive = map_service.deliveries_eta(points, dest) if dest and points else {}
    out = {}
    for r in rows:
        e = drive.get(r['id'])
        out[r['id']] = ({'minutes': math.ceil(e['minutes']) + PICKUP_BUFFER_MIN,
                         'km': e['km'], 'source': e['source']}
                        if e else {'minutes': None, 'km': None, 'source': 'none'})
    if map_service.enabled and map_service.last_error and not session.get('maps_warned'):
        session['maps_warned'] = True
        flash('Live Google Maps data is unavailable right now, so delivery times are approximate.', 'warning')
    return out


@app.route('/')
def home():
    db = get_db()
    q = (request.args.get('q') or '').strip()
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
    reachable = []
    rows = db.execute(sql + ' ORDER BY feedback_rating DESC, r.name', params).fetchall()
    etas = eta_for_restaurants(rows)
    for r in rows:
        e = etas[r['id']]
        reachable.append((r, e['minutes'], e['km']))
    reachable.sort(key=lambda x: x[1] if x[1] is not None else float('inf'))

    awaiting = []
    if session.get('role') == 'customer':
        awaiting = db.execute(
            "SELECT o.*, r.name AS rest_name, "
            "(SELECT group_concat(name || ' x' || qty, ', ') FROM order_items WHERE order_id = o.id) AS summary "
            "FROM orders o JOIN restaurants r ON r.id = o.restaurant_id "
            "WHERE o.user_id = ? AND o.status = 'delivered'", (session['user_id'],)).fetchall()
    can_order = bool(customer_point())
    return render_template('home.html', reachable=reachable, q=q, awaiting=awaiting,
                           ordering_available=session.get('role') == 'customer' and can_order)


@app.route('/restaurant/<int:rest_id>')
def restaurant_detail(rest_id):
    db = get_db()
    rest = db.execute('SELECT * FROM restaurants WHERE id = ? AND is_active = 1', (rest_id,)).fetchone()
    if not rest:
        abort(404, 'Restaurant not found.')
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
                           delivery_time=minutes, distance_km=est['km'],
                           cart=session.get('cart', {}),
                           ordering_available=session.get('role') == 'customer' and bool(customer_point()))


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
        f'SELECT m.*, r.name AS rest_name, r.address AS rest_address, r.lat AS rest_lat, r.lon AS rest_lon, r.is_open, r.is_active '
        f'FROM menu_items m JOIN restaurants r ON r.id = m.restaurant_id WHERE m.id IN ({marks})', ids).fetchall()
    found = {str(r['id']) for r in rows}
    if found != set(cart):                       # item was deleted by the restaurant
        session['cart'] = {k: v for k, v in cart.items() if k in found}
    etas = eta_for_restaurants([{'id': r['restaurant_id'], 'lat': r['rest_lat'], 'lon': r['rest_lon']} for r in rows])
    groups = {}
    for r in rows:
        qty = cart[str(r['id'])]
        grp = groups.setdefault(r['restaurant_id'], {
            'restaurant_id': r['restaurant_id'], 'name': r['rest_name'], 'items': [], 'subtotal': 0,
            'minutes': etas[r['restaurant_id']]['minutes'], 'km': etas[r['restaurant_id']]['km'],
            'is_open': bool(r['is_open']) and bool(r['is_active']), 'problems': []})
        line = qty * r['price']
        grp['items'].append({'id': r['id'], 'name': r['name'], 'price': r['price'], 'qty': qty,
                             'line': line, 'available': bool(r['is_available'])})
        grp['subtotal'] += line
    for grp in groups.values():
        if not customer_point():
            grp['problems'].append('Confirm your delivery location before ordering.')
        if not grp['is_open']:
            grp['problems'].append('This restaurant is currently closed.')
        if any(not i['available'] for i in grp['items']):
            grp['problems'].append('Some items are sold out.')
    return list(groups.values())


@app.route('/add_to_cart', methods=['POST'])
@login_required('customer')
def add_to_cart():
    db = get_db()
    item = db.execute(
        'SELECT m.*, r.address, r.lat, r.lon, r.is_open, r.is_active FROM menu_items m '
        'JOIN restaurants r ON r.id = m.restaurant_id WHERE m.id = ?',
        (request.form.get('item_id', type=int),)).fetchone()
    back = safe_next(url_for('view_cart'))
    if not item or not item['is_active']:
        flash('That item does not exist.', 'error')
    elif not item['is_available']:
        flash(f"{item['name']} is sold out.", 'error')
    elif not item['is_open']:
        flash('That restaurant is currently closed.', 'error')
    elif not customer_point():
        flash('Set a delivery location before adding items to your cart.', 'error')
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
    """Create one order and take its payment. Returns (ok, message, order_id)."""
    try:
        cur = db.execute(
            "INSERT INTO orders (restaurant_id, user_id, customer_email, delivery_address, total_amount, "
            "status, estimated_delivery_time, payment_ref, dest_lat, dest_lon) VALUES (?,?,?,?,?,'pending',?,?,?,?)",
            (group['restaurant_id'], user_id, email, address, group['subtotal'], group['minutes'], ref,
             point[0] if point else None, point[1] if point else None))
        order_id = cur.lastrowid
        db.executemany('INSERT INTO order_items (order_id, item_id, name, price, qty) VALUES (?,?,?,?,?)',
                       [(order_id, i['id'], i['name'], i['price'], i['qty']) for i in group['items']])
        db.execute("INSERT INTO transactions (order_id, restaurant_id, amount, type, payment_method, user_id) "
                   "VALUES (?,?,?,'payment',?,?)",
                   (order_id, group['restaurant_id'], group['subtotal'], payment_method, user_id))
        db.execute("INSERT INTO deliveries (order_id, delivery_agent_name, status, distance_km) "
                   "VALUES (?, 'Unassigned', 'not_requested', ?)",
                   (order_id, group.get('km') or 0.5))
    except sqlite3.Error as exc:
        db.rollback()
        return False, f'System error: {exc}', None

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


def ensure_razorpay_payment_captured(order_id, payment_id, amount_paise):
    """Confirm a payment belongs to this order and capture it before fulfillment."""
    key_id, key_secret = razorpay_credentials()
    if not key_id or not key_secret:
        return jsonify(error='Razorpay is not configured on the server.'), 503

    client = razorpay.Client(auth=(key_id, key_secret))
    try:
        payment = client.payment.fetch(payment_id)
    except (razorpay.errors.BadRequestError, razorpay.errors.GatewayError,
            razorpay.errors.ServerError, requests.exceptions.RequestException,
            OSError, TimeoutError) as exc:
        app.logger.warning('Razorpay payment lookup failed: %s', exc)
        return jsonify(error='Could not confirm payment status. Please retry.'), 502

    if (not isinstance(payment, dict) or payment.get('id') != payment_id or
            payment.get('order_id') != order_id or payment.get('amount') != amount_paise or
            payment.get('currency') != 'INR'):
        app.logger.error('Razorpay payment details did not match order %s.', order_id)
        return jsonify(error='Payment details do not match this order.'), 400

    if payment.get('status') == 'captured' and payment.get('captured') is True:
        return None
    if payment.get('status') != 'authorized':
        return jsonify(error='Payment has not been captured. Please retry or contact support.'), 409

    try:
        payment = client.payment.capture(payment_id, amount_paise)
    except (razorpay.errors.BadRequestError, razorpay.errors.GatewayError,
            razorpay.errors.ServerError, requests.exceptions.RequestException,
            OSError, TimeoutError) as exc:
        app.logger.warning('Razorpay payment capture failed for %s: %s', payment_id, exc)
        return jsonify(error='Payment capture could not be confirmed. Please retry.'), 502

    if (not isinstance(payment, dict) or payment.get('id') != payment_id or
            payment.get('order_id') != order_id or payment.get('amount') != amount_paise or
            payment.get('currency') != 'INR' or payment.get('status') != 'captured' or
            payment.get('captured') is not True):
        app.logger.error('Razorpay did not confirm capture for payment %s.', payment_id)
        return jsonify(error='Payment capture could not be confirmed. Please retry.'), 502
    return None


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
    point = customer_point()
    if not point:
        return jsonify(error='Set a delivery location before placing an order.'), 400
    groups = cart_groups(get_db())
    if not groups or any(group['problems'] for group in groups):
        return jsonify(error='Fix the problems in your cart before paying.'), 400
    if open_orders_for(get_db(), session['user_id']):
        return jsonify(error='Finish your active order before placing another.'), 409
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

    intent = session.get('razorpay_intent')
    if (not intent or intent.get('order_id') != order_id or
            intent.get('user_id') != session['user_id']):
        return jsonify(error='This payment session has expired. Check your orders before retrying.'), 400

    cart = dict(session.get('cart', {}))
    groups = cart_groups(db)
    if not groups or any(group['problems'] for group in groups):
        return jsonify(error='Your cart has changed or is no longer available. Contact support if payment was captured.'), 409
    amount_paise = int(round(sum(group['subtotal'] for group in groups) * 100))
    if (amount_paise != intent.get('amount') or
            checkout_fingerprint(cart) != intent.get('cart_fingerprint')):
        return jsonify(error='Your cart changed after payment started. Contact support if payment was captured.'), 409
    if open_orders_for(db, session['user_id']):
        return jsonify(error='An order is already active. Contact support if payment was captured.'), 409

    payment_error = ensure_razorpay_payment_captured(order_id, payment_id, amount_paise)
    if payment_error:
        return payment_error

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


@app.route('/checkout', methods=['POST'])
@login_required('customer')
def checkout():
    db = get_db()
    if session.get('razorpay_intent'):
        flash('Finish or cancel the Razorpay payment already in progress before paying from your wallet.',
              'error')
        return redirect(url_for('checkout_review'))
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
    point = customer_point()
    if not point:
        return redirect(url_for('location'))

    if open_orders_for(db, session['user_id']):
        return redirect(url_for('checkout_review'))             # shows the "confirm last order" screen

    results, cart = [], dict(session.get('cart', {}))
    for n, grp in enumerate(groups, start=1):
        if grp['problems']:
            ok, msg, order_id = False, ' '.join(grp['problems']), None
        else:
            ok, msg, order_id = place_order(db, session['user_id'], session['email'], grp, address,
                                            f"{token}-{grp['restaurant_id']}", point)
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
        "SELECT o.*, r.name AS rest_name, r.address AS rest_address FROM orders o "
        "JOIN restaurants r ON r.id = o.restaurant_id "
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
        review = db.execute('SELECT rating, feedback FROM reviews WHERE order_id = ?',
                            (selected['id'],)).fetchone()
        tip = db.execute('SELECT amount FROM delivery_tips WHERE order_id = ?',
                         (selected['id'],)).fetchone()
        level = progress_level(selected, delivery)
        detail = {'order': selected, 'items': items, 'delivery': delivery, 'level': level,
                  'review': review, 'tip': tip,
                  'steps': [(s, i + 1 <= level) for i, s in enumerate(TRACK_STEPS)]}
    return render_template('orders.html', rows=rows, detail=detail)


@app.route('/orders/<int:order_id>/tip', methods=['POST'])
@login_required('customer')
def tip_delivery_agent(order_id):
    amount = request.form.get('amount', type=int)
    if amount is None or not 1 <= amount <= 5000:
        flash('Enter a tip between ₹1 and ₹5,000.', 'error')
        return redirect(url_for('orders', order=order_id))

    db = get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        order = db.execute(
            "SELECT o.id, o.restaurant_id, o.status, d.delivery_agent_id "
            "FROM orders o JOIN deliveries d ON d.order_id = o.id "
            "WHERE o.id = ? AND o.user_id = ?", (order_id, session['user_id'])).fetchone()
        if not order or order['status'] not in ('delivered', 'completed') or not order['delivery_agent_id']:
            db.rollback()
            flash('A tip is available only after an assigned delivery agent completes the delivery.', 'error')
            return redirect(url_for('orders', order=order_id))
        if db.execute('SELECT 1 FROM delivery_tips WHERE order_id = ?', (order_id,)).fetchone():
            db.rollback()
            flash('You have already tipped the delivery agent for this order.', 'error')
            return redirect(url_for('orders', order=order_id))

        deducted, message = wallet_service.deduct(
            session['user_id'], amount, f'tip:customer:{order_id}', db=db)
        if not deducted:
            db.rollback()
            flash(f'Tip could not be sent: {message}.', 'error')
            return redirect(url_for('orders', order=order_id))
        credited, message = wallet_service.credit(
            order['delivery_agent_id'], amount, f'tip:agent:{order_id}', db=db)
        if not credited:
            db.rollback()
            app.logger.error('Could not credit tip for order %s: %s', order_id, message)
            flash('The tip could not be transferred. No money was taken.', 'error')
            return redirect(url_for('orders', order=order_id))

        db.execute('INSERT INTO delivery_tips (order_id, customer_id, agent_id, amount) VALUES (?,?,?,?)',
                   (order_id, session['user_id'], order['delivery_agent_id'], amount))
        db.execute(
            "INSERT INTO transactions (order_id, restaurant_id, amount, type, payment_method, user_id) "
            "VALUES (?,?,?,'agent_tip','wallet',?)",
            (order_id, order['restaurant_id'], amount, order['delivery_agent_id']))
        notify(db, order['delivery_agent_id'], f'You received a ₹{amount} tip for order #{order_id}.')
        db.commit()
    except sqlite3.Error:
        db.rollback()
        app.logger.exception('Could not record delivery tip for order %s', order_id)
        flash('The tip could not be recorded. Please try again.', 'error')
        return redirect(url_for('orders', order=order_id))

    flash(f'Thank you. Your ₹{amount} tip was sent to the delivery agent.', 'success')
    return redirect(url_for('orders', order=order_id))


def _own_order_update(sql, order_id):
    db = get_db()
    cur = db.execute(sql, (order_id, session['user_id']))
    db.commit()
    return cur.rowcount == 1


def refund_order(db, order, reason):
    ref = f"refund:order:{order['id']}"
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
    if ok:
        db.execute("INSERT INTO transactions (order_id, restaurant_id, amount, type, payment_method, user_id) "
                   "VALUES (?,?,?,'refund','wallet',?)",
                   (order['id'], order['restaurant_id'], order['total_amount'], order['user_id']))
        notify(db, order['user_id'], f"Order #{order['id']}: {reason}. {money(order['total_amount'])} refunded.")
        return True, ''
    return False, 'The wallet refund could not be recorded. The order was not changed.'


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
        "(SELECT group_concat(name || ' x' || qty, ', ') FROM order_items WHERE order_id = o.id) AS summary "
        'FROM orders o JOIN deliveries d ON d.order_id = o.id WHERE o.restaurant_id = ? '
        'ORDER BY o.id DESC', (rest['id'],)).fetchall()
    menu = db.execute('SELECT * FROM menu_items WHERE restaurant_id = ? ORDER BY category, id', (rest['id'],)).fetchall()
    reviews = db.execute(
        'SELECT rv.*, u.name AS customer_name, o.id AS order_id FROM reviews rv '
        'JOIN users u ON u.id = rv.user_id JOIN orders o ON o.id = rv.order_id '
        'WHERE rv.restaurant_id = ? ORDER BY rv.id DESC LIMIT 20', (rest['id'],)).fetchall()
    revenue_states = ('preparing', 'ready', 'out_for_delivery', 'delivered', 'completed', 'disputed')
    revenue = sum(o['total_amount'] for o in orders_
                  if o['status'] in revenue_states and (o['created_at'] or '')[:10] == _today(db))
    stats = {'new': sum(o['status'] == 'pending' for o in orders_),
             'active': sum(o['status'] in ('preparing', 'ready', 'out_for_delivery') for o in orders_),
             'revenue': revenue}
    return render_template('dashboard_restaurant.html', rest=rest, orders=orders_, menu=menu,
                           reviews=reviews, stats=stats)


def _today(db):
    return db.execute("SELECT date('now')").fetchone()[0]


@app.route('/restaurant/order/<int:order_id>/<action>', methods=['POST'])
@login_required('restaurant_admin')
def restaurant_order_action(order_id, action):
    db = get_db()
    rest = my_restaurant(db)
    order = db.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    delivery = db.execute('SELECT * FROM deliveries WHERE order_id = ?', (order_id,)).fetchone()
    if not order or not delivery:
        abort(404, 'Order not found.')
    if order['restaurant_id'] != rest['id']:
        abort(404, 'Order not found.')

    def set_status(new, *allowed):
        cur = db.execute(f"UPDATE orders SET status = ? WHERE id = ? AND status IN ({','.join('?' * len(allowed))})",
                         (new, order_id, *allowed))
        return cur.rowcount == 1

    msg = None
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
    elif action == 'ready' and set_status('ready', 'preparing'):
        if delivery['delivery_agent_id']:
            notify(db, delivery['delivery_agent_id'], f'Order #{order_id} is ready for pickup.')
        notify(db, order['user_id'], f'Order #{order_id} is ready.')
        msg = 'Marked as ready.'
    elif action == 'request_agent' and order['status'] in ('preparing', 'ready') and db.execute(
            "UPDATE deliveries SET status = 'pending' WHERE order_id = ? AND status = 'not_requested'",
            (order_id,)).rowcount == 1:
        db.execute('DELETE FROM delivery_rejections WHERE delivery_id = ?', (delivery['id'],))
        advance_expired_offers(db)
        assigned = assign_next_agent(db, delivery['id'])
        msg = ('A delivery request was sent to the best-ranked available agent.'
               if assigned else 'No available delivery agent; please self-deliver this order.')
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
        settle_order_id = order_id
        msg = 'Marked as delivered.'
    if msg:
        db.commit()
        if settle_order_id:
            settle_razorpay_order(db, settle_order_id)
        flash(msg, 'success')
    else:
        db.rollback()
        flash('That action is not possible for this order right now.', 'error')
    return redirect(url_for('restaurant_dashboard') + '#orders')


def pay_restaurant(db, order):
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


@app.route('/restaurant/menu/add', methods=['POST'])
@login_required('restaurant_admin')
def menu_add():
    db = get_db()
    rest = my_restaurant(db)
    name = (request.form.get('name') or '').strip()
    price = request.form.get('price', type=float)
    category = request.form.get('category') or 'Main Course'
    if not name or price is None or price <= 0 or category not in menu_category_names(db):
        flash('Enter an item name, a valid category, and a price above zero.', 'error')
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
    elif action == 'category':
        category = request.form.get('category') or ''
        if category not in menu_category_names(db):
            flash('Choose a valid menu category.', 'error')
            return redirect(url_for('restaurant_dashboard') + '#menu')
        db.execute('UPDATE menu_items SET category = ? WHERE id = ?', (category, item_id))
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
        point = maps_service.valid_point(request.form.get('lat'), request.form.get('lon'))
        if point:
            db.execute('UPDATE restaurants SET lat = ?, lon = ? WHERE id = ?', (point[0], point[1], rest['id']))
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
        f'r.name AS rest_name, r.address AS rest_address, r.lat AS rest_lat, r.lon AS rest_lon, o.dest_lat, o.dest_lon, u.name AS customer_name, '
        f'u.accessibility_note AS customer_note, '
        f"(SELECT group_concat(name || ' x' || qty, ', ') FROM order_items WHERE order_id = o.id) AS summary "
        f'FROM deliveries d JOIN orders o ON o.id = d.order_id JOIN restaurants r ON r.id = o.restaurant_id '
        f'LEFT JOIN users u ON u.id = o.user_id '
        f'WHERE d.delivery_agent_id = ? AND d.status IN ({marks}) LIMIT 1', (agent_id, *ACTIVE_DELIVERY_STATES)).fetchone()


def pending_requests(db, agent_id):
    return db.execute(
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


@app.route('/dashboard/delivery-agent')
@login_required('delivery_agent')
def delivery_agent_dashboard():
    db = get_db()
    agent = current_agent(db)
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
        "SELECT COALESCE((SELECT SUM(amount) FROM transactions WHERE type IN ('agent_payout', 'agent_tip') "
        "AND user_id = ? AND date(created_at) = date('now')), 0) + "
        "COALESCE((SELECT SUM(amount_paise / 100.0) FROM settlements WHERE user_id = ? "
        "AND recipient_role = 'delivery_agent' AND status IN ('submitted', 'paid') "
        "AND date(created_at) = date('now')), 0)",
        (agent['id'], agent['id'])).fetchone()[0]
    history = db.execute(
        "SELECT d.*, r.name AS rest_name FROM deliveries d JOIN orders o ON o.id = d.order_id "
        "JOIN restaurants r ON r.id = o.restaurant_id WHERE d.delivery_agent_id = ? "
        "AND d.status IN ('delivered', 'failed') ORDER BY d.id DESC LIMIT 10", (agent['id'],)).fetchall()
    settlements = db.execute(
        "SELECT s.*, o.id AS oid FROM settlements s JOIN orders o ON o.id = s.order_id "
        "WHERE s.user_id = ? AND s.recipient_role = 'delivery_agent' "
        "ORDER BY s.id DESC LIMIT 10", (agent['id'],)).fetchall()
    return render_template('dashboard_delivery.html', agent=agent, requests=reqs, earned=earned,
                           active=active_delivery(db, agent['id']), history=history,
                           settlements=settlements)


@app.route('/agent/settings', methods=['POST'])
@login_required('delivery_agent')
def agent_settings():
    db = get_db()
    if request.form.get('process_pending'):
        agent = current_agent(db)
        if not agent['payout_account_id']:
            flash('Add an approved Razorpay linked account before processing payouts.', 'error')
            return redirect(url_for('delivery_agent_dashboard') + '#payout')
        settle_pending_for_user(db, session['user_id'], 'delivery_agent')
        flash('Pending setup payouts were checked. Review the settlement status below.', 'success')
        return redirect(url_for('delivery_agent_dashboard') + '#payout')
    method = request.form.get('payment_method')
    if method in PAY_RATES:
        db.execute('UPDATE users SET payment_method = ? WHERE id = ?', (method, session['user_id']))
        flash(f'Payment method set to: {PAY_LABELS[method].lower()}.', 'success')
    if request.form.get('toggle_available'):
        db.execute('UPDATE users SET is_available = 1 - is_available WHERE id = ?', (session['user_id'],))
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
                           preview=request_preview(agent, req))


@app.route('/agent/request/<int:delivery_id>/accept', methods=['POST'])
@login_required('delivery_agent')
def agent_accept(delivery_id):
    db = get_db()
    agent = current_agent(db)
    if active_delivery(db, agent['id']):
        flash('Finish your current delivery before accepting another one.', 'error')
        return redirect(url_for('delivery_agent_dashboard'))
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
    return redirect(url_for('delivery_agent_dashboard'))


@app.route('/agent/active')
@login_required('delivery_agent')
def agent_active():
    db = get_db()
    active = active_delivery(db, session['user_id'])
    if not active:
        flash('You have no active delivery.', 'error')
        return redirect(url_for('delivery_agent_dashboard'))
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
        if not (order['payment_ref'] or '').startswith('razorpay:'):
            ok, _ = wallet_service.credit(session['user_id'], d['payout'], f"agent:{d['id']}", db=db)
            if ok:
                db.execute("INSERT INTO transactions (order_id, restaurant_id, amount, type, payment_method, user_id) "
                           "VALUES (?,?,?,'agent_payout','wallet',?)",
                           (d['order_id'], order['restaurant_id'], d['payout'], session['user_id']))
        notify(db, order['user_id'], f"Order #{d['order_id']} was delivered. Please confirm you received it.")
        db.commit()
        settle_razorpay_order(db, d['order_id'])
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
    refunded, error = refund_order(db, order, f'could not be delivered ({reason.lower()})')
    if not refunded:
        db.rollback()
        flash(error, 'error')
        return redirect(url_for('agent_active'))
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


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='OrderFood application and SQLite maintenance.')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('db-check', help='check SQLite integrity and foreign-key consistency')
    backup_parser = commands.add_parser('db-backup', help='create an atomic SQLite backup')
    backup_parser.add_argument('destination', help='new destination path; existing files are not overwritten')
    admin_parser = commands.add_parser('admin-create', help='create a platform administrator account')
    admin_parser.add_argument('email', help='email address for the new administrator')
    admin_parser.add_argument('--name', required=True, help='administrator display name')
    args = parser.parse_args()

    if args.command == 'db-check':
        health = database_health()
        print(json.dumps(health, indent=2))
        if health['integrity'] != ['ok'] or health['foreign_key_violations']:
            raise SystemExit(1)
    elif args.command == 'db-backup':
        print(backup_database(args.destination))
    elif args.command == 'admin-create':
        import getpass

        password = getpass.getpass('New administrator password (16+ characters): ')
        confirmation = getpass.getpass('Confirm password: ')
        if not hmac.compare_digest(password, confirmation):
            raise SystemExit('Passwords do not match.')
        init_database()
        user_id = create_platform_admin(args.email, args.name, password)
        print(f'Created platform administrator account {user_id}.')
    else:
        init_database()
        print('Google Maps: ' + ('enabled (key loaded)' if map_service.enabled else
              'NOT configured - add GOOGLE_MAPS_API_KEY to .env (see README). Using offline estimates.'))
        debug_enabled = (os.environ.get('FLASK_DEBUG') == '1' and
                         _deployment_environment not in {'production', 'prod'})
        app.run(debug=debug_enabled,
                host=os.environ.get('ORDERFOOD_HOST', '127.0.0.1'),
                port=int(os.environ.get('ORDERFOOD_PORT', 9000)))
