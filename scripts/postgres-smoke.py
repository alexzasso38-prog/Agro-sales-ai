#!/usr/bin/env python3
"""Smoke PostgreSQL locale. Crea un produttore test; non contatta provider.

Dalla radice:
AGRO_TEST_POSTGRES_URL=postgresql+psycopg://... .venv/bin/python scripts/postgres-smoke.py
Usare un database di test locale dedicato. Le tabelle e i dati di verifica persistono.
"""
import os
from pathlib import Path
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app

url = os.getenv('AGRO_TEST_POSTGRES_URL', '')
parsed = urlsplit(url)
if parsed.scheme != 'postgresql+psycopg' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
    sys.exit('Impostare AGRO_TEST_POSTGRES_URL su un database PostgreSQL locale di test.')
settings = Settings(demo_mode=False, database_url=url, jwt_secret=secrets.token_urlsafe(48), allow_external_integrations=False)
app = create_app(settings)
with TestClient(app) as client:
    assert client.get('/health').status_code == 200
    assert not client.get('/api/meta').json()['demo_mode']
    assert client.post('/api/auth/login', json={'email': 'demo@agrosales.test', 'password': 'DemoAgro2026!'}).status_code == 401
    suffix = uuid.uuid4().hex[:12]
    auth = client.post('/api/auth/register', json={'email': f'pg-{suffix}@agro.test', 'password': 'PostgresTest2026!', 'name': 'Verifica PG', 'company_name': 'Produttore PG fittizio'})
    assert auth.status_code == 201, auth.text
    headers = {'Authorization': f"Bearer {auth.json()['access_token']}"}
    profile = client.get('/api/profile', headers=headers).json()
    profile['catalog'] = [{'id': 'pg-oil', 'name': 'Olio demo PG', 'unit': 'litro', 'price': 12, 'category': 'olio', 'description': 'Fittizio'}]
    profile['service_areas'] = ['Bologna']
    assert client.put('/api/profile', headers=headers, json=profile).status_code == 200
    lead = client.post('/api/leads', headers=headers, json={'company_name': 'Ristorante fittizio PG', 'email': f'lead-{suffix}@horeca.test', 'city': 'Bologna', 'business_type': 'ristorante', 'menu_text': 'Olio extravergine', 'source': 'Prova PostgreSQL fittizia'})
    assert lead.status_code == 201, lead.text
    lead_id = lead.json()['id']
    assert client.post(f'/api/leads/{lead_id}/qualify', headers=headers).status_code == 200
    draft = client.post(f'/api/leads/{lead_id}/draft', headers=headers, json={'kind': 'outreach'})
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()['id']
    assert client.post(f'/api/drafts/{draft_id}/send', headers=headers).status_code == 409
    assert client.post(f'/api/drafts/{draft_id}/approve', headers=headers).status_code == 200
    assert client.post(f'/api/drafts/{draft_id}/send', headers=headers).status_code == 503
    assert client.get('/api/dashboard', headers=headers).json()['metrics']['sent_real'] == 0
    start = datetime.now(timezone.utc) + timedelta(days=5)
    booking = {'lead_id': lead_id, 'title': 'Meeting non confermato', 'start_at': start.isoformat(), 'end_at': (start + timedelta(minutes=30)).isoformat()}
    assert client.post('/api/appointments', headers=headers, json=booking).status_code == 503
    appointments = client.get('/api/appointments', headers=headers).json()
    assert len(appointments) == 1 and appointments[0]['status'] == 'failed' and not appointments[0]['provider_event_id']
    assert client.post('/api/appointments', headers=headers, json=booking).status_code == 503
    assert len(client.get('/api/appointments', headers=headers).json()) == 1
    audit = client.get('/api/audit', headers=headers).json()
    assert any(item['action'] == 'invio.errore' for item in audit)
    assert any(item['action'] == 'calendario.errore' for item in audit)
    print('PASS PostgreSQL: autenticazione, catalogo, lead, qualificazione, approvazione, invio disabilitato, calendario fallito senza conferma, retry e audit.')
