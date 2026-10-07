"""Configuration stays on the server; no secret is serialized by the API."""
from dataclasses import dataclass, field
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env')

def flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {'1', 'true', 'yes'}

@dataclass
class Settings:
    demo_mode: bool = field(default_factory=lambda: flag('DEMO_MODE', True))
    database_url: str = field(default_factory=lambda: os.getenv('DATABASE_URL', f'sqlite:///{ROOT / "backend/data/agro.db"}'))
    jwt_secret: str = field(default_factory=lambda: os.getenv('JWT_SECRET', 'demo-only-secret-never-use-in-production-2026'))
    token_expire_minutes: int = field(default_factory=lambda: int(os.getenv('TOKEN_EXPIRE_MINUTES', '480')))
    allow_external_integrations: bool = field(default_factory=lambda: flag('ALLOW_EXTERNAL_INTEGRATIONS'))
    openai_api_key: str = field(default_factory=lambda: os.getenv('OPENAI_API_KEY', ''))
    openai_model: str = field(default_factory=lambda: os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'))
    email_provider_url: str = field(default_factory=lambda: os.getenv('EMAIL_PROVIDER_URL', ''))
    email_api_key: str = field(default_factory=lambda: os.getenv('EMAIL_API_KEY', ''))
    email_from: str = field(default_factory=lambda: os.getenv('EMAIL_FROM', ''))
    search_provider_url: str = field(default_factory=lambda: os.getenv('SEARCH_PROVIDER_URL', ''))
    search_api_key: str = field(default_factory=lambda: os.getenv('SEARCH_API_KEY', ''))
    calendar_provider_url: str = field(default_factory=lambda: os.getenv('CALENDAR_PROVIDER_URL', ''))
    calendar_api_key: str = field(default_factory=lambda: os.getenv('CALENDAR_API_KEY', ''))
    crm_provider_url: str = field(default_factory=lambda: os.getenv('CRM_PROVIDER_URL', ''))
    crm_api_key: str = field(default_factory=lambda: os.getenv('CRM_API_KEY', ''))
    voice_provider_url: str = field(default_factory=lambda: os.getenv('VOICE_PROVIDER_URL', ''))
    voice_api_key: str = field(default_factory=lambda: os.getenv('VOICE_API_KEY', ''))
    cors_origins: list[str] = field(default_factory=lambda: os.getenv('CORS_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173').split(','))
    def __post_init__(self):
        if not self.demo_mode:
            if len(self.jwt_secret) < 32 or self.jwt_secret.startswith('demo-only'):
                raise ValueError('JWT_SECRET deve contenere almeno 32 caratteri ed essere diverso dal segreto demo.')
            if self.database_url.startswith('sqlite:'):
                raise ValueError('In produzione configura DATABASE_URL con PostgreSQL (postgresql+psycopg://).')
