from firebase_db import save_subscription, load_subscriptions, remove_expired_subscriptions
from paypal import create_paypal_payment, capture_payment
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackContext,
    CallbackQueryHandler,
    filters, ConversationHandler, MessageHandler,
)
from telegram.error import BadRequest
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import time
import requests
import json
import os
import random
import string
import asyncio
import logging

# from keep_alive import keep_alive
# keep_alive()

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('TOKEN')
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID'))
PRIVATE_CHANNEL_ID = int(os.getenv('PRIVATE_CHANNEL_ID'))
MSG_DELETE_TIME = int(os.getenv('MSG_DELETE_TIME'))  # Default to 0 if not set
# The number of members needed to trigger the reward
PAYMENT_URL = os.getenv('PAYMENT_URL')
ACCOUNT_URL = os.getenv('ACCOUNT_URL')
PAYMENT_CAPTURED_DETAILS_URL = os.getenv('PAYMENT_CAPTURED_DETAILS_URL')
PRODUCT_NAME = "iStock Photo Downloader"

subscription_data = {}
user_data = {}
codes_data = {}
CODES_FILE = "codes.json"
payment_status = False

indian_plan = "✅ Monthly Plan – Rs 50/-"
non_indian_plan = "✅ Monthly Plan – $2"

# Global variable to store the subscription code fetched from the API.
subscription_code = None
# Define conversation states
ENTER_CODE = 1
WAITING_FOR_CODE, WAITING_FOR_PAYMENT, WAITING_FOR_USER = range(3)

# ------------------ fetching Payment details made by user------------------ #
def fetch_payment_details(chat_id,payment_amount):
    response = requests.get(url=PAYMENT_CAPTURED_DETAILS_URL)
    try:
        response.raise_for_status()
        data = response.json()
        for entry in data:
            if entry['user_id'] == chat_id:
                if entry['amount'] == str(payment_amount):
                    return entry
        print("No payment details found! ")
    except requests.exceptions.HTTPError as err:
        print("HTTP Error:", err)

# ------------------ Redeem Codes------------------ #
def load_codes():
    try:
        with open(CODES_FILE, "r") as f:
            codes_data = json.load(f)
            if not isinstance(codes_data, dict):  # Ensure it is a dictionary
                codes_data = {}
            return codes_data
    except (FileNotFoundError, json.JSONDecodeError):
        return {}  # Return an empty dictionary if file not found or corrupted


def save_codes():
    with open(CODES_FILE, "w") as f:
        json.dump(codes_data, f, indent=4)


def generate_code(validity_days=1):
    codes_data = load_codes()  # Load existing codes from file
    # Generate a random alphanumeric code
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    # Set expiry date
    expiry_dt = datetime.now() + timedelta(days=validity_days)
    # Store the code with its expiry date
    codes_data[code] = expiry_dt.strftime("%Y-%m-%d %H:%M")
    # Save the updated codes back to the file
    with open(CODES_FILE, "w") as f:
        json.dump(codes_data, f, indent=4)
    return code


def remove_expired_codes():
    codes_data = load_codes()
    now = datetime.now()

    updated_codes = {
        code: expiry for code, expiry in codes_data.items()
        if datetime.strptime(expiry, "%Y-%m-%d %H:%M") > now
    }

    if len(updated_codes) != len(codes_data):
        save_codes()


async def generate_code_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("🚫 You are not authorized to use this command.")
        return
    keyboard = [
        [InlineKeyboardButton("1 Day", callback_data="generate_1")],
        [InlineKeyboardButton("1 Week", callback_data="generate_7")],
        [InlineKeyboardButton("1 Month", callback_data="generate_30")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Please choose a period for this subscription code:", reply_markup=reply_markup)

async def redeem_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Start the upload process """
    await update.message.reply_text("Please enter you subscription code:")
    return WAITING_FOR_CODE

async def process_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    """ Receive payment amount and prompt for user ID """
    code = update.message.text
    global codes_data
    codes_data = load_codes()
    if code in codes_data:
        user_name = update.message.from_user.full_name
        expiry_dt = datetime.strptime(codes_data[code], "%Y-%m-%d %H:%M")
        # Ensure expiry_dt is in the future
        expiry_timestamp = int(expiry_dt.timestamp())
        if expiry_timestamp <= int(time.time()):
            logger.error("Generated expiry date is invalid (in the past).")
            await update.message.reply_text("Error: The generated expiry date is invalid.")
            return
        day = expiry_dt.strftime("%Y-%m-%d")
        time_str = expiry_dt.strftime("%H:%M")
        day = expiry_dt.strftime("%Y-%m-%d %H:%M")

        save_subscription(user_id=user_id, name=user_name, expiry=expiry_dt)

        # Refresh subscriptions from Firestore
        global subscription_data
        subscription_data = load_subscriptions()  # Refresh from Firebase

        del codes_data[code]
        logger.error(f"Code {code} removed from codes_data.")
        save_codes()
        try:
            # Create a chat invite link with the expiry date from the code (as a Unix timestamp)
            invite_link = await context.bot.create_chat_invite_link(
                PRIVATE_CHANNEL_ID,
                member_limit=1,
                expire_date=expiry_timestamp
            )
        except Exception as e:
            await update.message.reply_text("Error generating invite link. Please try again later.")
            logger.error(f"Error creating invite link: {e}")

        await update.message.reply_text(
            f"<b>🔰CODE REDEEM SUCCESSFULLY🔰</b>\n\n"
            f"🚀 Here is your premium member invite link:\n{invite_link.invite_link}\n"
            f"<b>(Valid for one-time use)</b>\n\n"
            f"✅ After joining this channel, type /start to access the instructor account.\n\n"
            f"<b>🌐 Your plan will expire on {day} at {time_str}.</b>",
            parse_mode="HTML"
        )
        # Notify admin that this user has successfully generated the channel invite link.
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"<b>🔰SUBSCRIPTION ACTIVATED🔰</b>\n\n"
                 f"✅ Subscription code redeem successfully\n\n"
                 f"🆔<b>User ID:</b> {user_id}\n"
                 f"<b>Expiry:</b> {day} at {time_str}",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("❌ Invalid or expired code. Try again.")

    return ConversationHandler.END

# ------------------ Handler: Process Code Input ------------------ #
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global subscription_code  # Access the global variable
    query = update.callback_query
    await query.answer()  # Acknowledge the button press
    if query.data.startswith("generate_"):
        days = int(query.data.split("_")[1])
        code = generate_code(days)
        await query.message.reply_text(f"Generated Code: `{code}` \n(Valid for {days} days)", parse_mode="Markdown")

# ------------------ Periodic Task: Check Expired Subscriptions ------------------ #
async def check_expired_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    remove_expired_subscriptions()  # Remove expired entries from Firestore
    subscription_data = load_subscriptions()  # Refresh from Firebase
    now = datetime.now()
    expired_users = []
    for chat_id, details in list(subscription_data.items()):
        expiry_value = details["expiry"]
        if isinstance(expiry_value, str):
            expiry_date = datetime.strptime(expiry_value, "%Y-%m-%d %H:%M:%S")
        else:
            expiry_date = expiry_value
        if expiry_date < now:
            try:
                await context.bot.ban_chat_member(PRIVATE_CHANNEL_ID, chat_id, until_date=now)
                await context.bot.unban_chat_member(PRIVATE_CHANNEL_ID, chat_id)
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"<b>🔰SUBSCRIPTION EXPIRED🔰</b>\n\n"
                         f"📌 <a href='tg://user?id={chat_id}'>{subscription_data[chat_id]['name']}</a> "
                         f"removed from iStock Photo Downloader channel.",
                    parse_mode="HTML"
                )
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="<b>🔰SUBSCRIPTION EXPIRED🔰</b>\n\nPlz, type /start command to make the payment",
                    parse_mode="HTML"
                )
                logger.info(f"Removed expired user {chat_id} from the private channel.")
            except Exception as e:
                logger.error(f"Failed to remove/unban user {chat_id}: {e}")
            expired_users.append(chat_id)
    for chat_id in expired_users:
        del subscription_data[chat_id]

# ------------------ Admin Command: Show Users ------------------ #
async def show_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("🚫 You are not authorized to use this command!")
        return
    subscription_data = load_subscriptions()  # Refresh from Firebase
    if not subscription_data:
        await update.message.reply_text("⚠️ No active users found!")
        return
    user_list = "\n".join([
        f"👤 <a href='tg://user?id={chat_id}'>{details['name']}</a> (Expiry: {details['expiry'].strftime('%Y-%m-%d %H:%M')})"
        for chat_id, details in subscription_data.items()
    ])
    await update.message.reply_text(
        f"📜 <b>Active Users:</b>\n\n{user_list}",
        parse_mode="HTML",
        disable_web_page_preview=True
    )

# Modify the `start` function to schedule message deletion
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Determine the source of the request (message or callback query)
        if update.message:
            user_id = update.message.from_user.id
            chat_id = update.message.chat.id
        elif update.callback_query:
            user_id = update.callback_query.from_user.id
            chat_id = update.callback_query.message.chat.id
            await update.callback_query.answer()  # Acknowledge the callback query
        else:
            raise AttributeError("‼️Unable to determine the context of the request.")

        # Check if the user is a member of the private channel
        chat_member = await context.bot.get_chat_member(PRIVATE_CHANNEL_ID, user_id)
        is_premium = chat_member.status in ["member", "administrator", "creator"]

        button_text = f"🚀 Access {PRODUCT_NAME}" if is_premium else f"🚀 Click here to Buy"
        button = InlineKeyboardButton(
            button_text,
            web_app=WebAppInfo(url=ACCOUNT_URL) if is_premium else None,
            callback_data="buy_subscription" if not is_premium else None,
        )

        keyboard = [[button]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if is_premium:
            sent_message = await context.bot.send_message(
                chat_id,
                f"*🔰PREMIUM MEMBER!🔰*\n\n"
                f"‼️ You are already a premium member! Click the button below to access the {PRODUCT_NAME}",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            # Schedule the message deletion after MSG_DELETE_TIME
            context.job_queue.run_once(
                delete_message,
                when=MSG_DELETE_TIME,  # MSG_DELETE_TIME in seconds
                data={"chat_id": chat_id, "message_id": sent_message.message_id},
            )
        else:
            await update.message.reply_text(
                f"*🔰You are already a premium member!🔰*\n\n"
                f"*Steps to Use:*\n"
                f"1️⃣ Go to Shutterstock's official website: https://www.istockphoto.com/ , and open any image.\n"
                f"2️⃣ In browser address tap, copy the URL.\n"
                f"3️⃣ Paste this URL into the downloader and click on the GET IMAGES button.\n"
                f"4️⃣ When the Image appears after fetching the image, scroll down and click the Download Image button."
                if is_premium else
                f"*🔰You are not a premium member!🔰*"
                f"\n\n👁‍🗨 To use this bot, you must first purchase a subscription. Please click on the button below to make the payment."
                f"\n\n🆘*Need Help?* Contact to [Coding Services](https://t.me/coding_services)",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    except BadRequest as e:
        logger.error(f"BadRequest Error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {type(e).__name__} - {e}")

async def buy_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("For Indian Customers 🇮🇳", callback_data="india")],
        [InlineKeyboardButton("For Non-Indian Customers 🌐", callback_data="non_india")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"Please select an option based on your country or region. "
        f"This will help us provide you with payment methods suitable for your location.",
        reply_markup=reply_markup
    )


async def handle_customer_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id

    # Initialize user data for the chat ID if not already present
    if chat_id not in user_data:
        user_data[chat_id] = {}

    if query.data == "non_india":
        user_data[chat_id]["region"] = "Non-India"
        amount = 2
    else:
        user_data[chat_id]["region"] = "India"
        amount = 50

    user_data[chat_id]["amount"] = amount
    user_data[chat_id]["plan"] = "Monthly"

    sent_message = await query.edit_message_text(f"♻️ Creating an invoice for monthly plan. Please wait...")
    context.job_queue.run_once(
        delete_message,
        when=MSG_DELETE_TIME,  # MSG_DELETE_TIME in seconds
        data={"chat_id": chat_id, "message_id": sent_message.message_id},
    )

    if user_data[chat_id]["region"] == "Non-India":
        order_id, approve_url = create_paypal_payment(amount)
        user_data[chat_id]["order_id"] = order_id
    URL = approve_url if user_data[chat_id]["region"] == "Non-India" else PAYMENT_URL
    button_text = f"🚀Pay ${amount} now🚀" if user_data[chat_id]["region"] == "Non-India" else f"🚀Pay Rs {amount}/- now🚀"
    keyboard = [
        # [InlineKeyboardButton("Pay Now", web_app=WebAppInfo(url=URL))],
        [InlineKeyboardButton(button_text, url=URL)],
        [InlineKeyboardButton("✅ Verify Payment", callback_data="verify_payment")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id,
                                f"*🔰STEPS🔰*\n\n"
                                f"1️⃣ First click on *Pay Now* button, to make the payment.\n"
                                f"2️⃣ After making payment, you have to click on *Verify Payment* "
                                f"button to verfity your payment and wait for few seconds. \n\n"
                                f"🆔*Your User ID:* `{chat_id}` \n"
                                f"(Use this User ID on Razorpay Payment Gateway)"
                                f"\n\n🆘*Need Help?* Contact to [Coding Services](https://t.me/coding_services)",
                                   reply_markup=reply_markup, parse_mode="Markdown")



async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global payment_status
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    sent_message = await query.edit_message_text(f"♻️ Payment verifying. Please wait...")
    # Schedule the message deletion after MSG_DELETE_TIME
    context.job_queue.run_once(
        delete_message,
        when=MSG_DELETE_TIME,  # MSG_DELETE_TIME in seconds
        data={"chat_id": chat_id, "message_id": sent_message.message_id},
    )
    amount = int(user_data[chat_id]["amount"])
    if user_data[chat_id]["region"] == "Non-India":
        # Check if an order exists
        if "order_id" not in user_data[chat_id]:
            await query.edit_message_text("No payment found. Please start over.")
            return
        order_id = user_data[chat_id]["order_id"]
        try:

            # Verify the payment
            payment_result = capture_payment(order_id)
            if payment_result["status"] == "COMPLETED":
                user_name = payment_result['name']
                user_email = payment_result['email']
                currency = payment_result['currency']
                payment_status = True
        except requests.exceptions.HTTPError as e:
            await query.edit_message_text(f"🚫 Payment not completed. Please try again.")
    else:
        try:
            # Verify the payment
            user_id = str(chat_id)
            payment_details = fetch_payment_details(user_id, amount)
            if payment_details:
                payment_status = True
                user_name = payment_details['name']
                user_email = payment_details.get('email', "Unknown")  # Get email, default to "Unknown"
                user_mobile = payment_details.get('mobile', "Unknown")  # Get mobile, default to "Unknown"
                paid_amount = int(payment_details['amount'])
        except requests.exceptions.HTTPError as e:
            await query.edit_message_text(f"🚫 Payment not completed. Please try again.")

    if payment_status:
        expiry_date = datetime.now() + timedelta(days=30)
        day = expiry_date.strftime("%Y-%m-%d")
        time_str = expiry_date.strftime("%H:%M")
        plan = user_data[chat_id]["plan"]
        # Save to Firestore with real email & mobile
        if user_data[chat_id]["region"] == "Non-India":
            currency = "USD"
            save_subscription(user_id=chat_id, name=user_name, expiry=expiry_date, email=user_email, currency=currency)
        else:
            currency = "INR"
            save_subscription(user_id=chat_id, name=user_name, expiry=expiry_date, email=user_email, currency=currency, mobile=user_mobile)
            DELETED_CODES_URL = f"{PAYMENT_CAPTURED_DETAILS_URL}/amount/{paid_amount}"
            requests.delete(url=DELETED_CODES_URL)

        logger.info(f"User {chat_id} subscribed to {user_data[chat_id]['plan']} plan until {expiry_date}.")

        try:
            # Generate an invite link for the private channel that expires after one use
            invite_link = await context.bot.create_chat_invite_link(
                PRIVATE_CHANNEL_ID,
                member_limit=1  # The link will expire after one use
            )
        except Exception as e:
            logger.error(f"🚫 Failed to generate/send invite link: {e}")

        keyboard = [
            [
                InlineKeyboardButton(
                    "🚀 Click here after joining channel",
                    callback_data="is_premium_member"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id,
            f"<b>🔰PAYMENT VERIFIED🔰</b>\n\n"
                    f"🙏Thank you for making the payment.\n\n"
                    f"🚀 Here is your premium member invite link:\n{invite_link.invite_link}\n"
                    f"<b>(Valid for one-time use)</b>\n\n"
                    f"✅ After joining this channel, type /start or click on the button below to access the {PRODUCT_NAME}.\n\n"
                    f"<b>🌐 Your plan will expire on {day} at {time_str}.</b>",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        logger.info(f"Invite link sent to user {query.from_user.id}.")
        # Notify admin that this user has successfully generated the channel invite link.
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"<b>🔰SUBSCRIPTION PURCHASED🔰</b>\n\n"
                 f"<b>Name:</b> <a href='tg://user?id={chat_id}'>{user_name}</a>\n"
                 f"<b>Email:</b> {user_email}\n"
                 f"🆔<b>User ID:</b> {chat_id}\n"
                 f"<b>Expiry:</b> {day} at {time_str}"
                 f"<b>Currency:</b> {currency}",
            parse_mode="HTML"
        )
        context.job_queue.run_once(
            delete_message,
            when=0,
            data={"chat_id": sent_message.chat.id, "message_id": sent_message.message_id},
        )

    else:
        await query.edit_message_text("🚫 Payment not completed. Please try again.")


# ------------------ Delete Message Function ------------------ #
async def delete_message(context: CallbackContext):
    async def delete_message(context: CallbackContext):
        data = context.job.data
        chat_id = data["chat_id"]
        message_id = data["message_id"]
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)

# ------------------ New Admin Command: Admin Commands ------------------ #
async def admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("🚫 You are not authorized to use this command.")
        return
    await update.message.reply_text(
        """
Commands available:
/show_users - Show list of all premium users
/generate_code - Generate a subscription redeem code
"""
    )


# ------------------ Help Command ------------------ #
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        """
Commands available:
/start - Start the bot and check your membership
/redeem_code - Redeem subscription code provided by Admin
/admin_commands - Show all commands that only admin can use
/help - Show this help message
"""
    )

def main():
    global subscription_data, codes_data
    subscription_data = load_subscriptions()  # Load from Firebase
    codes_data = load_codes()
    application = Application.builder().token(TOKEN).build()
    # Upload file conversation handler
    conv_handler_upload = ConversationHandler(
        entry_points=[CommandHandler("redeem_code", redeem_code)],
        states={
            WAITING_FOR_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_code)],
        },
        fallbacks=[
            CommandHandler("redeem_code", redeem_code),
        ],
    )

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(start, pattern="^start$"))
    application.add_handler(CommandHandler("show_users", show_users))
    application.add_handler(CommandHandler("generate_code", generate_code_command))
    application.add_handler(CommandHandler("admin_commands", admin_commands))
    application.add_handler(CallbackQueryHandler(buy_subscription, pattern="^buy_subscription$"))
    application.add_handler(CallbackQueryHandler(handle_customer_choice, pattern="^(india|non_india)$"))
    application.add_handler(CallbackQueryHandler(verify_payment, pattern="^verify_payment$"))
    # application.add_handler(CallbackQueryHandler(is_premium_member, pattern="^is_premium_member$"))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(conv_handler_upload)

    # Add periodic job to check expired subscriptions
    scheduler = BackgroundScheduler(timezone="UTC")
    # scheduler.add_job(check_expired_subscriptions, "interval", minutes=1, args=[application])
    scheduler.add_job(
        lambda: asyncio.run(check_expired_subscriptions(application)),
        "interval",
        hours=1
    )
    scheduler.start()

    # Start polling
    application.run_polling()


if __name__ == "__main__":
    main()
