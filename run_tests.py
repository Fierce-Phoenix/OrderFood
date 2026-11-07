#!/usr/bin/env python3
"""Convenient test runner for OrderFood, including mocked Razorpay flows.

Usage:
    python run_tests.py                 # full application + payment suite
    python run_tests.py --payments-only # Razorpay-focused tests
"""
import argparse
import unittest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payments-only', action='store_true',
                        help='run only Razorpay/payment and refund/settlement tests')
    args = parser.parse_args()

    import test_app  # configures isolated test DB and test-only Razorpay credentials

    loader = unittest.TestLoader()
    if args.payments_only:
        names = [name for name in loader.getTestCaseNames(test_app.OrderFoodTests)
                 if ('razorpay' in name or 'refund' in name or 'route_settles' in name)]
        suite = unittest.TestSuite(test_app.OrderFoodTests(name) for name in names)
    else:
        suite = loader.loadTestsFromModule(test_app)

    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
