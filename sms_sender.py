import os
from twilio.rest import Client


def _twilio_client():
    account_sid = os.getenv('TWILIO_ACCOUNT_SID', '')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN', '')
    return Client(account_sid, auth_token)


def is_configured():
    return all([
        os.getenv('TWILIO_ACCOUNT_SID'),
        os.getenv('TWILIO_AUTH_TOKEN'),
        os.getenv('TWILIO_FROM_NUMBER'),
    ])


def send_reminder_sms(to_number, guest_name, checkin_str, checkout_str, respond_url):
    body = (
        f"Hi {guest_name}, your stay at Dixie Summerhouse Condo is 2 weeks away!\n"
        f"Check-in: {checkin_str}  Checkout: {checkout_str}\n"
        f"Confirm or message us: {respond_url}"
    )
    client = _twilio_client()
    client.messages.create(
        body=body,
        from_=os.getenv('TWILIO_FROM_NUMBER', ''),
        to=to_number,
    )
