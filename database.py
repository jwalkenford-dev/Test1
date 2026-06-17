import sqlite3
import uuid
import os

DB_PATH = os.getenv('DB_PATH', 'bookings.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS bookings (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                name           TEXT    NOT NULL,
                checkin        TEXT    NOT NULL,
                notes          TEXT    DEFAULT '',
                email          TEXT    DEFAULT '',
                token          TEXT    UNIQUE,
                reminder_sent  INTEGER DEFAULT 0,
                guest_response TEXT    DEFAULT '',
                gcal_event_id  TEXT    DEFAULT ''
            )
        ''')
        # Migrations
        for migration in [
            "ALTER TABLE bookings ADD COLUMN gcal_event_id TEXT DEFAULT ''",
            "ALTER TABLE bookings ADD COLUMN family_id INTEGER DEFAULT NULL",
            "ALTER TABLE bookings ADD COLUMN phone TEXT DEFAULT ''",
            "ALTER TABLE bookings ADD COLUMN sms_reminder_sent INTEGER DEFAULT 0",
            "ALTER TABLE bookings ADD COLUMN maid_text_sent INTEGER DEFAULT 0",
        ]:
            try:
                conn.execute(migration)
                conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists
        conn.execute('''
            CREATE TABLE IF NOT EXISTS families (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                family_name     TEXT    NOT NULL,
                contact1_name   TEXT    DEFAULT '',
                contact1_email  TEXT    DEFAULT '',
                contact1_phone  TEXT    DEFAULT '',
                contact2_name   TEXT    DEFAULT '',
                contact2_email  TEXT    DEFAULT '',
                contact2_phone  TEXT    DEFAULT ''
            )
        ''')
        try:
            conn.execute("ALTER TABLE families ADD COLUMN password_hash TEXT DEFAULT ''")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
        conn.execute('''
            CREATE TABLE IF NOT EXISTS comments (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                author        TEXT    NOT NULL,
                comment       TEXT    NOT NULL,
                follow_up     TEXT    DEFAULT '',
                created_at    TEXT    NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS photos (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                filename      TEXT    NOT NULL,
                caption       TEXT    DEFAULT '',
                uploader      TEXT    DEFAULT '',
                uploaded_at   TEXT    NOT NULL
            )
        ''')
        conn.commit()


def row_to_dict(row):
    return dict(row) if row else None


def get_all_bookings():
    with get_conn() as conn:
        rows = conn.execute('''
            SELECT b.*,
                   f.family_name  AS linked_family_name,
                   COALESCE(NULLIF(f.contact1_email,''), f.contact2_email, '') AS family_email
            FROM bookings b
            LEFT JOIN families f ON b.family_id = f.id
            ORDER BY b.checkin
        ''').fetchall()
    return [row_to_dict(r) for r in rows]


def get_booking_by_id(booking_id):
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM bookings WHERE id = ?', (booking_id,)).fetchone()
    return row_to_dict(row)


def get_booking_by_token(token):
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM bookings WHERE token = ?', (token,)).fetchone()
    return row_to_dict(row)


def add_booking(name, checkin, notes, email, family_id=None, phone=None):
    token = str(uuid.uuid4())
    with get_conn() as conn:
        cur = conn.execute(
            'INSERT INTO bookings (name, checkin, notes, email, token, family_id, phone) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (name, checkin, notes or '', email or '', token, family_id, phone or '')
        )
        conn.commit()
        row = conn.execute('SELECT * FROM bookings WHERE id = ?', (cur.lastrowid,)).fetchone()
    return row_to_dict(row)


def set_booking_family(booking_id, family_id):
    with get_conn() as conn:
        conn.execute('UPDATE bookings SET family_id = ? WHERE id = ?', (family_id, booking_id))
        conn.commit()


def get_booking_by_checkin(checkin):
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM bookings WHERE checkin = ?', (checkin,)).fetchone()
    return row_to_dict(row)


def update_booking(booking_id, name, checkin, notes, email, phone=None):
    with get_conn() as conn:
        conn.execute(
            'UPDATE bookings SET name=?, checkin=?, notes=?, email=?, phone=? WHERE id=?',
            (name, checkin, notes or '', email or '', phone or '', booking_id)
        )
        conn.commit()
        row = conn.execute('SELECT * FROM bookings WHERE id = ?', (booking_id,)).fetchone()
    return row_to_dict(row)


def delete_booking(booking_id):
    with get_conn() as conn:
        cur = conn.execute('DELETE FROM bookings WHERE id = ?', (booking_id,))
        conn.commit()
    return cur.rowcount


def get_unreminded_bookings_with_email():
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM bookings WHERE reminder_sent = 0').fetchall()
    return [row_to_dict(r) for r in rows]


def get_family_emails_for_booking_name(booking_name):
    """Return all contact1 emails for families matching the booking name.
    Handles slash-separated names (e.g. 'Klebba/Dearing') and suffix matches
    (e.g. 'Prieto' matches 'Lockfield Prieto').
    """
    parts = [p.strip() for p in booking_name.split('/')]
    seen = set()
    result = []
    with get_conn() as conn:
        for part in parts:
            rows = conn.execute(
                '''SELECT contact1_email FROM families
                   WHERE contact1_email != '' AND contact1_email IS NOT NULL
                   AND (family_name = ? OR family_name LIKE ? OR family_name LIKE ?)''',
                (part, f'% {part}', f'{part} %')
            ).fetchall()
            for r in rows:
                if r[0] not in seen:
                    seen.add(r[0])
                    result.append(r[0])
    return result


def set_gcal_event_id(booking_id, event_id):
    with get_conn() as conn:
        conn.execute('UPDATE bookings SET gcal_event_id = ? WHERE id = ?', (event_id or '', booking_id))
        conn.commit()


def mark_reminder_sent(booking_id):
    with get_conn() as conn:
        conn.execute('UPDATE bookings SET reminder_sent = 1 WHERE id = ?', (booking_id,))
        conn.commit()


def mark_sms_sent(booking_id):
    with get_conn() as conn:
        conn.execute('UPDATE bookings SET sms_reminder_sent = 1 WHERE id = ?', (booking_id,))
        conn.commit()


def mark_maid_text_sent(booking_id):
    with get_conn() as conn:
        conn.execute('UPDATE bookings SET maid_text_sent = 1 WHERE id = ?', (booking_id,))
        conn.commit()


def get_active_booking_for_date(date_str):
    """Return the booking whose week covers the given date (checkin <= date < checkin+7)."""
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM bookings WHERE maid_text_sent = 0'
        ).fetchall()
    for row in rows:
        d = row_to_dict(row)
        checkin = d['checkin']
        # Build the 7-day window for this booking
        from datetime import datetime, timedelta
        start = datetime.strptime(checkin, '%Y-%m-%d').date()
        end = start + timedelta(days=7)
        target = datetime.strptime(date_str, '%Y-%m-%d').date()
        if start <= target < end:
            return d
    return None


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------

def get_all_families():
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM families ORDER BY family_name COLLATE NOCASE').fetchall()
    return [row_to_dict(r) for r in rows]


def get_family_by_id(family_id):
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM families WHERE id = ?', (family_id,)).fetchone()
    return row_to_dict(row)


def add_family(family_name, c1_name, c1_email, c1_phone, c2_name, c2_email, c2_phone):
    with get_conn() as conn:
        cur = conn.execute(
            '''INSERT INTO families
               (family_name, contact1_name, contact1_email, contact1_phone,
                contact2_name, contact2_email, contact2_phone)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (family_name, c1_name or '', c1_email or '', c1_phone or '',
             c2_name or '', c2_email or '', c2_phone or '')
        )
        conn.commit()
        row = conn.execute('SELECT * FROM families WHERE id = ?', (cur.lastrowid,)).fetchone()
    return row_to_dict(row)


def update_family(family_id, family_name, c1_name, c1_email, c1_phone, c2_name, c2_email, c2_phone):
    with get_conn() as conn:
        conn.execute(
            '''UPDATE families SET
               family_name=?, contact1_name=?, contact1_email=?, contact1_phone=?,
               contact2_name=?, contact2_email=?, contact2_phone=?
               WHERE id=?''',
            (family_name, c1_name or '', c1_email or '', c1_phone or '',
             c2_name or '', c2_email or '', c2_phone or '', family_id)
        )
        conn.commit()
        row = conn.execute('SELECT * FROM families WHERE id = ?', (family_id,)).fetchone()
    return row_to_dict(row)


def delete_family(family_id):
    with get_conn() as conn:
        cur = conn.execute('DELETE FROM families WHERE id = ?', (family_id,))
        conn.commit()
    return cur.rowcount


def set_family_password(family_id, password_hash):
    with get_conn() as conn:
        conn.execute('UPDATE families SET password_hash = ? WHERE id = ?', (password_hash, family_id))
        conn.commit()


def get_family_by_email(email):
    """Return the first family where contact1_email or contact2_email matches (case-insensitive)."""
    with get_conn() as conn:
        row = conn.execute(
            'SELECT * FROM families WHERE LOWER(contact1_email) = LOWER(?) OR LOWER(contact2_email) = LOWER(?)',
            (email, email)
        ).fetchone()
    return row_to_dict(row)


def get_all_photos():
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM photos ORDER BY uploaded_at DESC').fetchall()
    return [row_to_dict(r) for r in rows]


def add_photo(filename, caption, uploader, uploaded_at):
    with get_conn() as conn:
        cur = conn.execute(
            'INSERT INTO photos (filename, caption, uploader, uploaded_at) VALUES (?, ?, ?, ?)',
            (filename, caption or '', uploader or '', uploaded_at)
        )
        conn.commit()
        row = conn.execute('SELECT * FROM photos WHERE id = ?', (cur.lastrowid,)).fetchone()
    return row_to_dict(row)


def delete_photo(photo_id):
    with get_conn() as conn:
        row = conn.execute('SELECT filename FROM photos WHERE id = ?', (photo_id,)).fetchone()
        filename = row['filename'] if row else None
        cur = conn.execute('DELETE FROM photos WHERE id = ?', (photo_id,))
        conn.commit()
    return filename, cur.rowcount


def get_all_comments():
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM comments ORDER BY created_at DESC').fetchall()
    return [row_to_dict(r) for r in rows]


def add_comment(author, comment, follow_up, created_at):
    with get_conn() as conn:
        cur = conn.execute(
            'INSERT INTO comments (author, comment, follow_up, created_at) VALUES (?, ?, ?, ?)',
            (author, comment, follow_up or '', created_at)
        )
        conn.commit()
        row = conn.execute('SELECT * FROM comments WHERE id = ?', (cur.lastrowid,)).fetchone()
    return row_to_dict(row)


def delete_comment(comment_id):
    with get_conn() as conn:
        cur = conn.execute('DELETE FROM comments WHERE id = ?', (comment_id,))
        conn.commit()
    return cur.rowcount


def save_guest_response(token, response_text):
    with get_conn() as conn:
        cur = conn.execute(
            'UPDATE bookings SET guest_response = ? WHERE token = ?',
            (response_text, token)
        )
        conn.commit()
    return cur.rowcount > 0
