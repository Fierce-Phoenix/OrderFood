# OrderFood

Food ordering platform (Flask + SQLite) with three interfaces: customer, restaurant, delivery agent.

## About

CS100 group project by **Vihaan Sujesh** and **Prathamesh Kashelkar**.

Food delivery platforms like Swiggy and Zomato charge restaurants commissions of roughly 25-30% per
order, and delivery agents are often paid minimum wage with no say in how they're compensated.
OrderFood is a transparent alternative: an open portal where customers order food, restaurants manage
their own menus and orders, and delivery agents pick their own payment method (per order, per km, or
per minute) and choose which deliveries to take.

Three stakeholders, three dashboards, one platform:
- **Customers** browse restaurants within a 30-minute delivery radius, order from multiple restaurants
  in one cart (each billed separately), pay from an in-app wallet, and track delivery status.
- **Restaurants** manage their menu and availability, accept or reject orders, and request a delivery
  agent or self-deliver.
- **Delivery agents** see open delivery requests, accept the ones they want, and get paid by their
  chosen method.

## Run
    pip install -r requirements.txt
    python orderfood_app.py          # http://127.0.0.1:9000
    python -m unittest -v test_app   # 15 end-to-end tests

Optional env vars: `ORDERFOOD_SECRET_KEY`, `ORDERFOOD_HOST` (default 127.0.0.1), `FLASK_DEBUG=1`.
Start fresh any time by deleting `orderfood.db` and `wallet.json`. An old `orderfood.db` is upgraded automatically.

## Demo accounts
| Role | Email | Password |
|---|---|---|
| Customer | customer@test.com | password123 |
| Restaurant (The Burger Joint) | admin@test.com | admin123 |
| Delivery agent | agent@test.com | agent123 |

## Walkthrough
1. Customer: add items from 2 restaurants, checkout. Each restaurant is a separate payment.
2. Restaurant (admin): Accept order, Request delivery agent (or Self-deliver once ready), Mark ready.
3. Agent: choose pay method, View request, Accept, At restaurant, Confirm pickup (needs "ready"), Mark delivered.
4. Customer: "I received my order". Only then can they place the next order.

Note: only The Burger Joint (id 5) has an owner account, so orders for other restaurants stay "pending" unless you
register a restaurant owner. Use The Burger Joint when demoing the full flow.

## What changed from the previous version
Bug fixes
- Crash on start: duplicated `conn.commit()/conn.close()` in `init_database()` removed.
- Syntax error in layout.html (`speechUtter utterance`) that broke the whole accessibility script.
- `login.html`/`register.html`/dashboards no longer duplicate layout; everything extends `layout.html`.
- Order history was keyed on the user's *name*; now keyed on `user_id`.
- Cart prices came from the browser; now always read from the database (qty supported).
- Wallet could be charged and the order then fail; payment now happens inside the DB transaction with refund on failure.
- Agent dashboard showed the restaurant as "Pickup: <agent name>"; fixed with real joins.

Security
- Passwords hashed (old plain-text rows are upgraded on first login).
- CSRF token on every POST; all state-changing GET routes are now POST.
- Role can no longer be forged for restaurant owners (name/address required, restaurant created and linked).
- Ownership checks: customers can only confirm/cancel their own orders; restaurants only touch their own orders/menu.
- Secret key from env or generated file instead of hard-coded; debug off and localhost-only by default.
- Wallet calls carry a reference, so a retried request can never charge or refund twice.

Features from the deliverables
- Multi-restaurant cart with quantities, +/-, remove, sold-out detection and same-restaurant replacement.
- Separate transaction per restaurant, payment table, partial failure screen with retry; failed items stay in cart.
- 30-minute rule enforced server side (not just by hiding buttons). "Too far" restaurants are view only.
- Delivery confirmation gate before a new order; cancel (refund) while pending; report a problem.
- Order tracking with 6 steps, one tab per order.
- Restaurant dashboard: accept/reject (refund), mark ready, request agent or self-deliver, menu add/edit/price/availability,
  open/closed, location edit, revenue.
- Agent: per order / per km / per minute payment, accept/reject, first agent wins, all-reject falls back to restaurant,
  pickup blocked until ready, "can't complete delivery" with reasons (not marked delivered, customer refunded), earnings.
- Notifications, accessibility notes shared between customer and agent, high contrast, text size, text-to-speech,
  working magnifier, voice input.

## Not implemented (mocked)
Real maps API (delivery time/distance are mocked in `ExternalMapService`), real payment gateway (JSON-file wallet),
"most affordable agent first" ordering (all free agents see every request, as in Deliverable 5), phone calls to customer.
Agent payouts are platform-funded in this mock; restaurants are credited when the order is delivered.
