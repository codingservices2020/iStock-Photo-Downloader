import logging
import requests
import os
import time
from dotenv import load_dotenv
load_dotenv()

# Logger setup
logging.basicConfig(level=logging.INFO)

PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_SECRET = os.getenv("PAYPAL_SECRET")
PAYPAL_API_BASE = os.getenv("PAYPAL_API_BASE")
ADMIN_URL = os.getenv('ADMIN_URL')

# Generate Access Token
def get_paypal_access_token():
    url = f"{PAYPAL_API_BASE}/v1/oauth2/token"
    headers = {"Accept": "application/json", "Accept-Language": "en_US"}
    data = {"grant_type": "client_credentials"}
    response = requests.post(url, headers=headers, data=data, auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET))
    response.raise_for_status()
    return response.json()["access_token"]


# Create PayPal Order
def create_paypal_payment(amount):
    access_token = get_paypal_access_token()
    url = f"{PAYPAL_API_BASE}/v2/checkout/orders"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    data = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "amount": {
                    "currency_code": "USD",
                    "value": amount
                           }
            }
        ],
        "application_context": {
            "return_url": "https://codingservices2020.github.io/Checkout-Page/",
            "cancel_url": ADMIN_URL
        }
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        order = response.json()
        approve_url = next(link["href"] for link in order["links"] if link["rel"] == "approve")
        return order["id"], approve_url
    except requests.exceptions.HTTPError as e:
        print(f"Failed to capture payment: {e.response.json()}")


# Capture Payment
def capture_payment(order_id):
    access_token = get_paypal_access_token()
    url = f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}/capture"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    try:
        response = requests.post(url, headers=headers)
        response.raise_for_status()
        payment_result = response.json()
        email = payment_result['payer']['email_address']
        name = payment_result['purchase_units'][0]['shipping']['name']['full_name']
        status = payment_result['purchase_units'][0]['payments']['captures'][0]['status']  # shows "COMPLETED" if paid successfully
        paid_amount = payment_result['purchase_units'][0]['payments']['captures'][0]['amount']['value']
        currency = payment_result['purchase_units'][0]['payments']['captures'][0]['amount']['currency_code']
        #  Breakdown of amount received by the seller
        seller_receivable_breakdown = payment_result['purchase_units'][0]['payments']['captures'][0]['seller_receivable_breakdown']
        paypal_fee = seller_receivable_breakdown['paypal_fee']['value']
        net_amount = seller_receivable_breakdown['net_amount']['value']

        data = {
            "status": status,
            "name": name,
            "email": email,
            "currency": currency,
            "paid_amount": paid_amount,
            "paypal_fee": paypal_fee,
            "net_amount": net_amount  # net_amount received by the seller
        }
        return data
    except requests.exceptions.HTTPError as e:
        print(f"Failed to capture payment: {e.response.json()}")




# # Workflow
# order_id, approve_url = create_paypal_payment(amount=2)
# print(f"Redirect the payer to approve the payment: {approve_url}")
# time.sleep(60)  # Simulate a delay for the payer to approve the payment
# payment_details = capture_payment(order_id)
# print(payment_details)


