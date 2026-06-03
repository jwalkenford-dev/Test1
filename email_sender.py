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

    yes_url = respond_url + '?attending=yes'
    no_url = respond_url + '?attending=no'

    plain = f"""Hi {guest_name},

This is a friendly reminder that your stay at Dixie Summerhouse Condo is coming up in 2 weeks!

  Check-in:  {checkin_str} (Friday)
  Checkout:  {checkout_str} (Friday)

Please confirm that your stay at Dixie Summerhouse for you or your guest. If you are unable to utilize the week, please let us know as well and we will make the Condo available for others use.

  YES, I will be there: {yes_url}
  NO, I can't make it:  {no_url}

We look forward to having you!

— Dixie Summerhouse Condo
"""

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:'Segoe UI',sans-serif;background:#f0f4f8;margin:0;padding:24px;">
  <div style="max-width:520px;margin:0 auto;background:white;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
    <div style="background:#2b6cb0;padding:24px 32px;">
      <h1 style="color:white;margin:0;font-size:1.3rem;">Dixie Summerhouse Condo</h1>
      <p style="color:rgba(255,255,255,0.8);margin:4px 0 0;font-size:0.85rem;">Upcoming Stay Reminder</p>
    </div>
    <div style="padding:28px 32px;">
      <p style="margin:0 0 16px;color:#2d3748;">Hi {guest_name},</p>
      <p style="margin:0 0 20px;color:#4a5568;line-height:1.6;">
        This is a friendly reminder that your stay at Dixie Summerhouse Condo is coming up in <strong>2 weeks</strong>!
      </p>
      <div style="background:#f0f4f8;border-radius:8px;padding:16px 20px;margin-bottom:20px;">
        <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #e2e8f0;font-size:0.9rem;">
          <span style="color:#718096;">Check-in</span>
          <strong style="color:#2d3748;">{checkin_str} (Friday)</strong>
        </div>
        <div style="display:flex;justify-content:space-between;padding:6px 0;font-size:0.9rem;">
          <span style="color:#718096;">Checkout</span>
          <strong style="color:#2d3748;">{checkout_str} (Friday)</strong>
        </div>
      </div>
      <p style="margin:0 0 24px;color:#4a5568;line-height:1.6;">
        Please confirm that your stay at Dixie Summerhouse for you or your guest. If you are unable to utilize the week, please let us know as well and we will make the Condo available for others use.
      </p>
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
        <tr>
          <td style="padding-right:8px;">
            <a href="{yes_url}" style="display:block;text-align:center;background:#276749;color:white;text-decoration:none;font-weight:600;font-size:0.95rem;padding:12px;border-radius:7px;">
              Yes, I'll be there
            </a>
          </td>
          <td style="padding-left:8px;">
            <a href="{no_url}" style="display:block;text-align:center;background:#c53030;color:white;text-decoration:none;font-weight:600;font-size:0.95rem;padding:12px;border-radius:7px;">
              No, I can't make it
            </a>
          </td>
        </tr>
      </table>
      <p style="margin:0;color:#718096;font-size:0.82rem;">
        — Dixie Summerhouse Condo
      </p>
    </div>
  </div>
</body>
</html>"""

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['To'] = to_address
    msg.attach(MIMEText(plain, 'plain'))
    msg.attach(MIMEText(html, 'html'))

    server, user = _smtp_connection()
    msg['From'] = user
    try:
        server.sendmail(user, to_address, msg.as_string())
    finally:
        server.quit()


def send_cancellation_notice(to_address, guest_name, checkin_str, checkout_str):
    subject = 'Your Week at Dixie Summerhouse Has Been Released'
    body = f"""Hi {guest_name},

Thank you for letting us know. Your booking for the week of {checkin_str} – {checkout_str} has been removed from the calendar and the condo will be made available for others.

If your plans change or you need anything, feel free to reach out.

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


def send_maid_notice(to_address, guest_name, checkout_str, maid_name, maid_phone):
    subject = 'Checkout Reminders — Dixie Summerhouse Condo'
    body = f"""Hi {guest_name},

A few reminders as your checkout approaches:

1. Contact Maid — {maid_name} at {maid_phone} by Monday prior to checkout to let her know what day and time you'll be departing.

2. Ensure sheets and towels are clean and there is no more than 1 load in the washing machine.

3. Ensure there is enough soap, dishwashing detergent, and laundry detergent for at least 2 days use.

Checkout: {checkout_str} (Friday)

Thanks and enjoy your stay!

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


def send_availability_email(to_addresses, checkin_str, checkout_str, guest_name='', guest_phone=''):
    subject = f'Dixie Summerhouse Condo Available — Week of {checkin_str}'
    contact_line = f'\nThe week was held by {guest_name}' + (f' ({guest_phone})' if guest_phone else '') + '.' if guest_name else ''
    body = f"""Hello,

Dixie Summerhouse Condo 303A is now available for the week of {checkin_str} – {checkout_str}.{contact_line}

If you would like to book this week, please contact Jon.

— Dixie Summerhouse Condo
"""
    server, user = _smtp_connection()
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = user
    msg['To'] = ', '.join(to_addresses)
    msg.attach(MIMEText(body, 'plain'))
    try:
        server.sendmail(user, to_addresses, msg.as_string())
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
