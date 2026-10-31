# OrderFood

A premium food delivery platform built with Flask and SQLite, designed to provide a transparent and fair ecosystem for customers, restaurant owners, and delivery agents. Developed as part of the CS100 course by **Vihaan Sujesh** and **Prathamesh Kashelkar**.

## Overview

OrderFood is an open portal that removes the heavy commissions typically charged by delivery platforms. It empowers stakeholders with dedicated dashboards:

<<<<<<< HEAD
- **Customers**: Browse restaurants within a 30-minute delivery radius, order from multiple restaurants in a single cart, pay via an in-app wallet or Razorpay Standard Checkout, and track delivery status in real-time.
- **Restaurants**: Manage menus and availability, accept or reject orders, configure a Razorpay payout account, and choose between requesting a delivery agent or self-delivering.
- **Delivery Agents**: Receive exclusive delivery offers ranked by pickup distance or payout cost, configure a Razorpay payout account, and choose their compensation method.

## Features

- **Multi-Restaurant Cart**: Search restaurants and dishes, add items from various restaurants with quantity controls and sold-out detection.
- **Platform Payments**: Customer Razorpay payments are collected by the platform before restaurant orders are created. After delivery, Razorpay Route transfers the restaurant share and delivery-agent compensation to their linked accounts. Wallet checkout remains an internal application ledger.
- **Menu Categories**: Categorized food menus with restaurant-side category selection and editing.
- **Proximity Enforcement**: A server-side 30-minute delivery rule ensures customers only order from reachable restaurants.
- **Order Lifecycle**: Full tracking from "Pending" to "Delivered," including a confirmation gate before customers can place new orders.
- **Verified Feedback**: Customers can review a restaurant only after confirming a completed order. Restaurants receive an in-app notification and ratings are calculated from submitted reviews.
=======
- **Customers**: Browse restaurants within a 30-minute delivery radius, order from multiple restaurants in a single cart, pay via an in-app wallet, and track delivery status in real-time.
- **Restaurants**: Manage menus and availability, accept or reject orders, and choose between requesting a delivery agent or self-delivering.
- **Delivery Agents**: Browse open delivery requests, select preferred orders, and choose their own compensation method (per order, per km, or per minute).

## Features

- **Multi-Restaurant Cart**: Add items from various restaurants with quantity controls and sold-out detection.
- **Transparent Payments**: Separate transactions per restaurant with a simulated wallet system and partial failure recovery.
- **Proximity Enforcement**: A server-side 30-minute delivery rule ensures customers only order from reachable restaurants.
- **Order Lifecycle**: Full tracking from "Pending" to "Delivered," including a confirmation gate before customers can place new orders.
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
- **Comprehensive Dashboards**: 
    - **Restaurant**: Kanban-style order queue (New $\rightarrow$ Preparing $\rightarrow$ Ready $\rightarrow$ History), menu management, and revenue tracking.
    - **Agent**: Flexible payout options, request management, and earnings tracking.
- **Accessibility**: Built-in tools for high contrast, adjustable text size, text-to-speech, magnifier, and voice input.

## Getting Started

### Installation
```bash
pip install -r requirements.txt
```

### Running the Application
```bash
python orderfood_app.py
```
<<<<<<< HEAD
The app will be available at `http://127.0.0.1:9000`. A fresh local database is created
automatically on first run; the SQLite database and generated development signing key are local
state and should not be committed or shared.

### Production security settings

Set `ORDERFOOD_ENV=production` and provide `ORDERFOOD_SECRET_KEY` from your deployment secret
manager (at least 32 characters). The app refuses to start in production without that key, uses
secure session cookies, and ignores `FLASK_DEBUG=1`. Keep `.env`, `.secret_key`, and the SQLite
database private. Rotate any credential that has been committed, uploaded, or shared.

### Razorpay Standard Checkout

The local, git-ignored `.env` file can hold the server credentials:

```dotenv
RAZORPAY_KEY_ID=your_test_key_id
RAZORPAY_KEY_SECRET=your_test_key_secret
```

The app loads these values at startup. Restart it after editing `.env`. The key ID is sent to the browser for Standard Checkout; the key secret stays on the server. Checkout creates a Razorpay order for the server-calculated cart total and only places restaurant orders after the payment signature is verified. For a multi-restaurant cart, one gateway payment is split into separate restaurant orders. The existing wallet payment option remains available.

Use Razorpay test-mode credentials and test payment instruments from the Razorpay documentation. No real charge is made with test credentials. If credentials are absent, wallet checkout continues to work and Razorpay is unavailable.

### Marketplace payouts

Customer payments are collected on the platform account. To send funds to restaurants and delivery agents after delivery:

1. Enable Razorpay Route for the platform account and create/KYC-verify linked accounts in the Razorpay Dashboard.
2. Set `RAZORPAY_ROUTE_ENABLED=true` in the server environment and configure `RAZORPAY_ROUTE_PLATFORM_FEE_BPS` for the platform share/processing fee in basis points (the default is `0`).
3. Restaurant owners and delivery agents enter only their approved `acc_...` linked-account ID in their dashboards. Bank details must be entered and verified with Razorpay, not stored by this app.

The agent's configured compensation is transferred first from the order amount; the restaurant receives the remaining amount after that compensation and the configured platform fee. If Route or a linked account is not ready, the app records a visible pending setup settlement and does not report it as paid. Transfers that have an uncertain provider response are flagged for Dashboard reconciliation and are not automatically retried, to avoid duplicate payouts.

Set `DELIVERY_ASSIGNMENT_STRATEGY=nearest` (default) or `cheapest` to rank the first exclusive two-minute agent offer. A decline or timeout advances to the next eligible agent; if no agents remain, the restaurant is notified to self-deliver.

### Running Tests
```bash
python3 run_tests.py                 # full application + Razorpay test suite
python3 run_tests.py --payments-only # Razorpay, refunds and Route settlement tests
```

See [TESTING.md](TESTING.md) for coverage details and the optional manual Razorpay Test Mode smoke test. Automated payment tests mock the Razorpay SDK and never make real charges.

## Google Maps Integration

OrderFood works like Zomato/Swiggy: customers pin where they are, the 30-minute promise is computed from
real coordinates, and everyone can watch the delivery agent move on a live map.

### Quick start (plug and play)

1. `pip install -r requirements.txt` (no extra packages are needed for maps).
2. Copy `.env.example` to `.env` and paste your key: `GOOGLE_MAPS_API_KEY=your-key`. (`.env` is git-ignored, so the key is never committed.)
3. In Google Cloud Console enable these APIs for the key: **Maps JavaScript API**, **Places API (New)**, **Geocoding API**, **Routes API**.
4. `python orderfood_app.py` - the console prints `Google Maps: enabled`.

No key? The app still runs: travel times use a straight-line estimate, and the location screen offers a list of Mumbai, Thane, and Mulund areas instead of the map.

### How it works

- **Location first.** After every login a customer must confirm a delivery location (address search, "use my current location", or tap/drag the pin) before seeing restaurants. It is saved on the account and pre-filled next time.
- **Seeded data.** The first start after this update relocates all existing restaurants around Thane and Mulund, with some near Vikhroli and Marol Naka. Future missing locations use the same areas; delivery drivers are placed around Mumbai. Restaurant owners can adjust their pin on **Dashboard > Restaurant info**.
- **Wallet storage.** Balances and idempotent wallet operations are stored in the `wallets` and `wallet_operations` SQLite tables and tied to user IDs. Existing balances are migrated from `wallet.json` on startup, after which that legacy file is removed.
- **30-minute rule.** Routes API `computeRouteMatrix` (one batched call per page) gives drive time from each restaurant to the customer's pin; the promise is drive time + 10 min pickup buffer and must be <= 30 min. Results are cached for 10 minutes. If Google is unreachable the app falls back to a straight-line estimate and shows a warning instead of failing.
- **Live tracking.** The agent's browser posts its position every few seconds (`POST /api/agent/location`) from real GPS, or from a **demo simulator** that drives along the real route (choose *Simulate driving* on the agent's active-delivery page; 1x/5x/20x speed). The customer (**My orders > Track live on map**), the restaurant (**Track** on an order card) and the agent all open the same map showing restaurant, delivery address, agent and route, with live ETA. Agents also see their own distance to each pickup, nearest first, and a route preview before accepting.
- **Privacy.** A tracking page or API only answers for the order's own customer, the order's restaurant, and the agent assigned to it (404 for anyone else), and agents only appear on the map while they have an active delivery.

### Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `GOOGLE_MAPS_API_KEY` | Key used in the browser (maps, search) and, by default, on the server (Routes API). |
| `GOOGLE_MAPS_SERVER_KEY` | Optional separate key for server calls. Needed if you restrict the browser key by HTTP referrer. |
| `GOOGLE_MAPS_MAP_ID` | Optional Cloud-styled Map ID (default `DEMO_MAP_ID`). |
| `GOOGLE_MAPS_REGION` | Search bias, default `in`. |
| `GOOGLE_TRAVEL_MODE` | `DRIVE` (default), `TWO_WHEELER` or `BICYCLE`. |
| `ORDERFOOD_ENV` | `development` (default) or `production`; production requires `ORDERFOOD_SECRET_KEY` and enables secure session cookies. |
| `ORDERFOOD_SECRET_KEY` | Session-signing secret; required in production and should be at least 32 characters. |

### Securing your key

A browser key is visible to anyone who opens the page, so restrict it in Cloud Console: **HTTP referrers** (e.g. `http://localhost:9000/*` plus your deployed domain) and limit it to the four APIs above. Because referrer-restricted keys cannot call the Routes API from the server, put a second key (restricted by API and, if you can, by server IP) in `GOOGLE_MAPS_SERVER_KEY`. Set a budget alert too; the Routes and Maps APIs are billed per request.

## User Walkthrough

1. **Customer**: Register or log in, add items from multiple restaurants, proceed to checkout, and pay using the wallet or Razorpay.
=======
The app will be available at `http://127.0.0.1:9000`.

### Running Tests
```bash
python -m unittest -v test_app
```

## Demo Accounts

| Role | Email | Password |
|---|---|---|
| Customer | customer@test.com | password123 |
| Restaurant (The Burger Joint) | admin@test.com | admin123 |
| Delivery agent | agent@test.com | agent123 |

## User Walkthrough

1. **Customer**: Add items from multiple restaurants, proceed to checkout, and pay using the simulated wallet.
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
2. **Restaurant**: Accept the order, prepare the food, and either mark it as "Ready" for an agent or choose "Self-deliver."
3. **Agent**: Select a payment method, accept the delivery request, confirm pickup once the restaurant marks the order as ready, and finally mark the order as delivered.
4. **Customer**: Confirm receipt of the order to clear the delivery gate and enable future ordering.

<<<<<<< HEAD
*Note: The app includes seed data for local development. Create production accounts through the registration flow and do not reuse development credentials.*


## Interface design

The shared interface uses a restrained, responsive visual system: a consistent system-font stack, compact navigation, neutral surfaces, clear hierarchy, and accessible focus states. The visual direction takes cues from Apple's emphasis on clarity and simplicity while retaining OrderFood's own identity.

## Automated tests

See [TESTING.md](TESTING.md) for the full application and Razorpay test-harness commands.


## Design

See [DESIGN_NOTES.md](DESIGN_NOTES.md) for the visual direction and design decisions.
=======
*Note: For a full end-to-end demo, use "The Burger Joint" as it has a pre-configured owner account.*
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
