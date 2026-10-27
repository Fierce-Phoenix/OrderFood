# OrderFood

A premium food delivery platform built with Flask and SQLite, designed to provide a transparent and fair ecosystem for customers, restaurant owners, and delivery agents. Developed as part of the CS100 course by **Vihaan Sujesh** and **Prathamesh Kashelkar**.

## Overview

OrderFood is an open portal that removes the heavy commissions typically charged by delivery platforms. It empowers stakeholders with dedicated dashboards:

- **Customers**: Browse restaurants within a 30-minute delivery radius, order from multiple restaurants in a single cart, pay via an in-app wallet, and track delivery status in real-time.
- **Restaurants**: Manage menus and availability, accept or reject orders, and choose between requesting a delivery agent or self-delivering.
- **Delivery Agents**: Browse open delivery requests, select preferred orders, and choose their own compensation method (per order, per km, or per minute).

## Features

- **Multi-Restaurant Cart**: Add items from various restaurants with quantity controls and sold-out detection.
- **Transparent Payments**: Separate transactions per restaurant with a simulated wallet system and partial failure recovery.
- **Proximity Enforcement**: A server-side 30-minute delivery rule ensures customers only order from reachable restaurants.
- **Order Lifecycle**: Full tracking from "Pending" to "Delivered," including a confirmation gate before customers can place new orders.
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
2. **Restaurant**: Accept the order, prepare the food, and either mark it as "Ready" for an agent or choose "Self-deliver."
3. **Agent**: Select a payment method, accept the delivery request, confirm pickup once the restaurant marks the order as ready, and finally mark the order as delivered.
4. **Customer**: Confirm receipt of the order to clear the delivery gate and enable future ordering.

*Note: For a full end-to-end demo, use "The Burger Joint" as it has a pre-configured owner account.*
