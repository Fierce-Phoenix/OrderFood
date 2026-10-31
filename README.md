# OrderFood

OrderFood is a food delivery web application developed using Flask and SQLite as part of the CS100 course by Vihaan Sujesh and Prathamesh Kashelkar.

The application connects customers, restaurants and delivery agents through a single platform. It supports multi-restaurant ordering, order management, delivery tracking and payment processing.

## Features

### Customer
- Browse restaurants and their menus.
- Add items from multiple restaurants to a single cart.
- Place orders using the application wallet or Razorpay Checkout.
- Select and save a delivery location.
- Track active deliveries on a live map.
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
- Server-side enforcement of a 30-minute delivery limit.
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

### Google Maps

To enable maps and route calculations, configure `GOOGLE_MAPS_API_KEY` in `.env`.

Enable the following APIs in Google Cloud Console:

- Maps JavaScript API
- Places API (New)
- Geocoding API
- Routes API

The application can still run without a Google Maps key. In that case, it uses fallback travel-time estimates and location options.

### Razorpay

Razorpay integration supports customer checkout through Standard Checkout.

Add your Razorpay Test Mode credentials to `.env`:

```env
RAZORPAY_KEY_ID=your_test_key_id
RAZORPAY_KEY_SECRET=your_test_key_secret
```

The application verifies payment signatures on the server before creating restaurant orders.

Use Test Mode credentials for development. Never commit payment credentials or expose the key secret in frontend code.

### Running the Application

Start the Flask application:

```bash
python3 orderfood_app.py
```

Open the application at:

`http://127.0.0.1:9000`

The application creates its local SQLite database when required.

## Payment and Settlements

Customer payments can be made through the internal application wallet or Razorpay.

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

## Project Structure

```text
CS100-Group-Project/
│
├── static/
│   ├── css/
│   └── JavaScript files
│
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