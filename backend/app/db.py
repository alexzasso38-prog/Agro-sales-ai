from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, event, String, Text, ForeignKey, JSON, UniqueConstraint, Integer, Boolean
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

def now():
    return datetime.now(timezone.utc).isoformat()

class Base(DeclarativeBase):
    pass

class Producer(Base):
    __tablename__ = 'producers'
    id: Mapped[int] = mapped_column(primary_key=True)
    profile: Mapped[dict] = mapped_column(JSON, default=dict)

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(Text)

class Lead(Base):
    __tablename__ = 'leads'
    __table_args__ = (UniqueConstraint('producer_id', 'dedup_email'), UniqueConstraint('producer_id', 'dedup_identity'))
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    company_name: Mapped[str] = mapped_column(String(250))
    contact_name: Mapped[str] = mapped_column(String(200), default='')
    email: Mapped[str] = mapped_column(String(254), default='')
    phone: Mapped[str] = mapped_column(String(100), default='')
    city: Mapped[str] = mapped_column(String(200), default='')
    business_type: Mapped[str] = mapped_column(String(100), default='')
    website: Mapped[str] = mapped_column(Text, default='')
    menu_text: Mapped[str] = mapped_column(Text, default='')
    notes: Mapped[str] = mapped_column(Text, default='')
    source: Mapped[str] = mapped_column(Text)
    source_date: Mapped[str] = mapped_column(String(50), default=now)
    stage: Mapped[str] = mapped_column(String(30), default='new')
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qualification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    stop_reason: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[str] = mapped_column(String(50), default=now)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    dedup_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    dedup_identity: Mapped[str] = mapped_column(String(500))

class Draft(Base):
    __tablename__ = 'drafts'
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id'), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey('tasks.id'), nullable=True, unique=True)
    kind: Mapped[str] = mapped_column(String(30), default='outreach')
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default='pending')
    created_at: Mapped[str] = mapped_column(String(50), default=now)
    approved_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sent_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(Text, default='')
    provider_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)

class Message(Base):
    __tablename__ = 'messages'
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id'), index=True)
    draft_id: Mapped[int | None] = mapped_column(ForeignKey('drafts.id'), nullable=True, unique=True)
    direction: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(Text, default='')
    body: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(40), default='')
    created_at: Mapped[str] = mapped_column(String(50), default=now)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)

class Task(Base):
    __tablename__ = 'tasks'
    __table_args__ = (UniqueConstraint('lead_id', 'step'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id'), index=True)
    kind: Mapped[str] = mapped_column(String(40), default='followup')
    due_at: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default='scheduled')
    step: Mapped[int] = mapped_column(Integer)
    last_error: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[str] = mapped_column(String(50), default=now)

class Audit(Base):
    __tablename__ = 'audit'
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey('leads.id'), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(50), default=now)

class Appointment(Base):
    __tablename__ = 'appointments'
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id'), index=True)
    title: Mapped[str] = mapped_column(Text)
    start_at: Mapped[str] = mapped_column(String(50))
    end_at: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default='pending')
    provider_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    booking_key: Mapped[str] = mapped_column(String(100), unique=True)

class Handoff(Base):
    __tablename__ = 'handoffs'
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id'), index=True)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default='open')
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(50), default=now)

def database(url):
    parsed = make_url(url)
    if parsed.get_backend_name() == 'sqlite' and parsed.database and parsed.database != ':memory:':
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 30} if url.startswith('sqlite:') else {}, pool_pre_ping=True)
    if url.startswith('sqlite:'):
        @event.listens_for(engine, 'connect')
        def sqlite_pragmas(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA journal_mode=WAL')
    return engine, sessionmaker(engine, expire_on_commit=False)
