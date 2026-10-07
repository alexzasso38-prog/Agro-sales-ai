"""Independent regressions for concurrent approval, stops and ambiguous retries.

All adapters are local fakes; no email provider or other external host is called.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.config import Settings
from app.main import create_app
from app import integrations


@pytest.fixture
def setup(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'review.db'}", demo_mode=True))
    with TestClient(app) as client:
        auth = client.post("/api/auth/register", json={
            "name": "Verifica concorrenza", "email": "concorrenza@review.test",
            "password": "ReviewLocale2026!", "company_name": "Produttore fittizio review",
        })
        assert auth.status_code == 201
        headers = {"Authorization": f"Bearer {auth.json()['access_token']}"}
        profile = client.get("/api/profile", headers=headers).json()
        profile["catalog"] = [{"id": "p-review", "name": "Olio demo", "category": "olio", "unit": "l", "price": 12.5, "description": "Fittizio"}]
        profile["followup_days"] = [1, 3]
        assert client.put("/api/profile", headers=headers, json=profile).status_code == 200
        lead = client.post("/api/leads", headers=headers, json={
            "company_name": "Ristorante fittizio review", "email": "info@ristorante-review.test",
            "source": "Fixture fittizia test review",
        }).json()
        draft = client.post(f"/api/leads/{lead['id']}/draft", headers=headers, json={"kind": "outreach"}).json()
        assert client.post(f"/api/drafts/{draft['id']}/approve", headers=headers).status_code == 200
        yield app, client, headers, lead, draft


def simulated_success(key):
    return {"simulated": True, "provider_message_id": f"review-{key}"}


def test_edit_cannot_overwrite_a_concurrently_claimed_send(setup, monkeypatch):
    app, client, headers, lead, draft = setup
    edit_ready, release_edit, provider_ready, release_provider = (Event() for _ in range(4))
    edited_subject = "Soggetto review nuovo non approvato"
    captured = []

    def before_sql(connection, cursor, statement, parameters, context, many):
        # Stop after PATCH has read/validated the old approved status but before
        # its SQL mutation. Then let send atomically claim the old approved draft.
        if statement.lstrip().upper().startswith("UPDATE DRAFTS") and edited_subject in str(parameters):
            edit_ready.set()
            assert release_edit.wait(10), "Il test non ha rilasciato la modifica"

    def fake_send(settings, recipient, subject, body, key):
        captured.append((subject, body))
        provider_ready.set()
        assert release_provider.wait(10), "Il test non ha rilasciato il provider locale"
        return simulated_success(key)

    monkeypatch.setattr(integrations, "send_email", fake_send)
    event.listen(app.state.engine, "before_cursor_execute", before_sql)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            editing = pool.submit(client.patch, f"/api/drafts/{draft['id']}", headers=headers,
                                  json={"subject": edited_subject, "body": "Testo nuovo non approvato"})
            assert edit_ready.wait(10), "PATCH non ha raggiunto la mutazione SQL"
            sending = pool.submit(client.post, f"/api/drafts/{draft['id']}/send", headers=headers)
            assert provider_ready.wait(10), "Invio non ha acquisito la bozza"
            release_edit.set()
            edited = editing.result(timeout=10)
            release_provider.set()
            sent = sending.result(timeout=10)
        assert edited.status_code == 409
        assert sent.status_code == 200
        stored = next(item for item in client.get("/api/drafts", headers=headers).json() if item["id"] == draft["id"])
        message = client.get("/api/conversations", headers=headers).json()[0]
        assert stored["status"] == "sent"
        assert stored["subject"] == message["subject"] == captured[0][0] == draft["subject"]
        assert stored["body"] == message["body"] == captured[0][1] == draft["body"]
    finally:
        release_edit.set()
        release_provider.set()
        event.remove(app.state.engine, "before_cursor_execute", before_sql)


def test_reply_during_inflight_send_cannot_create_new_followups(setup, monkeypatch):
    app, client, headers, lead, draft = setup
    provider_ready, release_provider = Event(), Event()

    def fake_send(settings, recipient, subject, body, key):
        provider_ready.set()
        assert release_provider.wait(10), "Il test non ha rilasciato il provider locale"
        return simulated_success(key)

    monkeypatch.setattr(integrations, "send_email", fake_send)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            sending = pool.submit(client.post, f"/api/drafts/{draft['id']}/send", headers=headers)
            assert provider_ready.wait(10)
            response = client.post(f"/api/leads/{lead['id']}/reply", headers=headers,
                                   json={"body": "Non scrivetemi più.", "event": "unsubscribe"})
            assert response.status_code == 200
            release_provider.set()
            assert sending.result(timeout=10).status_code == 200
        assert client.get(f"/api/leads/{lead['id']}", headers=headers).json()["stop_reason"] == "unsubscribe"
        assert client.get("/api/tasks", headers=headers).json() == []
    finally:
        release_provider.set()


def test_ambiguous_retry_preserves_payload_and_idempotency_key(setup, monkeypatch):
    app, client, headers, lead, draft = setup
    calls = []

    def fake_send(settings, recipient, subject, body, key):
        calls.append((recipient, subject, body, key))
        if len(calls) == 1:
            raise integrations.IntegrationError("Timeout simulato dopo possibile invio.", "provider_timeout", True)
        return simulated_success(key)

    monkeypatch.setattr(integrations, "send_email", fake_send)
    assert client.post(f"/api/drafts/{draft['id']}/send", headers=headers).status_code == 503
    assert client.patch(f"/api/drafts/{draft['id']}", headers=headers,
                        json={"subject": "Nuovo soggetto", "body": "Nuovo testo"}).status_code == 409
    assert client.post(f"/api/drafts/{draft['id']}/approve", headers=headers).status_code == 200
    assert client.post(f"/api/drafts/{draft['id']}/send", headers=headers).status_code == 200
    assert client.post(f"/api/drafts/{draft['id']}/send", headers=headers).status_code == 200
    assert len(calls) == 2 and calls[0] == calls[1]
    assert len(client.get("/api/conversations", headers=headers).json()) == 1


@pytest.mark.parametrize("body", [
    "Non desidero ricevere altre email.", "Cancellatemi dalla lista.",
    "Non inviatemi altri messaggi.", "Non scrivetemi più.",
])
def test_common_italian_optouts_block_every_outbound_kind(setup, body):
    app, client, headers, lead, draft = setup
    response = client.post(f"/api/leads/{lead['id']}/reply", headers=headers, json={"body": body})
    assert response.status_code == 200
    assert response.json()["classification"] == "unsubscribe"
    assert response.json()["draft"] is None
    assert client.post(f"/api/leads/{lead['id']}/draft", headers=headers, json={"kind": "reply"}).status_code == 409
    assert client.post(f"/api/drafts/{draft['id']}/send", headers=headers).status_code == 409


def test_ai_cannot_add_products_or_commercial_promises_without_numbers(setup, monkeypatch):
    app, client, headers, lead, draft = setup
    # Only the generator is exercised; network-capable adapters remain patched.
    # Mutating the test settings avoids provisioning a real production database.
    app.state.settings.demo_mode = False
    app.state.settings.allow_external_integrations = True
    app.state.settings.openai_api_key = "local-fake-never-used-on-network"
    invented = "Abbiamo tartufi bianchi freschi, consegna immediata garantita e pagamento in contanti accettato."
    monkeypatch.setattr(integrations, "generate_ai", lambda *args, **kwargs: {
        "subject": "Proposta commerciale", "body": invented, "handoff_required": False, "reason": "",
    })
    response = client.post(f"/api/leads/{lead['id']}/draft", headers=headers, json={"kind": "outreach"})
    assert response.status_code == 201
    body = response.json()["body"]
    assert "tartufi" not in body.lower()
    assert "consegna immediata garantita" not in body.lower()
    assert "pagamento in contanti accettato" not in body.lower()
    assert response.json()["status"] == "pending"


def test_ai_qualification_cannot_invent_volumes_suppliers_or_interest(setup, monkeypatch):
    app, client, headers, lead, draft = setup
    app.state.settings.demo_mode = False
    app.state.settings.allow_external_integrations = True
    app.state.settings.openai_api_key = "local-fake-never-used-on-network"
    invented = "Acquista duecento kg al mese da Fornitore Inventato ed è pronto a ordinare."
    monkeypatch.setattr(integrations, "generate_ai", lambda *args, **kwargs: {
        "score": 100, "summary": "Interesse sicuro", "verified_facts": [invented],
        "hypotheses": [invented], "missing_data": [], "method": "Mock locale",
    })
    response = client.post(f"/api/leads/{lead['id']}/qualify", headers=headers)
    assert response.status_code == 200
    qualification = response.json()["qualification"]
    assert invented not in qualification["verified_facts"]
    assert all(invented not in item for item in qualification["hypotheses"])
    assert qualification["score"] != 100
    assert any("Volumi" in item for item in qualification["missing_data"])


def test_crm_sync_versions_use_distinct_idempotency_keys(setup, monkeypatch):
    app, client, headers, lead, draft = setup
    calls = []

    def fake_crm(settings, payload, key):
        calls.append((payload.copy(), key))
        return {"id": "demo-crm", "provider_id": "demo-crm", "simulated": True}

    monkeypatch.setattr(integrations, "sync_crm", fake_crm)
    url = f"/api/leads/{lead['id']}/crm-sync"
    assert client.post(url, headers=headers).status_code == 200
    assert client.post(url, headers=headers).status_code == 200
    assert client.patch(f"/api/leads/{lead['id']}", headers=headers,
                        json={"stage": "interested", "notes": "Esigenze aggiornate dall’operatore."}).status_code == 200
    assert client.post(url, headers=headers).status_code == 200
    assert calls[0] == calls[1]
    assert calls[0][1] != calls[2][1]
    assert calls[2][0]["stage"] == "interested"


def test_unexpected_interruption_does_not_record_success_or_duplicate_send(setup, monkeypatch):
    app, client, headers, lead, draft = setup
    calls = []

    def interrupted(settings, recipient, subject, body, key):
        calls.append(key)
        raise RuntimeError("Interruzione simulata del processo dopo la prenotazione del lavoro")

    monkeypatch.setattr(integrations, "send_email", interrupted)
    url = f"/api/drafts/{draft['id']}/send"
    with pytest.raises(RuntimeError):
        client.post(url, headers=headers)
    assert client.post(url, headers=headers).status_code == 409
    assert len(calls) == 1
    assert client.get("/api/conversations", headers=headers).json() == []
    assert client.get("/api/tasks", headers=headers).json() == []
    metrics = client.get("/api/dashboard", headers=headers).json()["metrics"]
    assert metrics["sent_real"] == metrics["sent_demo"] == 0
