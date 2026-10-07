import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app

@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(database_url=f'sqlite:///{tmp_path / "test.db"}'))
    with TestClient(app) as client:
        response = client.post('/api/auth/login', json={'email': 'demo@agrosales.test', 'password': 'DemoAgro2026!'})
        assert response.status_code == 200
        client.headers['Authorization'] = f'Bearer {response.json()["access_token"]}'
        yield client

@pytest.fixture
def lead(client):
    return client.post('/api/leads', json={'company_name': 'Ristorante test', 'city': 'Milano', 'email': 'purchasing@restaurant.test', 'business_type': 'Ristorante', 'source': 'Fixture test locale', 'menu_text': 'Pomodori datterini e olio extravergine.'}).json()

@pytest.fixture
def draft(client, lead):
    response = client.post(f'/api/leads/{lead["id"]}/draft', json={})
    assert response.status_code == 201
    return response.json()
