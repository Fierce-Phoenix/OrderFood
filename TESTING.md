# OrderFood test harness

The test harness runs the Flask application against an isolated temporary SQLite database. Razorpay calls are mocked in automated tests, so the suite does not contact the payment provider and cannot charge a real payment method.

## Install dependencies

```bash
python3 -m pip install -r requirements.txt
```

## Run the full suite

```bash
python3 run_tests.py
```

## Run payment-focused tests

```bash
python3 run_tests.py --payments-only
```

The payment suite covers Razorpay order creation, server-side amount calculation, missing credentials, invalid gateway responses, SDK failures, HMAC signature verification, malformed verification payloads, cart changes after checkout starts, idempotency, cancellation, refunds, and settlement logic.

## Optional browser checkout smoke test

For a manual end-to-end browser test, configure Razorpay Test Mode credentials in your local `.env`, restart Flask, and use the provider's official test payment flow. Keep the key secret on the server. Never put `RAZORPAY_KEY_SECRET` in browser code, screenshots, source control, or shared logs. Automated tests use their own test-only credentials and do not read production credentials from `.env`.

## Isolation and safety

The harness sets a temporary database path and test-only Flask/Razorpay configuration before importing the application. It should not alter your normal application database, wallet file, or real payment configuration.

The test environment is restored and its temporary directory is removed when the test module exits.
Do not invoke individual tests by importing the application first in the same process, since the
application reads its database and provider configuration during import. Use `run_tests.py` or
`python3 -m unittest test_app` so the isolated settings are applied before import.
