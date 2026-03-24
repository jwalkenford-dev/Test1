import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for

load_dotenv()

from database import (
    add_booking,
    add_family,
    delete_booking,
    delete_family,
    get_all_bookings,
    get_all_families,
    get_booking_by_checkin,
    get_booking_by_id,
    get_booking_by_token,
    get_family_by_id,
    get_unreminded_bookings_with_email,
    init_db,
    mark_reminder_sent,
    save_guest_response,
    update_booking,
    update_family,
)
from email_sender import send_reminder, send_response_ack

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')

BASE_URL = os.getenv('BASE_URL', 'http://localhost:5000')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_date(s):
    return datetime.strptime(s, '%Y-%m-%d').date()


def date_key(d):
    return d.strftime('%Y-%m-%d')


def booking_days(checkin_str):
    """Return set of date strings covered by a booking (checkin through checkout)."""
    start = parse_date(checkin_str)
    return {date_key(start + timedelta(days=i)) for i in range(8)}


def has_conflict(checkin_str, exclude_id=None):
    new_days = booking_days(checkin_str)
    for b in get_all_bookings():
        if exclude_id and b['id'] == exclude_id:
            continue
        if new_days & booking_days(b['checkin']):
            return True
    return False


def is_friday(date_str):
    return parse_date(date_str).weekday() == 4


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.get('/api/bookings')
def list_bookings():
    return jsonify(get_all_bookings())


@app.post('/api/bookings')
def create_booking():
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    checkin = (data.get('checkin') or '').strip()
    notes = (data.get('notes') or '').strip()
    email = (data.get('email') or '').strip()

    if not name:
        return jsonify({'error': 'Guest name is required.'}), 400
    if not checkin:
        return jsonify({'error': 'Check-in date is required.'}), 400
    if not is_friday(checkin):
        return jsonify({'error': 'Check-in must be a Friday.'}), 400
    if has_conflict(checkin):
        return jsonify({'error': 'Week overlaps an existing booking.'}), 409

    booking = add_booking(name, checkin, notes, email)
    return jsonify(booking), 201


@app.delete('/api/bookings/<int:booking_id>')
def remove_booking(booking_id):
    if delete_booking(booking_id) == 0:
        return jsonify({'error': 'Booking not found.'}), 404
    return jsonify({'ok': True})


@app.post('/api/bookings/import')
def import_bookings():
    import csv
    import io

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded.'}), 400

    f = request.files['file']
    filename = f.filename.lower()

    rows = []
    try:
        if filename.endswith('.csv'):
            text = f.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
        elif filename.endswith(('.xlsx', '.xls')):
            import openpyxl
            wb = openpyxl.load_workbook(f, data_only=True)
            ws = wb.active
            headers = [str(c.value).strip().lower() if c.value else '' for c in next(ws.iter_rows(min_row=1, max_row=1))]
            for row in ws.iter_rows(min_row=2, values_only=True):
                rows.append({headers[i]: (str(v).strip() if v is not None else '') for i, v in enumerate(row)})
        else:
            return jsonify({'error': 'Unsupported file type. Upload a .csv or .xlsx file.'}), 400
    except Exception as e:
        return jsonify({'error': f'Could not parse file: {e}'}), 400

    created, updated, skipped = [], [], []

    for i, row in enumerate(rows, start=2):
        # Normalise column names (accept "guest name", "Guest Name", etc.)
        norm = {k.strip().lower().replace(' ', '_'): v for k, v in row.items()}
        name = norm.get('name') or norm.get('guest_name') or norm.get('guest') or ''
        checkin = norm.get('checkin') or norm.get('check_in') or norm.get('check-in') or norm.get('date') or ''
        email = norm.get('email') or norm.get('guest_email') or ''
        notes = norm.get('notes') or norm.get('note') or ''

        name = name.strip()
        checkin = checkin.strip()
        email = email.strip()
        notes = notes.strip()

        if not name or not checkin:
            skipped.append({'row': i, 'reason': 'Missing name or check-in date'})
            continue

        # Normalise date formats MM/DD/YYYY or DD/MM/YYYY → YYYY-MM-DD
        if '/' in checkin:
            parts = checkin.split('/')
            if len(parts) == 3:
                try:
                    m_part, d_part, y_part = parts
                    checkin = f"{int(y_part):04d}-{int(m_part):02d}-{int(d_part):02d}"
                except ValueError:
                    skipped.append({'row': i, 'reason': f'Unrecognised date format: {checkin}'})
                    continue

        try:
            if not is_friday(checkin):
                skipped.append({'row': i, 'reason': f'{checkin} is not a Friday'})
                continue
        except ValueError:
            skipped.append({'row': i, 'reason': f'Invalid date: {checkin}'})
            continue

        existing = get_booking_by_checkin(checkin)
        if existing:
            update_booking(existing['id'], name, checkin, notes, email)
            updated.append({'id': existing['id'], 'name': name, 'checkin': checkin})
        else:
            if has_conflict(checkin):
                skipped.append({'row': i, 'reason': f'Week starting {checkin} overlaps an existing booking'})
                continue
            b = add_booking(name, checkin, notes, email)
            created.append({'id': b['id'], 'name': name, 'checkin': checkin})

    return jsonify({'created': created, 'updated': updated, 'skipped': skipped})


@app.post('/api/bookings/<int:booking_id>/email')
def send_manual_email(booking_id):
    b = get_booking_by_id(booking_id)
    if not b:
        return jsonify({'error': 'Booking not found.'}), 404
    if not b['email']:
        return jsonify({'error': 'No email address on this booking.'}), 400

    checkin = parse_date(b['checkin'])
    checkout = checkin + timedelta(days=7)
    respond_url = f"{BASE_URL}/respond/{b['token']}"

    try:
        send_reminder(
            b['email'], b['name'],
            checkin.strftime('%B %d, %Y'),
            checkout.strftime('%B %d, %Y'),
            respond_url,
        )
        mark_reminder_sent(b['id'])
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.get('/respond/<token>')
def respond_page(token):
    b = get_booking_by_token(token)
    if not b:
        return render_template('respond.html', not_found=True)
    checkin = parse_date(b['checkin'])
    checkout = checkin + timedelta(days=7)
    submitted = request.args.get('submitted') == '1'
    return render_template(
        'respond.html',
        booking=b,
        checkin_fmt=checkin.strftime('%B %d, %Y'),
        checkout_fmt=checkout.strftime('%B %d, %Y'),
        submitted=submitted,
        not_found=False,
    )


@app.post('/respond/<token>')
def submit_response(token):
    b = get_booking_by_token(token)
    if not b:
        return render_template('respond.html', not_found=True)

    message = (request.form.get('message') or '').strip()
    if message:
        save_guest_response(token, message)
        if b['email']:
            try:
                send_response_ack(b['email'], b['name'])
            except Exception:
                pass

    return redirect(url_for('respond_page', token=token, submitted=1))


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------

@app.get('/families')
def families_page():
    return render_template('families.html')


@app.get('/api/families')
def list_families():
    return jsonify(get_all_families())


@app.post('/api/families')
def create_family():
    data = request.get_json(force=True)
    family_name = (data.get('family_name') or '').strip()
    if not family_name:
        return jsonify({'error': 'Family name is required.'}), 400
    f = add_family(
        family_name,
        (data.get('contact1_name') or '').strip(),
        (data.get('contact1_email') or '').strip(),
        (data.get('contact1_phone') or '').strip(),
        (data.get('contact2_name') or '').strip(),
        (data.get('contact2_email') or '').strip(),
        (data.get('contact2_phone') or '').strip(),
    )
    return jsonify(f), 201


@app.put('/api/families/<int:family_id>')
def edit_family(family_id):
    if not get_family_by_id(family_id):
        return jsonify({'error': 'Family not found.'}), 404
    data = request.get_json(force=True)
    family_name = (data.get('family_name') or '').strip()
    if not family_name:
        return jsonify({'error': 'Family name is required.'}), 400
    f = update_family(
        family_id,
        family_name,
        (data.get('contact1_name') or '').strip(),
        (data.get('contact1_email') or '').strip(),
        (data.get('contact1_phone') or '').strip(),
        (data.get('contact2_name') or '').strip(),
        (data.get('contact2_email') or '').strip(),
        (data.get('contact2_phone') or '').strip(),
    )
    return jsonify(f)


@app.delete('/api/families/<int:family_id>')
def remove_family(family_id):
    if delete_family(family_id) == 0:
        return jsonify({'error': 'Family not found.'}), 404
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def check_and_send_reminders():
    today = datetime.today().date()
    target = today + timedelta(days=14)
    for b in get_unreminded_bookings_with_email():
        try:
            checkin = parse_date(b['checkin'])
            if checkin == target:
                checkout = checkin + timedelta(days=7)
                respond_url = f"{BASE_URL}/respond/{b['token']}"
                send_reminder(
                    b['email'], b['name'],
                    checkin.strftime('%B %d, %Y'),
                    checkout.strftime('%B %d, %Y'),
                    respond_url,
                )
                mark_reminder_sent(b['id'])
        except Exception as e:
            print(f"[reminder] Failed for booking {b['id']}: {e}")


def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_and_send_reminders, 'cron', hour=8, minute=0)
    scheduler.start()


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

init_db()

# Avoid double-start in Flask debug reloader
if os.environ.get('WERKZEUG_RUN_MAIN') != 'false':
    start_scheduler()

if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true', use_reloader=False)
