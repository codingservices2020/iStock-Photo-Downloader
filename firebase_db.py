from datetime import datetime, timedelta
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DB_FILE_NAME = "testing_database"  # Define the firebase database file
# DB_FILE_NAME = "iStock_Downloader_subscriptions"  # Define the firebase database file

# Build the Firebase credentials dictionary dynamically
firebase_config = {
    "type": os.getenv("FIREBASE_TYPE"),
    "project_id": os.getenv("FIREBASE_PROJECT_ID"),
    "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
    "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
    "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
    "client_id": os.getenv("FIREBASE_CLIENT_ID"),
    "auth_uri": os.getenv("FIREBASE_AUTH_URI"),
    "token_uri": os.getenv("FIREBASE_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_CERT_URL"),
    "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_CERT_URL"),
    "universe_domain": os.getenv("FIREBASE_UNIVERSE_DOMAIN"),
}

# Initialize Firebase app with loaded credentials
cred = credentials.Certificate(firebase_config)
firebase_admin.initialize_app(cred)

# Firestore database instance
db = firestore.client()


def save_subscription(user_id, name, expiry, email="Unknown", currency="Unknown", mobile="Unknown"):
    """Save user subscription to Firestore with email & mobile"""
    try:
        doc_ref = db.collection(DB_FILE_NAME).document(str(user_id))
        doc_ref.set({
            "currency": currency,
            "name": name,
            "expiry": expiry.strftime("%Y-%m-%d %H:%M"),
            "email": email,
            "mobile": mobile
        })
        print(f"✅ Subscription saved for user {user_id} until {expiry}")
    except Exception as e:
        print(f"❌ Failed to save subscription for {user_id}: {e}")



def load_subscriptions():
    """Load all subscriptions from Firestore, safely handling errors"""
    try:
        users_ref = db.collection(DB_FILE_NAME).stream()
        return {
            user.id: {
                "currency": user.to_dict().get("currency", "Unknown"),
                "name": user.to_dict().get("name", "Unknown"),
                "expiry": datetime.strptime(user.to_dict().get("expiry", "9999-12-31 23:59"), "%Y-%m-%d %H:%M"),
                "email": user.to_dict().get("email", "Unknown"),
                "mobile": user.to_dict().get("mobile", "Unknown")
            }
            for user in users_ref
        }
    except Exception as e:
        print(f"Firestore Error: {e}")
        return {}  # Return empty dict instead of crashing



def remove_expired_subscriptions():
    """Remove expired subscriptions from Firestore"""
    now = datetime.now()
    users_ref = db.collection(DB_FILE_NAME).stream()

    for user in users_ref:
        data = user.to_dict()
        expiry_str = data.get("expiry", "9999-12-31 23:59")
        expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d %H:%M")

        if expiry_date < now:
            db.collection(DB_FILE_NAME).document(user.id).delete()
            print(f"Deleted expired subscription for user {user.id}")


    # remove_expired_subscriptions()
#iStock_Downloader_subscriptions
