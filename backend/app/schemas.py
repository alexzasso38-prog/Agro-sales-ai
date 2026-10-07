from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator
import re

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Login(Strict):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=256)

class Register(Login):
    name: str = Field(min_length=1, max_length=200)
    company_name: str = Field(min_length=1, max_length=250)
    @field_validator('password')
    @classmethod
    def strong(cls, value):
        if len(value) < 12:
            raise ValueError('La password deve contenere almeno 12 caratteri.')
        return value

class Product(Strict):
    id: str
    name: str = Field(min_length=1, max_length=250)
    category: str = Field(default='', max_length=100)
    unit: str = Field(default='kg', max_length=50)
    price: float = Field(ge=0, le=100000)
    description: str = Field(default='', max_length=5000)

class Profile(Strict):
    company_name: str = Field(min_length=1, max_length=250)
    description: str = Field(default='', max_length=10000)
    contact_name: str = Field(default='', max_length=200)
    contact_email: str = Field(default='', max_length=254)
    phone: str = Field(default='', max_length=100)
    minimum_order: str = Field(default='', max_length=1000)
    service_areas: list[str] = Field(default_factory=list, max_length=100)
    delivery_terms: str = Field(default='', max_length=5000)
    payment_terms: str = Field(default='', max_length=5000)
    catalog: list[Product] = Field(default_factory=list, max_length=500)
    followup_days: list[int] = Field(default_factory=lambda: [3, 7], max_length=10)
    @field_validator('followup_days')
    @classmethod
    def days(cls, value):
        if any(day < 1 or day > 365 for day in value) or value != sorted(set(value)):
            raise ValueError('Le scadenze devono essere crescenti, uniche e tra 1 e 365 giorni.')
        return value

class LeadInput(Strict):
    company_name: str = Field(min_length=1, max_length=250)
    contact_name: str = Field(default='', max_length=200)
    email: str = Field(default='', max_length=254)
    phone: str = Field(default='', max_length=100)
    city: str = Field(default='', max_length=200)
    business_type: str = Field(default='', max_length=100)
    website: str = Field(default='', max_length=2048)
    menu_text: str = Field(default='', max_length=30000)
    notes: str = Field(default='', max_length=10000)
    source: str = Field(min_length=1, max_length=2000)
    @field_validator('email')
    @classmethod
    def email_valid(cls, value):
        value = value.strip().lower()
        if value and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Indirizzo email non valido.')
        return value
    @field_validator('company_name', 'source')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Il valore non può essere vuoto.')
        return value.strip()

class LeadPatch(Strict):
    stage: Literal['new', 'discovered', 'qualifying', 'qualified', 'low_priority', 'outreach_ready', 'contacted', 'follow_up', 'replied', 'interested', 'meeting', 'appointment', 'handoff', 'won', 'lost', 'do_not_contact'] | None = None
    notes: str | None = Field(default=None, max_length=10000)

class Search(Strict):
    query: str = Field(min_length=1, max_length=300)
    city: str = Field(default='', max_length=200)

class DraftInput(Strict):
    kind: Literal['outreach', 'reply'] = 'outreach'
    instructions: str = Field(default='', max_length=5000)

class DraftEdit(Strict):
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=30000)

class Reply(Strict):
    body: str = Field(min_length=1, max_length=30000)
    subject: str = Field(default='', max_length=500)
    event: Literal['reply', 'rejection', 'unsubscribe', 'hard_bounce'] = 'reply'
    external_event_id: str | None = Field(default=None, min_length=1, max_length=200)

class Stop(Strict):
    reason: str = Field(min_length=1, max_length=1000)

class Booking(Strict):
    lead_id: int
    title: str = Field(min_length=1, max_length=500)
    start_at: datetime
    end_at: datetime
