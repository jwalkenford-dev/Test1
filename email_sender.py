import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def _smtp_connection():
    user = os.getenv('GMAIL_USER', '')
    password = os.getenv('GMAIL_APP_PASSWORD', '').replace(' ', '')
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.ehlo()
    server.starttls()
    server.login(user, password)
    return server, user


def send_reminder(to_address, guest_name, checkin_str, checkout_str, respond_url):
    subject = 'Reminder: Your Upcoming Stay at Dixie Summerhouse Condo'
    body = f"""Hi {guest_name},

This is a friendly reminder that your stay at Dixie Summerhouse Condo is coming up in 2 weeks!

  Check-in:  {checkin_str} (Friday)
  Checkout:  {checkout_str} (Friday)

Please confirm your stay or send us a message using the link below:

  {respond_url}

We look forward to having you!

— Dixie Summerhouse Condo
"""
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['To'] = to_address
    msg.attach(MIMEText(body, 'plain'))

    server, user = _smtp_connection()
    msg['From'] = user
    try:
        server.sendmail(user, to_address, msg.as_string())
    finally:
        server.quit()


def send_response_ack(to_address, guest_name):
    subject = 'We received your message — Dixie Summerhouse Condo'
    body = f"""Hi {guest_name},

Thank you — we've received your response and will be in touch if needed.

See you soon!

— Dixie Summerhouse Condo
"""
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['To'] = to_address
    msg.attach(MIMEText(body, 'plain'))

    server, user = _smtp_connection()
    msg['From'] = user
    try:
        server.sendmail(user, to_address, msg.as_string())
    finally:
        server.quit()
