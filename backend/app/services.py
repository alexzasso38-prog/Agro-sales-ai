"""Grounded local analysis: observations are labelled by source, never inferred sales facts."""
from datetime import datetime, timedelta, timezone
import re
import uuid
from sqlalchemy import select, update
from .db import Lead, Draft, Task, Message, Handoff, Audit, Producer, now

def audit(session, tenant, action, detail, lead_id=None):
    session.add(Audit(producer_id=tenant, action=action, detail=detail, lead_id=lead_id))

def qualification(lead, profile):
    facts = [f'Ragione sociale dichiarata: {lead.company_name} (fonte: {lead.source}; acquisita {lead.source_date}).']
    missing = ['Volumi di acquisto non verificati.', 'Fornitori attuali non noti.', 'Interesse commerciale non verificato.']
    hypotheses = []
    score = 10
    if lead.business_type:
        facts.append(f'Tipologia riportata dalla fonte: {lead.business_type}.')
        if any(word in lead.business_type.lower() for word in ['ristor', 'hotel', 'bar', 'catering', 'horeca', 'trattoria']):
            score += 20
    else:
        missing.append('Tipologia attività mancante.')
    if lead.city:
        facts.append(f'Città riportata dalla fonte: {lead.city}.')
        if any(area.casefold() == lead.city.casefold() for area in profile.get('service_areas', [])):
            score += 25
            facts.append('La città coincide con una zona servita nel profilo del produttore.')
        else:
            missing.append('Copertura della consegna da verificare con il commerciale.')
    else:
        missing.append('Città mancante; copertura consegna non verificabile.')
    if lead.menu_text:
        facts.append('È presente un testo menu fornito dalla fonte; non è stato verificato indipendentemente.')
        # No instruction in this text can alter scoring or the catalog. Only literal culinary matches.
        tokens = set(re.findall(r'\b[\wàèéìòù]{4,}\b', lead.menu_text.lower()))
        matches = []
        for item in profile.get('catalog', []):
            terms = set(re.findall(r'\b[\wàèéìòù]{4,}\b', (item['name'] + ' ' + item.get('category', '')).lower()))
            if tokens & terms:
                matches.append(item['name'])
        if matches:
            score += min(30, len(matches) * 10)
            hypotheses.append(f'Possibile compatibilità culinaria con {", ".join(matches)} sulla base di parole presenti nel menu; da confermare.')
        else:
            missing.append('Abbinamento catalogo/menu da verificare.')
    else:
        missing.append('Menu non disponibile.')
    if lead.email:
        facts.append('Email presente nella fonte; recapito e consenso al contatto non verificati.')
        score += 5
    else:
        missing.append('Email non disponibile: invio impossibile senza un recapito verificato dall’operatore.')
    if not profile.get('catalog'):
        missing.append('Catalogo del produttore ancora da compilare.')
    return {'score': min(score, 90), 'summary': 'Compatibilità indicativa basata sui dati disponibili, non una previsione di acquisto.', 'verified_facts': facts, 'hypotheses': hypotheses, 'missing_data': missing, 'method': 'Regole locali trasparenti; dati osservati e provenienza esplicita, nessuna verifica indipendente dei siti.'}

def classify(body, event='reply'):
    text = body.lower()
    if event != 'reply':
        classification = event
    elif re.search(r'disiscr|unsubscribe|rimuov|cancellat|non contatta|non scriv|non invia|non (?:desidero|vogliamo|voglio).*?(?:email|messaggi|contatt|ricevere)|smette(?:te|re).*?(?:scriv|contatt|invia)', text):
        classification = 'unsubscribe'
    elif re.search(r'non (?:siamo |sono )?interessat|non (?:ho|abbiamo).*?interesse|non (?:ci|mi) interessa|rifiut|no grazie', text):
        classification = 'rejection'
    elif re.search(r'invalid recipient|user unknown|indirizzo inesistente|hard bounce', text):
        classification = 'hard_bounce'
    elif re.search(r'interessat|campion|preventivo|ordinare|acquistare', text):
        classification = 'interested'
    elif '?' in body or re.search(r'quanto|quando|potete|vorrei|posso|prezzo|consegna', text):
        classification = 'question'
    else:
        classification = 'other'
    amount = re.search(r'\b\d+(?:[.,]\d+)?\s*(?:kg|litri|l|pezzi|confezioni|casse|bottiglie)\b', body, re.I)
    timing = re.search(r'\b(?:entro|dal|il|per)\s+(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica|domani|la prossima settimana)\b', body, re.I)
    needs = [line.strip()[:1000] for line in body.splitlines() if re.search(r'vorrei|cerch|serv|bisogn|interess|campion|preventivo', line, re.I)]
    protected = bool(re.search(r'scont|gratis|gratuit|esclusiv|pagamento|credito|dilazion|reso|deroga|consegna.*(?:urgente|garantita|fuori zona)|ignora|ignore|istruzion|system prompt', text))
    handoff = classification not in {'rejection', 'unsubscribe', 'hard_bounce'} and (protected or classification in {'question', 'other'} or not amount or not timing)
    reason = 'Richieste di condizioni non autorizzate o istruzioni non attendibili.' if protected else 'Informazioni commerciali incomplete: il commerciale deve verificare esigenze, quantità e tempistiche.'
    return {'classification': classification, 'handoff_required': handoff, 'reason': reason if handoff else '', 'extracted': {'needs': needs, 'quantity': amount.group(0) if amount else None, 'timing': timing.group(0) if timing else None}}

def make_handoff(session, tenant, lead, reason, summary):
    handoff = Handoff(producer_id=tenant, lead_id=lead.id, reason=reason, summary=summary[:5000])
    session.add(handoff)
    audit(session, tenant, 'commerciale.coinvolto', reason, lead.id)
    return handoff

def draft_text(lead, profile, kind='outreach', followup=False, handoff=False, intro_key='presentation'):
    products = profile.get('catalog', [])[:3]
    catalog = '\n'.join(f'- {item["name"]}: € {item["price"]:.2f}/{item["unit"]}' for item in products)
    company = profile['company_name']
    if handoff:
        return f'R: informazioni da {company}', 'Grazie per il messaggio. Ho inoltrato le richieste al nostro commerciale, che verificherà disponibilità e condizioni prima di formulare una proposta. Non sono ancora confermati ordini, sconti o appuntamenti.'
    if kind == 'reply':
        intro = 'Grazie per il messaggio. Ecco le informazioni disponibili dal nostro catalogo:'
        subject = f'R: catalogo e condizioni di {company}'
    elif followup:
        intro = f'Riprendo il precedente messaggio per condividere il catalogo di {company}.'
        subject = f'Catalogo {company}: un breve aggiornamento'
    elif intro_key == 'catalog':
        intro = f'Vi condivido alcuni prodotti del catalogo di {company} per valutare una possibile collaborazione.'
        subject = f'Il catalogo di {company} per {lead.company_name}'
    else:
        intro = f'Sono {profile.get("contact_name") or "il referente commerciale"} di {company}. Vorrei presentarvi alcuni prodotti del nostro catalogo per valutare insieme una possibile collaborazione.'
        subject = f'{company}: proposta per {lead.company_name}'
    body = f'Buongiorno,\n\n{intro}\n\n{catalog or "Catalogo ancora da confermare con il commerciale."}'
    for label, key in [('Ordine minimo', 'minimum_order'), ('Consegna', 'delivery_terms'), ('Pagamento', 'payment_terms')]:
        if profile.get(key):
            body += f'\n{label}: {profile[key]}'
    body += '\n\nQuali prodotti, quantità e tempistiche potrebbero essere utili alla vostra attività? Il commerciale verificherà ogni richiesta prima della conferma.\n\nSe non desiderate altri messaggi, rispondete “disiscrivimi”.'
    body += f'\n\n{profile.get("contact_name", "")}\n{company}'
    return subject, body

def create_draft(session, tenant, lead, profile, kind='outreach', task_id=None, handoff=False):
    subject, body = draft_text(lead, profile, kind, bool(task_id), handoff)
    draft = Draft(producer_id=tenant, lead_id=lead.id, kind=kind, subject=subject, body=body, task_id=task_id, idempotency_key=str(uuid.uuid4()))
    session.add(draft)
    audit(session, tenant, 'bozza.creata', 'Bozza da modificare e approvare prima dell’invio.', lead.id)
    session.flush()
    return draft

def stop_contact(session, tenant, lead, reason):
    lead.stop_reason = reason
    session.execute(update(Task).where(Task.producer_id == tenant, Task.lead_id == lead.id, Task.status.in_(['scheduled', 'processing', 'needs_approval', 'automation_managed'])).values(status='cancelled'))
    session.execute(update(Draft).where(Draft.producer_id == tenant, Draft.lead_id == lead.id, Draft.kind == 'outreach', Draft.status.in_(['pending', 'approved', 'failed'])).values(status='cancelled'))
    audit(session, tenant, 'ricontatti.interrotti', reason, lead.id)
    # A manual stop, inbound reply or bounce also stops persisted agent jobs.
    from .automation import on_contact_stopped
    on_contact_stopped(session, tenant, lead)

def run_due(session, tenant=None):
    where = [Task.status == 'scheduled', Task.due_at <= now()]
    if tenant is not None:
        where.append(Task.producer_id == tenant)
    ids = session.scalars(select(Task.id).where(*where).order_by(Task.due_at).limit(100)).all()
    result = {'processed': 0, 'created_drafts': 0, 'sent': 0, 'failed': 0}
    for task_id in ids:
        try:
            claimed = session.execute(update(Task).where(Task.id == task_id, Task.status == 'scheduled').values(status='processing')).rowcount
            if not claimed:
                session.rollback()
                continue
            task = session.get(Task, task_id)
            lead = session.get(Lead, task.lead_id)
            result['processed'] += 1
            if lead.stop_reason:
                task.status = 'cancelled'
                audit(session, task.producer_id, 'attività.annullata', lead.stop_reason, lead.id)
            else:
                profile = session.get(Producer, task.producer_id).profile
                create_draft(session, task.producer_id, lead, profile, task_id=task.id)
                task.status = 'needs_approval'
                result['created_drafts'] += 1
            session.commit()
        except Exception:
            session.rollback()
            task = session.get(Task, task_id)
            if task and task.status == 'scheduled':
                task.status = 'failed'
                task.last_error = 'Generazione bozza non riuscita; verifica profilo e catalogo.'
                audit(session, task.producer_id, 'worker.errore', task.last_error, task.lead_id)
                session.commit()
            result['failed'] += 1
    return result

def schedule_followups(session, tenant, lead, profile):
    if session.scalar(select(Task.id).where(Task.lead_id == lead.id).limit(1)):
        return
    for step, days in enumerate(profile.get('followup_days', [3, 7]), 1):
        session.add(Task(producer_id=tenant, lead_id=lead.id, step=step, due_at=(datetime.now(timezone.utc) + timedelta(days=days)).isoformat()))
    audit(session, tenant, 'sequenza.programmata', 'Le scadenze generano bozze; ogni invio richiede approvazione.', lead.id)
