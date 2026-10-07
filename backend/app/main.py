from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import io
import json
import re
import logging
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, update, func, exists
from sqlalchemy.exc import IntegrityError
import jwt
from .config import Settings
from .db import Base, database, User, Producer, Lead, Draft, Message, Task, Audit, Appointment, Handoff, now
from .auth import hash_password, verify_password, token
from . import schemas as S
from . import services as svc
from . import integrations as adapters
from . import automation as auto
from .automation_routes import register_automation_routes
from .automation_models import Campaign
from .seed import seed, DEMO_LEADS

logger = logging.getLogger('agro')
bearer = HTTPBearer(auto_error=False)

def create_app(settings=None):
    settings = settings or Settings()
    if settings.database_url.startswith('sqlite:///'):
        Path(settings.database_url.removeprefix('sqlite:///')).parent.mkdir(parents=True, exist_ok=True)
    engine, sessions = database(settings.database_url)
    @asynccontextmanager
    async def lifespan(app):
        Base.metadata.create_all(engine)
        if settings.demo_mode:
            with sessions() as session:
                seed(session)
        else:
            with sessions() as session:
                if session.scalar(select(User.id).where(User.email == 'demo@agrosales.test')):
                    raise RuntimeError('Il database contiene l’account demo con credenziali pubbliche. Usa un database di produzione separato; nessun dato è stato eliminato.')
        yield
        engine.dispose()

    app = FastAPI(title='Agro Sales AI', version='2.0.0', lifespan=lifespan)
    app.state.settings, app.state.engine, app.state.sessions = settings, engine, sessions
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=['GET', 'POST', 'PUT', 'PATCH'], allow_headers=['Authorization', 'Content-Type'])

    def db():
        with sessions() as session:
            yield session
    def current(request: Request, credentials: HTTPAuthorizationCredentials = Depends(bearer), session=Depends(db)):
        try:
            if credentials is None:
                raise ValueError()
            payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=['HS256'], options={'require': ['sub', 'exp', 'iat']})
            user = session.get(User, int(payload['sub']))
            if not user:
                raise ValueError()
            if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and session.scalar(select(Campaign.id).where(Campaign.producer_id == user.producer_id).limit(1)):
                # Match worker lock ordering before any authenticated state change.
                session.execute(update(Producer).where(Producer.id == user.producer_id).values(profile=Producer.profile))
            return user
        except (jwt.PyJWTError, ValueError, TypeError):
            raise HTTPException(401, 'Accesso richiesto: effettua il login.', headers={'WWW-Authenticate': 'Bearer'})

    def own(session, model, resource_id, user):
        obj = session.scalar(select(model).where(model.id == resource_id, model.producer_id == user.producer_id))
        if obj is None:
            raise HTTPException(404, 'Risorsa non trovata.')
        return obj
    def output(session, item):
        hidden = {'producer_id', 'dedup_email', 'dedup_identity', 'password_hash', 'idempotency_key', 'booking_key'}
        result = {col.name: getattr(item, col.name) for col in item.__table__.columns if col.name not in hidden}
        if hasattr(item, 'lead_id') and item.lead_id is not None:
            result['company_name'] = session.get(Lead, item.lead_id).company_name
        return result
    def many(session, model, user):
        return [output(session, item) for item in session.scalars(select(model).where(model.producer_id == user.producer_id).order_by(model.id.desc())).all()]
    def profile(session, user):
        return session.get(Producer, user.producer_id).profile
    def user_output(session, user):
        return {'id': user.id, 'name': user.name, 'email': user.email, 'company_name': profile(session, user)['company_name']}
    def fail(session, user, action, detail, lead_id=None, status=409):
        svc.audit(session, user.producer_id, action, detail, lead_id)
        session.commit()
        raise HTTPException(status, detail)
    def blocked(lead, kind):
        return bool(lead.stop_reason and not (lead.stop_reason == 'reply' and kind == 'reply'))
    def lead_input_data(lead):
        return {field: getattr(lead, field) for field in ['company_name', 'city', 'business_type', 'menu_text', 'notes', 'source', 'source_date']}
    def suggest_draft(session, user, lead, draft):
        if not settings.demo_mode and settings.openai_api_key and settings.allow_external_integrations:
            try:
                incoming = session.scalar(select(Message).where(Message.lead_id == lead.id, Message.direction == 'inbound').order_by(Message.id.desc()).limit(1))
                data = lead_input_data(lead)
                if incoming:
                    data['incoming_message'] = incoming.body
                approved_profile = profile(session, user)
                candidate = adapters.generate_ai(settings, 'draft_plan', approved_profile, data)
                available = {str(item['id']): item for item in approved_profile.get('catalog', [])}
                selected = candidate.get('product_ids', [])
                safe_shape = set(candidate) == {'intro_key', 'product_ids', 'handoff_required', 'reason'} and candidate.get('intro_key') in {'presentation', 'catalog'} and isinstance(selected, list) and all(isinstance(item, str) and item in available for item in selected)
                if not safe_shape:
                    svc.audit(session, user.producer_id, 'ai.proposta.scartata', 'La proposta non rispetta i dati autorizzati; usata la bozza locale.', lead.id)
                    svc.make_handoff(session, user.producer_id, lead, 'Proposta AI da verificare.', 'Controllare condizioni commerciali prima di rispondere.')
                elif candidate['handoff_required']:
                    svc.make_handoff(session, user.producer_id, lead, 'Il piano AI segnala informazioni da verificare.', 'Il commerciale deve verificare le richieste; consultare lo storico per i dati dichiarati dal contatto.')
                    draft.subject, draft.body = svc.draft_text(lead, approved_profile, draft.kind, handoff=True)
                else:
                    grounded_profile = dict(approved_profile)
                    if selected:
                        grounded_profile['catalog'] = [available[item] for item in dict.fromkeys(selected)][:3]
                    draft.subject, draft.body = svc.draft_text(lead, grounded_profile, draft.kind, bool(draft.task_id), intro_key=candidate['intro_key'])
                    svc.audit(session, user.producer_id, 'ai.bozza.generata', 'OpenAI sceglie prodotti e apertura tra opzioni autorizzate; testo composto da dati del catalogo, da approvare.', lead.id)
            except adapters.IntegrationError as error:
                svc.audit(session, user.producer_id, 'ai.errore', str(error) + ' Usata bozza locale.', lead.id)
        return draft

    @app.get('/health')
    def health():
        with sessions() as session:
            session.execute(select(1))
        return {'status': 'ok', 'demo_mode': settings.demo_mode}

    @app.get('/api/meta')
    def meta():
        return {'app_name': 'Agro Sales AI', 'demo_mode': settings.demo_mode, 'integrations': adapters.integration_status(settings)}

    @app.post('/api/auth/register', status_code=201)
    def register(body: S.Register, session=Depends(db)):
        email = body.email.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise HTTPException(422, 'Email non valida.')
        if not settings.demo_mode and email == 'demo@agrosales.test':
            raise HTTPException(422, 'Indirizzo riservato alla demo; usa un indirizzo del produttore.')
        if session.scalar(select(User).where(User.email == email)):
            raise HTTPException(409, 'Registrazione non disponibile per questo indirizzo.')
        producer = Producer(profile=S.Profile(company_name=body.company_name, contact_name=body.name, contact_email=email).model_dump())
        session.add(producer)
        session.flush()
        user = User(producer_id=producer.id, email=email, name=body.name, password_hash=hash_password(body.password))
        session.add(user)
        try:
            session.flush()
            svc.audit(session, producer.id, 'account.creato', 'Nuovo produttore con spazio dati separato.')
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, 'Registrazione non disponibile per questo indirizzo.')
        return {'access_token': token(user.id, settings), 'user': user_output(session, user), 'demo_mode': settings.demo_mode}

    @app.post('/api/auth/login')
    def login(body: S.Login, session=Depends(db)):
        user = session.scalar(select(User).where(User.email == body.email.strip().lower()))
        if not user or not verify_password(body.password, user.password_hash):
            if user:
                svc.audit(session, user.producer_id, 'accesso.rifiutato', 'Credenziali non valide.')
                session.commit()
            raise HTTPException(401, 'Email o password non valide.')
        svc.audit(session, user.producer_id, 'accesso.eseguito', 'Accesso autenticato.')
        session.commit()
        return {'access_token': token(user.id, settings), 'user': user_output(session, user), 'demo_mode': settings.demo_mode}

    @app.get('/api/auth/me')
    def me(user=Depends(current), session=Depends(db)):
        return user_output(session, user)

    @app.get('/api/profile')
    def get_profile(user=Depends(current), session=Depends(db)):
        return profile(session, user)

    @app.put('/api/profile')
    def put_profile(body: S.Profile, user=Depends(current), session=Depends(db)):
        producer = session.get(Producer, user.producer_id)
        producer.profile = body.model_dump()
        svc.audit(session, user.producer_id, 'profilo.aggiornato', 'Catalogo e condizioni approvate dal produttore aggiornati.')
        session.commit()
        return producer.profile

    def insert_lead(session, user, body, demo=None):
        data = body.model_dump()
        identity = '|'.join(re.sub(r'\W+', '', data[field].casefold()) for field in ['company_name', 'city'])
        email = data['email'] or None
        if session.scalar(select(Lead.id).where(Lead.producer_id == user.producer_id, (Lead.dedup_identity == identity) | ((Lead.dedup_email == email) if email else False))):
            return None
        lead = Lead(producer_id=user.producer_id, **data, dedup_email=email, dedup_identity=identity, demo=settings.demo_mode if demo is None else demo)
        try:
            with session.begin_nested():
                session.add(lead)
                session.flush()
        except IntegrityError:
            return None
        svc.audit(session, user.producer_id, 'lead.creato', f'Dati acquisiti dalla fonte: {body.source}.', lead.id)
        return lead

    @app.get('/api/leads')
    def leads(user=Depends(current), session=Depends(db)):
        return many(session, Lead, user)

    @app.post('/api/leads', status_code=201)
    def add_lead(body: S.LeadInput, user=Depends(current), session=Depends(db)):
        lead = insert_lead(session, user, body)
        if lead is None:
            fail(session, user, 'lead.duplicato', 'Contatto già presente per email o identità aziendale.')
        session.commit()
        return output(session, lead)

    @app.post('/api/leads/import')
    async def import_csv(file: UploadFile = File(...), user=Depends(current), session=Depends(db)):
        raw = await file.read(2_000_001)
        if len(raw) > 2_000_000:
            fail(session, user, 'import.errore', 'CSV troppo grande (massimo 2 MB).', status=413)
        try:
            reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
            if not reader.fieldnames or 'company_name' not in reader.fieldnames:
                raise ValueError('Manca la colonna company_name.')
            rows = list(reader)
            if len(rows) > 5000:
                raise ValueError('Massimo 5000 righe per importazione.')
        except (UnicodeDecodeError, csv.Error, ValueError) as error:
            fail(session, user, 'import.errore', f'CSV non valido: {str(error)[:300]}', status=422)
        result = {'imported': 0, 'duplicates': 0, 'errors': []}
        for number, row in enumerate(rows, 2):
            if not any(row.values()):
                continue
            try:
                data = {key: (row.get(key) or '') for key in S.LeadInput.model_fields}
                data['source'] = data['source'] or f'CSV caricato dall’operatore: {Path(file.filename or "import.csv").name}'
                body = S.LeadInput(**data)
                result['imported' if insert_lead(session, user, body) else 'duplicates'] += 1
            except (ValueError, TypeError):
                result['errors'].append({'row': number, 'detail': 'Riga non valida: verifica ragione sociale, email e lunghezza dei campi.'})
        svc.audit(session, user.producer_id, 'import.completato', f'{result["imported"]} importati, {result["duplicates"]} duplicati, {len(result["errors"])} errori.')
        session.commit()
        return result

    @app.post('/api/leads/search')
    def search(body: S.Search, user=Depends(current), session=Depends(db)):
        try:
            if settings.demo_mode:
                contacts = [dict(item, source='Ricerca demo su dataset fittizio locale', notes='Attività fittizia, nessun dato trovato online.') for item in DEMO_LEADS if (not body.city or body.city.casefold() in item['city'].casefold()) and (body.query.casefold() in (item['company_name'] + ' ' + item['business_type']).casefold() or body.query.casefold() in ['horeca', 'ristoranti', 'ristorante'])]
                for item in contacts:
                    item.pop('stage', None)
            else:
                contacts = adapters.search_leads(settings, body.query, body.city)
        except adapters.IntegrationError as error:
            fail(session, user, 'ricerca.errore', str(error), status=503)
        result = {'imported': 0, 'duplicates': 0, 'errors': []}
        for index, item in enumerate(contacts, 1):
            try:
                body = S.LeadInput(**{key: value for key, value in item.items() if key in S.LeadInput.model_fields})
                result['imported' if insert_lead(session, user, body) else 'duplicates'] += 1
            except ValueError:
                result['errors'].append({'row': index, 'detail': 'Dati provider non validi; nessun recapito inventato.'})
        svc.audit(session, user.producer_id, 'ricerca.completata', f'{result["imported"]} importati; ricerca {"simulata" if settings.demo_mode else "provider"}.')
        session.commit()
        return result

    @app.get('/api/leads/{lead_id}')
    def lead_detail(lead_id: int, user=Depends(current), session=Depends(db)):
        lead = own(session, Lead, lead_id, user)
        result = output(session, lead)
        for key, model in [('conversations', Message), ('drafts', Draft), ('tasks', Task), ('activities', Audit), ('appointments', Appointment)]:
            result[key] = [output(session, item) for item in session.scalars(select(model).where(model.producer_id == user.producer_id, model.lead_id == lead.id).order_by(model.id.desc())).all()]
        return result

    @app.patch('/api/leads/{lead_id}')
    def patch_lead(lead_id: int, body: S.LeadPatch, user=Depends(current), session=Depends(db)):
        lead = own(session, Lead, lead_id, user)
        old_stage = lead.stage
        if body.stage in {'won', 'lost', 'do_not_contact'}:
            svc.stop_contact(session, user.producer_id, lead, body.stage)
        for key, value in body.model_dump(exclude_none=True).items():
            setattr(lead, key, value)
        if old_stage != lead.stage:
            auto.on_stage_changed(session, user.producer_id, lead, old_stage)
        svc.audit(session, user.producer_id, 'lead.aggiornato', 'Pipeline o note aggiornate dall’operatore.', lead.id)
        session.commit()
        return output(session, lead)

    @app.post('/api/leads/{lead_id}/qualify')
    def qualify(lead_id: int, user=Depends(current), session=Depends(db)):
        lead = own(session, Lead, lead_id, user)
        result = svc.qualification(lead, profile(session, user))
        if not settings.demo_mode and settings.openai_api_key and settings.allow_external_integrations:
            try:
                approved = profile(session, user)
                proposal = adapters.generate_ai(settings, 'qualification_plan', approved, lead_input_data(lead))
                available = {str(item['id']): item['name'] for item in approved.get('catalog', [])}
                selected = proposal.get('product_ids', [])
                if set(proposal) != {'product_ids', 'rationale_key'} or not isinstance(selected, list) or any(not isinstance(item, str) or item not in available for item in selected) or proposal.get('rationale_key') not in {'possible_menu_fit', 'insufficient_data'}:
                    svc.audit(session, user.producer_id, 'ai.proposta.scartata', 'Piano di qualificazione non conforme; mantenuti fatti e analisi locali.', lead.id)
                elif selected and lead.menu_text and proposal['rationale_key'] == 'possible_menu_fit':
                    products = ', '.join(available[item] for item in dict.fromkeys(selected))
                    result['hypotheses'].append(f'OpenAI propone di verificare la compatibilità culinaria di prodotti del catalogo: {products}. Abbinamento indicativo, da confermare con il commerciale.')
                    result['method'] += '; OpenAI seleziona solo prodotti esistenti da valutare, senza modificare fatti o punteggio.'
            except adapters.IntegrationError as error:
                svc.audit(session, user.producer_id, 'ai.errore', str(error) + ' Analisi locale mantenuta.', lead.id)
        lead.qualification, lead.score = result, result['score']
        if lead.stage == 'new':
            lead.stage = 'qualified'
        svc.audit(session, user.producer_id, 'lead.qualificato', f'Punteggio indicativo {lead.score}/100; fatti osservati distinti dalle ipotesi.', lead.id)
        session.commit()
        return output(session, lead)

    @app.post('/api/leads/{lead_id}/draft', status_code=201)
    def make_draft(lead_id: int, body: S.DraftInput, user=Depends(current), session=Depends(db)):
        lead = own(session, Lead, lead_id, user)
        if blocked(lead, body.kind):
            fail(session, user, 'bozza.bloccata', 'Contatto sospeso: ' + lead.stop_reason, lead.id)
        if body.kind == 'reply' and not session.scalar(select(Message.id).where(Message.lead_id == lead.id, Message.direction == 'inbound').limit(1)):
            fail(session, user, 'bozza.bloccata', 'Nessuna risposta ricevuta a cui rispondere.', lead.id)
        request_info = svc.classify(body.instructions) if body.instructions else None
        handoff = bool(body.instructions and request_info['handoff_required'])
        if handoff:
            svc.make_handoff(session, user.producer_id, lead, 'Richieste dell’operatore da verificare rispetto alle condizioni approvate.', body.instructions)
        draft = svc.create_draft(session, user.producer_id, lead, profile(session, user), body.kind, handoff=handoff)
        if not handoff:
            suggest_draft(session, user, lead, draft)
        session.commit()
        return output(session, draft)

    @app.post('/api/leads/{lead_id}/reply')
    def reply(lead_id: int, body: S.Reply, user=Depends(current), session=Depends(db)):
        lead = own(session, Lead, lead_id, user)
        if auto.campaign_for_lead(session, user.producer_id, lead.id):
            result = auto.ingest_response(session, user.producer_id, lead, body.body, event=body.event, subject=body.subject, settings=settings, external_event_id=body.external_event_id)
            # Keep the existing response vocabulary; campaign consumers also get the richer sales class.
            sales_class = result['classification']
            result['sales_classification'] = sales_class
            result['classification'] = {'NOT_INTERESTED': 'rejection', 'MEETING_REQUEST': 'question', 'OBJECTION': 'question', 'OUT_OF_OFFICE': 'other'}.get(sales_class, sales_class.lower())
            return result
        classification = svc.classify(body.body, body.event)
        event = classification['classification']
        terminal = event in {'rejection', 'unsubscribe', 'hard_bounce'}
        # Any inbound message interrupts sequences. Existing terminal stops remain terminal.
        reason = event if terminal else (lead.stop_reason if lead.stop_reason and lead.stop_reason != 'reply' else 'reply')
        svc.stop_contact(session, user.producer_id, lead, reason)
        if terminal:
            session.execute(update(Draft).where(Draft.producer_id == user.producer_id, Draft.lead_id == lead.id, Draft.status.in_(['pending', 'approved', 'failed'])).values(status='cancelled'))
        if event == 'interested':
            lead.stage = 'interested'
        elif event == 'rejection':
            lead.stage = 'lost'
        message = Message(producer_id=user.producer_id, lead_id=lead.id, direction='inbound', subject=body.subject, body=body.body, classification=event, simulated=settings.demo_mode)
        session.add(message)
        draft = None
        if not terminal and lead.stop_reason == 'reply':
            if classification['handoff_required']:
                extracted = classification['extracted']
                summary = f'Esigenze dichiarate: {"; ".join(extracted["needs"]) or "non indicate"}\nQuantità dichiarata: {extracted["quantity"] or "non indicata"}\nTempistiche dichiarate: {extracted["timing"] or "non indicate"}'
                svc.make_handoff(session, user.producer_id, lead, classification['reason'], summary)
            draft = svc.create_draft(session, user.producer_id, lead, profile(session, user), kind='reply', handoff=classification['handoff_required'])
            if not classification['handoff_required']:
                suggest_draft(session, user, lead, draft)
        svc.audit(session, user.producer_id, 'risposta.registrata', f'Classificazione {event}; sequenze interrotte.', lead.id)
        session.commit()
        return {'message': output(session, message), **classification, 'draft': output(session, draft) if draft else None}

    @app.post('/api/leads/{lead_id}/stop')
    def stop(lead_id: int, body: S.Stop, user=Depends(current), session=Depends(db)):
        lead = own(session, Lead, lead_id, user)
        svc.stop_contact(session, user.producer_id, lead, 'manuale: ' + body.reason)
        session.execute(update(Draft).where(Draft.producer_id == user.producer_id, Draft.lead_id == lead.id, Draft.status.in_(['pending', 'approved', 'failed'])).values(status='cancelled'))
        session.commit()
        return output(session, lead)

    @app.get('/api/drafts')
    def drafts(user=Depends(current), session=Depends(db)):
        return many(session, Draft, user)

    @app.patch('/api/drafts/{draft_id}')
    def edit(draft_id: int, body: S.DraftEdit, user=Depends(current), session=Depends(db)):
        draft = own(session, Draft, draft_id, user)
        if draft.status in {'sent', 'sending', 'cancelled'} or draft.error:
            fail(session, user, 'bozza.modifica.bloccata', 'Bozza inviata, sospesa o già tentata: modifica non consentita.', draft.lead_id)
        changed = session.execute(update(Draft).where(Draft.id == draft.id, Draft.producer_id == user.producer_id, Draft.status.in_(['pending', 'approved', 'rejected']), Draft.error == '').values(subject=body.subject, body=body.body, status='pending', approved_at=None)).rowcount
        if not changed:
            fail(session, user, 'bozza.modifica.bloccata', 'Stato bozza cambiato durante la richiesta: aggiorna la pagina.', draft.lead_id)
        session.expire_all()
        draft = own(session, Draft, draft_id, user)
        svc.audit(session, user.producer_id, 'bozza.modificata', 'Ogni modifica richiede una nuova approvazione.', draft.lead_id)
        session.commit()
        return output(session, draft)

    @app.post('/api/drafts/{draft_id}/approve')
    def approve(draft_id: int, user=Depends(current), session=Depends(db)):
        draft = own(session, Draft, draft_id, user)
        lead = own(session, Lead, draft.lead_id, user)
        if blocked(lead, draft.kind) or draft.status not in {'pending', 'approved', 'failed'}:
            fail(session, user, 'bozza.approvazione.bloccata', 'Bozza non approvabile oppure contatto sospeso.', lead.id)
        allowed_contact = exists(select(Lead.id).where(Lead.id == draft.lead_id, (Lead.stop_reason == '') | ((Lead.stop_reason == 'reply') & (draft.kind == 'reply'))))
        changed = session.execute(update(Draft).where(Draft.id == draft.id, Draft.producer_id == user.producer_id, Draft.status.in_(['pending', 'approved', 'failed']), Draft.subject == draft.subject, Draft.body == draft.body, allowed_contact).values(status='approved', approved_at=now())).rowcount
        if not changed:
            fail(session, user, 'bozza.approvazione.bloccata', 'Stato o testo cambiato durante la richiesta: aggiorna la pagina.', draft.lead_id)
        session.expire_all()
        draft = own(session, Draft, draft_id, user)
        svc.audit(session, user.producer_id, 'bozza.approvata', 'Testo approvato dall’operatore; invio ancora da eseguire.', lead.id)
        session.commit()
        return output(session, draft)

    @app.post('/api/drafts/{draft_id}/reject')
    def reject(draft_id: int, user=Depends(current), session=Depends(db)):
        draft = own(session, Draft, draft_id, user)
        if draft.status in {'sent', 'sending'}:
            fail(session, user, 'bozza.rifiuto.bloccato', 'Invio già eseguito o in corso.', draft.lead_id)
        changed = session.execute(update(Draft).where(Draft.id == draft.id, Draft.producer_id == user.producer_id, Draft.status.not_in(['sent', 'sending'])).values(status='rejected')).rowcount
        if not changed:
            fail(session, user, 'bozza.rifiuto.bloccato', 'Invio già eseguito o in corso.', draft.lead_id)
        session.expire_all()
        draft = own(session, Draft, draft_id, user)
        if draft.task_id:
            session.get(Task, draft.task_id).status = 'cancelled'
        auto.on_draft_rejected(session, user.producer_id, draft)
        svc.audit(session, user.producer_id, 'bozza.rifiutata', 'Bozza rifiutata dall’operatore.', draft.lead_id)
        session.commit()
        return output(session, draft)

    @app.post('/api/drafts/{draft_id}/send')
    def send(draft_id: int, user=Depends(current), session=Depends(db)):
        draft = own(session, Draft, draft_id, user)
        lead = own(session, Lead, draft.lead_id, user)
        if draft.status == 'sent':
            return output(session, draft)
        auto.campaign_send_guard(session, user.producer_id, draft, settings)
        if blocked(lead, draft.kind):
            fail(session, user, 'invio.bloccato', 'Ricontatti interrotti: ' + lead.stop_reason, lead.id)
        if not lead.email:
            fail(session, user, 'invio.bloccato', 'Email mancante: nessun indirizzo viene inventato.', lead.id)
        contact_allowed = exists(select(Lead.id).where(Lead.id == draft.lead_id, (Lead.stop_reason == '') | ((Lead.stop_reason == 'reply') & (draft.kind == 'reply'))))
        claimed = session.execute(update(Draft).where(Draft.id == draft.id, Draft.producer_id == user.producer_id, Draft.status == 'approved', Draft.subject == draft.subject, Draft.body == draft.body, contact_allowed).values(status='sending')).rowcount
        if not claimed:
            session.rollback()
            session.expire_all()
            existing = own(session, Draft, draft.id, user)
            if existing.status == 'sent':
                return output(session, existing)
            fail(session, user, 'invio.bloccato', 'Serve una bozza approvata; un altro invio può essere già in corso.', lead.id)
        session.commit()
        session.refresh(draft)
        try:
            sent = auto.email_provider(settings).send(lead.email, draft.subject, draft.body, draft.idempotency_key)
        except adapters.IntegrationError as error:
            draft.status, draft.error = 'failed', str(error)
            svc.audit(session, user.producer_id, 'invio.errore', str(error) + ' Eventuale retry usa la stessa chiave, testo immutabile.', lead.id)
            if error.code == 'invalid_recipient':
                svc.stop_contact(session, user.producer_id, lead, 'hard_bounce')
            session.commit()
            raise HTTPException(503, str(error))
        # Reload after provider latency. A reply/stop received in the meantime stays authoritative.
        sent_lead_id = draft.lead_id
        session.expire_all()
        session.execute(update(Producer).where(Producer.id == user.producer_id).values(profile=Producer.profile))
        lead = session.scalar(select(Lead).where(Lead.id == sent_lead_id, Lead.producer_id == user.producer_id).with_for_update().execution_options(populate_existing=True))
        draft = own(session, Draft, draft_id, user)
        draft.status, draft.sent_at, draft.error = 'sent', now(), ''
        draft.simulated, draft.provider_message_id = sent['simulated'], sent['provider_message_id']
        session.add(Message(producer_id=user.producer_id, lead_id=lead.id, draft_id=draft.id, direction='outbound', subject=draft.subject, body=draft.body, simulated=sent['simulated']))
        if draft.task_id:
            session.get(Task, draft.task_id).status = 'completed'
        elif draft.kind == 'outreach' and not lead.stop_reason and not auto.campaign_for_lead(session, user.producer_id, lead.id):
            svc.schedule_followups(session, user.producer_id, lead, profile(session, user))
        if lead.stage in {'new', 'qualified'}:
            lead.stage = 'contacted'
        svc.audit(session, user.producer_id, 'invio.simulato' if sent['simulated'] else 'email.inviata', 'Registrazione demo, nessuna email reale.' if sent['simulated'] else 'Provider email ha confermato l’invio.', lead.id)
        auto.on_draft_sent(session, user.producer_id, draft, settings)
        session.commit()
        return output(session, draft)

    @app.get('/api/tasks')
    def tasks(user=Depends(current), session=Depends(db)):
        return many(session, Task, user)

    @app.post('/api/tasks/{task_id}/cancel')
    def cancel_task(task_id: int, user=Depends(current), session=Depends(db)):
        task = own(session, Task, task_id, user)
        if task.status == 'completed':
            raise HTTPException(409, 'Attività già completata.')
        task.status = 'cancelled'
        auto.cancel_followup(session, user.producer_id, task)
        session.execute(update(Draft).where(Draft.task_id == task.id, Draft.status.in_(['pending', 'approved'])).values(status='cancelled'))
        svc.audit(session, user.producer_id, 'attività.annullata', 'Attività annullata dall’operatore.', task.lead_id)
        session.commit()
        return output(session, task)

    @app.post('/api/worker/run')
    def worker(user=Depends(current), session=Depends(db)):
        result = svc.run_due(session, user.producer_id)
        result['automation'] = auto.run_due(session, settings, tenant=user.producer_id)
        return result

    @app.get('/api/conversations')
    def conversations(user=Depends(current), session=Depends(db)):
        return many(session, Message, user)

    @app.get('/api/appointments')
    def appointments(user=Depends(current), session=Depends(db)):
        return many(session, Appointment, user)

    @app.post('/api/appointments', status_code=201)
    def book(body: S.Booking, user=Depends(current), session=Depends(db)):
        lead = own(session, Lead, body.lead_id, user)
        if body.start_at.tzinfo is None or body.end_at.tzinfo is None:
            raise HTTPException(422, 'Le date devono includere il fuso orario.')
        start, end = body.start_at.astimezone(timezone.utc), body.end_at.astimezone(timezone.utc)
        if end <= start or start <= datetime.now(timezone.utc):
            raise HTTPException(422, 'Inserisci un intervallo futuro con fine successiva all’inizio.')
        data = {'lead_id': lead.id, 'title': body.title, 'start_at': start.isoformat(), 'end_at': end.isoformat()}
        key = hashlib.sha256(f'{user.producer_id}:{json.dumps(data, sort_keys=True)}'.encode()).hexdigest()
        # Producer row write serializes booking creation and overlap check, also on SQLite.
        session.execute(update(Producer).where(Producer.id == user.producer_id).values(profile=Producer.profile))
        appointment = session.scalar(select(Appointment).where(Appointment.booking_key == key, Appointment.producer_id == user.producer_id))
        if appointment and appointment.status in {'simulated', 'confirmed'}:
            session.rollback()
            return output(session, appointment)
        if appointment and appointment.status == 'booking':
            fail(session, user, 'calendario.bloccato', 'Prenotazione già in corso; attendere l’esito.', lead.id)
        if settings.demo_mode and session.scalar(select(Appointment.id).where(Appointment.producer_id == user.producer_id, Appointment.status.in_(['simulated', 'confirmed', 'booking']), Appointment.start_at < data['end_at'], Appointment.end_at > data['start_at'])):
            fail(session, user, 'calendario.conflitto', 'Appuntamento sovrapposto a una prenotazione esistente.', lead.id)
        if appointment is None:
            appointment = Appointment(producer_id=user.producer_id, **data, booking_key=key, status='booking')
            session.add(appointment)
        else:
            appointment.status = 'booking'
        session.commit()
        try:
            result = adapters.book_calendar(settings, {**data, 'contact_email': lead.email}, key)
        except adapters.IntegrationError as error:
            appointment.status = 'failed'
            svc.audit(session, user.producer_id, 'calendario.errore', str(error) + ' Nessun appuntamento confermato.', lead.id)
            session.commit()
            raise HTTPException(503, str(error))
        # A stop/unsubscribe received while the provider was booking remains authoritative.
        session.expire_all()
        session.execute(update(Producer).where(Producer.id == user.producer_id).values(profile=Producer.profile))
        lead = session.scalar(select(Lead).where(Lead.id == body.lead_id, Lead.producer_id == user.producer_id).with_for_update().execution_options(populate_existing=True))
        appointment = own(session, Appointment, appointment.id, user)
        appointment.provider_event_id, appointment.simulated = result['provider_event_id'], result['simulated']
        appointment.status = 'simulated' if result['simulated'] else 'confirmed'
        if lead.stop_reason in {'', 'reply'}:
            svc.stop_contact(session, user.producer_id, lead, 'meeting')
            lead.stage = 'appointment'
        svc.audit(session, user.producer_id, 'appuntamento.simulato' if result['simulated'] else 'appuntamento.confermato', 'Evento solo demo.' if result['simulated'] else 'Prenotazione riuscita sul provider calendario.', lead.id)
        auto.on_booking(session, user.producer_id, lead, appointment, settings)
        session.commit()
        return output(session, appointment)

    @app.get('/api/handoffs')
    def handoffs(user=Depends(current), session=Depends(db)):
        return many(session, Handoff, user)

    @app.post('/api/handoffs/{handoff_id}/resolve')
    def resolve(handoff_id: int, user=Depends(current), session=Depends(db)):
        handoff = own(session, Handoff, handoff_id, user)
        handoff.status = 'resolved'
        svc.audit(session, user.producer_id, 'commerciale.risolto', 'Passaggio al commerciale completato dall’operatore.', handoff.lead_id)
        session.commit()
        return output(session, handoff)

    @app.post('/api/leads/{lead_id}/crm-sync')
    def sync(lead_id: int, user=Depends(current), session=Depends(db)):
        lead = own(session, Lead, lead_id, user)
        try:
            payload = output(session, lead)
            version = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]
            result = adapters.sync_crm(settings, payload, f'producer-{user.producer_id}-lead-{lead.id}-{version}')
        except adapters.IntegrationError as error:
            fail(session, user, 'crm.errore', str(error), lead.id, status=503)
        svc.audit(session, user.producer_id, 'crm.simulato' if result['simulated'] else 'crm.sincronizzato', 'Sincronizzazione demo.' if result['simulated'] else 'Sincronizzazione confermata dal provider.', lead.id)
        session.commit()
        return result

    @app.get('/api/audit')
    def audits(user=Depends(current), session=Depends(db)):
        return many(session, Audit, user)

    @app.get('/api/dashboard')
    def dashboard(user=Depends(current), session=Depends(db)):
        tenant = user.producer_id
        def count(model, *conditions):
            return session.scalar(select(func.count()).select_from(model).where(model.producer_id == tenant, *conditions))
        metrics = {'leads': count(Lead), 'qualified': count(Lead, Lead.score.is_not(None)), 'pending_drafts': count(Draft, Draft.status.in_(['pending', 'approved'])), 'scheduled_tasks': count(Task, Task.status.in_(['scheduled', 'needs_approval', 'automation_managed'])), 'appointments': count(Appointment, Appointment.status.in_(['simulated', 'confirmed'])), 'sent_real': count(Message, Message.direction == 'outbound', Message.simulated == False), 'sent_demo': count(Message, Message.direction == 'outbound', Message.simulated == True), 'replies': count(Message, Message.direction == 'inbound')}
        return {'metrics': metrics, 'pipeline': [{'stage': stage, 'count': total} for stage, total in session.execute(select(Lead.stage, func.count()).where(Lead.producer_id == tenant).group_by(Lead.stage))], 'recent_activity': many(session, Audit, user)[:8], 'upcoming_tasks': [output(session, item) for item in session.scalars(select(Task).where(Task.producer_id == tenant, Task.status.in_(['scheduled', 'needs_approval', 'automation_managed'])).order_by(Task.due_at).limit(6)).all()]}

    register_automation_routes(app, db, current, settings)
    return app

app = create_app()
