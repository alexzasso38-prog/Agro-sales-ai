"""Production must never expose the public demo identity retained in a DB.

SQLite is used to isolate this security regression. The config's production flag
is changed after validation only for this test; real Settings requires PostgreSQL.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.config import Settings
from app.db import User
from app.main import create_app

def production_test_settings(path):
    settings = Settings(database_url=f'sqlite:///{path}', jwt_secret='production-test-secret-not-a-real-account-2026')
    settings.demo_mode = False
    return settings

def test_production_refuses_existing_demo_database_without_deleting_data(tmp_path):
    path = tmp_path / 'existing-demo.db'
    demo = create_app(Settings(database_url=f'sqlite:///{path}'))
    with TestClient(demo) as client:
        assert client.post('/api/auth/login', json={'email': 'demo@agrosales.test', 'password': 'DemoAgro2026!'}).status_code == 200
        with demo.state.sessions() as session:
            before = [(user.id, user.email, user.password_hash) for user in session.scalars(select(User)).all()]
    production = create_app(production_test_settings(path))
    with pytest.raises(RuntimeError, match='account demo con credenziali pubbliche'):
        with TestClient(production):
            pytest.fail('Il database demo non deve avviarsi in modalità produzione.')
    with production.state.sessions() as session:
        after = [(user.id, user.email, user.password_hash) for user in session.scalars(select(User)).all()]
    assert after == before

def test_clean_production_never_seeds_or_allows_reserved_demo_identity(tmp_path):
    production = create_app(production_test_settings(tmp_path / 'clean.db'))
    with TestClient(production) as client:
        with production.state.sessions() as session:
            assert session.scalar(select(func.count()).select_from(User)) == 0
        assert client.post('/api/auth/login', json={'email': 'demo@agrosales.test', 'password': 'DemoAgro2026!'}).status_code == 401
        payload = {'name': 'Produttore', 'company_name': 'Azienda produzione', 'email': 'demo@agrosales.test', 'password': 'StrongRegister2026!'}
        assert client.post('/api/auth/register', json=payload).status_code == 422
        assert client.post('/api/auth/register', json={**payload, 'email': 'producer@clean.test'}).status_code == 201
