# OrderFood

OrderFood is a food delivery web application developed using Flask and SQLite as part of the CS100 course by Vihaan Sujesh and Prathamesh Kashelkar.

The application connects customers, restaurants and delivery agents through a single platform. It supports multi-restaurant ordering, order management, delivery tracking and payment processing.

## Features

### Customer
- Browse restaurants and their menus.
- Browse in read-only mode when a delivery location or Maps is unavailable.
- Add items from multiple restaurants to a single cart.
- Place orders using the application wallet or Razorpay Checkout.
- Set a precise delivery location to enable ordering.
- Track active deliveries on a live map.
- Tip a delivery agent from the application wallet after delivery.
- Review restaurants after completing an order.

### Restaurant
- Manage menus, categories and item availability.
- Accept or reject incoming orders.
- Track orders through preparation and delivery.
- Monitor revenue and order history.
- Request a delivery agent or choose self-delivery.

### Delivery Agent
- View and accept available delivery requests.
- View pickup locations and route information.
- Choose a compensation method.
- Update delivery status.
- Track completed deliveries and earnings.

### Platform
- Multi-restaurant cart and checkout.
- No fixed delivery-area or distance eligibility limit.
- Customer, restaurant and delivery-agent dashboards.
- Order status notifications and delivery tracking.
- Accessibility tools, including text resizing, high contrast, text-to-speech and voice input.

## Technology

| Component | Technology |
|---|---|
| Backend | Python, Flask |
| Database | SQLite |
| Frontend | HTML, CSS, JavaScript |
| Maps and routing | Google Maps Platform |
| Payments | Razorpay Standard Checkout |
| Testing | Python unittest |

## Getting Started

### Requirements

- Python 3
- pip
- A Google Maps API key (optional)
- Razorpay Test Mode credentials (optional)

### Installation

Clone the repository:

```bash
git clone https://github.com/Fierce-Phoenix/CS100-Group-Project.git
cd CS100-Group-Project
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

### Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

Add the required configuration to `.env`.

Do not upload `.env` or share API secrets. The example file can be committed, but actual credentials must remain private.

The example leaves optional provider keys blank so a fresh local setup uses offline maps and does
not attempt payment-provider requests. Common settings include:

| Variable | Purpose | Default |
|---|---|---|
| `ORDERFOOD_ENV` | Environment mode (`development` or `production`) | `development` |
| `ORDERFOOD_SECRET_KEY` | Flask session-signing key; required in production and at least 32 characters | Generated local key in development |
| `ORDERFOOD_DB` | SQLite database path | `orderfood.db` in the project directory |
| `ORDERFOOD_DB_BUSY_TIMEOUT_MS` | Maximum wait for a SQLite lock (1-60000 ms) | `5000` |
| `ORDERFOOD_HOST`, `ORDERFOOD_PORT` | Bind address and port for the development server | `127.0.0.1`, `9000` |
| `GOOGLE_MAPS_API_KEY` | Browser Maps/Places and fallback server key | Empty; offline location estimates |
| `GOOGLE_MAPS_SERVER_KEY` | Optional server-only key for geocoding/routes | Empty; uses `GOOGLE_MAPS_API_KEY` |
| `GOOGLE_MAPS_REGION` | Optional Places search region hint | Empty; unrestricted place search |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | Razorpay checkout credentials | Empty; online checkout unavailable |
| `RAZORPAY_ROUTE_ENABLED` | Enable configured marketplace transfers | `false` |
| `ORDERFOOD_SEED_DEMO_USERS` | Seed demo accounts outside production only | Disabled |

### Google Maps

To enable maps and route calculations, configure `GOOGLE_MAPS_API_KEY` in `.env`.

Enable the following APIs in Google Cloud Console:

- Maps JavaScript API
- Places API (New)
- Geocoding API
- Routes API

The application can still run without a Google Maps key. Customers can browse menus read-only, and
ordering stays disabled until they confirm a precise location. Route estimates fall back to
straight-line calculations when the server Maps service is unavailable.

### Razorpay

Razorpay integration supports customer checkout through Standard Checkout.

Add your Razorpay Test Mode credentials to `.env`:

```env
RAZORPAY_KEY_ID=your_test_key_id
RAZORPAY_KEY_SECRET=your_test_key_secret
```

The application verifies payment signatures on the server, confirms each payment belongs to the
expected order and amount, and ensures it is captured before creating restaurant orders. If a
payment is only authorized, the server captures it before fulfillment.

Use Test Mode credentials for development. Never commit payment credentials or expose the key secret in frontend code.

### Running the Application

Start the Flask application:

```bash
python3 orderfood_app.py
```

Open the application at:

`http://127.0.0.1:9000`

The application creates its local SQLite database when required. During registration, users choose
Customer, Restaurant partner, or Delivery agent. Customer accounts are created immediately.
Restaurant and delivery-agent choices submit an onboarding application; they do not grant staff
access. Applications are stored in the `account_applications` table; staff passwords are hashed
while pending, and an administrator must approve an application before the applicant can log in.
The platform-admin console supports application review, approval/rejection, and an audit log.
The app does not seed demo
users by default. For local-only demo/test fixtures, set
`ORDERFOOD_SEED_DEMO_USERS=1`; production mode ignores this option.

Create the first platform administrator using a trusted terminal. This creates a new account only;
it will not elevate an existing user's role:

```bash
python3 orderfood_app.py admin-create admin@example.com --name "Platform Administrator"
```

The command prompts for a confirmed password of at least 16 characters. Keep platform-admin
credentials restricted and do not expose this command through a public web endpoint.

`python3 orderfood_app.py` starts Flask's development server and is intended only for local use.
For deployment, run the `orderfood_app:app` WSGI application with a production WSGI server behind
HTTPS. Set `ORDERFOOD_ENV=production`, provide a stable secret of at least 32 characters through
your deployment secret manager, use a persistent writable database path, and keep debug mode off.
Restrict browser Maps keys to the deployed site and keep server/payment secrets server-side. Back
up the SQLite database before upgrades; startup applies schema migrations.

### Data storage and operations

SQLite is the sole database for mutable application data, including accounts, menus, orders,
wallets, payment references, delivery records, reviews, and onboarding applications. The checked-in
`data/catalog.json` and `data/platform.json` are versioned seed/policy configuration, not live
records. The legacy wallet JSON is imported once and removed after a successful import.

Each connection enables foreign-key enforcement, a configurable busy timeout, `synchronous=NORMAL`,
and SQLite's trusted-schema restriction. The database uses WAL mode; place the database and its
`-wal`/`-shm` sidecars together on a persistent local filesystem. Do not put an active database on
NFS or another network filesystem, share it between hosts, or copy only the main database file
while the application is running. Run one application host with local storage. Restrict database
and backup access because they contain personal, order, and financial records.

The maintenance commands inspect or back up the configured database without initializing or
migrating it:

```bash
python3 orderfood_app.py db-check
python3 orderfood_app.py db-backup /secure/backups/orderfood-YYYYMMDD-HHMMSS.sqlite3
```

`db-check` reports SQLite integrity and foreign-key violations and exits nonzero if either check
fails. `db-backup` uses SQLite's online backup API, validates the copy, creates it atomically, and
refuses to overwrite an existing destination. Schedule backups to encrypted, access-restricted,
off-host storage, and regularly test restoring one. Before an application upgrade, take and verify
a backup with the currently deployed version. For restore, stop every application worker, restore
the backup to the configured database path with owner-only permissions, then restart the app.
Startup migrations run transactionally and reject databases created by a newer application.

### Restaurant onboarding at scale

The public restaurant-partner application captures the requested restaurant, owner identity, and
a password hash. A platform administrator reviews it at **Restaurant onboarding** and explicitly
approves or rejects it. Approval creates the restaurant and owner account transactionally. For
bulk listings, upload a UTF-8 CSV in the same admin console with exactly these headers:

```text
restaurant_name,restaurant_slug,address,description,owner_name,owner_email,menu_json
```

For example, the last column can contain
`"[{""name"":""Paneer Tikka"",""price"":180,""category"":""Appetizers""}]"` as a CSV-escaped JSON
array.
Imports are limited to 2 MiB and 500 rows, validate all rows before writing, reject malformed or
conflicting data as a batch, and are idempotent on a repeated slug/owner-email pair. The pending
review queue is capped at 500 rows to keep the review page manageable. Imported
restaurants enter a review queue; administrators can review rows individually or approve/reject
a selected batch. `menu_json` must contain 1-200 items with `name`, positive numeric `price`, and
an existing `category`; `description` and boolean `available` are optional. Menu JSON is validated
and staged with each restaurant, then copied into the live menu table in the same transaction that
creates the inactive listing. Approval creates listings **inactive**. The named owner must then
submit a normal restaurant-partner application with that email, and an administrator approves
the account before the restaurant becomes visible. This separates bulk data intake from verified
ownership and customer-facing activation. Every import and review action is recorded in
`admin_audit_log`, including administrator bootstrap events; imported restaurants do not receive
credentials from a CSV. The application
does not verify email addresses or business documents automatically, so an administrator must
complete those checks independently before approving either stage.

## Catalog and location data

The SQLite database is the source of truth for live restaurants, menus, and menu categories.
On a new database, `data/catalog.json` supplies the initial restaurants, menu items, categories,
and restaurant-card presentation metadata. Restaurant styles are associated with stable slugs,
not display names. Seed restaurant and menu records are inserted only when the restaurant table
is empty; editing the JSON does not overwrite existing restaurant or menu data.

Menu category choices are stored in the `menu_categories` table and validated by the application
and database. The category definitions in `data/catalog.json` add or update those choices during
database initialization.

Restaurant and delivery-agent onboarding has no geographic eligibility restriction. The location
picker uses a precise map pin rather than predefined delivery areas. `data/platform.json` holds
fixed operational settings that are not edited through the app, such as the local demo customer's
wallet balance, delivery-agent payout rates, and delivery failure reasons. Publicly registered
customers always start with a zero wallet balance; grants need
to be issued through an authorized, auditable funding process. On production startup, unchanged
built-in demo passwords are revoked. Legacy wallet balances are preserved: old balances without
reliable funding provenance cannot safely be classified as signup credit, so review their ledger
and reconcile them through an auditable process rather than subtracting funds automatically.

## Payment and Settlements

Customer payments can be made through the internal application wallet or Razorpay.
After an assigned agent delivers an order, a customer may send a one-time tip of ₹1–₹5,000 to the
delivery agent from their application wallet.

The Razorpay integration supports payment verification and the platform's marketplace settlement workflow.

Razorpay Route can be configured for transfers to restaurants and delivery agents after delivery. This requires the appropriate Razorpay account setup and linked accounts.

Settlement configuration is optional. Transfers that cannot be completed are recorded as pending rather than being reported as successful.

## Testing

The project includes an automated test harness.

Install dependencies and run the full test suite:

```bash
python3 run_tests.py
```

To run payment-focused tests:

```bash
python3 run_tests.py --payments-only
```

The automated tests use an isolated temporary SQLite database. Razorpay calls are mocked, so automated tests do not make real payments.

See [TESTING.md](TESTING.md) for further details.

Before sharing or committing changes, check `git status`, confirm `.env`, `.secret_key`, and local
database files are not tracked, run the full test suite, and run `git diff --check`. Tests use
temporary storage and test-only credentials; they do not require real Maps or Razorpay credentials.

## Project Structure

```text
CS100-Group-Project/
│
├── static/
│   ├── css/
│   └── JavaScript files
│
├── data/
│   ├── catalog.json
│   └── platform.json
├── templates/
│   └── HTML templates
│
├── orderfood_app.py
├── maps_service.py
├── requirements.txt
├── run_tests.py
├── test_app.py
├── .env.example
├── .gitignore
├── TESTING.md
└── README.md
```