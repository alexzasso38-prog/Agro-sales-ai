"""Validated campaign controls; all defaults require human communication approval."""
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)


class CampaignCreate(Strict):
    name: str = Field(min_length=1, max_length=250)
    objective: str = Field(default='Acquisire potenziali clienti HORECA.', max_length=5000)
    target: str = Field(default='Ristoranti', min_length=1, max_length=200)
    city: str = Field(default='Milano', min_length=1, max_length=200)
    lead_count: int = Field(default=20, ge=1, le=500)
    product_ids: list[str] = Field(default_factory=list, max_length=100)
    minimum_score: int = Field(default=70, ge=0, le=100)
    outreach_mode: Literal['DRAFT', 'APPROVAL_REQUIRED', 'AUTO_SEND'] = 'APPROVAL_REQUIRED'
    followup_enabled: bool = True
    followup_days: list[int] = Field(default_factory=lambda: [0, 3, 7, 14], max_length=10)
    handoff_threshold: int = Field(default=85, ge=0, le=100)
    autonomy_level: Literal['LOW', 'MEDIUM', 'HIGH'] = 'LOW'
    provider: Literal['mock', 'csv', 'configured'] = 'mock'
    csv_rows: list[dict] = Field(default_factory=list, max_length=500)
    demo_day_seconds: float = Field(default=10, ge=1, le=3600)
    max_emails: int = Field(default=100, ge=1, le=1000)
    max_followups: int = Field(default=3, ge=0, le=9)
    rate_limit_per_minute: int = Field(default=20, ge=1, le=100)
    authorize_auto_send: bool = False

    @model_validator(mode='before')
    @classmethod
    def normalize_aliases(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        for alias, canonical in [('min_score', 'minimum_score'), ('sequence_days', 'followup_days'),
                                 ('autonomy', 'autonomy_level'), ('day_seconds', 'demo_day_seconds')]:
            if alias in value:
                if canonical in value:
                    raise ValueError(f'Specifica soltanto {canonical}, senza duplicare {alias}.')
                value[canonical] = value.pop(alias)
        return value

    @field_validator('name', 'target', 'city')
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Il campo non può essere vuoto.')
        return value

    @field_validator('followup_days')
    @classmethod
    def days(cls, value):
        if not value or value[0] != 0 or value != sorted(set(value)) or any(day < 0 or day > 365 for day in value):
            raise ValueError('La sequenza deve iniziare dal giorno 0 e contenere giorni crescenti tra 0 e 365.')
        return value

    @model_validator(mode='after')
    def csv_present(self):
        if self.provider == 'csv' and not self.csv_rows:
            raise ValueError('Importa almeno una riga CSV per usare il provider CSV.')
        return self


class Accelerate(Strict):
    seconds: float = Field(default=30, gt=0, le=86400)


class SimulateResponse(Strict):
    preset: Literal['interested', 'price_list', 'sample', 'price_objection', 'not_interested', 'meeting', 'unsubscribe', 'out_of_office'] = 'interested'
    body: str | None = Field(default=None, min_length=1, max_length=30000)
    subject: str = Field(default='', max_length=500)
    event: Literal['reply', 'rejection', 'unsubscribe', 'hard_bounce'] = 'reply'


class SimulateVoice(Strict):
    preset: str = Field(default='interested', max_length=100)
    transcript: str | None = Field(default=None, min_length=1, max_length=30000)


class HandoffAction(Strict):
    note: str = Field(default='', max_length=3000)


class ExcludeLead(Strict):
    reason: str = Field(default='Escluso dalla campagna dall’operatore.', min_length=1, max_length=1000)
