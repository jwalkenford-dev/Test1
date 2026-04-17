import os
from datetime import datetime, timedelta

SCOPES = ['https://www.googleapis.com/auth/calendar.events']
CREDENTIALS_FILE = os.getenv('GCAL_CREDENTIALS_FILE', 'credentials.json')
TOKEN_FILE = os.getenv('GCAL_TOKEN_FILE', 'token.json')
CALENDAR_ID = os.getenv('GCAL_CALENDAR_ID', 'primary')


def is_configured():
    return os.path.exists(CREDENTIALS_FILE)


def get_service():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        return None

    if not os.path.exists(TOKEN_FILE):
        return None

    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    except Exception:
        return None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(TOKEN_FILE, 'w') as f:
                    f.write(creds.to_json())
            except Exception:
                return None
        else:
            return None

    try:
        return build('calendar', 'v3', credentials=creds)
    except Exception:
        return None


def get_auth_url(redirect_uri):
    if not is_configured():
        return None
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE, scopes=SCOPES, redirect_uri=redirect_uri
    )
    auth_url, state = flow.authorization_url(access_type='offline', prompt='consent')
    return auth_url, state


def exchange_code(code, state, redirect_uri):
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE, scopes=SCOPES, state=state, redirect_uri=redirect_uri
    )
    flow.fetch_token(code=code)
    with open(TOKEN_FILE, 'w') as f:
        f.write(flow.credentials.to_json())


def _make_body(name, checkin_str, notes=''):
    checkin = datetime.strptime(checkin_str, '%Y-%m-%d').date()
    checkout = checkin + timedelta(days=7)
    return {
        'summary': f'{name} — Dixie Summerhouse',
        'description': notes or '',
        'start': {'date': checkin.isoformat()},
        'end': {'date': checkout.isoformat()},
    }


def create_event(name, checkin_str, notes=''):
    service = get_service()
    if not service:
        return None
    try:
        from googleapiclient.errors import HttpError
        result = service.events().insert(
            calendarId=CALENDAR_ID, body=_make_body(name, checkin_str, notes)
        ).execute()
        return result.get('id')
    except Exception:
        return None


def update_event(event_id, name, checkin_str, notes=''):
    service = get_service()
    if not service or not event_id:
        return False
    try:
        from googleapiclient.errors import HttpError
        service.events().update(
            calendarId=CALENDAR_ID,
            eventId=event_id,
            body=_make_body(name, checkin_str, notes),
        ).execute()
        return True
    except Exception:
        return False


def delete_event(event_id):
    service = get_service()
    if not service or not event_id:
        return False
    try:
        service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
        return True
    except Exception:
        return False
