"""Integration checks for the persistent sales workflow, using only local mocks.

Every test gets an isolated SQLite database from conftest. Moving job due dates
replaces wall-clock waits while still executing the real worker/orchestrator.
"""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading

import pytest
from sqlalchemy import select, update

from app import integrations
from app.db import Draft


def campaign_body(client, **changes):
    profile = client.get('/api/profile').json()
    body = {
        'name': 'Ristoranti premium Milano — test fittizio',
        'objective': 'Valutare clienti HORECA fittizi senza contatti esterni.',
        'target': 'Ristoranti',
        'city': 'Milano',
        'lead_count': 6,
        'product_ids': [item['id'] for item in profile['catalog']],
        'minimum_score': 70,
        'outreach_mode': 'APPROVAL_REQUIRED',
        'followup_enabled': True,
        'followup_days': [0, 3, 7, 14],
        'handoff_threshold': 85,
        'autonomy_level': 'LOW',
        'provider': 'mock',
        'demo_day_seconds': 10,
        'max_emails': 30,
        'max_followups': 3,
        'rate_limit_per_minute': 30,
    }
    return {**body, **changes}


def create_campaign(client, **changes):
    response = client.post('/api/campaigns', json=campaign_body(client, **changes))
    assert response.status_code == 201, response.text
    return response.json()


def campaign_records(client, campaign_id):
    from app.automation_models import CampaignLead
    with client.app.state.sessions() as session:
        rows = session.scalars(select(CampaignLead).where(CampaignLead.campaign_id == campaign_id)).all()
        return [{col.name: getattr(item, col.name) for col in item.__table__.columns} for item in rows]


def campaign_leads(client, campaign_id):
    ids = {row['lead_id'] for row in campaign_records(client, campaign_id)}
    return [lead for lead in client.get('/api/leads').json() if lead['id'] in ids]


def campaign_drafts(client, campaign_id):
    ids = {lead['id'] for lead in campaign_leads(client, campaign_id)}
    return [draft for draft in client.get('/api/drafts').json() if draft['lead_id'] in ids]


def due_all(client, campaign_id):
    from app.automation_models import AgentTask
    with client.app.state.sessions() as session:
        session.execute(update(AgentTask).where(AgentTask.campaign_id == campaign_id).values(due_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()))
        session.commit()


def drive(client, campaign_id, cycles=20):
    for _ in range(cycles):
        due_all(client, campaign_id)
        response = client.post('/api/worker/run')
        assert response.status_code == 200, response.text


def start_and_drive(client, **changes):
    campaign = create_campaign(client, **changes)
    response = client.post(f'/api/campaigns/{campaign["id"]}/start')
    assert response.status_code == 200, response.text
    drive(client, campaign['id'])
    return campaign


def send_approved(client, draft):
    url = f'/api/drafts/{draft["id"]}'
    assert client.post(url + '/approve').status_code == 200
    response = client.post(url + '/send')
    assert response.status_code == 200, response.text
    assert response.json()['simulated'] is True
    return response.json()


def test_campaign_creation_and_validation(client):
    campaign = create_campaign(client)
    assert campaign['name'].startswith('Ristoranti premium Milano')
    assert campaign['outreach_mode'] == 'APPROVAL_REQUIRED'
    assert campaign['autonomy_level'] == 'LOW'
    assert any(row['id'] == campaign['id'] for row in client.get('/api/campaigns').json())
    assert client.post('/api/campaigns', json=campaign_body(client, product_ids=['missing-product'])).status_code == 422
    assert client.post('/api/campaigns', json=campaign_body(client, followup_days=[0, 7, 3])).status_code == 422
    assert client.post('/api/campaigns', json=campaign_body(client, lead_count=0)).status_code == 422
    assert client.get(f'/api/campaigns/{campaign["id"]}', headers={'Authorization': ''}).status_code == 401


def test_campaign_tenant_boundary(client):
    campaign = start_and_drive(client, lead_count=2)
    tasks = client.get(f'/api/campaigns/{campaign["id"]}/tasks').json()
    response = client.post('/api/auth/register', json={'name': 'Secondo produttore', 'email': 'campaign-tenant@producer.test', 'password': 'StrongCampaign2026!', 'company_name': 'Seconda azienda fittizia'})
    assert response.status_code == 201
    client.headers['Authorization'] = f'Bearer {response.json()["access_token"]}'
    assert client.get('/api/campaigns').json() == []
    for suffix in ['', '/events', '/agents', '/tasks']:
        assert client.get(f'/api/campaigns/{campaign["id"]}{suffix}').status_code == 404
    for action in ['start', 'pause', 'resume', 'stop']:
        assert client.post(f'/api/campaigns/{campaign["id"]}/{action}').status_code == 404
    if tasks:
        assert client.post(f'/api/agent-tasks/{tasks[0]["id"]}/retry').status_code == 404


def test_persistent_orchestrator_leads_threshold_and_approval(client, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('La demo non può contattare provider esterni')
    monkeypatch.setattr(integrations, '_request_json', forbidden)
    campaign = start_and_drive(client)
    leads = campaign_leads(client, campaign['id'])
    assert len(leads) == campaign['lead_count']
    assert all(lead['demo'] and lead['source'] and lead['source_date'] for lead in leads)
    assert all(not lead['email'] or lead['email'].endswith('.test') for lead in leads)
    assert all(lead['score'] is not None for lead in leads)
    assert any(lead['score'] < campaign['minimum_score'] for lead in leads)
    assert any(lead['score'] >= campaign['minimum_score'] for lead in leads)
    eligible = {lead['id'] for lead in leads if lead['score'] >= campaign['minimum_score']}
    drafts = campaign_drafts(client, campaign['id'])
    assert {draft['lead_id'] for draft in drafts} == eligible
    assert all(draft['status'] == 'pending' for draft in drafts)
    assert client.post(f'/api/drafts/{drafts[0]["id"]}/send').status_code == 409
    tasks = client.get(f'/api/campaigns/{campaign["id"]}/tasks').json()
    events = client.get(f'/api/campaigns/{campaign["id"]}/events').json()
    assert tasks and events
    from app.automation_models import AgentRun
    with client.app.state.sessions() as session:
        assert session.scalar(select(AgentRun.id).where(AgentRun.campaign_id == campaign['id'])) is not None
    for lead in leads:
        qualification = lead['qualification']
        assert qualification['verified_facts'] and qualification['missing_data']
        assert isinstance(qualification['hypotheses'], list)
    before = len(drafts)
    drive(client, campaign['id'], cycles=3)
    assert len(campaign_drafts(client, campaign['id'])) == before
    metrics = client.get('/api/dashboard').json()['metrics']
    assert metrics['sent_real'] == 0 and metrics['sent_demo'] == 0


def test_campaign_pause_resume_stop_and_agent_pause(client):
    campaign = create_campaign(client)
    url = f'/api/campaigns/{campaign["id"]}'
    assert client.post(url + '/start').status_code == 200
    assert client.post(url + '/pause').status_code == 200
    drive(client, campaign['id'], cycles=2)
    assert campaign_leads(client, campaign['id']) == []
    assert client.post(url + '/resume').status_code == 200
    assert client.post(url + '/agents/lead_generation/pause').status_code == 200
    drive(client, campaign['id'], cycles=2)
    assert campaign_leads(client, campaign['id']) == []
    assert client.post(url + '/agents/lead_generation/resume').status_code == 200
    drive(client, campaign['id'])
    assert campaign_leads(client, campaign['id'])
    assert client.post(url + '/stop').status_code == 200
    before = len(campaign_drafts(client, campaign['id']))
    drive(client, campaign['id'], cycles=2)
    assert len(campaign_drafts(client, campaign['id'])) == before
    assert client.post(url + '/resume').status_code == 409


def test_approval_send_followup_response_handoff_shared_pipeline(client):
    campaign = start_and_drive(client, lead_count=1, minimum_score=0)
    url = f'/api/campaigns/{campaign["id"]}'
    draft = campaign_drafts(client, campaign['id'])[0]
    sent = send_approved(client, draft)
    retry = client.post(f'/api/drafts/{draft["id"]}/send')
    assert retry.status_code == 200
    assert retry.json()['sent_at'] == sent['sent_at']
    detail = client.get(f'/api/leads/{draft["lead_id"]}').json()
    assert len([message for message in detail['conversations'] if message.get('draft_id') == draft['id']]) == 1
    assert detail['stage'] == 'contacted'
    jobs = client.get(url + '/tasks').json()
    assert any(row['agent'] == 'follow_up' and row['status'] == 'QUEUED' for row in jobs)
    assert client.post(url + '/accelerate', json={'seconds': 40}).status_code == 200
    drive(client, campaign['id'], cycles=3)
    followups = [item for item in campaign_drafts(client, campaign['id']) if item['id'] != draft['id']]
    assert followups and all(item['status'] == 'pending' for item in followups)
    response = client.post(url + f'/leads/{draft["lead_id"]}/simulate-response', json={'preset': 'interested', 'body': 'Sono interessato a 20 kg entro venerdì. Budget dichiarato 250 euro.'})
    assert response.status_code == 200, response.text
    drive(client, campaign['id'], cycles=5)
    detail = client.get(f'/api/leads/{draft["lead_id"]}').json()
    assert detail['stop_reason'] == 'reply'
    assert detail['stage'] in {'interested', 'handoff'}
    assert any(message['direction'] == 'inbound' and message['simulated'] for message in detail['conversations'])
    assert all(item['status'] in {'cancelled', 'sent'} for item in detail['drafts'] if item['kind'] != 'reply')
    handoffs = client.get('/api/human-closer').json()
    assert any(item['lead_id'] == draft['lead_id'] for item in handoffs)
    from app.automation_models import ConversationEvent
    with client.app.state.sessions() as session:
        assert session.scalar(select(ConversationEvent.id).where(ConversationEvent.lead_id == draft['lead_id'])) is not None
    events = client.get(url + '/events').json()
    assert any(item['agent'] == 'sales' for item in events)
    assert any(item['agent'] == 'crm' for item in events)
    metrics = client.get('/api/dashboard').json()['metrics']
    assert metrics['sent_real'] == 0 and metrics['sent_demo'] == 1


@pytest.mark.parametrize('preset', ['not_interested', 'unsubscribe'])
def test_campaign_terminal_response_stops_sequence(client, preset):
    campaign = start_and_drive(client, lead_count=1, minimum_score=0)
    draft = campaign_drafts(client, campaign['id'])[0]
    send_approved(client, draft)
    body = {'preset': preset} if preset == 'not_interested' else {'body': 'Disiscrivimi e non inviatemi altre email.'}
    response = client.post(f'/api/campaigns/{campaign["id"]}/leads/{draft["lead_id"]}/simulate-response', json=body)
    assert response.status_code == 200, response.text
    drive(client, campaign['id'], cycles=5)
    detail = client.get(f'/api/leads/{draft["lead_id"]}').json()
    assert detail['stage'] in {'lost', 'do_not_contact'}
    assert detail['stop_reason'] in {'rejection', 'unsubscribe'}
    assert client.post(f'/api/leads/{draft["lead_id"]}/draft', json={}).status_code == 409
    assert len([item for item in detail['conversations'] if item['direction'] == 'outbound']) == 1
    assert not any(item['kind'] == 'reply' and item['status'] == 'pending' for item in detail['drafts'])


def test_legacy_manual_reply_uses_sales_orchestrator(client):
    campaign = start_and_drive(client, lead_count=1, minimum_score=0)
    lead = campaign_leads(client, campaign['id'])[0]
    result = client.post(f'/api/leads/{lead["id"]}/reply', json={'body': 'Vorrei un appuntamento per valutare i formaggi. Potete applicare uno sconto del 30%?'} )
    assert result.status_code == 200
    drive(client, campaign['id'], cycles=5)
    from app.automation_models import ConversationEvent
    with client.app.state.sessions() as session:
        assert session.scalar(select(ConversationEvent.id).where(ConversationEvent.lead_id == lead['id'])) is not None
    assert any(item['lead_id'] == lead['id'] for item in client.get('/api/human-closer').json())
    replies = [item for item in campaign_drafts(client, campaign['id']) if item['kind'] == 'reply']
    assert replies and all(item['status'] == 'pending' for item in replies)
    assert all('30%' not in item['body'] for item in replies)


def test_demo_voice_transcript_reuses_conversation_flow(client):
    campaign = start_and_drive(client, lead_count=1, minimum_score=0)
    lead = campaign_leads(client, campaign['id'])[0]
    response = client.post(f'/api/campaigns/{campaign["id"]}/leads/{lead["id"]}/simulate-voice', json={'transcript': 'Trascrizione fittizia: sono interessato ai formaggi, vorrei una degustazione e un appuntamento.'})
    assert response.status_code == 200, response.text
    drive(client, campaign['id'], cycles=5)
    detail = client.get(f'/api/leads/{lead["id"]}').json()
    assert any(message['direction'] == 'inbound' and message['simulated'] and 'fittizia' in message['body'] for message in detail['conversations'])
    assert any(item['lead_id'] == lead['id'] for item in client.get('/api/human-closer').json())
    assert client.get('/api/meta').json()['integrations']['voice']['status'] in {'not_connected', 'demo'}


@pytest.mark.parametrize('autonomy,outreach,automatic', [('LOW', 'APPROVAL_REQUIRED', False), ('MEDIUM', 'APPROVAL_REQUIRED', False), ('HIGH', 'AUTO_SEND', True)])
def test_demo_autonomy_first_outreach(client, autonomy, outreach, automatic):
    campaign = start_and_drive(client, lead_count=1, minimum_score=0, autonomy_level=autonomy, outreach_mode=outreach, authorize_auto_send=True, followup_enabled=False)
    draft = campaign_drafts(client, campaign['id'])[0]
    assert draft['status'] == ('sent' if automatic else 'pending')
    assert draft['simulated'] is automatic
    assert client.get('/api/dashboard').json()['metrics']['sent_real'] == 0


def test_auto_send_campaign_email_cap_and_rate_limit(client):
    campaign = start_and_drive(client, lead_count=3, minimum_score=0, autonomy_level='HIGH', outreach_mode='AUTO_SEND', authorize_auto_send=True, max_emails=1, rate_limit_per_minute=1, followup_enabled=False)
    drafts = campaign_drafts(client, campaign['id'])
    assert len([row for row in drafts if row['status'] == 'sent']) == 1
    assert client.get('/api/dashboard').json()['metrics']['sent_real'] == 0
    drive(client, campaign['id'], cycles=3)
    assert len([row for row in campaign_drafts(client, campaign['id']) if row['status'] == 'sent']) == 1


def test_campaign_rate_limit_expires_without_losing_approval(client):
    campaign = start_and_drive(client, lead_count=2, minimum_score=0, rate_limit_per_minute=1, max_emails=10, followup_enabled=False)
    first, second = campaign_drafts(client, campaign['id'])
    send_approved(client, first)
    url = f'/api/drafts/{second["id"]}'
    assert client.post(url + '/approve').status_code == 200
    limited = client.post(url + '/send')
    assert limited.status_code == 409
    assert 'frequenza' in limited.json()['detail'].lower()
    assert next(item for item in client.get('/api/drafts').json() if item['id'] == second['id'])['status'] == 'approved'
    with client.app.state.sessions() as session:
        session.execute(update(Draft).where(Draft.id == first['id']).values(sent_at=(datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()))
        session.commit()
    assert client.post(url + '/send').status_code == 200


def test_campaign_rate_limit_counts_an_inflight_send_with_old_approval(client, monkeypatch):
    campaign = start_and_drive(client, lead_count=2, minimum_score=0, rate_limit_per_minute=1, max_emails=10, followup_enabled=False)
    first, second = campaign_drafts(client, campaign['id'])
    for draft in [first, second]:
        assert client.post(f'/api/drafts/{draft["id"]}/approve').status_code == 200
    with client.app.state.sessions() as session:
        session.execute(update(Draft).where(Draft.id == first['id']).values(approved_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat()))
        session.commit()
    entered, release = threading.Event(), threading.Event()
    calls = []
    def fake_send(settings, recipient, subject, body, key):
        calls.append(key)
        entered.set()
        assert release.wait(5)
        return {'provider_message_id': 'demo-rate-flight', 'simulated': True}
    monkeypatch.setattr(integrations, 'send_email', fake_send)
    with ThreadPoolExecutor(max_workers=2) as pool:
        sending = pool.submit(client.post, f'/api/drafts/{first["id"]}/send')
        assert entered.wait(5)
        try:
            assert client.post(f'/api/drafts/{second["id"]}/send').status_code == 409
        finally:
            release.set()
        assert sending.result().status_code == 200
    assert len(calls) == 1


def test_expired_claim_recovery_is_persistent_and_does_not_duplicate_discovery(client):
    from app.automation_models import AgentTask
    campaign = create_campaign(client, lead_count=1, minimum_score=0)
    assert client.post(f'/api/campaigns/{campaign["id"]}/start').status_code == 200
    task = client.get(f'/api/campaigns/{campaign["id"]}/tasks').json()[0]
    with client.app.state.sessions() as session:
        session.execute(update(AgentTask).where(AgentTask.id == task['id']).values(status='RUNNING', claim_token='expired-worker-test', lease_until=(datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()))
        session.commit()
    response = client.post('/api/worker/run')
    assert response.status_code == 200
    assert response.json()['automation']['recovered'] == 1
    drive(client, campaign['id'], cycles=4)
    assert len(campaign_leads(client, campaign['id'])) == 1
    assert len(campaign_drafts(client, campaign['id'])) == 1
    assert client.post('/api/worker/run').json()['automation']['recovered'] == 0


def test_automatic_retry_keeps_generated_payload_and_provider_idempotency(client, monkeypatch):
    from app import automation
    generator = automation.providers.outreach
    generated, attempted = [], []
    def changing_generator(*args, **kwargs):
        result = generator(*args, **kwargs)
        generated.append(result['body'])
        return {**result, 'body': result['body'] + f'\nVersione fittizia {len(generated)}.'}
    def ambiguous_send(settings, recipient, subject, body, key):
        attempted.append((key, recipient, subject, body))
        if len(attempted) == 1:
            raise integrations.IntegrationError('Timeout demo ambiguo', 'provider_timeout', True)
        return {'provider_message_id': 'demo-automatic-retry', 'simulated': True}
    monkeypatch.setattr(automation.providers, 'outreach', changing_generator)
    monkeypatch.setattr(integrations, 'send_email', ambiguous_send)
    campaign = start_and_drive(client, lead_count=1, minimum_score=0, autonomy_level='HIGH', outreach_mode='AUTO_SEND', authorize_auto_send=True, followup_enabled=False)
    assert len(attempted) == 1 and len(generated) == 1
    failed = next(item for item in client.get(f'/api/campaigns/{campaign["id"]}/tasks').json() if item['status'] == 'FAILED')
    assert client.post(f'/api/agent-tasks/{failed["id"]}/retry').status_code == 200
    drive(client, campaign['id'], cycles=4)
    assert len(generated) == 1, 'Una risposta provider ambigua deve conservare il testo già tentato'
    assert len(attempted) == 2 and attempted[0] == attempted[1]
    drafts = campaign_drafts(client, campaign['id'])
    assert len(drafts) == 1 and drafts[0]['status'] == 'sent'
    detail = client.get(f'/api/leads/{drafts[0]["lead_id"]}').json()
    assert len([item for item in detail['conversations'] if item['direction'] == 'outbound']) == 1


def test_delayed_crm_job_cannot_override_human_won_result(client):
    campaign = start_and_drive(client, lead_count=1, minimum_score=0, handoff_threshold=0)
    url = f'/api/campaigns/{campaign["id"]}'
    lead = campaign_leads(client, campaign['id'])[0]
    assert client.post(url + '/agents/crm/pause').status_code == 200
    assert client.post(url + f'/leads/{lead["id"]}/simulate-response', json={'preset': 'interested'}).status_code == 200
    drive(client, campaign['id'], cycles=4)
    assert any(item['agent'] == 'crm' and item['status'] == 'QUEUED' for item in client.get(url + '/tasks').json())
    handoff = next(item for item in client.get('/api/human-closer').json() if item['lead_id'] == lead['id'])
    assert client.post(f'/api/human-closer/{handoff["id"]}/won', json={}).status_code == 200
    assert client.post(url + '/agents/crm/resume').status_code == 200
    drive(client, campaign['id'], cycles=4)
    assert client.get(f'/api/leads/{lead["id"]}').json()['stage'] == 'won'


def test_unsubscribe_during_automatic_send_records_confirmed_message_without_followups(client, monkeypatch):
    campaign = create_campaign(client, lead_count=1, minimum_score=0, autonomy_level='HIGH', outreach_mode='AUTO_SEND', authorize_auto_send=True)
    url = f'/api/campaigns/{campaign["id"]}'
    assert client.post(url + '/agents/outreach/pause').status_code == 200
    assert client.post(url + '/start').status_code == 200
    drive(client, campaign['id'], cycles=3)
    lead = campaign_leads(client, campaign['id'])[0]
    entered, release = threading.Event(), threading.Event()
    def waiting_send(settings, recipient, subject, body, key):
        entered.set()
        assert release.wait(8)
        return {'provider_message_id': 'demo-inflight-unsubscribe', 'simulated': True}
    monkeypatch.setattr(integrations, 'send_email', waiting_send)
    assert client.post(url + '/agents/outreach/resume').status_code == 200
    due_all(client, campaign['id'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        sending = pool.submit(client.post, '/api/worker/run')
        assert entered.wait(5)
        try:
            stopped = pool.submit(client.post, url + f'/leads/{lead["id"]}/simulate-response', json={'preset': 'unsubscribe'})
            assert stopped.result(timeout=5).status_code == 200
        finally:
            release.set()
        assert sending.result(timeout=5).status_code == 200
    detail = client.get(f'/api/leads/{lead["id"]}').json()
    assert detail['stop_reason'] == 'unsubscribe'
    assert detail['stage'] == 'do_not_contact'
    assert len([item for item in detail['conversations'] if item['direction'] == 'outbound']) == 1
    assert any(item['status'] == 'sent' and item['simulated'] for item in detail['drafts'])
    assert not any(item['status'] in {'scheduled', 'automation_managed', 'needs_approval'} for item in detail['tasks'])


def test_failed_job_retry_preserves_identity_and_audit(client):
    from app.automation_models import Campaign, AgentTask
    campaign = create_campaign(client, lead_count=1, minimum_score=0)
    with client.app.state.sessions() as session:
        record = session.get(Campaign, campaign['id'])
        record.config = {**record.config, 'provider': 'invalid-provider-test'}
        session.commit()
    assert client.post(f'/api/campaigns/{campaign["id"]}/start').status_code == 200
    assert client.post('/api/worker/run').status_code == 200
    failed = next(item for item in client.get(f'/api/campaigns/{campaign["id"]}/tasks').json() if item['status'] == 'FAILED')
    assert failed['last_error'] and failed['attempts'] == 1
    with client.app.state.sessions() as session:
        original_key = session.get(AgentTask, failed['id']).idempotency_key
        record = session.get(Campaign, campaign['id'])
        record.config = {**record.config, 'provider': 'mock'}
        session.commit()
    response = client.post(f'/api/agent-tasks/{failed["id"]}/retry')
    assert response.status_code == 200, response.text
    assert response.json()['id'] == failed['id']
    drive(client, campaign['id'])
    assert len(campaign_leads(client, campaign['id'])) == 1
    assert len(campaign_drafts(client, campaign['id'])) == 1
    with client.app.state.sessions() as session:
        recovered = session.get(AgentTask, failed['id'])
        assert recovered.idempotency_key == original_key
        assert recovered.status == 'COMPLETED' and recovered.attempts == 2
    events = client.get(f'/api/campaigns/{campaign["id"]}/events').json()
    assert any(item['event_type'] == 'task_failed' for item in events)
    assert any(item['event_type'] == 'task_retry' for item in events)
    assert client.post(f'/api/agent-tasks/{failed["id"]}/retry').status_code == 409


def test_followup_maximum_and_medium_autonomy(client):
    campaign = start_and_drive(client, lead_count=1, minimum_score=0, autonomy_level='MEDIUM', authorize_auto_send=True, max_followups=2)
    draft = campaign_drafts(client, campaign['id'])[0]
    assert draft['status'] == 'pending'  # First contact still needs human approval.
    send_approved(client, draft)
    detail = client.get(f'/api/leads/{draft["lead_id"]}').json()
    assert len(detail['tasks']) == 2
    drive(client, campaign['id'], cycles=5)
    drafts = campaign_drafts(client, campaign['id'])
    assert len(drafts) == 3
    assert all(item['status'] == 'sent' and item['simulated'] for item in drafts)
    drive(client, campaign['id'], cycles=3)
    assert len(campaign_drafts(client, campaign['id'])) == 3


def test_meeting_calendar_failure_does_not_confirm_and_success_stops_jobs(client, monkeypatch):
    campaign = start_and_drive(client, lead_count=1, minimum_score=0)
    draft = campaign_drafts(client, campaign['id'])[0]
    send_approved(client, draft)
    start = datetime.now(timezone.utc) + timedelta(days=5)
    booking = {'lead_id': draft['lead_id'], 'title': 'Incontro fittizio campagna', 'start_at': start.isoformat(), 'end_at': (start + timedelta(minutes=30)).isoformat()}
    def failing(*args, **kwargs):
        raise integrations.IntegrationError('Calendario simulato indisponibile')
    monkeypatch.setattr(integrations, 'book_calendar', failing)
    assert client.post('/api/appointments', json=booking).status_code == 503
    assert client.get(f'/api/leads/{draft["lead_id"]}').json()['stage'] == 'contacted'
    monkeypatch.setattr(integrations, 'book_calendar', lambda *args: {'provider_event_id': 'demo-campaign-booking', 'simulated': True})
    response = client.post('/api/appointments', json=booking)
    assert response.status_code == 201 and response.json()['status'] == 'simulated'
    detail = client.get(f'/api/leads/{draft["lead_id"]}').json()
    assert detail['stage'] == 'appointment'
    assert all(item['status'] == 'cancelled' for item in detail['tasks'])
    drive(client, campaign['id'], cycles=3)
    assert len(campaign_drafts(client, campaign['id'])) == 1


@pytest.mark.parametrize('result', ['won', 'lost'])
def test_human_closer_ownership_and_outcome_update_existing_crm(client, result):
    campaign = start_and_drive(client, lead_count=1, minimum_score=0)
    lead = campaign_leads(client, campaign['id'])[0]
    assert client.post(f'/api/campaigns/{campaign["id"]}/leads/{lead["id"]}/simulate-response', json={'preset': 'meeting'}).status_code == 200
    drive(client, campaign['id'], cycles=5)
    handoff = next(item for item in client.get('/api/human-closer').json() if item['lead_id'] == lead['id'])
    response = client.post(f'/api/human-closer/{handoff["id"]}/take', json={'note': 'Verifica del commerciale fittizia'})
    assert response.status_code == 200 and response.json()['status'] == 'in_progress'
    assert response.json().get('owner_name')
    assert client.post(f'/api/human-closer/{handoff["id"]}/{result}', json={'note': 'Esito fittizio registrato in test'}).status_code == 200
    assert client.get(f'/api/leads/{lead["id"]}').json()['stage'] == result


def test_csv_campaign_provenance_missing_email_and_dedup(client):
    rows = [
        {'company_name': 'CSV Campagna Fittizia', 'city': 'Milano', 'email': 'campaign-csv@horeca.test', 'business_type': 'Ristorante', 'menu_text': 'Olio extravergine e pomodori datterini', 'source': 'CSV prova dichiarata', 'source_url': 'https://example.test/menu'},
        {'company_name': 'Duplicato CSV', 'city': 'Milano', 'email': 'campaign-csv@horeca.test', 'business_type': 'Ristorante', 'source': 'CSV duplicato'},
        {'company_name': 'CSV senza email fittizia', 'city': 'Milano', 'business_type': 'Ristorante', 'source': 'CSV senza recapito'},
    ]
    first = start_and_drive(client, provider='csv', csv_rows=rows, lead_count=3, minimum_score=0)
    leads = campaign_leads(client, first['id'])
    assert len(leads) == 2
    assert all(row['source'] and row['source_date'] for row in leads)
    missing = next(row for row in leads if row['company_name'] == 'CSV senza email fittizia')
    assert missing['email'] == ''
    second = start_and_drive(client, provider='csv', csv_rows=rows, lead_count=3, minimum_score=0)
    assert {row['id'] for row in campaign_leads(client, second['id'])} == {row['id'] for row in leads}
    assert sum(row['email'] == 'campaign-csv@horeca.test' for row in client.get('/api/leads').json()) == 1


def test_existing_sqlite_rows_survive_additive_schema_upgrade(tmp_path):
    """Start from an actual legacy schema, rather than creating new metadata."""
    from fastapi.testclient import TestClient
    from app.auth import hash_password
    from app.config import Settings
    from app.main import create_app
    path = tmp_path / 'legacy.db'
    profile = {'company_name': 'Produttore legacy', 'catalog': [], 'service_areas': [], 'followup_days': [3, 7]}
    with sqlite3.connect(path) as connection:
        connection.executescript('''
            CREATE TABLE producers (id INTEGER PRIMARY KEY, profile JSON NOT NULL);
            CREATE TABLE users (id INTEGER PRIMARY KEY, producer_id INTEGER NOT NULL,
                email VARCHAR(254) NOT NULL UNIQUE, name VARCHAR(200) NOT NULL,
                password_hash TEXT NOT NULL);
            CREATE TABLE leads (id INTEGER PRIMARY KEY, producer_id INTEGER NOT NULL,
                company_name VARCHAR(250) NOT NULL, contact_name VARCHAR(200) NOT NULL,
                email VARCHAR(254) NOT NULL, phone VARCHAR(100) NOT NULL, city VARCHAR(200) NOT NULL,
                business_type VARCHAR(100) NOT NULL, website TEXT NOT NULL, menu_text TEXT NOT NULL,
                notes TEXT NOT NULL, source TEXT NOT NULL, source_date VARCHAR(50) NOT NULL,
                stage VARCHAR(30) NOT NULL, score INTEGER, qualification JSON,
                stop_reason TEXT NOT NULL, created_at VARCHAR(50) NOT NULL, demo BOOLEAN NOT NULL,
                dedup_email VARCHAR(254), dedup_identity VARCHAR(500) NOT NULL,
                UNIQUE(producer_id,dedup_email), UNIQUE(producer_id,dedup_identity));
        ''')
        connection.execute('INSERT INTO producers VALUES (?,?)', (50, json.dumps(profile)))
        connection.execute('INSERT INTO users VALUES (?,?,?,?,?)', (50, 50, 'legacy@producer.test', 'Legacy test', hash_password('LegacyTest2026!')))
        connection.execute('INSERT INTO leads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (50, 50, 'Ristorante legacy fittizio', '', 'legacy@horeca.test', '', 'Milano', 'Ristorante', '', 'Olio EVO', 'Nota da preservare', 'Fonte legacy originale', '2026-01-02T08:00:00+00:00', 'interested', 72, json.dumps({'verified_facts': ['Fatto storico']}), '', '2026-01-02T08:00:00+00:00', True, 'legacy@horeca.test', 'ristorantelegacyfittizio|milano'))
    settings = Settings(database_url=f'sqlite:///{path}', demo_mode=True, allow_external_integrations=False)
    for _ in range(2):
        with TestClient(create_app(settings)) as restarted:
            login = restarted.post('/api/auth/login', json={'email': 'legacy@producer.test', 'password': 'LegacyTest2026!'})
            assert login.status_code == 200
            restarted.headers['Authorization'] = f'Bearer {login.json()["access_token"]}'
            lead = restarted.get('/api/leads/50').json()
            assert lead['company_name'] == 'Ristorante legacy fittizio'
            assert lead['notes'] == 'Nota da preservare'
            assert lead['score'] == 72 and lead['stage'] == 'interested'
            assert lead['source'] == 'Fonte legacy originale'
            assert lead['source_date'] == '2026-01-02T08:00:00+00:00'
            assert restarted.get('/api/profile').json()['company_name'] == 'Produttore legacy'
            assert restarted.get('/api/campaigns').json() == []


def test_campaign_jobs_and_events_survive_app_restart(client):
    from fastapi.testclient import TestClient
    from app.main import create_app
    campaign = start_and_drive(client, lead_count=2)
    url = f'/api/campaigns/{campaign["id"]}'
    original_tasks = client.get(url + '/tasks').json()
    original_events = client.get(url + '/events').json()
    original_leads = campaign_leads(client, campaign['id'])
    with TestClient(create_app(client.app.state.settings)) as restarted:
        restarted.headers['Authorization'] = client.headers['Authorization']
        assert restarted.get(url).status_code == 200
        assert {item['id'] for item in restarted.get(url + '/tasks').json()} == {item['id'] for item in original_tasks}
        assert {item['id'] for item in restarted.get(url + '/events').json()} == {item['id'] for item in original_events}
        assert {item['id'] for item in campaign_leads(restarted, campaign['id'])} == {item['id'] for item in original_leads}


def test_rejected_outreach_does_not_leave_workflow_waiting_forever(client):
    campaign = start_and_drive(client, lead_count=1, minimum_score=0, followup_enabled=False)
    draft = campaign_drafts(client, campaign['id'])[0]
    assert client.post(f'/api/drafts/{draft["id"]}/reject').status_code == 200
    drive(client, campaign['id'], cycles=2)
    tasks = client.get(f'/api/campaigns/{campaign["id"]}/tasks').json()
    assert not any(item['status'] in {'QUEUED', 'RUNNING', 'WAITING'} for item in tasks)
    assert client.post(f'/api/drafts/{draft["id"]}/send').status_code == 409
    assert client.get(f'/api/campaigns/{campaign["id"]}').json()['status'] == 'COMPLETED'
    assert client.get('/api/dashboard').json()['metrics']['sent_demo'] == 0


def test_incoming_event_retry_is_deduplicated_and_cannot_move_to_another_lead(client):
    from app.automation_models import ConversationEvent
    campaign = start_and_drive(client, lead_count=2, minimum_score=0)
    first, second = campaign_leads(client, campaign['id'])
    body = {'body': 'Siamo interessati ai prodotti, vorrei un preventivo.', 'external_event_id': 'demo-incoming-unique-event'}
    one = client.post(f'/api/leads/{first["id"]}/reply', json=body)
    two = client.post(f'/api/leads/{first["id"]}/reply', json=body)
    assert one.status_code == two.status_code == 200
    assert one.json()['message']['id'] == two.json()['message']['id']
    assert two.json()['duplicate'] is True
    assert client.post(f'/api/leads/{second["id"]}/reply', json=body).status_code == 409
    drive(client, campaign['id'], cycles=3)
    with client.app.state.sessions() as session:
        assert len(session.scalars(select(ConversationEvent).where(ConversationEvent.external_event_id == body['external_event_id'])).all()) == 1
    assert len([item for item in client.get(f'/api/leads/{first["id"]}').json()['conversations'] if item['direction'] == 'inbound']) == 1
    assert not any(item['direction'] == 'inbound' for item in client.get(f'/api/leads/{second["id"]}').json()['conversations'])
