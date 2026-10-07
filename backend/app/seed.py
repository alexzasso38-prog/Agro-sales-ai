"""Explicitly fictitious fixtures. Never loaded in production."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import User, Producer, Lead, Message, Task, Appointment
from .auth import hash_password
from .services import audit, qualification, create_draft, make_handoff

DEMO_PROFILE = {
    'company_name': 'Cascina Verde · azienda fittizia',
    'description': 'DEMO: produttore immaginario di ortaggi, formaggi premium, olio EVO, salumi e conserve per la ristorazione.',
    'contact_name': 'Giulia Rossi (personaggio demo)', 'contact_email': 'giulia@cascinaverde.test', 'phone': '',
    'minimum_order': '€ 120', 'service_areas': ['Milano', 'Monza', 'Como'],
    'delivery_terms': 'Consegna il martedì e il venerdì; disponibilità da confermare prima dell’ordine.',
    'payment_terms': 'Bonifico a 30 giorni dalla fattura.', 'followup_days': [3, 7],
    'catalog': [
        {'id': 'p1', 'name': 'Pomodori datterini', 'category': 'ortaggi', 'unit': 'kg', 'price': 3.8, 'description': 'Pomodori da filiera locale. Prodotto fittizio demo.'},
        {'id': 'p2', 'name': 'Olio extravergine', 'category': 'olio', 'unit': 'l', 'price': 12.5, 'description': 'Bottiglia da 1 litro. Prodotto fittizio demo.'},
        {'id': 'p3', 'name': 'Passata di pomodoro', 'category': 'conserve', 'unit': 'bottiglia', 'price': 3.2, 'description': 'Formato da 700 g. Prodotto fittizio demo.'},
        {'id': 'demo-formaggi', 'name': 'Formaggi premium DEMO', 'category': 'formaggi', 'unit': 'kg', 'price': 18.0, 'description': 'Prodotto completamente fittizio per lo scenario campagne.'},
        {'id': 'demo-salumi', 'name': 'Salumi artigianali DEMO', 'category': 'salumi', 'unit': 'kg', 'price': 22.0, 'description': 'Prodotto completamente fittizio per lo scenario campagne.'},
    ],
}

DEMO_LEADS = [
    {'company_name': 'Trattoria del Borgo · fittizia', 'contact_name': 'Marco Bianchi (demo)', 'email': 'acquisti@trattoriaborgo.test', 'city': 'Milano', 'business_type': 'Ristorante', 'menu_text': 'Menu fittizio: pasta con pomodori datterini, verdure di stagione, olio extravergine.', 'stage': 'qualified'},
    {'company_name': 'Hotel Lago Sereno · fittizio', 'contact_name': 'Elena Conti (demo)', 'email': 'chef@lagosereno.test', 'city': 'Como', 'business_type': 'Hotel', 'menu_text': 'Menu fittizio: colazione, buffet di ortaggi e bruschette con olio extravergine.', 'stage': 'interested'},
    {'company_name': 'Bistrot Radici · fittizio', 'email': 'info@radici.test', 'city': 'Monza', 'business_type': 'Ristorante', 'menu_text': 'Menu fittizio: passata di pomodoro e piatti stagionali.', 'stage': 'new'},
    {'company_name': 'Catering Campo Aperto · fittizio', 'email': '', 'city': 'Bergamo', 'business_type': 'Catering', 'menu_text': '', 'stage': 'new'},
]

def seed(session):
    try:
        _seed(session)
    except IntegrityError:
        # API and CLI worker may start concurrently; the unique demo account wins.
        session.rollback()
        if not session.scalar(select(User.id).where(User.email == 'demo@agrosales.test')):
            raise

def _seed(session):
    if session.scalar(select(User.id).where(User.email == 'demo@agrosales.test')):
        return
    producer = Producer(profile=DEMO_PROFILE)
    session.add(producer)
    session.flush()
    session.add(User(producer_id=producer.id, email='demo@agrosales.test', name='Giulia · demo', password_hash=hash_password('DemoAgro2026!')))
    leads = []
    for item in DEMO_LEADS:
        lead = Lead(producer_id=producer.id, **item, source='Dataset locale fittizio Agro Sales AI', notes='Contatto completamente inventato per la demo; nessun recapito reale.', demo=True, dedup_email=item['email'] or None, dedup_identity=(item['company_name'] + '|' + item['city']).casefold())
        session.add(lead)
        session.flush()
        leads.append(lead)
    leads[0].qualification = qualification(leads[0], producer.profile)
    leads[0].score = leads[0].qualification['score']
    create_draft(session, producer.id, leads[0], producer.profile)
    leads[1].stop_reason = 'reply'
    session.add(Message(producer_id=producer.id, lead_id=leads[1].id, direction='inbound', subject='Interesse per il catalogo — messaggio fittizio', body='Vorremmo valutare un campione di olio; potete fornire informazioni? Dati demo inventati.', classification='interested', simulated=True))
    create_draft(session, producer.id, leads[1], producer.profile, kind='reply', handoff=True)
    make_handoff(session, producer.id, leads[1], 'Quantità e tempistiche non indicate nella risposta demo.', 'Il commerciale deve verificare richieste campioni e disponibilità. Tutti i dati sono fittizi.')
    due = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    session.add(Task(producer_id=producer.id, lead_id=leads[2].id, step=1, due_at=due))
    tomorrow = datetime.now(timezone.utc) + timedelta(days=2)
    session.add(Appointment(producer_id=producer.id, lead_id=leads[1].id, title='Presentazione catalogo — appuntamento fittizio', start_at=tomorrow.isoformat(), end_at=(tomorrow + timedelta(minutes=30)).isoformat(), status='simulated', provider_event_id='demo-fixture-calendar', simulated=True, booking_key=f'demo-fixture-{producer.id}'))
    audit(session, producer.id, 'demo.inizializzata', 'Dati completamente fittizi, nessun invio o chiamata reale.')
    session.commit()
