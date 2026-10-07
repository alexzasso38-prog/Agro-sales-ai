#!/usr/bin/env python3
"""Exercise 20-lead demo automation with SQLite, or a dedicated LOCAL PostgreSQL.

By default all data is temporary. AGRO_TEST_POSTGRES_URL enables a local test
database: schema and fictitious producer data remain there for inspection.
No real AI, email, search, CRM, calendar or voice provider is contacted.
"""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from app.config import Settings
from app.main import create_app


def check(value, label):
    assert value, label
    print('PASS', label)


def exercise(url):
    settings = Settings(database_url=url, demo_mode=True, allow_external_integrations=False)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post('/api/auth/register', json={
            'email': f'automation-smoke-{uuid.uuid4().hex[:12]}@agro.test',
            'password': 'AutomationDemo2026!', 'name': 'Commerciale fittizio',
            'company_name': 'Cascina Verde · scenario di verifica DEMO',
        })
        check(response.status_code == 201, 'Produttore fittizio isolato')
        client.headers['Authorization'] = f'Bearer {response.json()["access_token"]}'
        profile = client.get('/api/profile').json()
        profile['service_areas'] = ['Milano']
        client.put('/api/profile', json=profile).raise_for_status()
        campaign = client.post('/api/campaigns/demo-scenario')
        campaign.raise_for_status()
        ident = campaign.json()['id']
        path = f'/api/campaigns/{ident}'
        client.post(path + '/start').raise_for_status()
        for _ in range(30):
            client.post('/api/worker/run').raise_for_status()
            detail = client.get(path).json()
            if len(detail['leads']) == 20 and all(item['qualification'] for item in detail['leads']):
                break
            client.post(path + '/accelerate', json={'seconds': 2}).raise_for_status()
        check(len(detail['leads']) == 20, '20 lead demo scoperti tramite job persistenti')
        check(len(detail['agents']) == 6 and bool(detail['events']) and bool(detail['tasks']), 'Sei agenti, job ed eventi nel database')
        check(any(item['workflow_stage'] == 'LOW_PRIORITY' for item in detail['leads']), 'Lead sotto soglia esclusi dall’outreach')
        candidate = next(item for item in detail['leads'] if item['score'] >= 70 and not item['stop_reason'])
        lead_id = candidate['lead_id']
        client.post('/api/worker/run').raise_for_status()
        drafts = client.get('/api/drafts').json()
        draft = next(item for item in drafts if item['lead_id'] == lead_id and item['kind'] == 'outreach')
        check(draft['status'] == 'pending', 'Bozza attende approvazione umana')
        client.post(f'/api/drafts/{draft["id"]}/approve').raise_for_status()
        sent = client.post(f'/api/drafts/{draft["id"]}/send')
        sent.raise_for_status()
        client.post(f'/api/drafts/{draft["id"]}/send').raise_for_status()
        check(sent.json()['simulated'] is True and sent.json()['status'] == 'sent', 'Invio demo approvato e idempotente')
        client.post(path + '/accelerate', json={'seconds': 40}).raise_for_status()
        client.post('/api/worker/run').raise_for_status()
        timeline = client.get(f'/api/leads/{lead_id}').json()
        check(any(item['task_id'] for item in timeline['drafts']), 'Follow-up scaduto realmente preparato dal worker')
        client.post(path + f'/leads/{lead_id}/simulate-response', json={'preset': 'interested'}).raise_for_status()
        client.post('/api/worker/run').raise_for_status()
        inbox = client.get('/api/human-closer').json()
        handoff = next(item for item in inbox if item['lead_id'] == lead_id)
        check(bool(handoff['last_reply']) and bool(handoff['extracted']), 'Risposta analizzata, CRM aggiornato e Human Closer popolato')
        client.post(f'/api/human-closer/{handoff["id"]}/take', json={'note': 'Verifica locale demo'}).raise_for_status()
        check(bool(client.get(f'/api/human-closer/{handoff["id"]}').json()['owner_name']), 'Presa in carico persistente')
        start = datetime.now(timezone.utc) + timedelta(days=40)
        booked = client.post('/api/appointments', json={'lead_id': lead_id, 'title': 'Incontro fittizio di verifica',
            'start_at': start.isoformat(), 'end_at': (start + timedelta(minutes=30)).isoformat()})
        booked.raise_for_status()
        check(booked.json()['status'] == 'simulated', 'Calendario resta simulato e ricontatti interrotti')
        client.post(path + '/accelerate', json={'seconds': 1000}).raise_for_status()
        client.post('/api/worker/run').raise_for_status()
        check(all(item['status'] == 'cancelled' for item in client.get(f'/api/leads/{lead_id}').json()['tasks']), 'Nessun follow-up dopo risposta/appuntamento')
        check(client.get('/api/dashboard').json()['metrics']['sent_real'] == 0, 'Zero invii reali')
        expected_events = len(client.get(path).json()['events'])
        token = client.headers['Authorization']
    with TestClient(create_app(settings)) as restarted:
        restarted.headers['Authorization'] = token
        detail = restarted.get(path).json()
        check(len(detail['leads']) == 20 and len(detail['events']) == expected_events, 'Campagna, lead ed eventi conservati al riavvio')


def main():
    url = os.getenv('AGRO_TEST_POSTGRES_URL')
    if url:
        parsed = make_url(url)
        if parsed.drivername != 'postgresql+psycopg' or parsed.host not in {'localhost', '127.0.0.1', '::1'}:
            raise ValueError('Usa esclusivamente un PostgreSQL locale dedicato ai test.')
        exercise(url)
    else:
        with TemporaryDirectory(prefix='agro-automation-test-') as directory:
            exercise(f'sqlite:///{Path(directory) / "demo.db"}')


if __name__ == '__main__':
    main()
