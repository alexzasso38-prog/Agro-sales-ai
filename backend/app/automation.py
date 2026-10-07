"""Durable sales orchestrator, shared by the API and the existing worker.

Every transition, task, event and claim is persisted. Providers supply data;
trusted code owns workflow, approval and permissions. The demo uses exactly the
same tables and queue as production, with explicitly simulated providers.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import uuid
from sqlalchemy import select, update, func, exists, or_
from sqlalchemy.exc import IntegrityError
from .db import Producer, User, Lead, Draft, Message, Task, Handoff, Appointment, now
from .automation_models import (Campaign, CampaignLead, AgentRun, AgentTask,
                                AgentEvent, AutomationRule, FollowUpSequence, ConversationEvent, HandoffOwnership)
from .automation_schemas import CampaignCreate
from . import services as svc
from . import integrations
from . import automation_providers as providers

AGENTS = {
    'lead_generation': 'Lead Generation Agent', 'qualification': 'Qualification Agent',
    'outreach': 'Outreach Agent', 'follow_up': 'Follow-up Agent',
    'sales': 'Sales Agent', 'crm': 'CRM Agent',
}
ACTIVE_TASKS = ['QUEUED', 'RUNNING', 'WAITING']
TERMINAL_REASONS = {'rejection', 'unsubscribe', 'hard_bounce'}


class AutomationError(RuntimeError):
    def __init__(self, message, status_code=409):
        super().__init__(message)
        self.status_code = status_code


def _data(value):
    return value.model_dump() if hasattr(value, 'model_dump') else dict(value)


def _own(session, model, tenant, ident):
    item = session.scalar(select(model).where(model.id == ident, model.producer_id == tenant))
    if item is None:
        raise AutomationError('Risorsa non trovata.', 404)
    return item


def _serialize(item):
    hidden = {'producer_id', 'idempotency_key', 'claim_token', 'booking_key'}
    return {column.name: getattr(item, column.name) for column in item.__table__.columns if column.name not in hidden}


def _profile(session, campaign):
    profile = dict(session.get(Producer, campaign.producer_id).profile)
    selected = campaign.config.get('product_ids', [])
    if selected:
        profile['catalog'] = [item for item in profile.get('catalog', []) if str(item['id']) in selected]
    return profile


def _event(session, campaign, agent, event_type, message, lead_id=None, task_id=None, details=None):
    event = AgentEvent(producer_id=campaign.producer_id, campaign_id=campaign.id, agent=agent,
                       event_type=event_type, message=message, lead_id=lead_id, task_id=task_id,
                       details=details or {})
    session.add(event)
    run = session.scalar(select(AgentRun).where(AgentRun.campaign_id == campaign.id, AgentRun.agent == agent))
    if run:
        run.last_action, run.updated_at = message, now()
    svc.audit(session, campaign.producer_id, 'automazione.' + event_type, message, lead_id)
    return event


def _enqueue(session, campaign, agent, kind, key, lead_id=None, payload=None, due_at=None):
    stable = f'campaign:{campaign.id}:{key}'
    found = session.scalar(select(AgentTask).where(AgentTask.idempotency_key == stable))
    if found:
        return found
    task = AgentTask(producer_id=campaign.producer_id, campaign_id=campaign.id, agent=agent, kind=kind,
                     lead_id=lead_id, payload=payload or {}, due_at=due_at or now(), idempotency_key=stable)
    session.add(task)
    session.flush()
    return task


def _link(session, campaign_id, lead_id):
    return session.scalar(select(CampaignLead).where(CampaignLead.campaign_id == campaign_id, CampaignLead.lead_id == lead_id))


def campaign_for_lead(session, tenant, lead_id):
    return session.scalar(select(Campaign).join(CampaignLead).where(
        Campaign.producer_id == tenant, CampaignLead.lead_id == lead_id,
        Campaign.status.in_(['RUNNING', 'PAUSED', 'COMPLETED', 'FAILED', 'STOPPED'])).order_by(Campaign.id.desc()).limit(1))


def campaign_for_draft(session, tenant, draft):
    """Match only a draft actually owned by an automation task, not other CRM drafts."""
    task = session.scalar(select(AgentTask).where(AgentTask.producer_id == tenant,
        AgentTask.lead_id == draft.lead_id, AgentTask.result['draft_id'].as_integer() == draft.id).order_by(AgentTask.id.desc()).limit(1))
    if task:
        return session.get(Campaign, task.campaign_id)
    linked = session.scalar(select(CampaignLead).where(CampaignLead.producer_id == tenant, CampaignLead.draft_id == draft.id))
    return session.get(Campaign, linked.campaign_id) if linked else None


def create_campaign(session, tenant, data, settings):
    body = CampaignCreate.model_validate(_data(data))
    config = body.model_dump()
    producer = session.get(Producer, tenant)
    available = {str(item['id']) for item in producer.profile.get('catalog', [])}
    if any(product not in available for product in body.product_ids):
        raise AutomationError('Seleziona soltanto prodotti del catalogo del produttore.', 422)
    if body.provider == 'mock' and not settings.demo_mode:
        raise AutomationError('Il provider con attività fittizie è disponibile solo nella demo.', 422)
    if not settings.demo_mode:
        if body.demo_day_seconds != 10:
            raise AutomationError('L’accelerazione temporale è disponibile soltanto nella demo.', 422)
        automatic = body.outreach_mode == 'AUTO_SEND' or body.autonomy_level != 'LOW'
        if automatic and not (body.authorize_auto_send and settings.allow_external_integrations and settings.email_provider_url and settings.email_api_key):
            raise AutomationError('Gli invii automatici reali richiedono autorizzazione esplicita e un provider email collegato.', 422)
    campaign = Campaign(producer_id=tenant, name=body.name, objective=body.objective, target=body.target,
                        city=body.city, lead_count=body.lead_count, config=config, demo=settings.demo_mode)
    session.add(campaign)
    session.flush()
    for agent in AGENTS:
        session.add(AgentRun(producer_id=tenant, campaign_id=campaign.id, agent=agent))
    for name, rule in [('score_threshold', {'minimum_score': body.minimum_score}),
                       ('communication_limits', {'max_emails': body.max_emails, 'max_followups': body.max_followups, 'rate_limit_per_minute': body.rate_limit_per_minute}),
                       ('human_handoff', {'threshold': body.handoff_threshold}),
                       ('approval', {'mode': body.outreach_mode, 'autonomy': body.autonomy_level})]:
        session.add(AutomationRule(producer_id=tenant, campaign_id=campaign.id, name=name, config=rule))
    _event(session, campaign, 'lead_generation', 'campaign_created', f'Campagna “{campaign.name}” creata; nessuna comunicazione inviata.')
    session.commit()
    return campaign_detail(session, tenant, campaign.id)


def demo_scenario(session, tenant, settings):
    if not settings.demo_mode:
        raise AutomationError('Lo scenario con dati fittizi è disponibile solo nella demo.', 403)
    producer = session.get(Producer, tenant)
    profile = dict(producer.profile)
    catalog = list(profile.get('catalog', []))
    additions = [
        {'id': 'demo-formaggi', 'name': 'Formaggi premium DEMO', 'category': 'formaggi', 'unit': 'kg', 'price': 18.0, 'description': 'Prodotto fittizio per lo scenario operativo.'},
        {'id': 'demo-salumi', 'name': 'Salumi artigianali DEMO', 'category': 'salumi', 'unit': 'kg', 'price': 24.0, 'description': 'Prodotto fittizio per lo scenario operativo.'},
    ]
    if not any('olio' in item['name'].lower() for item in catalog):
        additions.append({'id': 'demo-olio', 'name': 'Olio EVO DEMO', 'category': 'olio', 'unit': 'l', 'price': 12.0, 'description': 'Prodotto fittizio per lo scenario operativo.'})
    for item in additions:
        if not any(existing['id'] == item['id'] for existing in catalog):
            catalog.append(item)
    profile['catalog'] = catalog
    producer.profile = profile
    session.flush()
    selected = [str(item['id']) for item in catalog if any(word in item['name'].lower() for word in ['formagg', 'salum', 'olio'])]
    return create_campaign(session, tenant, CampaignCreate(name='Ristoranti premium Milano', target='Ristoranti premium',
        city='Milano', lead_count=20, product_ids=selected, minimum_score=70), settings)


def change_campaign(session, tenant, campaign_id, action):
    campaign = _own(session, Campaign, tenant, campaign_id)
    # Row write serializes start/stop with claims on both SQLite and PostgreSQL.
    session.execute(update(Producer).where(Producer.id == tenant).values(id=Producer.id))
    session.execute(update(Campaign).where(Campaign.id == campaign_id).values(id=Campaign.id))
    if action == 'start':
        if campaign.status == 'RUNNING':
            return campaign_detail(session, tenant, campaign_id)
        if campaign.status != 'DRAFT':
            raise AutomationError('Una campagna già avviata deve essere ripresa, non riavviata.')
        campaign.status, campaign.started_at = 'RUNNING', now()
        _enqueue(session, campaign, 'lead_generation', 'DISCOVER', 'discover:0', payload={'index': 0})
        _event(session, campaign, 'lead_generation', 'campaign_started', 'Lead Generation Agent avviato. Ricerca prospect HORECA…')
    elif action == 'pause':
        if campaign.status not in ['RUNNING', 'PAUSED']:
            raise AutomationError('La campagna non è in esecuzione.')
        if campaign.status != 'PAUSED':
            campaign.config = dict(campaign.config) | {'paused_at': now()}
        campaign.status = 'PAUSED'
        _event(session, campaign, 'crm', 'campaign_paused', 'Campagna in pausa: attività e comunicazioni sospese.')
    elif action == 'resume':
        if campaign.status not in ['PAUSED', 'FAILED', 'RUNNING']:
            raise AutomationError('La campagna non può essere ripresa.')
        paused_at = campaign.config.get('paused_at')
        if paused_at and campaign.status == 'PAUSED':
            elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(paused_at)
            for task in session.scalars(select(AgentTask).where(AgentTask.campaign_id == campaign_id, AgentTask.kind == 'FOLLOWUP', AgentTask.status == 'QUEUED')):
                task.due_at = (datetime.fromisoformat(task.due_at) + elapsed).isoformat()
                legacy = session.get(Task, task.payload.get('legacy_task_id'))
                if legacy:
                    legacy.due_at = task.due_at
            campaign.config = {key: value for key, value in campaign.config.items() if key != 'paused_at'}
        campaign.status, campaign.last_error = 'RUNNING', ''
        _event(session, campaign, 'crm', 'campaign_resumed', 'Campagna ripresa: il worker può continuare le attività persistenti.')
    elif action == 'stop':
        if campaign.status != 'STOPPED':
            campaign.status, campaign.finished_at = 'STOPPED', now()
            session.execute(update(AgentTask).where(AgentTask.campaign_id == campaign_id, AgentTask.status.in_(ACTIVE_TASKS)).values(status='CANCELLED', claim_token=None, lease_until=None))
            for link in session.scalars(select(CampaignLead).where(CampaignLead.campaign_id == campaign_id)):
                _cancel_sequence(session, campaign, link.lead_id, 'Campagna interrotta.')
                if link.draft_id:
                    draft = session.get(Draft, link.draft_id)
                    if draft and draft.status in ['pending', 'approved', 'failed']:
                        draft.status = 'cancelled'
            _event(session, campaign, 'crm', 'campaign_stopped', 'Campagna interrotta dall’operatore; job e bozze pendenti annullati.')
    else:
        raise AutomationError('Azione campagna non valida.', 422)
    session.commit()
    return campaign_detail(session, tenant, campaign_id)


def change_agent(session, tenant, campaign_id, agent, action):
    campaign = _own(session, Campaign, tenant, campaign_id)
    session.execute(update(Producer).where(Producer.id == tenant).values(id=Producer.id))
    run = session.scalar(select(AgentRun).where(AgentRun.campaign_id == campaign_id, AgentRun.agent == agent))
    if run is None or action not in ['pause', 'resume']:
        raise AutomationError('Agente o azione non disponibile.', 404)
    run.paused = action == 'pause'
    run.status = 'PAUSED' if run.paused else 'IDLE'
    _event(session, campaign, agent, 'agent_' + action, f'{AGENTS[agent]}: ' + ('in pausa.' if run.paused else 'ripreso.'))
    session.commit()
    return agent_status(session, tenant, campaign_id)


def retry_task(session, tenant, task_id):
    task = _own(session, AgentTask, tenant, task_id)
    session.execute(update(Producer).where(Producer.id == tenant).values(id=Producer.id))
    campaign = _own(session, Campaign, tenant, task.campaign_id)
    if task.status != 'FAILED' or campaign.status == 'STOPPED':
        raise AutomationError('È possibile riprovare solo un’attività fallita di una campagna attiva.')
    task.status, task.last_error, task.due_at = 'QUEUED', '', now()
    task.claim_token, task.lease_until = None, None
    if campaign.status == 'FAILED':
        campaign.status, campaign.last_error = 'RUNNING', ''
    _event(session, campaign, task.agent, 'task_retry', 'Retry richiesto; conservata la stessa chiave di idempotenza.', task.lead_id, task.id)
    session.commit()
    return _serialize(task)


def accelerate(session, tenant, campaign_id, data, settings):
    campaign = _own(session, Campaign, tenant, campaign_id)
    if not settings.demo_mode or not campaign.demo:
        raise AutomationError('L’accelerazione temporale è disponibile soltanto nella demo.', 403)
    seconds = float(_data(data).get('seconds', 30))
    if seconds <= 0 or seconds > 86400:
        raise AutomationError('Accelerazione non valida.', 422)
    for task in session.scalars(select(AgentTask).where(AgentTask.campaign_id == campaign.id, AgentTask.status == 'QUEUED')):
        task.due_at = (datetime.fromisoformat(task.due_at) - timedelta(seconds=seconds)).isoformat()
        if task.payload.get('legacy_task_id'):
            legacy = session.get(Task, task.payload['legacy_task_id'])
            if legacy:
                legacy.due_at = task.due_at
    _event(session, campaign, 'follow_up', 'demo_time_accelerated', f'Orologio DEMO accelerato di {seconds:g} secondi; nessun invio reale.')
    session.commit()
    return campaign_detail(session, tenant, campaign_id)


def _transition(session, campaign, link, stage, reason, agent, event=None):
    old = link.workflow_stage
    link.workflow_stage, link.current_agent, link.updated_at = stage, agent, now()
    lead = session.get(Lead, link.lead_id)
    mapping = {'DISCOVERED': 'discovered', 'QUALIFYING': 'qualifying', 'QUALIFIED': 'qualified',
               'OUTREACH_READY': 'outreach_ready', 'CONTACTED': 'contacted', 'FOLLOW_UP': 'follow_up',
               'REPLIED': 'replied', 'INTERESTED': 'interested', 'MEETING': 'appointment',
               'HANDOFF': 'handoff', 'WON': 'won', 'LOST': 'lost', 'DO_NOT_CONTACT': 'do_not_contact',
               'LOW_PRIORITY': 'low_priority'}
    if stage in mapping:
        lead.stage = mapping[stage]
    _event(session, campaign, 'crm', 'crm_transition', f'{lead.company_name}: {old} → {stage}. {reason}', lead.id,
           details={'old_state': old, 'new_state': stage, 'reason': reason, 'agent': agent,
                    'campaign': campaign.id, 'related_event': event})


def _cancel_sequence(session, campaign, lead_id, reason):
    session.execute(update(AgentTask).where(AgentTask.campaign_id == campaign.id, AgentTask.lead_id == lead_id,
        AgentTask.kind.in_(['OUTREACH', 'FOLLOWUP']), AgentTask.status.in_(ACTIVE_TASKS)).values(status='CANCELLED', claim_token=None, lease_until=None))
    sequence = session.scalar(select(FollowUpSequence).where(FollowUpSequence.campaign_id == campaign.id, FollowUpSequence.lead_id == lead_id))
    if sequence:
        sequence.status, sequence.stop_reason = 'STOPPED', reason
    session.execute(update(Task).where(Task.producer_id == campaign.producer_id, Task.lead_id == lead_id,
        Task.status.in_(['automation_managed', 'scheduled', 'processing', 'needs_approval'])).values(status='cancelled'))
    session.execute(update(Draft).where(Draft.producer_id == campaign.producer_id, Draft.lead_id == lead_id,
        Draft.kind == 'outreach', Draft.status.in_(['pending', 'approved', 'failed'])).values(status='cancelled'))


def on_contact_stopped(session, tenant, lead):
    session.execute(update(Producer).where(Producer.id == tenant).values(id=Producer.id))
    terminal_stage = {'meeting': 'MEETING', 'won': 'WON', 'lost': 'LOST', 'rejection': 'LOST'}.get(lead.stop_reason)
    if terminal_stage is None and lead.stage in ['won', 'lost']:
        terminal_stage = lead.stage.upper()
    for campaign in session.scalars(select(Campaign).join(CampaignLead).where(Campaign.producer_id == tenant, CampaignLead.lead_id == lead.id)):
        _cancel_sequence(session, campaign, lead.id, lead.stop_reason or 'Contatto sospeso.')
        if lead.stop_reason and lead.stop_reason != 'reply':
            session.execute(update(Draft).where(Draft.producer_id == tenant, Draft.lead_id == lead.id,
                Draft.status.in_(['pending', 'approved', 'failed'])).values(status='cancelled'))
            session.execute(update(AgentTask).where(AgentTask.campaign_id == campaign.id, AgentTask.lead_id == lead.id,
                AgentTask.status.in_(ACTIVE_TASKS)).values(status='CANCELLED', claim_token=None, lease_until=None))
            link = _link(session, campaign.id, lead.id)
            if link.workflow_stage not in ['WON', 'LOST']:
                _transition(session, campaign, link, terminal_stage or 'DO_NOT_CONTACT', lead.stop_reason, 'crm')


def campaign_send_guard(session, tenant, draft, settings):
    campaign = campaign_for_draft(session, tenant, draft)
    if campaign is None:
        return True
    # The producer write protects campaign-wide limits against concurrent sends,
    # including calls through the pre-existing manual send endpoint.
    session.execute(update(Producer).where(Producer.id == tenant).values(id=Producer.id))
    session.execute(update(Campaign).where(Campaign.id == campaign.id).values(id=Campaign.id))
    session.refresh(campaign)
    if campaign.status != 'RUNNING':
        raise AutomationError('Campagna in pausa o interrotta: invio sospeso.')
    agent = 'follow_up' if draft.task_id else ('sales' if draft.kind == 'reply' else 'outreach')
    run = session.scalar(select(AgentRun).where(AgentRun.campaign_id == campaign.id, AgentRun.agent == agent))
    if run and run.paused:
        raise AutomationError('Agente in pausa: comunicazione sospesa.')
    owned_drafts = select(AgentTask.result['draft_id'].as_integer()).where(AgentTask.campaign_id == campaign.id)
    relevant = [Draft.producer_id == tenant, Draft.id.in_(owned_drafts),
        or_(Draft.status.in_(['sent', 'sending']), (Draft.status == 'failed') & (Draft.error != '')), Draft.id != draft.id]
    total = session.scalar(select(func.count()).select_from(Draft).where(*relevant))
    if total >= campaign.config['max_emails']:
        raise AutomationError('Raggiunto il limite massimo di email della campagna.')
    minute = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    recent = session.scalar(select(func.count()).select_from(Draft).where(*relevant,
        or_(Draft.sent_at >= minute, Draft.status == 'sending', (Draft.status == 'failed') & (Draft.approved_at >= minute))))
    if recent >= campaign.config['rate_limit_per_minute']:
        raise AutomationError('Limite di frequenza raggiunto; attendi un minuto prima di inviare.')
    return True


def on_draft_sent(session, tenant, draft, settings):
    campaign = campaign_for_draft(session, tenant, draft)
    if campaign is None:
        return False
    link = _link(session, campaign.id, draft.lead_id)
    lead = session.get(Lead, draft.lead_id)
    # A late provider confirmation must not override a concurrent response/stop.
    if not lead.stop_reason and campaign.status == 'RUNNING':
        _transition(session, campaign, link, 'FOLLOW_UP' if draft.task_id else 'CONTACTED',
                    'Comunicazione simulata registrata.' if draft.simulated else 'Provider email ha confermato l’invio.', 'outreach')
    _event(session, campaign, 'follow_up' if draft.task_id else 'outreach', 'message_simulated' if draft.simulated else 'message_sent',
           f'{lead.company_name}: ' + ('invio DEMO/SIMULATO; nessuna email reale.' if draft.simulated else 'invio confermato dal provider.'), lead.id,
           details={'draft_id': draft.id, 'simulated': draft.simulated})
    for task in session.scalars(select(AgentTask).where(AgentTask.campaign_id == campaign.id, AgentTask.lead_id == lead.id,
        AgentTask.status == 'WAITING', AgentTask.result['draft_id'].as_integer() == draft.id)):
        task.status, task.completed_at = 'COMPLETED', now()
        run = session.scalar(select(AgentRun).where(AgentRun.campaign_id == campaign.id, AgentRun.agent == task.agent))
        if run:
            run.tasks_completed += 1
            run.status, run.current_task = 'IDLE', ''
    if draft.task_id:
        legacy = session.get(Task, draft.task_id)
        if legacy:
            legacy.status = 'completed'
    elif draft.kind == 'outreach' and not lead.stop_reason and campaign.config['followup_enabled']:
        sequence = session.scalar(select(FollowUpSequence).where(FollowUpSequence.campaign_id == campaign.id, FollowUpSequence.lead_id == lead.id))
        if sequence is None:
            sequence = FollowUpSequence(producer_id=tenant, campaign_id=campaign.id, lead_id=lead.id,
                config={'days': campaign.config['followup_days'], 'day_seconds': campaign.config['demo_day_seconds'] if settings.demo_mode else 86400})
            session.add(sequence)
            start = datetime.now(timezone.utc)
            seconds = campaign.config['demo_day_seconds'] if settings.demo_mode else 86400
            # Keep the original CRM task table usable, reserving a disjoint step
            # range so legacy sequences are never deleted or overwritten.
            for number, day in enumerate(campaign.config['followup_days'][1:campaign.config['max_followups'] + 1], 1):
                due = (start + timedelta(seconds=day * seconds)).isoformat()
                legacy = Task(producer_id=tenant, lead_id=lead.id, step=campaign.id * 100 + number,
                              kind='followup', due_at=due, status='automation_managed')
                session.add(legacy)
                session.flush()
                _enqueue(session, campaign, 'follow_up', 'FOLLOWUP', f'followup:{lead.id}:{number}', lead.id,
                         {'number': number, 'legacy_task_id': legacy.id}, due)
            _event(session, campaign, 'follow_up', 'followups_scheduled', f'{lead.company_name}: sequenza follow-up programmata nel worker persistente.', lead.id)
    session.flush()
    _refresh_campaign(session, campaign)
    return True


def on_booking(session, tenant, lead, appointment, settings=None):
    if appointment.status not in ['simulated', 'confirmed']:
        return
    for campaign in session.scalars(select(Campaign).join(CampaignLead).where(Campaign.producer_id == tenant, CampaignLead.lead_id == lead.id)):
        _cancel_sequence(session, campaign, lead.id, 'Appuntamento prenotato con successo.')
        link = _link(session, campaign.id, lead.id)
        if not lead.stop_reason or lead.stop_reason in ['reply', 'meeting']:
            if link.workflow_stage not in ['DO_NOT_CONTACT', 'WON', 'LOST']:
                _transition(session, campaign, link, 'MEETING', 'Prenotazione riuscita: demo simulata.' if appointment.simulated else 'Provider calendario ha confermato la prenotazione.', 'crm')


def ingest_response(session, tenant, lead, body, event='reply', subject='', settings=None, channel='email', external_event_id=None, campaign_id=None):
    # Serialize concurrent provider retries before checking their external id.
    session.execute(update(Producer).where(Producer.id == tenant).values(id=Producer.id))
    campaign = _own(session, Campaign, tenant, campaign_id) if campaign_id else campaign_for_lead(session, tenant, lead.id)
    if campaign is None:
        raise AutomationError('Il lead non appartiene a una campagna.', 404)
    if external_event_id:
        existing = session.scalar(select(ConversationEvent).where(ConversationEvent.producer_id == tenant, ConversationEvent.external_event_id == external_event_id))
        if existing:
            if existing.lead_id != lead.id:
                raise AutomationError('Identificativo evento già utilizzato per un altro contatto.')
            message = session.get(Message, existing.message_id)
            return {'message': _serialize(message), 'classification': message.classification, 'event': _serialize(existing), 'draft': None, 'duplicate': True}
    # Intake never depends on an AI provider. Persist the message and interrupt
    # sequences immediately; the durable SALES job owns optional AI analysis.
    local_settings = {'demo_mode': settings.demo_mode, 'allow_external_integrations': False}
    classification = providers.analyze_response(local_settings, body, event, _profile(session, campaign))
    terminal = classification['classification'] in ['NOT_INTERESTED', 'UNSUBSCRIBE', 'HARD_BOUNCE']
    reason = {'NOT_INTERESTED': 'rejection', 'UNSUBSCRIBE': 'unsubscribe', 'HARD_BOUNCE': 'hard_bounce'}.get(classification['classification'], 'reply')
    # Preserve any earlier terminal/manual stop. A new positive response never
    # silently reactivates an address that has opted out.
    if not lead.stop_reason or lead.stop_reason == 'reply' or terminal:
        lead.stop_reason = reason
    on_contact_stopped(session, tenant, lead)
    message = Message(producer_id=tenant, lead_id=lead.id, direction='inbound', subject=subject,
                      body=body, classification=classification['classification'].lower(), simulated=bool(settings.demo_mode))
    session.add(message)
    session.flush()
    conversation = ConversationEvent(producer_id=tenant, campaign_id=campaign.id, lead_id=lead.id,
        message_id=message.id, channel=channel, body=body, event_type=event,
        external_event_id=external_event_id, simulated=bool(settings.demo_mode))
    session.add(conversation)
    session.flush()
    if campaign.status == 'COMPLETED':
        campaign.status, campaign.finished_at = 'RUNNING', None
    if campaign.status != 'STOPPED':
        _enqueue(session, campaign, 'sales', 'SALES', f'conversation:{conversation.id}', lead.id,
                 {'conversation_id': conversation.id})
    _event(session, campaign, 'sales', 'response_received', f'{lead.company_name}: ' + ('trascrizione DEMO ricevuta' if channel == 'voice' else 'risposta ricevuta') + '; follow-up interrotti, analisi Sales Agent accodata.', lead.id)
    link = _link(session, campaign.id, lead.id)
    if link.workflow_stage not in ['WON', 'LOST']:
        if terminal or lead.stop_reason != 'reply':
            _transition(session, campaign, link, 'LOST' if reason == 'rejection' else 'DO_NOT_CONTACT', lead.stop_reason, 'sales')
        else:
            _transition(session, campaign, link, 'REPLIED', 'Risposta ricevuta; nessun interesse ancora confermato dal commerciale.', 'sales')
    session.commit()
    return {'message': _serialize(message), **classification, 'event': _serialize(conversation), 'draft': None, 'analysis_status': 'QUEUED'}


def on_reply(session, tenant, lead, message, classification, settings):
    """Compatibility hook for authenticated provider ingestion of existing messages."""
    campaign = campaign_for_lead(session, tenant, lead.id)
    if campaign is None:
        return False
    existing = session.scalar(select(ConversationEvent).where(ConversationEvent.message_id == message.id))
    if existing is None:
        existing = ConversationEvent(producer_id=tenant, campaign_id=campaign.id, lead_id=lead.id,
            message_id=message.id, body=message.body, simulated=message.simulated)
        session.add(existing)
        session.flush()
    _cancel_sequence(session, campaign, lead.id, lead.stop_reason or 'reply')
    _enqueue(session, campaign, 'sales', 'SALES', f'conversation:{existing.id}', lead.id, {'conversation_id': existing.id})
    return True


def simulate_response(session, tenant, campaign_id, lead_id, data, settings):
    campaign = _own(session, Campaign, tenant, campaign_id)
    if not settings.demo_mode or not campaign.demo:
        raise AutomationError('Le risposte simulate sono disponibili soltanto nella demo.', 403)
    lead = _own(session, Lead, tenant, lead_id)
    if _link(session, campaign_id, lead_id) is None:
        raise AutomationError('Lead non presente nella campagna.', 404)
    data = _data(data)
    simulated = providers.DemoResponseSimulator().simulate(lead, data.get('preset', 'interested'), _profile(session, campaign))
    body = data.get('body') or simulated['body']
    return ingest_response(session, tenant, lead, body, data.get('event', 'reply'), data.get('subject', 'Risposta DEMO'), settings, campaign_id=campaign.id)


def simulate_voice(session, tenant, campaign_id, lead_id, data, settings):
    campaign = _own(session, Campaign, tenant, campaign_id)
    if not settings.demo_mode or not campaign.demo:
        raise AutomationError('Le chiamate simulate sono disponibili soltanto nella demo.', 403)
    lead = _own(session, Lead, tenant, lead_id)
    if _link(session, campaign_id, lead_id) is None:
        raise AutomationError('Lead non presente nella campagna.', 404)
    data = _data(data)
    try:
        simulated = providers.DemoVoiceProvider().simulate(lead, _profile(session, campaign), data.get('preset', 'interested'))
    except ValueError as error:
        raise AutomationError('Scenario voce demo non disponibile.', 422) from error
    transcript = data.get('transcript') or simulated['summary'] + '\n' + '\n'.join(
        f'{item["speaker"]}: {item["text"]}' for item in simulated['transcript'])
    return ingest_response(session, tenant, lead, transcript, 'reply', 'Trascrizione chiamata DEMO', settings, channel='voice', campaign_id=campaign.id)


def _auto_allowed(campaign, kind, sensitive=False):
    config = campaign.config
    if config['outreach_mode'] == 'DRAFT' or sensitive or config['autonomy_level'] == 'LOW':
        return False
    if config['autonomy_level'] == 'MEDIUM':
        return kind == 'FOLLOWUP'
    return config['outreach_mode'] == 'AUTO_SEND' or kind == 'FOLLOWUP'


def email_provider(settings):
    return providers.MockEmailProvider() if settings.demo_mode else providers.ConfiguredEmailProvider(settings)


def _automatic_send(session, campaign, draft, settings, task=None):
    if draft.status == 'sent':
        return True
    # Persist exactly the generated subject/body and durable task->draft link
    # before any mutation call. A timeout or process death never regenerates AI
    # text under an already-used idempotency key.
    claim_token = task.claim_token if task else None
    session.commit()
    campaign_send_guard(session, campaign.producer_id, draft, settings)
    if task:
        owned = session.execute(update(AgentTask).where(AgentTask.id == task.id,
            AgentTask.status == 'RUNNING', AgentTask.claim_token == claim_token).values(
                lease_until=(datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat())).rowcount
        if not owned:
            session.rollback()
            raise AutomationError('Attività sospesa prima dell’invio; nessuna comunicazione eseguita.')
    lead = session.get(Lead, draft.lead_id)
    if lead.stop_reason and not (lead.stop_reason == 'reply' and draft.kind == 'reply'):
        draft.status = 'cancelled'
        return False
    if not lead.email:
        raise AutomationError('Email mancante; nessun indirizzo viene inventato.')
    # Approval is a logged authorization under the configured autonomy rule.
    if draft.status in ['pending', 'failed']:
        draft.status, draft.approved_at = 'approved', now()
        _event(session, campaign, 'outreach', 'autonomy_approved', 'Comunicazione autorizzata dalla regola di autonomia della campagna.', lead.id,
               details={'draft_id': draft.id, 'autonomy': campaign.config['autonomy_level']})
    if draft.status not in ['approved', 'sending']:
        return False
    draft.status = 'sending'
    session.flush()
    subject, body, key = draft.subject, draft.body, draft.idempotency_key
    session.commit()
    try:
        result = email_provider(settings).send(lead.email, subject, body, key)
    except integrations.IntegrationError as error:
        session.refresh(draft)
        if draft.status != 'sent':
            draft.status, draft.error = 'failed', str(error)
        session.commit()
        raise
    # Replies, pauses and stops can arrive during provider latency. They stay
    # authoritative; recording a confirmed transport result does not resume a
    # stopped workflow. Fence the ownership before applying agent effects.
    session.expire_all()
    session.execute(update(Producer).where(Producer.id == campaign.producer_id).values(id=Producer.id))
    session.execute(update(Campaign).where(Campaign.id == campaign.id).values(id=Campaign.id))
    if task:
        fenced = session.execute(update(AgentTask).where(AgentTask.id == task.id,
            AgentTask.status == 'RUNNING', AgentTask.claim_token == claim_token).values(
                lease_until=(datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat())).rowcount
        # A cancelled/stale task cannot schedule further effects. A successful
        # provider result is still recorded once, even if a reply arrived while
        # the transport operation was already in flight.
    session.refresh(draft)
    session.refresh(lead)
    session.refresh(campaign)
    draft.status, draft.sent_at, draft.error = 'sent', now(), ''
    draft.simulated, draft.provider_message_id = result['simulated'], result['provider_message_id']
    if not session.scalar(select(Message.id).where(Message.draft_id == draft.id)):
        session.add(Message(producer_id=campaign.producer_id, lead_id=lead.id, draft_id=draft.id,
            direction='outbound', subject=subject, body=body, simulated=result['simulated']))
    on_draft_sent(session, campaign.producer_id, draft, settings)
    return True


def _create_workflow_draft(session, campaign, task, lead, settings, kind='outreach', incoming=None, handoff=False):
    # Stable legacy task ownership gives an additional database uniqueness
    # constraint, so a reclaimed job cannot create a second communication.
    legacy_id = task.payload.get('legacy_task_id')
    if kind == 'reply':
        legacy_id = None
    existing_id = task.result.get('draft_id')
    draft = session.get(Draft, existing_id) if existing_id else None
    if not draft and legacy_id:
        draft = session.scalar(select(Draft).where(Draft.task_id == legacy_id))
    if draft is None:
        candidate = providers.outreach(settings, lead, _profile(session, campaign), kind=kind,
                                       followup=task.kind == 'FOLLOWUP', incoming=incoming)
        if handoff or candidate.get('handoff_required'):
            subject, body = svc.draft_text(lead, _profile(session, campaign), kind=kind, handoff=True)
        else:
            subject, body = candidate['subject'], candidate['body']
        draft = Draft(producer_id=campaign.producer_id, lead_id=lead.id, kind=kind, task_id=legacy_id,
            subject=subject, body=body, idempotency_key=hashlib.sha256(f'{task.idempotency_key}:email'.encode()).hexdigest())
        session.add(draft)
        session.flush()
        task.result = dict(task.result) | {'draft_id': draft.id, 'provider': candidate.get('provider', 'local'),
                                         'cta': candidate.get('cta', '')}
        link = _link(session, campaign.id, lead.id)
        link.draft_id = draft.id
        _event(session, campaign, task.agent, 'draft_ready', f'{lead.company_name}: personalizzazione completata, bozza pronta; in attesa di approvazione umana.', lead.id,
               task.id, {'draft_id': draft.id, 'mode': campaign.config['outreach_mode'], 'simulated_provider': settings.demo_mode})
    if legacy_id:
        session.get(Task, legacy_id).status = 'needs_approval'
    return draft


def _ensure_handoff(session, campaign, link, reason, summary=None):
    if link.handoff_id:
        return session.get(Handoff, link.handoff_id)
    lead = session.get(Lead, link.lead_id)
    handoff = svc.make_handoff(session, campaign.producer_id, lead, reason,
        summary or f'Compatibilità indicativa {lead.score or 0}/100. Verificare esigenze, quantità e tempistiche; nessun valore economico stimato.')
    session.flush()
    link.handoff_id = handoff.id
    _event(session, campaign, 'sales', 'human_handoff', f'{lead.company_name}: opportunità passata al commerciale. {reason}', lead.id,
           details={'handoff_id': handoff.id})
    return handoff


def _discover(session, campaign, task, settings):
    index = int(task.payload['index'])
    config = dict(campaign.config) | {'city': campaign.city, 'business_type': campaign.target}
    provider_name = config.get('provider', 'mock')
    if provider_name == 'mock':
        if not settings.demo_mode:
            raise AutomationError('Il provider fittizio è bloccato in produzione.')
        candidate = providers.MockLeadProvider().discover(index, config)
    elif provider_name == 'csv':
        candidate = providers.CSVImportProvider(config.get('csv_rows', [])).discover(index, config)
    elif provider_name == 'configured':
        # A single durable search result snapshot, reused by all subsequent jobs.
        if settings.demo_mode:
            raise AutomationError('La demo non contatta il provider di ricerca reale; usa Mock o CSV.')
        cached = config.get('provider_results')
        if cached is None:
            cached = integrations.search_leads(settings, campaign.target, campaign.city)
            campaign.config = dict(campaign.config) | {'provider_results': cached}
        candidate = providers.CSVImportProvider(cached).discover(index, config)
        if candidate:
            candidate['provider'] = 'configured'
    else:
        raise AutomationError('Provider lead non riconosciuto: verifica la configurazione.')
    if candidate is None:
        _event(session, campaign, 'lead_generation', 'discovery_completed', 'Provider esaurito: nessun contatto inventato per raggiungere il numero richiesto.', task_id=task.id)
        return {'discovered': 0, 'exhausted': True}
    from .schemas import LeadInput
    fields = set(LeadInput.model_fields)
    body = LeadInput.model_validate({key: candidate[key] for key in fields if key in candidate})
    data = body.model_dump()
    identity = '|'.join(re.sub(r'\W+', '', data[key].casefold()) for key in ['company_name', 'city'])
    email = data['email'] or None
    lead = session.scalar(select(Lead).where(Lead.producer_id == campaign.producer_id,
        or_(Lead.dedup_identity == identity, Lead.dedup_email == email if email else False)))
    duplicate = lead is not None
    if lead is None:
        try:
            with session.begin_nested():
                lead = Lead(producer_id=campaign.producer_id, **data, dedup_email=email, dedup_identity=identity,
                            source_date=candidate.get('source_date') or now(), demo=bool(candidate.get('demo', False)))
                session.add(lead)
                session.flush()
        except IntegrityError:
            lead = session.scalar(select(Lead).where(Lead.producer_id == campaign.producer_id,
                or_(Lead.dedup_identity == identity, Lead.dedup_email == email if email else False)))
            duplicate = True
    link = _link(session, campaign.id, lead.id)
    if link is None:
        link = CampaignLead(producer_id=campaign.producer_id, campaign_id=campaign.id, lead_id=lead.id,
                            source_data={key: candidate.get(key) for key in ['address', 'source_url', 'source_date', 'provider', 'metadata']})
        session.add(link)
        session.flush()
        if lead.stop_reason:
            link.excluded = True
            _transition(session, campaign, link, 'DO_NOT_CONTACT', 'Contatto già sospeso: nessuna nuova sequenza avviata.', 'lead_generation')
        else:
            _transition(session, campaign, link, 'DISCOVERED', 'Dati acquisiti dalla fonte con data e deduplica.', 'lead_generation')
            _enqueue(session, campaign, 'qualification', 'QUALIFY', f'qualify:{lead.id}', lead.id)
    count = session.scalar(select(func.count()).select_from(CampaignLead).where(CampaignLead.campaign_id == campaign.id))
    _event(session, campaign, 'lead_generation', 'lead_discovered', f'Lead trovato: {lead.company_name}. ' + ('Contatto già presente riutilizzato.' if duplicate else 'Lead salvato.') + f' {count}/{campaign.lead_count} lead trovati.', lead.id, task.id,
           {'progress': count, 'total': campaign.lead_count, 'duplicate': duplicate, 'demo': lead.demo})
    if index + 1 < campaign.lead_count:
        _enqueue(session, campaign, 'lead_generation', 'DISCOVER', f'discover:{index + 1}',
                 payload={'index': index + 1}, due_at=(datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat())
    else:
        _event(session, campaign, 'lead_generation', 'discovery_completed', f'Ricerca completata: {count} contatti salvati.', task_id=task.id)
    return {'lead_id': lead.id, 'discovered': int(not duplicate), 'duplicate': duplicate}


def _execute(session, campaign, task, settings):
    if task.kind == 'DISCOVER':
        return _discover(session, campaign, task, settings)
    lead = _own(session, Lead, campaign.producer_id, task.lead_id)
    link = _link(session, campaign.id, lead.id)
    if link.workflow_stage in ['WON', 'LOST']:
        return {'cancelled': True, 'reason': 'Esito commerciale terminale già registrato.'}
    if link.excluded or (lead.stop_reason and task.kind != 'SALES' and not (task.kind == 'CRM')):
        return {'cancelled': True, 'reason': lead.stop_reason or 'Lead escluso.'}
    if task.kind == 'QUALIFY':
        _transition(session, campaign, link, 'QUALIFYING', 'Analisi dei dati e del catalogo in corso.', 'qualification')
        _event(session, campaign, 'qualification', 'qualification_started', f'Qualification Agent sta analizzando {lead.company_name}. Analisi catalogo…', lead.id, task.id)
        result = providers.qualification(settings, lead, _profile(session, campaign))
        link.qualification, lead.qualification, lead.score = result, result, result['total_score']
        _event(session, campaign, 'qualification', 'lead_scored', f'{lead.company_name}: product fit {result["product_fit"]}; potenziale commerciale {result["commercial_potential"]}; confidence {result["confidence"]}; score finale {lead.score}/100.', lead.id, task.id, result)
        if lead.score >= campaign.config['minimum_score']:
            _transition(session, campaign, link, 'QUALIFIED', 'Soglia superata: passaggio a Outreach Agent.', 'qualification')
            _enqueue(session, campaign, 'outreach', 'OUTREACH', f'outreach:{lead.id}', lead.id)
            if lead.score >= campaign.config['handoff_threshold']:
                _ensure_handoff(session, campaign, link, 'Compatibilità elevata: il commerciale può valutare il prospect; interesse non ancora verificato.')
        else:
            _transition(session, campaign, link, 'LOW_PRIORITY', 'Score sotto soglia: nessuna bozza o comunicazione generata.', 'qualification')
        return result
    if task.kind in ['OUTREACH', 'FOLLOWUP']:
        _event(session, campaign, task.agent, 'outreach_started', f'Sto preparando ' + ('il follow-up' if task.kind == 'FOLLOWUP' else 'l’email') + f' per {lead.company_name}.', lead.id, task.id)
        draft = _create_workflow_draft(session, campaign, task, lead, settings)
        _transition(session, campaign, link, 'FOLLOW_UP' if task.kind == 'FOLLOWUP' else 'OUTREACH_READY', 'Bozza disponibile per revisione.', task.agent)
        if _auto_allowed(campaign, task.kind):
            _automatic_send(session, campaign, draft, settings, task)
            return dict(task.result) | {'sent': draft.status == 'sent'}
        return dict(task.result) | {'waiting_approval': True}
    if task.kind == 'SALES':
        conversation = _own(session, ConversationEvent, campaign.producer_id, task.payload['conversation_id'])
        result = providers.analyze_response(settings, conversation.body, conversation.event_type, _profile(session, campaign))
        conversation.classification, conversation.extracted = result['classification'], result['extracted']
        if conversation.message_id:
            session.get(Message, conversation.message_id).classification = result['classification'].lower()
        category = result['classification']
        _event(session, campaign, 'sales', 'response_analyzed', f'{lead.company_name}: risposta classificata {category}; dati dichiarati estratti, informazioni assenti conservate come mancanti.', lead.id, task.id, result)
        terminal = category in ['NOT_INTERESTED', 'UNSUBSCRIBE', 'HARD_BOUNCE'] or lead.stop_reason != 'reply'
        stage = {'NOT_INTERESTED': 'LOST', 'UNSUBSCRIBE': 'DO_NOT_CONTACT', 'HARD_BOUNCE': 'DO_NOT_CONTACT',
                 'INTERESTED': 'INTERESTED', 'MEETING_REQUEST': 'INTERESTED'}.get(category, 'REPLIED')
        if lead.stop_reason not in ['', 'reply'] and not category in ['NOT_INTERESTED', 'UNSUBSCRIBE', 'HARD_BOUNCE']:
            stage = 'DO_NOT_CONTACT'
        _enqueue(session, campaign, 'crm', 'CRM', f'crm:conversation:{conversation.id}', lead.id,
                 {'stage': stage, 'reason': f'Sales Agent: {category}', 'conversation_id': conversation.id,
                  'handoff': (bool(result['handoff_required']) or category in ['INTERESTED', 'MEETING_REQUEST', 'OBJECTION', 'QUESTION']) and not terminal, 'analysis': result})
        if not terminal and category != 'OUT_OF_OFFICE':
            draft = _create_workflow_draft(session, campaign, task, lead, settings, 'reply',
                                          conversation.body, bool(result['handoff_required']))
            # Sensitive/commercial replies always require human review.
            if _auto_allowed(campaign, 'SALES', sensitive=bool(result['handoff_required'])):
                _automatic_send(session, campaign, draft, settings, task)
            elif draft.status in ['pending', 'approved', 'failed']:
                result['waiting_approval'] = True
            result['draft_id'] = draft.id
        return result
    if task.kind == 'CRM':
        payload = task.payload
        if link.workflow_stage == 'MEETING' and payload['stage'] not in ['DO_NOT_CONTACT', 'LOST', 'WON']:
            return {'cancelled': True, 'reason': 'Appuntamento già prenotato; stato commerciale conservato.'}
        if lead.stop_reason not in ['', 'reply'] and payload['stage'] not in ['DO_NOT_CONTACT', 'LOST']:
            return {'cancelled': True, 'reason': 'Contatto interrotto; stato commerciale conservato.'}
        _transition(session, campaign, link, payload['stage'], payload['reason'], 'sales', payload.get('conversation_id'))
        if payload.get('handoff'):
            analysis = payload.get('analysis', {})
            extracted = analysis.get('extracted', {})
            reason = analysis.get('reason') or 'Risposta commerciale da valutare: esigenze e condizioni richiedono verifica umana.'
            handoff = _ensure_handoff(session, campaign, link, reason,
                'Esigenze, quantità, budget e tempistiche dichiarati (nessuna stima):\n' + json.dumps(extracted, ensure_ascii=False)[:4500])
            # Reuse an existing high-score handoff; enrich its summary after an
            # actual response instead of creating duplicate opportunity cards.
            handoff.reason, handoff.summary = reason, 'Dati dichiarati dal contatto:\n' + json.dumps(extracted, ensure_ascii=False)[:4500]
            _transition(session, campaign, link, 'HANDOFF', 'Passaggio al commerciale richiesto.', 'crm')
        return {'stage': link.workflow_stage, 'handoff_id': link.handoff_id}
    raise AutomationError('Tipo di attività non supportato.')


def _refresh_campaign(session, campaign):
    queued = session.scalar(select(func.count()).select_from(AgentTask).where(AgentTask.campaign_id == campaign.id,
        AgentTask.status.in_(ACTIVE_TASKS)))
    failed = session.scalar(select(func.count()).select_from(AgentTask).where(AgentTask.campaign_id == campaign.id, AgentTask.status == 'FAILED'))
    if campaign.status == 'RUNNING' and not queued:
        if failed:
            campaign.status = 'FAILED'
        else:
            campaign.status, campaign.finished_at = 'COMPLETED', now()
            _event(session, campaign, 'crm', 'campaign_completed', 'Workflow corrente completato; dati e conversazioni conservati. Una nuova risposta può riaprire l’analisi.')


def run_due(session, settings, tenant=None, max_jobs=12):
    result = {'processed': 0, 'completed': 0, 'created_drafts': 0, 'sent': 0, 'failed': 0, 'recovered': 0}
    scope = [AgentTask.producer_id == tenant] if tenant is not None else []
    # CAS recovery only touches expired claims, never live workers.
    expired = session.scalars(select(AgentTask.id).where(*scope, AgentTask.status == 'RUNNING', AgentTask.lease_until <= now())).all()
    for ident in expired:
        recovered = session.execute(update(AgentTask).where(AgentTask.id == ident, AgentTask.status == 'RUNNING', AgentTask.lease_until <= now()).values(
            status='QUEUED', claim_token=None, lease_until=None)).rowcount
        result['recovered'] += recovered
    session.commit()
    for _ in range(max(1, min(max_jobs, 100))):
        ident = session.scalar(select(AgentTask.id).join(Campaign).join(AgentRun,
            (AgentRun.campaign_id == AgentTask.campaign_id) & (AgentRun.agent == AgentTask.agent)).where(
                *scope, AgentTask.status == 'QUEUED', AgentTask.due_at <= now(),
                Campaign.status == 'RUNNING', AgentRun.paused == False).order_by(AgentTask.due_at, AgentTask.id).limit(1))
        if ident is None:
            session.rollback()
            break
        token = str(uuid.uuid4())
        campaign_id = session.scalar(select(AgentTask.campaign_id).where(AgentTask.id == ident))
        producer_id = session.scalar(select(Campaign.producer_id).where(Campaign.id == campaign_id))
        session.execute(update(Producer).where(Producer.id == producer_id).values(id=Producer.id))
        session.execute(update(Campaign).where(Campaign.id == campaign_id).values(id=Campaign.id))
        # Parent status and agent pause checked again atomically at claim time.
        enabled = exists(select(Campaign.id).where(Campaign.id == AgentTask.campaign_id, Campaign.status == 'RUNNING'))
        unpaused = exists(select(AgentRun.id).where(AgentRun.campaign_id == AgentTask.campaign_id, AgentRun.agent == AgentTask.agent, AgentRun.paused == False))
        claimed = session.execute(update(AgentTask).where(AgentTask.id == ident, AgentTask.status == 'QUEUED', enabled, unpaused).values(
            status='RUNNING', claim_token=token, lease_until=(datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat(),
            attempts=AgentTask.attempts + 1)).rowcount
        if not claimed:
            session.rollback()
            continue
        task = session.get(AgentTask, ident)
        run = session.scalar(select(AgentRun).where(AgentRun.campaign_id == task.campaign_id, AgentRun.agent == task.agent))
        run.status, run.current_task, run.updated_at = 'WORKING', task.kind, now()
        session.commit()  # Claim survives worker termination.
        result['processed'] += 1
        try:
            # Write-lock and fence the task before any effects. A stale owner
            # cannot write after a reclaimer has replaced its claim token.
            # Producer -> campaign -> task is also the lock order of controls,
            # provider ingestion and manual sends, including FK insert locks.
            session.execute(update(Producer).where(Producer.id == task.producer_id).values(id=Producer.id))
            session.execute(update(Campaign).where(Campaign.id == task.campaign_id).values(id=Campaign.id))
            fenced = session.execute(update(AgentTask).where(AgentTask.id == ident, AgentTask.status == 'RUNNING', AgentTask.claim_token == token).values(
                lease_until=(datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat())).rowcount
            if not fenced:
                session.rollback()
                continue
            session.refresh(task)
            campaign = session.get(Campaign, task.campaign_id)
            session.refresh(campaign)
            run = session.scalar(select(AgentRun).where(AgentRun.campaign_id == campaign.id, AgentRun.agent == task.agent))
            session.refresh(run)
            if campaign.status != 'RUNNING' or run.paused:
                task.status, task.claim_token, task.lease_until = 'QUEUED', None, None
                if run.paused or campaign.status == 'PAUSED':
                    run.status = 'PAUSED'
                session.commit()
                continue
            outcome = _execute(session, campaign, task, settings)
            session.flush()
            session.refresh(task)
            if task.status != 'RUNNING' or task.claim_token != token:
                # A response or stop received during provider latency owns the
                # task state. Only the durable provider confirmation survives.
                session.commit()
                continue
            # task.result contains its durable communication id before the next
            # stage; retain it for retries/approval and provider idempotency.
            task.result = dict(task.result) | outcome
            task.status = 'CANCELLED' if outcome.get('cancelled') else ('WAITING' if outcome.get('waiting_approval') else 'COMPLETED')
            task.completed_at = now() if task.status in ['COMPLETED', 'CANCELLED'] else None
            task.claim_token, task.lease_until = None, None
            run = session.scalar(select(AgentRun).where(AgentRun.campaign_id == campaign.id, AgentRun.agent == task.agent))
            run.status = 'WAITING' if task.status == 'WAITING' else 'IDLE'
            run.tasks_completed += int(task.status == 'COMPLETED')
            run.current_task = 'Attesa approvazione umana' if task.status == 'WAITING' else ''
            run.next_action = 'Approvare la bozza' if task.status == 'WAITING' else 'Attendere il prossimo evento'
            run.updated_at = now()
            result['completed'] += int(task.status == 'COMPLETED')
            result['created_drafts'] += int(bool(outcome.get('draft_id')))
            result['sent'] += int(bool(outcome.get('sent')))
            _refresh_campaign(session, campaign)
            session.commit()
        except Exception as error:
            session.rollback()
            # Errors contain application messages only; provider bodies, keys,
            # injected content and arbitrary exception text never enter audit.
            safe = str(error) if isinstance(error, (AutomationError, integrations.IntegrationError)) else 'Attività non riuscita: verifica dati, catalogo e configurazione; riprova dalla scheda agente.'
            throttled = isinstance(error, AutomationError) and safe.startswith('Limite di frequenza')
            capped = isinstance(error, AutomationError) and safe.startswith('Raggiunto il limite')
            paused = isinstance(error, AutomationError) and safe.startswith(('Campagna in pausa', 'Agente in pausa'))
            final_status = 'QUEUED' if throttled or paused else ('WAITING' if capped else 'FAILED')
            session.execute(update(Producer).where(Producer.id == task.producer_id).values(id=Producer.id))
            session.execute(update(Campaign).where(Campaign.id == task.campaign_id).values(id=Campaign.id))
            changed = session.execute(update(AgentTask).where(AgentTask.id == ident, AgentTask.status == 'RUNNING', AgentTask.claim_token == token).values(
                status=final_status, last_error=safe, claim_token=None, lease_until=None,
                due_at=(datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat() if throttled else now())).rowcount
            if changed:
                task = session.get(AgentTask, ident)
                campaign = session.get(Campaign, task.campaign_id)
                campaign.last_error = safe
                run = session.scalar(select(AgentRun).where(AgentRun.campaign_id == campaign.id, AgentRun.agent == task.agent))
                run.status, run.error_count, run.last_action = ('PAUSED' if paused else ('WAITING' if throttled or capped else 'ERROR')), run.error_count + int(not (throttled or capped or paused)), safe
                _event(session, campaign, task.agent, 'communication_paused' if paused else ('communication_limited' if throttled or capped else 'task_failed'), safe, task.lead_id, task.id)
                if isinstance(error, integrations.IntegrationError) and error.code == 'invalid_recipient' and task.lead_id:
                    lead = session.get(Lead, task.lead_id)
                    lead.stop_reason = 'hard_bounce'
                    on_contact_stopped(session, campaign.producer_id, lead)
                _refresh_campaign(session, campaign)
                session.commit()
            else:
                session.rollback()
            result['failed'] += int(not (throttled or capped or paused))
    return result


def events(session, tenant, campaign_id, after_id=0):
    _own(session, Campaign, tenant, campaign_id)
    return [_serialize(item) for item in session.scalars(select(AgentEvent).where(AgentEvent.producer_id == tenant,
        AgentEvent.campaign_id == campaign_id, AgentEvent.id > after_id).order_by(AgentEvent.id.desc()).limit(200)).all()]


def tasks(session, tenant, campaign_id):
    _own(session, Campaign, tenant, campaign_id)
    return [_serialize(item) for item in session.scalars(select(AgentTask).where(AgentTask.producer_id == tenant,
        AgentTask.campaign_id == campaign_id).order_by(AgentTask.id.desc()).limit(1000)).all()]


def agent_status(session, tenant, campaign_id):
    campaign = _own(session, Campaign, tenant, campaign_id)
    result = []
    for run in session.scalars(select(AgentRun).where(AgentRun.campaign_id == campaign_id).order_by(AgentRun.id)):
        data = _serialize(run)
        pending = session.scalar(select(AgentTask).where(AgentTask.campaign_id == campaign_id,
            AgentTask.agent == run.agent, AgentTask.status.in_(ACTIVE_TASKS)).order_by(AgentTask.due_at).limit(1))
        if run.paused or campaign.status == 'PAUSED':
            data['status'] = 'PAUSED'
        elif pending:
            ongoing_discovery = run.agent == 'lead_generation' and pending.status == 'QUEUED' and campaign.status == 'RUNNING'
            data['status'] = 'WORKING' if pending.status == 'RUNNING' or ongoing_discovery else 'WAITING'
            data['current_task'] = 'Attesa approvazione umana' if pending.status == 'WAITING' else pending.kind
            data['next_action'] = 'Approvazione bozza' if pending.status == 'WAITING' else f'Job previsto {pending.due_at}'
        elif run.status != 'ERROR':
            data['status'], data['current_task'] = 'IDLE', ''
        data['name'] = AGENTS[run.agent]
        result.append(data)
    return result


agents = agent_status


def _lead_output(session, link):
    lead = session.get(Lead, link.lead_id)
    data = _serialize(link) | {'company_name': lead.company_name, 'contact_name': lead.contact_name, 'email': lead.email,
        'city': lead.city, 'score': lead.score, 'source': lead.source, 'source_date': lead.source_date,
        'provider': link.source_data.get('provider'), 'demo': lead.demo, 'stage': link.workflow_stage,
        'stop_reason': lead.stop_reason}
    stage = link.workflow_stage
    job_rows = session.scalars(select(AgentTask).where(AgentTask.campaign_id == link.campaign_id, AgentTask.lead_id == link.lead_id)).all()
    outreach_ids = [job.result.get('draft_id') for job in job_rows if job.kind == 'OUTREACH' and job.result.get('draft_id')]
    outreach_sent = bool(outreach_ids and session.scalar(select(Draft.id).where(Draft.id.in_(outreach_ids), Draft.status == 'sent').limit(1)))
    conversations = session.scalars(select(ConversationEvent).where(ConversationEvent.campaign_id == link.campaign_id,
        ConversationEvent.lead_id == link.lead_id)).all()
    followup_pending = any(job.kind == 'FOLLOWUP' and job.status in ACTIVE_TASKS for job in job_rows)
    done = {'DISCOVERED': True, 'QUALIFIED': bool(link.qualification), 'OUTREACH': outreach_sent,
            'FOLLOW_UP': any(job.kind == 'FOLLOWUP' and job.status == 'COMPLETED' for job in job_rows) and not followup_pending,
            'RESPONSE': any(item.classification != 'PENDING' for item in conversations), 'HANDOFF': bool(link.handoff_id)}
    active = {'DISCOVERED': 'QUALIFIED', 'QUALIFYING': 'QUALIFIED', 'QUALIFIED': 'OUTREACH',
              'OUTREACH_READY': 'OUTREACH', 'CONTACTED': 'FOLLOW_UP', 'FOLLOW_UP': 'FOLLOW_UP',
              'REPLIED': 'RESPONSE', 'INTERESTED': 'HANDOFF'}.get(stage)
    names = [('DISCOVERED', 'Scoperto'), ('QUALIFIED', 'Qualificato'), ('OUTREACH', 'Outreach'),
             ('FOLLOW_UP', 'Follow-up'), ('RESPONSE', 'Risposta'), ('HANDOFF', 'Commerciale')]
    stopped = stage in ['LOW_PRIORITY', 'DO_NOT_CONTACT', 'LOST', 'WON']
    data['graph'] = [{'step': key, 'label': label, 'status': 'completed' if done[key] else
        ('stopped' if stopped else ('active' if key == active else 'pending'))} for key, label in names]
    return data


def _campaign_output(session, campaign):
    config = {key: value for key, value in campaign.config.items() if key not in ['csv_rows', 'provider_results']}
    data = _serialize(campaign) | config
    links = session.scalars(select(CampaignLead).where(CampaignLead.campaign_id == campaign.id).order_by(CampaignLead.id)).all()
    lead_ids = [link.lead_id for link in links]
    owned_drafts = select(AgentTask.result['draft_id'].as_integer()).where(AgentTask.campaign_id == campaign.id)
    drafts = session.scalars(select(Draft).where(Draft.producer_id == campaign.producer_id, Draft.id.in_(owned_drafts))).all() if lead_ids else []
    data['metrics'] = {'discovered': len(links), 'qualified': sum(bool(link.qualification and link.qualification.get('total_score', 0) >= campaign.config['minimum_score']) for link in links),
        'low_priority': sum(link.workflow_stage == 'LOW_PRIORITY' for link in links),
        'pending_approval': sum(draft.status in ['pending', 'approved'] for draft in drafts),
        'sent_simulated': sum(draft.status == 'sent' and draft.simulated for draft in drafts),
        'sent_real': sum(draft.status == 'sent' and not draft.simulated for draft in drafts),
        'handoffs': sum(bool(link.handoff_id) for link in links),
        'failed_tasks': session.scalar(select(func.count()).select_from(AgentTask).where(AgentTask.campaign_id == campaign.id, AgentTask.status == 'FAILED'))}
    return data


def list_campaigns(session, tenant):
    return [_campaign_output(session, campaign) for campaign in session.scalars(select(Campaign).where(Campaign.producer_id == tenant).order_by(Campaign.id.desc()))]


def campaign_detail(session, tenant, campaign_id):
    campaign = _own(session, Campaign, tenant, campaign_id)
    return _campaign_output(session, campaign) | {
        'leads': [_lead_output(session, item) for item in session.scalars(select(CampaignLead).where(CampaignLead.campaign_id == campaign_id).order_by(CampaignLead.id))],
        'agents': agent_status(session, tenant, campaign_id), 'events': events(session, tenant, campaign_id),
        'tasks': tasks(session, tenant, campaign_id),
        'rules': [_serialize(item) for item in session.scalars(select(AutomationRule).where(AutomationRule.campaign_id == campaign_id))]}


def exclude_lead(session, tenant, campaign_id, lead_id, reason='Escluso dalla campagna dall’operatore.'):
    campaign = _own(session, Campaign, tenant, campaign_id)
    lead = _own(session, Lead, tenant, lead_id)
    link = _link(session, campaign_id, lead_id)
    if link is None:
        raise AutomationError('Lead non presente nella campagna.', 404)
    link.excluded = True
    lead.stop_reason = 'manuale: ' + reason
    on_contact_stopped(session, tenant, lead)
    session.commit()
    return _lead_output(session, link)


def handoff_detail(session, tenant, handoff_id):
    handoff = _own(session, Handoff, tenant, handoff_id)
    lead = _own(session, Lead, tenant, handoff.lead_id)
    link = session.scalar(select(CampaignLead).where(CampaignLead.producer_id == tenant, CampaignLead.handoff_id == handoff.id))
    campaign = session.get(Campaign, link.campaign_id) if link else None
    incoming = session.scalar(select(Message).where(Message.producer_id == tenant, Message.lead_id == lead.id, Message.direction == 'inbound').order_by(Message.id.desc()).limit(1))
    conversation = session.scalar(select(ConversationEvent).where(ConversationEvent.producer_id == tenant, ConversationEvent.lead_id == lead.id).order_by(ConversationEvent.id.desc()).limit(1))
    profile = _profile(session, campaign) if campaign else session.get(Producer, tenant).profile
    qualification = link.qualification if link else (lead.qualification or {})
    ownership = session.scalar(select(HandoffOwnership).where(HandoffOwnership.producer_id == tenant, HandoffOwnership.handoff_id == handoff_id))
    owner = session.get(User, ownership.user_id) if ownership else None
    compatible = [item for item in profile.get('catalog', []) if item['id'] in qualification.get('product_ids', [])]
    metadata = []
    if campaign:
        metadata = [_serialize(item) for item in session.scalars(select(AgentEvent).where(AgentEvent.campaign_id == campaign.id, AgentEvent.lead_id == lead.id).order_by(AgentEvent.id.desc()).limit(60))]
    return _serialize(handoff) | {'company_name': lead.company_name, 'contact_name': lead.contact_name,
        'email': lead.email, 'phone': lead.phone, 'score': lead.score, 'qualification': qualification,
        'campaign_id': campaign.id if campaign else None, 'campaign_name': campaign.name if campaign else None,
        'products': compatible, 'compatible_products': [item['name'] for item in compatible], 'last_reply': incoming.body if incoming else '',
        'extracted': conversation.extracted if conversation else {}, 'objections': (conversation.extracted or {}).get('objections', []) if conversation else [],
        'timeline': metadata, 'history': metadata, 'potential_value': None,
        'next_action': 'Verificare esigenze e condizioni dichiarate; proporre disponibilità senza confermare appuntamenti prima della prenotazione.',
        'demo': lead.demo, 'stage': lead.stage, 'owner_id': owner.id if owner else None,
        'owner_name': owner.name if owner else None, 'claimed_at': ownership.claimed_at if ownership else None}


def handoffs(session, tenant):
    return [handoff_detail(session, tenant, handoff.id) for handoff in session.scalars(select(Handoff).where(Handoff.producer_id == tenant).order_by(Handoff.id.desc()))]


def handoff_action(session, tenant, handoff_id, action, user_id=None, note=''):
    handoff = _own(session, Handoff, tenant, handoff_id)
    session.execute(update(Producer).where(Producer.id == tenant).values(id=Producer.id))
    lead = _own(session, Lead, tenant, handoff.lead_id)
    link = session.scalar(select(CampaignLead).where(CampaignLead.producer_id == tenant, CampaignLead.handoff_id == handoff.id))
    campaign = session.get(Campaign, link.campaign_id) if link else None
    if action in ['take', 'take_ownership']:
        if user_id is None:
            raise AutomationError('È richiesto un utente autenticato per prendere in carico l’opportunità.', 401)
        owner = _own(session, User, tenant, user_id)
        session.execute(update(Handoff).where(Handoff.id == handoff.id).values(id=Handoff.id))
        ownership = session.scalar(select(HandoffOwnership).where(HandoffOwnership.handoff_id == handoff.id))
        if ownership is None:
            ownership = HandoffOwnership(producer_id=tenant, handoff_id=handoff.id, user_id=owner.id, note=note)
            session.add(ownership)
        else:
            ownership.user_id, ownership.note, ownership.claimed_at = owner.id, note, now()
        handoff.status = 'in_progress'
        svc.audit(session, tenant, 'commerciale.presa_in_carico', f'Opportunità presa in carico dall’utente {user_id}.', lead.id)
    elif action in ['contact', 'contacted']:
        handoff.status = 'contacted'
        svc.audit(session, tenant, 'commerciale.contatto', 'Attività di contatto annotata; nessuna comunicazione esterna eseguita.' + (' Nota: ' + note if note else ''), lead.id)
    elif action in ['won', 'lost']:
        handoff.status, lead.stage = action, action
        lead.stop_reason = 'manuale: esito commerciale ' + action.upper()
        if campaign:
            _cancel_sequence(session, campaign, lead.id, 'Esito commerciale registrato dall’operatore.')
            _transition(session, campaign, link, action.upper(), 'Esito commerciale registrato dall’operatore.', 'crm')
        on_contact_stopped(session, tenant, lead)
        svc.audit(session, tenant, 'commerciale.' + action, 'Esito commerciale registrato dall’operatore.', lead.id)
    else:
        raise AutomationError('Azione commerciale non valida.', 422)
    session.commit()
    return handoff_detail(session, tenant, handoff_id)


def cancel_followup(session, tenant, legacy_task):
    session.execute(update(Producer).where(Producer.id == tenant).values(id=Producer.id))
    for task in session.scalars(select(AgentTask).where(AgentTask.producer_id == tenant,
        AgentTask.payload['legacy_task_id'].as_integer() == legacy_task.id, AgentTask.status.in_(ACTIVE_TASKS))):
        task.status, task.claim_token, task.lease_until = 'CANCELLED', None, None
        campaign = session.get(Campaign, task.campaign_id)
        _event(session, campaign, 'follow_up', 'followup_cancelled', 'Follow-up annullato dall’operatore.', legacy_task.lead_id, task.id)


def on_draft_rejected(session, tenant, draft):
    for task in session.scalars(select(AgentTask).where(AgentTask.producer_id == tenant,
        AgentTask.result['draft_id'].as_integer() == draft.id, AgentTask.status == 'WAITING')):
        task.status, task.completed_at = 'CANCELLED', now()
        campaign = session.get(Campaign, task.campaign_id)
        _event(session, campaign, task.agent, 'draft_rejected', 'Bozza rifiutata dall’operatore: nessun invio verrà eseguito.', draft.lead_id, task.id)
        _refresh_campaign(session, campaign)


def on_stage_changed(session, tenant, lead, old_state, reason='Aggiornamento operatore'):
    for link in session.scalars(select(CampaignLead).where(CampaignLead.producer_id == tenant, CampaignLead.lead_id == lead.id)):
        campaign = session.get(Campaign, link.campaign_id)
        stage = {'appointment': 'MEETING'}.get(lead.stage, lead.stage.upper())
        _transition(session, campaign, link, stage, reason, 'crm')
        if stage in ['WON', 'LOST', 'DO_NOT_CONTACT']:
            lead.stop_reason = lead.stop_reason or 'manuale: stato ' + stage
            on_contact_stopped(session, tenant, lead)
