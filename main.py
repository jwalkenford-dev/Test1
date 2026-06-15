import os
from datetime import datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo('America/Chicago')


def now_central():
    return datetime.now(CENTRAL)

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

from database import (
    add_booking,
    add_comment,
    add_family,
    add_photo,
    delete_booking,
    delete_comment,
    delete_family,
    delete_photo,
    get_active_booking_for_date,
    get_all_bookings,
    get_all_comments,
    get_all_families,
    get_all_photos,
    get_booking_by_checkin,
    get_booking_by_id,
    get_booking_by_token,
    get_family_by_email,
    get_family_by_id,
    get_family_emails_for_booking_name,
    get_unreminded_bookings_with_email,
    init_db,
    mark_maid_text_sent,
    mark_reminder_sent,
    mark_sms_sent,
    save_guest_response,
    set_booking_family,
    set_family_password,
    set_gcal_event_id,
    update_booking,
    update_family,
)
import gcal
from email_sender import send_reminder, send_response_ack, send_cancellation_notice, send_maid_notice, send_availability_email, send_comment_notification, send_photo_notification


def broadcast_availability(checkin, checkout, guest_name='', guest_phone=''):
    """Email all family contact1 emails that the condo is available."""
    emails = [f['contact1_email'] for f in get_all_families() if f.get('contact1_email')]
    if emails:
        try:
            send_availability_email(
                emails,
                checkin.strftime('%B %d, %Y'),
                checkout.strftime('%B %d, %Y'),
                guest_name=guest_name,
                guest_phone=guest_phone,
            )
        except Exception as e:
            print(f"[broadcast] Email failed: {e}")

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')

BASE_URL = os.getenv('BASE_URL', 'http://localhost:5000')

UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads')
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4', 'mov', 'avi', 'webm'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated


@app.get('/login')
def login_page():
    if session.get('logged_in'):
        return redirect(url_for('index'))
    error = request.args.get('error')
    return render_template('login.html', error=error)


@app.post('/login')
def login_submit():
    email = (request.form.get('email') or '').strip().lower()
    password = (request.form.get('password') or '').strip()

    # Admin override via env vars
    admins = [
        ((os.getenv('ADMIN_EMAIL') or '').strip().lower(), os.getenv('ADMIN_PASSWORD') or ''),
        ((os.getenv('ADMIN_EMAIL_2') or '').strip().lower(), os.getenv('ADMIN_PASSWORD_2') or ''),
    ]
    for admin_email, admin_password in admins:
        if admin_email and email == admin_email and password == admin_password:
            session['logged_in'] = True
            session['user_name'] = 'Admin'
            return redirect(url_for('index'))

    # Check families table
    family = get_family_by_email(email)
    if family and family.get('password_hash') and check_password_hash(family['password_hash'], password):
        session['logged_in'] = True
        session['user_name'] = family['family_name']
        session['family_id'] = family['id']
        return redirect(url_for('index'))

    return redirect(url_for('login_page', error='Invalid email or password.'))


@app.get('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))


@app.get('/change-password')
@login_required
def change_password_page():
    return render_template('change_password.html')


@app.post('/change-password')
@login_required
def change_password_submit():
    family_id = session.get('family_id')
    if not family_id:
        return render_template('change_password.html', error='Password changes are not available for admin accounts.')

    current = (request.form.get('current_password') or '').strip()
    new_pw = (request.form.get('new_password') or '').strip()
    confirm = (request.form.get('confirm_password') or '').strip()

    if not current or not new_pw or not confirm:
        return render_template('change_password.html', error='All fields are required.')
    if new_pw != confirm:
        return render_template('change_password.html', error='New passwords do not match.')
    if len(new_pw) < 6:
        return render_template('change_password.html', error='New password must be at least 6 characters.')

    family = get_family_by_id(family_id)
    if not family or not check_password_hash(family['password_hash'], current):
        return render_template('change_password.html', error='Current password is incorrect.')

    set_family_password(family_id, generate_password_hash(new_pw, method='pbkdf2:sha256'))
    return render_template('change_password.html', success=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_date(s):
    return datetime.strptime(s, '%Y-%m-%d').date()


def date_key(d):
    return d.strftime('%Y-%m-%d')


def booking_days(checkin_str):
    """Return set of date strings covered by a booking (nights only, checkout day excluded)."""
    start = parse_date(checkin_str)
    return {date_key(start + timedelta(days=i)) for i in range(7)}


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
@login_required
def index():
    return render_template('index.html')



@app.get('/api/bookings')
@login_required
def list_bookings():
    return jsonify(get_all_bookings())


@app.post('/api/bookings')
@login_required
def create_booking():
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    checkin = (data.get('checkin') or '').strip()
    notes = (data.get('notes') or '').strip()
    email = (data.get('email') or '').strip()
    phone = (data.get('phone') or '').strip()
    family_id = data.get('family_id') or None

    if not name:
        return jsonify({'error': 'Guest name is required.'}), 400
    if not checkin:
        return jsonify({'error': 'Check-in date is required.'}), 400
    if not is_friday(checkin):
        return jsonify({'error': 'Check-in must be a Friday.'}), 400
    if has_conflict(checkin):
        return jsonify({'error': 'Week overlaps an existing booking.'}), 409

    booking = add_booking(name, checkin, notes, email, family_id, phone)
    event_id = gcal.create_event(name, checkin, notes)
    if event_id:
        set_gcal_event_id(booking['id'], event_id)
        booking['gcal_event_id'] = event_id
    return jsonify(booking), 201


@app.put('/api/bookings/<int:booking_id>')
@login_required
def edit_booking(booking_id):
    b = get_booking_by_id(booking_id)
    if not b:
        return jsonify({'error': 'Booking not found.'}), 404
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    checkin = (data.get('checkin') or '').strip()
    notes = (data.get('notes') or '').strip()
    email = (data.get('email') or '').strip()
    phone = (data.get('phone') or '').strip()

    if not name:
        return jsonify({'error': 'Guest name is required.'}), 400
    if not checkin:
        return jsonify({'error': 'Check-in date is required.'}), 400
    if not is_friday(checkin):
        return jsonify({'error': 'Check-in must be a Friday.'}), 400
    if has_conflict(checkin, exclude_id=booking_id):
        return jsonify({'error': 'Week overlaps an existing booking.'}), 409

    updated = update_booking(booking_id, name, checkin, notes, email, phone)
    if b.get('gcal_event_id'):
        gcal.update_event(b['gcal_event_id'], name, checkin, notes)
    elif gcal.get_service():
        event_id = gcal.create_event(name, checkin, notes)
        if event_id:
            set_gcal_event_id(booking_id, event_id)
            updated['gcal_event_id'] = event_id
    return jsonify(updated)


@app.delete('/api/bookings/<int:booking_id>')
@login_required
def remove_booking(booking_id):
    b = get_booking_by_id(booking_id)
    if not b:
        return jsonify({'error': 'Booking not found.'}), 404
    if b.get('gcal_event_id'):
        gcal.delete_event(b['gcal_event_id'])
    if delete_booking(booking_id) == 0:
        return jsonify({'error': 'Booking not found.'}), 404
    return jsonify({'ok': True})


@app.put('/api/bookings/<int:booking_id>/family')
@login_required
def link_family(booking_id):
    if not get_booking_by_id(booking_id):
        return jsonify({'error': 'Booking not found.'}), 404
    data = request.get_json(force=True)
    family_id = data.get('family_id') or None
    set_booking_family(booking_id, family_id)
    return jsonify({'ok': True})


@app.post('/api/bookings/import')
@login_required
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
            all_rows = list(ws.iter_rows(min_row=1, values_only=True))

            # Find the header row: first row that contains "name" in any column
            header_row_idx = 0
            for i, row in enumerate(all_rows[:6]):
                if any(str(v).strip().lower() == 'name' for v in row if v is not None):
                    header_row_idx = i
                    break

            header_row = all_rows[header_row_idx]
            first_data = all_rows[header_row_idx + 1] if header_row_idx + 1 < len(all_rows) else []

            # Build headers; unnamed date columns become 'checkin' then 'checkout'
            headers = []
            date_cols_seen = 0
            for j, val in enumerate(header_row):
                h = str(val).strip().lower() if val else ''
                if not h:
                    data_val = first_data[j] if j < len(first_data) else None
                    if isinstance(data_val, datetime):
                        h = 'checkin' if date_cols_seen == 0 else 'checkout'
                        date_cols_seen += 1
                    else:
                        h = f'_col{j}'
                headers.append(h)

            for row in all_rows[header_row_idx + 1:]:
                if not any(v for v in row if v is not None):
                    continue  # skip empty rows
                row_dict = {}
                for j, val in enumerate(row):
                    if j >= len(headers):
                        continue
                    if isinstance(val, datetime):
                        row_dict[headers[j]] = val.strftime('%Y-%m-%d')
                    elif val is not None:
                        row_dict[headers[j]] = str(val).strip()
                    else:
                        row_dict[headers[j]] = ''
                rows.append(row_dict)
        else:
            return jsonify({'error': 'Unsupported file type. Upload a .csv or .xlsx file.'}), 400
    except Exception as e:
        return jsonify({'error': f'Could not parse file: {e}'}), 400

    created, updated, skipped = [], [], []

    for i, row in enumerate(rows, start=2):
        # Normalise column names (accept "guest name", "Guest Name", etc.)
        norm = {k.strip().lower().replace(' ', '_'): v for k, v in row.items()}
        name = norm.get('name') or norm.get('guest_name') or norm.get('guest') or ''
        checkin = norm.get('checkin') or norm.get('check_in') or norm.get('check-in') or norm.get('start_date') or norm.get('start') or norm.get('date') or ''
        email = norm.get('email') or norm.get('guest_email') or ''
        notes = norm.get('notes') or norm.get('note') or norm.get('event_date') or norm.get('event date') or ''

        name = name.strip()
        checkin = checkin.strip()
        email = email.strip()
        notes = notes.strip()

        if not name or not checkin:
            skipped.append({'row': i, 'reason': 'Missing name or check-in date'})
            continue

        # Normalise date formats
        # DD-Mon-YY → YYYY-MM-DD (e.g. "6-Feb-26")
        if '-' in checkin and not checkin[0:4].isdigit():
            for fmt in ('%d-%b-%y', '%d-%b-%Y'):
                try:
                    checkin = datetime.strptime(checkin, fmt).strftime('%Y-%m-%d')
                    break
                except ValueError:
                    pass

        # MM/DD/YYYY → YYYY-MM-DD
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
            if existing.get('gcal_event_id'):
                gcal.update_event(existing['gcal_event_id'], name, checkin, notes)
            else:
                event_id = gcal.create_event(name, checkin, notes)
                if event_id:
                    set_gcal_event_id(existing['id'], event_id)
            updated.append({'id': existing['id'], 'name': name, 'checkin': checkin})
        else:
            if has_conflict(checkin):
                skipped.append({'row': i, 'reason': f'Week starting {checkin} overlaps an existing booking'})
                continue
            b = add_booking(name, checkin, notes, email)
            event_id = gcal.create_event(name, checkin, notes)
            if event_id:
                set_gcal_event_id(b['id'], event_id)
            created.append({'id': b['id'], 'name': name, 'checkin': checkin})

    return jsonify({'created': created, 'updated': updated, 'skipped': skipped})


@app.post('/api/bookings/<int:booking_id>/email')
@login_required
def send_manual_email(booking_id):
    b = get_booking_by_id(booking_id)
    if not b:
        return jsonify({'error': 'Booking not found.'}), 404
    effective_emails = [b['email']] if b.get('email') else get_family_emails_for_booking_name(b['name'])
    if not effective_emails:
        return jsonify({'error': 'No email address on this booking.'}), 400

    checkin = parse_date(b['checkin'])
    checkout = checkin + timedelta(days=7)
    respond_url = f"{BASE_URL}/respond/{b['token']}"

    try:
        for email in effective_emails:
            send_reminder(
                email, b['name'],
                checkin.strftime('%B %d, %Y'),
                checkout.strftime('%B %d, %Y'),
                respond_url,
            )
        mark_reminder_sent(b['id'])
        return jsonify({'ok': True, 'emails': effective_emails})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.post('/api/bookings/<int:booking_id>/sms')
@login_required
def send_manual_sms(booking_id):
    if not sms_sender.is_configured():
        return jsonify({'error': 'Twilio credentials not configured.'}), 503
    b = get_booking_by_id(booking_id)
    if not b:
        return jsonify({'error': 'Booking not found.'}), 404
    effective_phone = b.get('phone') or ''
    if not effective_phone and b.get('family_id'):
        fam = get_family_by_id(b['family_id'])
        if fam:
            effective_phone = fam.get('contact1_phone') or fam.get('contact2_phone') or ''
    if not effective_phone:
        return jsonify({'error': 'No phone number on this booking.'}), 400

    checkin = parse_date(b['checkin'])
    checkout = checkin + timedelta(days=7)
    respond_url = f"{BASE_URL}/respond/{b['token']}"

    try:
        sms_sender.send_reminder_sms(
            effective_phone, b['name'],
            checkin.strftime('%B %d, %Y'),
            checkout.strftime('%B %d, %Y'),
            respond_url,
        )
        mark_sms_sent(b['id'])
        return jsonify({'ok': True, 'phone': effective_phone})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.get('/respond/<token>')
def respond_page(token):
    b = get_booking_by_token(token)
    if not b:
        return render_template('respond.html', not_found=True)
    checkin = parse_date(b['checkin'])
    checkout = checkin + timedelta(days=7)
    attending = request.args.get('attending')

    if attending == 'no':
        guest_name = b['name']
        guest_email = b.get('email') or ''
        guest_phone = b.get('phone') or ''
        if b.get('gcal_event_id'):
            gcal.delete_event(b['gcal_event_id'])
        delete_booking(b['id'])
        if guest_email:
            try:
                send_cancellation_notice(
                    guest_email, guest_name,
                    checkin.strftime('%B %d, %Y'),
                    checkout.strftime('%B %d, %Y'),
                )
            except Exception:
                pass
        broadcast_availability(checkin, checkout, guest_name=guest_name, guest_phone=guest_phone)
        return render_template('respond.html', not_found=False, cancelled=True, booking_name=guest_name, submitted=False)

    if attending == 'yes':
        save_guest_response(token, 'Confirmed')
        mark_reminder_sent(b['id'])
        return render_template(
            'respond.html',
            booking=b,
            checkin_fmt=checkin.strftime('%B %d, %Y'),
            checkout_fmt=checkout.strftime('%B %d, %Y'),
            submitted=True,
            not_found=False,
            cancelled=False,
        )

    submitted = request.args.get('submitted') == '1'
    return render_template(
        'respond.html',
        booking=b,
        checkin_fmt=checkin.strftime('%B %d, %Y'),
        checkout_fmt=checkout.strftime('%B %d, %Y'),
        submitted=submitted,
        not_found=False,
        cancelled=False,
    )


@app.post('/respond/<token>')
def submit_response(token):
    b = get_booking_by_token(token)
    if not b:
        return render_template('respond.html', not_found=True)

    attending = request.form.get('attending', 'yes')
    message = (request.form.get('message') or '').strip()

    if attending == 'no':
        guest_name = b['name']
        checkin = parse_date(b['checkin'])
        checkout = checkin + timedelta(days=7)
        guest_email = b.get('email') or ''
        guest_phone = b.get('phone') or ''
        if b.get('gcal_event_id'):
            gcal.delete_event(b['gcal_event_id'])
        delete_booking(b['id'])
        if guest_email:
            try:
                send_cancellation_notice(
                    guest_email, guest_name,
                    checkin.strftime('%B %d, %Y'),
                    checkout.strftime('%B %d, %Y'),
                )
            except Exception:
                pass
        broadcast_availability(checkin, checkout, guest_name=guest_name, guest_phone=guest_phone)
        return render_template('respond.html', not_found=False, cancelled=True, booking_name=guest_name, submitted=False)

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

@app.get('/info')
@login_required
def info_page():
    return render_template('info.html')


@app.get('/photos')
@login_required
def photos_page():
    return render_template('photos.html')


@app.get('/api/photos')
@login_required
def list_photos():
    return jsonify(get_all_photos())


@app.post('/api/photos')
@login_required
def upload_photo():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded.'}), 400
    f = request.files['file']
    if not f.filename or not allowed_file(f.filename):
        return jsonify({'error': 'Invalid file type. Use JPG, PNG, GIF, or WEBP.'}), 400

    import uuid as _uuid
    ext = f.filename.rsplit('.', 1)[1].lower()
    filename = f'{_uuid.uuid4().hex}.{ext}'
    f.save(os.path.join(UPLOAD_FOLDER, filename))

    caption = (request.form.get('caption') or '').strip()
    uploader = (request.form.get('uploader') or '').strip()
    uploaded_at = now_central().strftime('%Y-%m-%d %H:%M')
    photo = add_photo(filename, caption, uploader, uploaded_at)

    VIDEO_EXTS = {'mp4', 'mov', 'avi', 'webm'}
    media_type = 'video' if ext in VIDEO_EXTS else 'photo'
    emails = [f['contact1_email'] for f in get_all_families() if f.get('contact1_email')]
    if emails:
        try:
            send_photo_notification(emails, uploader or 'Someone', caption, media_type, uploaded_at)
        except Exception as e:
            print(f"[photo] Email notification failed: {e}")

    return jsonify(photo), 201


@app.get('/uploads/<filename>')
@login_required
def serve_upload(filename):
    from flask import send_from_directory
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.delete('/api/photos/<int:photo_id>')
@login_required
def remove_photo(photo_id):
    filename, rowcount = delete_photo(photo_id)
    if rowcount == 0:
        return jsonify({'error': 'Photo not found.'}), 404
    if filename:
        try:
            os.remove(os.path.join(UPLOAD_FOLDER, filename))
        except OSError:
            pass
    return jsonify({'ok': True})


@app.get('/comments')
@login_required
def comments_page():
    return render_template('comments.html')


@app.get('/api/comments')
@login_required
def list_comments():
    return jsonify(get_all_comments())


@app.post('/api/comments')
@login_required
def create_comment():
    data = request.get_json(force=True)
    author = (data.get('author') or '').strip()
    comment = (data.get('comment') or '').strip()
    follow_up = (data.get('follow_up') or '').strip()
    if not author:
        return jsonify({'error': 'Name is required.'}), 400
    if not comment:
        return jsonify({'error': 'Comment is required.'}), 400
    created_at = now_central().strftime('%Y-%m-%d %H:%M')
    c = add_comment(author, comment, follow_up, created_at)

    emails = [f['contact1_email'] for f in get_all_families() if f.get('contact1_email')]
    if emails:
        try:
            send_comment_notification(emails, author, comment, follow_up, created_at)
        except Exception as e:
            print(f"[comment] Email notification failed: {e}")

    return jsonify(c), 201


@app.delete('/api/comments/<int:comment_id>')
@login_required
def remove_comment(comment_id):
    if delete_comment(comment_id) == 0:
        return jsonify({'error': 'Comment not found.'}), 404
    return jsonify({'ok': True})


@app.get('/families')
@login_required
def families_page():
    return render_template('families.html')


@app.get('/api/families')
@login_required
def list_families():
    return jsonify(get_all_families())


@app.post('/api/families')
@login_required
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
@login_required
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
@login_required
def remove_family(family_id):
    if delete_family(family_id) == 0:
        return jsonify({'error': 'Family not found.'}), 404
    return jsonify({'ok': True})


@app.post('/api/families/<int:family_id>/password')
@login_required
def set_password(family_id):
    if not get_family_by_id(family_id):
        return jsonify({'error': 'Family not found.'}), 404
    data = request.get_json(force=True)
    password = (data.get('password') or '').strip()
    if not password:
        return jsonify({'error': 'Password is required.'}), 400
    set_family_password(family_id, generate_password_hash(password))
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# Google Calendar
# ---------------------------------------------------------------------------

@app.get('/gcal/connect')
@login_required
def gcal_connect():
    from flask import session
    redirect_uri = f"{BASE_URL}/gcal/callback"
    result = gcal.get_auth_url(redirect_uri)
    if not result:
        return ('credentials.json not found. Download OAuth credentials from Google Cloud Console '
                'and save as credentials.json in the app directory.'), 400
    auth_url, state = result
    session['gcal_state'] = state
    return redirect(auth_url)


@app.get('/gcal/callback')
def gcal_callback():
    from flask import session
    state = session.get('gcal_state')
    code = request.args.get('code')
    redirect_uri = f"{BASE_URL}/gcal/callback"
    try:
        gcal.exchange_code(code, state, redirect_uri)
    except Exception as e:
        return f'Google Calendar auth failed: {e}', 400
    return redirect('/?gcal=connected')


@app.get('/api/gcal/status')
@login_required
def gcal_status():
    return jsonify({
        'configured': gcal.is_configured(),
        'authenticated': gcal.get_service() is not None,
    })


@app.post('/api/gcal/sync')
@login_required
def gcal_sync_all():
    if not gcal.get_service():
        return jsonify({'error': 'Google Calendar not connected.'}), 400
    synced, failed = [], []
    for b in get_all_bookings():
        if not b.get('gcal_event_id'):
            event_id = gcal.create_event(b['name'], b['checkin'], b.get('notes', ''))
            if event_id:
                set_gcal_event_id(b['id'], event_id)
                synced.append(b['id'])
            else:
                failed.append(b['id'])
    return jsonify({'synced': len(synced), 'failed': len(failed)})


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


def check_and_send_reminders():
    today = now_central().date()
    target = today + timedelta(days=14)
    for b in get_unreminded_bookings_with_email():
        try:
            checkin = parse_date(b['checkin'])
            if checkin != target:
                continue
            checkout = checkin + timedelta(days=7)
            respond_url = f"{BASE_URL}/respond/{b['token']}"
            checkin_fmt = checkin.strftime('%B %d, %Y')
            checkout_fmt = checkout.strftime('%B %d, %Y')

            if not b.get('reminder_sent'):
                emails = [b['email']] if b.get('email') else get_family_emails_for_booking_name(b['name'])
                for email in emails:
                    try:
                        send_reminder(email, b['name'], checkin_fmt, checkout_fmt, respond_url)
                    except Exception as e:
                        print(f"[reminder] Email failed for booking {b['id']} to {email}: {e}")
                if emails:
                    mark_reminder_sent(b['id'])

        except Exception as e:
            print(f"[reminder] Failed for booking {b['id']}: {e}")


MAID_NAME = 'Mandy Giles'
MAID_PHONE = '251-243-8068'


def check_and_send_sunday_maid_text():
    today = now_central().date()
    b = get_active_booking_for_date(today.strftime('%Y-%m-%d'))
    if not b:
        return
    email = b.get('effective_email', '')
    if not email:
        print(f"[maid-notice] No email for booking {b['id']} — skipping")
        return
    checkout = parse_date(b['checkin']) + timedelta(days=7)
    checkout_fmt = checkout.strftime('%B %d, %Y')
    try:
        send_maid_notice(email, b['name'], checkout_fmt, MAID_NAME, MAID_PHONE)
        mark_maid_text_sent(b['id'])
        print(f"[maid-notice] Sent to {b['name']} at {email}")
    except Exception as e:
        print(f"[maid-notice] Failed for booking {b['id']}: {e}")


def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler(timezone=CENTRAL)
    scheduler.add_job(check_and_send_reminders, 'cron', hour=8, minute=0)
    scheduler.add_job(check_and_send_sunday_maid_text, 'cron', day_of_week='sun', hour=8, minute=0)
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
