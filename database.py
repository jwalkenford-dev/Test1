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
                guest_response TEXT    DEFAULT ''
            )
        ''')
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
        conn.commit()


def row_to_dict(row):
    return dict(row) if row else None


def get_all_bookings():
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM bookings ORDER BY checkin').fetchall()
    return [row_to_dict(r) for r in rows]


def get_booking_by_id(booking_id):
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM bookings WHERE id = ?', (booking_id,)).fetchone()
    return row_to_dict(row)


def get_booking_by_token(token):
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM bookings WHERE token = ?', (token,)).fetchone()
    return row_to_dict(row)


def add_booking(name, checkin, notes, email):
    token = str(uuid.uuid4())
    with get_conn() as conn:
        cur = conn.execute(
            'INSERT INTO bookings (name, checkin, notes, email, token) VALUES (?, ?, ?, ?, ?)',
            (name, checkin, notes or '', email or '', token)
        )
        conn.commit()
        row = conn.execute('SELECT * FROM bookings WHERE id = ?', (cur.lastrowid,)).fetchone()
    return row_to_dict(row)


def get_booking_by_checkin(checkin):
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM bookings WHERE checkin = ?', (checkin,)).fetchone()
    return row_to_dict(row)


def update_booking(booking_id, name, checkin, notes, email):
    with get_conn() as conn:
        conn.execute(
            'UPDATE bookings SET name=?, checkin=?, notes=?, email=? WHERE id=?',
            (name, checkin, notes or '', email or '', booking_id)
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
        rows = conn.execute(
            "SELECT * FROM bookings WHERE reminder_sent = 0 AND email != ''"
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def mark_reminder_sent(booking_id):
    with get_conn() as conn:
        conn.execute('UPDATE bookings SET reminder_sent = 1 WHERE id = ?', (booking_id,))
        conn.commit()


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


def save_guest_response(token, response_text):
    with get_conn() as conn:
        cur = conn.execute(
            'UPDATE bookings SET guest_response = ? WHERE token = ?',
            (response_text, token)
        )
        conn.commit()
    return cur.rowcount > 0
