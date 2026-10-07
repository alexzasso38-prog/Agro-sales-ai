"""Additive automation tables sharing the existing application metadata.

Import this module before ``Base.metadata.create_all``. Existing CRM tables and
rows are never altered or removed.
"""
from sqlalchemy import String, Text, ForeignKey, JSON, UniqueConstraint, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, now


class Campaign(Base):
    __tablename__ = 'campaigns'
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    name: Mapped[str] = mapped_column(String(250))
    objective: Mapped[str] = mapped_column(Text, default='Acquisire potenziali clienti HORECA.')
    target: Mapped[str] = mapped_column(String(200), default='Ristoranti')
    city: Mapped[str] = mapped_column(String(200), default='Milano')
    lead_count: Mapped[int] = mapped_column(Integer, default=20)
    status: Mapped[str] = mapped_column(String(30), default='DRAFT', index=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(50), default=now)
    started_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default='')
    demo: Mapped[bool] = mapped_column(Boolean, default=True)


class CampaignLead(Base):
    __tablename__ = 'campaign_leads'
    __table_args__ = (UniqueConstraint('campaign_id', 'lead_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey('campaigns.id'), index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id'), index=True)
    workflow_stage: Mapped[str] = mapped_column(String(40), default='DISCOVERED')
    current_agent: Mapped[str] = mapped_column(String(40), default='qualification')
    qualification: Mapped[dict] = mapped_column(JSON, default=dict)
    source_data: Mapped[dict] = mapped_column(JSON, default=dict)
    draft_id: Mapped[int | None] = mapped_column(ForeignKey('drafts.id'), nullable=True)
    handoff_id: Mapped[int | None] = mapped_column(ForeignKey('handoffs.id'), nullable=True)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String(50), default=now)
    updated_at: Mapped[str] = mapped_column(String(50), default=now)


class AgentRun(Base):
    __tablename__ = 'agent_runs'
    __table_args__ = (UniqueConstraint('campaign_id', 'agent'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey('campaigns.id'), index=True)
    agent: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default='IDLE')
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    current_task: Mapped[str] = mapped_column(Text, default='')
    last_action: Mapped[str] = mapped_column(Text, default='')
    next_action: Mapped[str] = mapped_column(Text, default='')
    tasks_completed: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[str] = mapped_column(String(50), default=now)


class AgentTask(Base):
    __tablename__ = 'agent_tasks'
    __table_args__ = (UniqueConstraint('idempotency_key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey('campaigns.id'), index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey('leads.id'), nullable=True, index=True)
    agent: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default='QUEUED', index=True)
    due_at: Mapped[str] = mapped_column(String(50), default=now, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default='')
    idempotency_key: Mapped[str] = mapped_column(String(200))
    claim_token: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_until: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), default=now)
    completed_at: Mapped[str | None] = mapped_column(String(50), nullable=True)


class AgentEvent(Base):
    __tablename__ = 'agent_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey('campaigns.id'), index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey('leads.id'), nullable=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey('agent_tasks.id'), nullable=True)
    agent: Mapped[str] = mapped_column(String(40))
    event_type: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(50), default=now, index=True)


class AutomationRule(Base):
    __tablename__ = 'automation_rules'
    __table_args__ = (UniqueConstraint('campaign_id', 'name'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey('campaigns.id'), index=True)
    name: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class FollowUpSequence(Base):
    __tablename__ = 'followup_sequences'
    __table_args__ = (UniqueConstraint('campaign_id', 'lead_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey('campaigns.id'), index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id'), index=True)
    status: Mapped[str] = mapped_column(String(30), default='ACTIVE')
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[str] = mapped_column(String(50), default=now)
    stop_reason: Mapped[str] = mapped_column(Text, default='')


class ConversationEvent(Base):
    __tablename__ = 'conversation_events'
    __table_args__ = (UniqueConstraint('producer_id', 'external_event_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey('campaigns.id'), index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id'), index=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey('messages.id'), nullable=True)
    channel: Mapped[str] = mapped_column(String(30), default='email')
    direction: Mapped[str] = mapped_column(String(20), default='inbound')
    event_type: Mapped[str] = mapped_column(String(50), default='reply')
    body: Mapped[str] = mapped_column(Text, default='')
    classification: Mapped[str] = mapped_column(String(50), default='PENDING')
    extracted: Mapped[dict] = mapped_column(JSON, default=dict)
    external_event_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String(50), default=now)


class HandoffOwnership(Base):
    __tablename__ = 'handoff_ownership'
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[int] = mapped_column(ForeignKey('producers.id'), index=True)
    handoff_id: Mapped[int] = mapped_column(ForeignKey('handoffs.id'), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    note: Mapped[str] = mapped_column(Text, default='')
    claimed_at: Mapped[str] = mapped_column(String(50), default=now)
