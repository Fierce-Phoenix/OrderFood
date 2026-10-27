# OrderFood

A premium, art-directed food delivery platform (Flask + SQLite, server-rendered) with three
interfaces: customer, restaurant owner, delivery agent.

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

## Design

A warm-ivory / deep-forest / terracotta-accent identity: `Fraunces` for display type, `Inter` for UI
text, a small set of hand-drawn line icons (`templates/_icons.html`) standing in for cuisine tags and
status glyphs instead of emoji, and curated food photography per restaurant with a graceful
gradient+icon fallback (`static/interactions.js: ofImgFallback`) if a photo can't load. The customer
login page carries a single Three.js hero (a slowly orbiting plate, `static/hero3d.js`) that skips
itself under `prefers-reduced-motion`, on small screens, or without WebGL -- every other screen,
especially the two dashboards, stays decoration-free and fast. Design tokens, shared components and
page-specific layout live in `static/css/{tokens,base,components,pages}.css`.

## Run
    pip install -r requirements.txt
    python orderfood_app.py          # http://127.0.0.1:9000
    python -m unittest -v test_app   # 15 end-to-end tests

Optional env vars: `ORDERFOOD_SECRET_KEY`, `ORDERFOOD_HOST` (default 127.0.0.1), `ORDERFOOD_PORT`
(default 9000), `FLASK_DEBUG=1`.
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

## What changed in this redesign
Visual and interaction design
- Full design system (colour/type/spacing/motion tokens, buttons, forms, cards, pills, toasts,
  timeline, dashboards) replacing the old single generic stylesheet.
- Restaurant discovery got real client-side filtering (cuisine chips, "open now", sort by time/rating)
  and curated photography; the menu page got a sticky category nav with scrollspy and a floating cart
  summary; checkout got a wallet meter and an explicit "simulated wallet" label; order tracking got an
  animated timeline.
- The restaurant dashboard's order list became a Kanban-style queue (New / Preparing / Ready-out /
  History) over the same data, so the owner sees what needs attention at a glance. The agent dashboard
  keeps its flat, fast, low-chrome layout on purpose.
- Flash messages became auto-dismissing toasts with icons; buttons get a small press animation; cards
  fade in on scroll. All of it respects `prefers-reduced-motion`, and every control still works as a
  plain form/link with JavaScript off.
- Accessibility toolbar (contrast, text size, text-to-speech, magnifier, voice input) kept byte-for-byte
  functionally, just restyled.

Bug fixes (this redesign)
- `ExternalMapService` used to geocode addresses for real via Nominatim and run Haversine on the
  result. Free-text delivery addresses like "Hostel Block B" geocode to arbitrary, sometimes very
  distant, real-world places, so a restaurant well within range could suddenly read as thousands of
  minutes away the moment a customer typed an address -- breaking the core 30-minute rule and making
  checkout depend on a live third-party network call with no offline fallback. The service is now
  fully mocked and deterministic (matching what the UI has always told the customer); the `requests`
  dependency was removed.
- `.secret_key` (the Flask session/CSRF signing key) was committed to the repo. It's now untracked and
  gitignored; `orderfood_app.py` already generates one automatically if the file is missing. If you're
  deploying this beyond local demo use, rotate the key (delete `.secret_key` and restart).

Bug fixes (previous version)
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
Real maps API (delivery time/distance are a deterministic mock in `ExternalMapService` -- no network
calls are made), real payment gateway (JSON-file wallet, clearly labelled "simulated" at checkout),
"most affordable agent first" ordering (all free agents see every request, as in Deliverable 5), phone
calls to customer. Agent payouts are platform-funded in this mock; restaurants are credited when the
order is delivered.
