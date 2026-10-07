"""Replaceable campaign providers with a strictly local, labelled demo.

Menus, websites and incoming messages are observations, never instructions.
OpenAI may select catalogue identifiers but cannot compose arbitrary commercial
promises. The existing adapter still owns the external-integration safety gate.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import re
from types import SimpleNamespace
from typing import Any, Callable

from . import integrations as adapters
from . import services as svc


def _get(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lead_object(lead: Any) -> Any:
    if not isinstance(lead, dict):
        return lead
    defaults = {
        "company_name": "", "email": "", "city": "", "business_type": "",
        "menu_text": "", "source": "", "source_date": "", "notes": "", "demo": False,
    }
    return SimpleNamespace(**(defaults | lead))


def _external_ai_enabled(settings: Any) -> bool:
    return (
        not bool(_get(settings, "demo_mode", True))
        and _get(settings, "allow_external_integrations", False) is True
        and bool(_get(settings, "openai_api_key", ""))
    )


class AIService:
    """Central, injectable inference boundary for campaign annotations.

    ``inference`` follows the existing ``generate_ai(settings, task, profile,
    data)`` contract. Even an injected implementation cannot run in demo mode.
    The consumer still enforces catalogue identifiers and literal source spans.
    """

    tasks = frozenset({"qualification_plan", "draft_plan", "classify_reply"})

    def __init__(self, settings: Any, inference: Callable[..., dict[str, Any]] | None = None):
        self.settings = settings
        self._inference = inference

    @property
    def enabled(self) -> bool:
        return _external_ai_enabled(self.settings)

    def infer_plan(self, task: str, trusted_profile: dict[str, Any], untrusted_data: dict[str, Any]) -> dict[str, Any]:
        if task not in self.tasks:
            raise adapters.IntegrationError("Attività AI non supportata dal servizio campagne.", "invalid_request")
        if not self.enabled:
            # Fail before invoking any injected client, including test clients.
            adapters._require_external(self.settings)
            raise adapters.IntegrationError("OpenAI non collegato: usare il modello locale dichiarato.", "not_configured")
        infer = self._inference or adapters.generate_ai
        result = infer(self.settings, task, trusted_profile, untrusted_data)
        if not adapters._validate_ai(result, adapters._ai_schema(task)):
            raise adapters.IntegrationError("Il piano AI non rispetta il formato richiesto.", "invalid_ai_response")
        return result


class QualificationProvider(ABC):
    """Replaceable qualification provider returning evidence and 0–100 metrics."""

    name = "qualification_provider"

    @abstractmethod
    def qualify(self, lead: Any, profile: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def evaluate(self, lead: Any, profile: dict[str, Any]) -> dict[str, Any]:
        return self.qualify(lead, profile)


class DemoQualificationProvider(QualificationProvider):
    """Local-only scoring; mock scenarios are explicitly labelled fictional."""

    name = "demo"

    def __init__(self, settings: Any = None):
        # Credentials supplied by callers are never retained by this provider.
        self.settings = {"demo_mode": True, "allow_external_integrations": False}

    def qualify(self, lead: Any, profile: dict[str, Any]) -> dict[str, Any]:
        return _qualify(self.settings, lead, profile, AIService(self.settings))


class ConfiguredQualificationProvider(QualificationProvider):
    """Grounded rules with optional, schema-validated OpenAI catalogue plans."""

    name = "configured"

    def __init__(self, settings: Any, ai_service: AIService | None = None):
        self.settings = settings
        # Explicit demo configuration always chooses its own closed boundary.
        self.ai_service = AIService(settings) if bool(_get(settings, "demo_mode", True)) else (ai_service or AIService(settings))

    def qualify(self, lead: Any, profile: dict[str, Any]) -> dict[str, Any]:
        return _qualify(self.settings, lead, profile, self.ai_service)


def _list(config: dict[str, Any], *keys: str, default: list[str]) -> list[str]:
    for key in keys:
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, list):
            result = [str(item).strip() for item in value if str(item).strip()]
            if result:
                return result
    return default


class LeadProvider(ABC):
    """Discover one lead per job so progress survives worker restarts."""

    name = "lead_provider"

    @abstractmethod
    def discover(self, index: int, config: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError


class MockLeadProvider(LeadProvider):
    name = "mock"

    def discover(self, index: int, config: dict[str, Any]) -> dict[str, Any]:
        if index < 0:
            raise ValueError("L'indice del contatto deve essere positivo o zero.")
        cities = _list(config, "cities", "target_cities", "city", default=["Milano", "Monza", "Como"])
        categories = _list(
            config, "categories", "target_categories", "business_types", "business_type",
            default=["Ristorante", "Hotel", "Catering", "Bistrot", "Bar"],
        )
        category = categories[index % len(categories)]
        city = cities[index % len(cities)]
        identifier = index + 1
        website = f"https://locale-demo-{identifier}.example"
        menus = [
            "Menu fittizio: pasta al pomodoro e insalata di stagione.",
            "Menu fittizio: colazione con yogurt, pane e confetture.",
            "Menu fittizio: bruschette con olio extravergine e verdure.",
            "Menu fittizio: pomodori datterini, passata di pomodoro e olio extravergine.",
        ]
        return {
            "company_name": f"{category} Demo {identifier:04d}",
            "contact_name": f"Referente fittizio {identifier}",
            "email": f"acquisti@locale-demo-{identifier}.test",
            "phone": "", "city": city, "business_type": category,
            "address": f"Via della Simulazione {identifier} — indirizzo fittizio, {city}",
            "website": website, "menu_text": menus[index % len(menus)],
            "notes": f"DATI FITTIZI DEMO; contatto inventato, nessuna attività reale. Indice demo: {index}.",
            "source": "MockLeadProvider — DATI FITTIZI DEMO",
            "source_url": website, "source_date": _timestamp(),
            "provider": self.name, "demo": True,
            "metadata": {"fictional": True, "demo_index": index, "independently_verified": False},
        }


class CSVImportProvider(LeadProvider):
    name = "csv"

    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = deepcopy(rows)

    def discover(self, index: int, config: dict[str, Any]) -> dict[str, Any] | None:
        if index < 0:
            raise ValueError("L'indice del contatto deve essere positivo o zero.")
        if index >= len(self.rows):
            return None
        row = deepcopy(self.rows[index])
        row["source"] = str(row.get("source") or "CSV importato dall'utente")
        # Collection time is owned by the application; original source dates are
        # retained separately, and do not masquerade as an independent check.
        original_date = row.get("source_date")
        row["source_date"] = _timestamp()
        row["provider"] = self.name
        row["source_url"] = str(row.get("source_url") or row.get("website") or "")
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        row["metadata"] = metadata | {"row_number": index + 1, "independently_verified": False}
        if original_date:
            row["metadata"]["provider_source_date"] = str(original_date)[:100]
        # Missing addresses, email addresses and menu information stay missing.
        return row


def _catalog_matches(lead: Any, profile: dict[str, Any]) -> list[dict[str, Any]]:
    menu = str(_get(lead, "menu_text", "")).casefold()
    tokens = set(re.findall(r"\b[\wàèéìòù]{4,}\b", menu))
    return [
        item for item in profile.get("catalog", [])
        if tokens & set(re.findall(r"\b[\wàèéìòù]{4,}\b", (item.get("name", "") + " " + item.get("category", "")).casefold()))
    ]


def _demo_index(lead: Any) -> int:
    marker = re.search(r"Indice demo: (\d+)\.", str(_get(lead, "notes", "")))
    if marker:
        return int(marker.group(1))
    return int(hashlib.sha256(str(_get(lead, "company_name", "")).encode()).hexdigest()[:8], 16)


def qualification(settings: Any, lead: Any, profile: dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper selecting an explicit, replaceable provider."""
    provider = DemoQualificationProvider(settings) if bool(_get(settings, "demo_mode", True)) else ConfiguredQualificationProvider(settings)
    return provider.qualify(lead, profile)


def _qualify(settings: Any, lead: Any, profile: dict[str, Any], ai_service: AIService) -> dict[str, Any]:
    """Produce scored, sourced evidence; no claim about buying interest."""
    lead = _lead_object(lead)
    result = svc.qualification(lead, profile)
    matches = _catalog_matches(lead, profile)
    provider = "local_rules"
    model = "transparent-rules-v1"
    product_ids = [item["id"] for item in matches if item.get("id")]
    if ai_service.enabled:
        plan = ai_service.infer_plan("qualification_plan", profile, {
            "company_name": lead.company_name, "business_type": lead.business_type,
            "city": lead.city, "menu_text": lead.menu_text,
            "source": lead.source, "source_date": lead.source_date,
        })
        allowed = {item["id"] for item in profile.get("catalog", [])}
        if any(identifier not in allowed for identifier in plan["product_ids"]):
            raise adapters.IntegrationError("L'AI ha indicato un prodotto fuori catalogo.", "invalid_ai_response")
        product_ids = list(dict.fromkeys(plan["product_ids"]))
        provider, model = "openai", _get(settings, "openai_model", "gpt-4.1-mini")
        # The model selects catalogue products; factual evidence and numeric
        # scoring remain local, so prompt injection cannot invent sales facts.
    fictional_data = bool(_get(lead, "demo", False)) and "MockLeadProvider" in lead.source
    fictional_mock = bool(_get(settings, "demo_mode", True)) and fictional_data
    if fictional_mock:
        score = 55 + (_demo_index(lead) % 8) * 5
        provider, model = "mock", "deterministic-demo-v1"
        result["summary"] = "Punteggio fittizio per provare il filtro della campagna; non indica interesse o volumi reali."
        result["method"] = "Simulazione deterministica: score 55–90 distribuito sui contatti inventati."
        result["verified_facts"].insert(0, "Tutti i dati di questo contatto sono FITTIZI DEMO, senza verifica esterna.")
    else:
        score = int(result["score"])
    # Separate 0–100 indicators feed the documented weighted total.
    # Confidence expresses data coverage, never probability of a sale.
    commercial_potential = max(0, score - 5)
    coverage_fields = (lead.source, lead.source_date, lead.business_type, lead.city, lead.menu_text, lead.email)
    confidence = 75 if fictional_mock else min(45, 10 + sum(bool(value) for value in coverage_fields) * 6)
    if fictional_mock:
        # Preserve the transparent 55–90 demo scenarios while applying the same
        # 55/30/15 formula that is used for every campaign qualification.
        product_fit = min(100, max(0, round((score - commercial_potential * .30 - confidence * .15) / .55)))
    else:
        product_fit = min(100, score + 5)
    score = round(product_fit * .55 + commercial_potential * .30 + confidence * .15)
    source_date = str(_get(lead, "source_date", ""))
    evidence = [
        {"kind": "fact", "text": fact, "source": lead.source, "observed_at": source_date, "independently_verified": False}
        for fact in result["verified_facts"]
    ] + [
        {"kind": "inference", "text": text, "source": lead.source, "observed_at": source_date}
        for text in result["hypotheses"]
    ] + [{"kind": "unknown", "text": text} for text in result["missing_data"]]
    return result | {
        "score": score, "total_score": score, "product_fit": product_fit,
        "commercial_potential": commercial_potential, "confidence": confidence,
        "reason": result["summary"], "rationale": result["summary"],
        "positive_signals": [f"Parole del menu compatibili con {item['name']} (da confermare)." for item in matches],
        "negative_signals": [item for item in result["missing_data"] if "consegna" in item.lower() or "Email" in item],
        "missing_information": result["missing_data"], "evidence": evidence,
        "timestamp": _timestamp(), "provider": provider, "model": model,
        "product_ids": product_ids,
        "score_meaning": "Indice di compatibilità dei dati disponibili; non probabilità di acquisto.",
        "confidence_meaning": "Copertura fittizia della simulazione." if fictional_mock else "Copertura delle informazioni riportate dalla fonte, senza verifica indipendente.",
        "metadata": {"fictional": fictional_data, "simulated_scoring": fictional_mock, "independently_verified": False, "indicators_scale": "0–100", "score_weights": {"product_fit": .55, "commercial_potential": .30, "confidence": .15}},
    }


def outreach(settings: Any, lead: Any, profile: dict[str, Any], kind: str = "outreach", followup: bool = False, incoming: str | None = None) -> dict[str, Any]:
    """Return an editable draft assembled from producer-approved catalogue data."""
    lead = _lead_object(lead)
    handoff = False
    reason = ""
    if incoming is not None:
        response = analyze_response(settings, incoming, profile=profile)
        handoff, reason = response["handoff_required"], response["reason"]
    selected = _catalog_matches(lead, profile) or profile.get("catalog", [])[:3]
    intro = "presentation"
    provider = "mock" if bool(_get(settings, "demo_mode", True)) else "local_template"
    model = "catalogue-template-v1"
    ai_service = AIService(settings)
    if ai_service.enabled:
        plan = ai_service.infer_plan("draft_plan", profile, {
            "company_name": lead.company_name, "menu_text": lead.menu_text,
            "incoming_message": incoming, "kind": kind, "followup": followup,
        })
        allowed = {item["id"]: item for item in profile.get("catalog", [])}
        if any(identifier not in allowed for identifier in plan["product_ids"]):
            raise adapters.IntegrationError("L'AI ha indicato un prodotto fuori catalogo.", "invalid_ai_response")
        if plan["product_ids"]:
            selected = [allowed[identifier] for identifier in dict.fromkeys(plan["product_ids"])]
        intro = plan["intro_key"]
        handoff = handoff or plan["handoff_required"]
        if handoff and not reason:
            reason = "Il commerciale deve verificare le condizioni richieste."
        provider, model = "openai", _get(settings, "openai_model", "gpt-4.1-mini")
    if not profile.get("catalog"):
        handoff = True
        reason = "Catalogo mancante: il commerciale deve completare le informazioni."
    subject, body = svc.draft_text(lead, profile | {"catalog": selected}, kind, followup, handoff, intro)
    return {
        "subject": subject, "body": body,
        "cta": "Quali prodotti, quantità e tempistiche potrebbero essere utili alla vostra attività?",
        "provider": provider, "model": model, "timestamp": _timestamp(),
        "product_ids": [item["id"] for item in selected if item.get("id")],
        "handoff_required": handoff, "reason": reason,
        "approval_required": True,
    }


_CLASSIFICATION = {
    "interested": "INTERESTED", "question": "QUESTION", "rejection": "NOT_INTERESTED",
    "unsubscribe": "UNSUBSCRIBE", "hard_bounce": "HARD_BOUNCE", "other": "OTHER",
    "not_interested": "NOT_INTERESTED", "meeting_request": "MEETING_REQUEST",
    "out_of_office": "OUT_OF_OFFICE", "objection": "OBJECTION",
}


def _exact_fragments(pattern: str, body: str) -> list[str]:
    return list(dict.fromkeys(match.group(0) for match in re.finditer(pattern, body, re.I)))[:30]


def analyze_response(settings: Any, body: str, event: str = "reply", profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extract literal text spans only; opt-outs take precedence over interest."""
    local_event = event.casefold()
    local = svc.classify(body, local_event)
    classification = _CLASSIFICATION.get(local["classification"], "OTHER")
    provider, model = "local_rules", "literal-extraction-v1"
    ai_handoff = False
    ai_service = AIService(settings)
    if ai_service.enabled and local_event == "reply":
        annotation = ai_service.infer_plan("classify_reply", profile or {}, {"body": body, "event": event})
        # Schema validation alone cannot prevent fabricated extracts. Every
        # extracted span must occur literally in the original incoming message.
        extracted = annotation.get("extracted", {})
        if not isinstance(extracted, dict):
            raise adapters.IntegrationError("L'AI ha restituito un'estrazione non valida.", "invalid_ai_response")
        for value in extracted.values():
            fragments = value if isinstance(value, list) else [value] if value is not None else []
            if any(not isinstance(fragment, str) or not fragment.strip() or fragment not in body for fragment in fragments):
                raise adapters.IntegrationError("L'AI ha estratto informazioni assenti dal messaggio originale.", "invalid_ai_response")
        suggested = _CLASSIFICATION.get(str(annotation.get("classification", "")).casefold())
        if suggested is None:
            raise adapters.IntegrationError("Classificazione AI non valida.", "invalid_ai_response")
        # Local opt-out, rejection and bounce detection is never overwritten.
        if classification not in {"UNSUBSCRIBE", "NOT_INTERESTED", "HARD_BOUNCE"}:
            classification = suggested
        ai_handoff = annotation.get("handoff_required") is True
        provider, model = "openai", _get(settings, "openai_model", "gpt-4.1-mini")
    # Special campaign classes never override a permanent-stop event.
    if classification not in {"UNSUBSCRIBE", "NOT_INTERESTED", "HARD_BOUNCE"}:
        if re.search(r"fuori (?:ufficio|sede)|out of office|assente fino|in ferie|risposta automatica", body, re.I):
            classification = "OUT_OF_OFFICE"
        elif re.search(r"appuntamento|incontr(?:o|ar|iam)|videochiamata|call\b|ci sentiamo|disponibil[ei].*(?:lunedì|martedì|mercoledì|giovedì|venerdì|domani|ore)", body, re.I):
            classification = "MEETING_REQUEST"
        elif re.search(r"troppo (?:caro|costos)|prezz[oi].*(?:alt[oi]|elevat)|sconto|pagamento|esclusiva|omaggio|fuori zona", body, re.I):
            classification = "OBJECTION"
    quantities = _exact_fragments(r"\b\d+(?:[.,]\d+)?\s*(?:kg|chilogrammi|litri|l|pezzi|confezioni|casse|bottiglie)\b", body)
    budgets = _exact_fragments(r"(?:€\s*\d+(?:[.,]\d+)?|\b\d+(?:[.,]\d+)?\s*(?:euro|€))", body)
    timing = _exact_fragments(r"\b(?:entro|dal|il|per)\s+(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica|domani|la prossima settimana)\b", body)
    availability = _exact_fragments(r"\b(?:lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica|domani)(?:\s+(?:alle|ore)\s+\d{1,2}(?:[:.]\d{2})?)?|\b(?:alle|ore)\s+\d{1,2}(?:[:.]\d{2})?", body)
    questions = [match.group(0).strip() for match in re.finditer(r"[^.!?\n]+\?", body)][:30]
    objections = [line.strip() for line in body.splitlines() if re.search(r"troppo caro|costos|scont|pagamento|esclusiv|omagg|fuori zona", line, re.I)][:30]
    products = []
    generic_catalog_words = {
        "demo", "fittizio", "fittizia", "fittizi", "fittizie", "prodotto", "prodotti",
        "stagionale", "stagionali", "stagione", "fresco", "fresca", "freschi", "fresche",
        "locale", "locali", "biologico", "biologica", "biologici", "biologiche",
        "artigianale", "artigianali", "con", "per", "del", "della", "delle", "dei", "gli",
    }
    for item in (profile or {}).get("catalog", []):
        full_name = re.search(r"(?<!\w)" + re.escape(item["name"]) + r"(?!\w)", body, re.I)
        if full_name:
            products.append(full_name.group(0))
            continue
        # A source may say "formaggi" while the catalogue title is "Formaggi
        # stagionati Demo". Keep only the literal mention, never expand it to an
        # invented full product title or selected product identifier.
        category = str(item.get("category", "")).strip()
        aliases = [category] if category and category.casefold() not in generic_catalog_words else []
        aliases += [token for token in re.findall(r"\b[\wàèéìòù]{4,}\b", item["name"]) if token.casefold() not in generic_catalog_words]
        for alias in aliases:
            match = re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", body, re.I)
            if match:
                products.append(match.group(0))
    products = list(dict.fromkeys(products))[:30]
    stop = classification in {"UNSUBSCRIBE", "NOT_INTERESTED", "HARD_BOUNCE"}
    handoff = not stop and (local["handoff_required"] or ai_handoff or classification in {"MEETING_REQUEST", "OBJECTION", "QUESTION", "OTHER"})
    if classification == "OUT_OF_OFFICE":
        handoff = False
    reason = local["reason"] if handoff else ""
    if handoff and not reason:
        reason = "Il commerciale deve verificare le informazioni e le condizioni richieste."
    if classification == "MEETING_REQUEST":
        reason = "Richiesta appuntamento: verificare disponibilità e prenotare il calendario prima di confermare."
    return {
        "classification": classification, "handoff_required": handoff, "reason": reason,
        "stop_contact": stop, "provider": provider, "model": model,
        "timestamp": _timestamp(),
        "extracted": {
            "products": products, "quantities": quantities, "quantity": quantities[0] if quantities else None,
            "budget": budgets[0] if budgets else None, "budgets": budgets,
            "timing": timing[0] if timing else None, "timings": timing,
            "questions": questions, "objections": objections, "availability": availability,
            "needs": local["extracted"]["needs"],
        },
    }


class EmailProvider(ABC):
    name = "email_provider"

    @abstractmethod
    def send(self, to: str, subject: str, body: str, idempotency_key: str) -> dict[str, Any]:
        raise NotImplementedError


class MockEmailProvider(EmailProvider):
    name = "mock"

    def send(self, to: str, subject: str, body: str, idempotency_key: str) -> dict[str, Any]:
        return adapters.send_email({"demo_mode": True}, to, subject, body, idempotency_key) | {"provider": self.name}


class ConsoleEmailProvider(MockEmailProvider):
    """Local dry-run sink: no recipient, message content or credential logging."""
    name = "console"

    def send(self, to: str, subject: str, body: str, idempotency_key: str) -> dict[str, Any]:
        result = super().send(to, subject, body, idempotency_key)
        print("Agro Sales AI: invio simulato registrato, nessuna trasmissione esterna.")
        return result


class ConfiguredEmailProvider(EmailProvider):
    name = "configured_http"

    def __init__(self, settings: Any):
        self.settings = settings

    def send(self, to: str, subject: str, body: str, idempotency_key: str) -> dict[str, Any]:
        return adapters.send_email(self.settings, to, subject, body, idempotency_key) | {"provider": self.name}


class VoiceProvider(ABC):
    @abstractmethod
    def status(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def simulate(self, lead: Any, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError


class DemoVoiceProvider(VoiceProvider):
    def status(self) -> dict[str, Any]:
        return {"status": "not_connected", "label": "non collegato", "simulated": True}

    def simulate(self, lead: Any, profile: dict[str, Any] | None = None, preset: str = 'interested') -> dict[str, Any]:
        company = (profile or {}).get("company_name", "il produttore demo")
        response = DemoResponseSimulator().simulate(lead, preset, profile)
        transcript = [
            {"speaker": "agente", "text": f"Simulazione locale: presentazione del catalogo di {company}."},
            {"speaker": "contatto", "text": response['body']},
            {"speaker": "agente", "text": "Il commerciale verificherà esigenze, quantità, disponibilità e condizioni."},
        ]
        return self.status() | {
            "provider": "demo_voice", "transcript": transcript,
            "summary": "Conversazione telefonica FITTIZIA DEMO; nessuna chiamata effettuata.",
            "handoff_required": True, "timestamp": _timestamp(),
        }


class DemoResponseSimulator:
    """Produce fictional incoming messages without an email provider."""
    variants = ("interested", "question", "not_interested", "meeting_request", "unsubscribe", "out_of_office", "objection", "hard_bounce")

    def simulate(self, lead: Any, variant: str | None = None, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        variant = (variant or self.variants[_demo_index(lead) % len(self.variants)]).casefold()
        variant = {'meeting': 'meeting_request', 'price_objection': 'objection'}.get(variant, variant)
        names = [item["name"] for item in (profile or {}).get("catalog", [])[:2]]
        product = names[0] if names else "i prodotti del catalogo"
        bodies = {
            "interested": f"Siamo interessati a {product}: vorremmo 20 kg per la prossima settimana. Budget 300 euro. Potete verificare disponibilità?",
            "question": "Qual è l'ordine minimo? Potete consegnare nella nostra zona?",
            "price_list": "Potete inviarci il listino dei formaggi e dell’olio EVO?",
            "sample": "Siamo interessati. Vorremmo valutare un campione dei vostri prodotti.",
            "not_interested": "Non siamo interessati alla proposta, grazie.",
            "meeting_request": "Vorremmo un appuntamento per presentare il catalogo. Siamo disponibili martedì alle 10:00.",
            "unsubscribe": "Disiscrivimi, non desidero ricevere altri messaggi.",
            "out_of_office": "Risposta automatica: sono fuori ufficio fino al 20/10; leggerò i messaggi al rientro.",
            "objection": "Il prezzo ci sembra troppo caro: possiamo avere uno sconto e pagamento a 90 giorni?",
            "hard_bounce": "Hard bounce: indirizzo inesistente (evento simulato).",
        }
        if variant not in bodies:
            raise ValueError("Tipo di risposta demo non supportato.")
        event = "hard_bounce" if variant == "hard_bounce" else "reply"
        body = bodies[variant] + "\n\nDATI FITTIZI DEMO — messaggio generato localmente."
        return {
            "body": body, "subject": "Risposta simulata alla proposta — DEMO",
            "event": event, "classification": {'price_list': 'QUESTION', 'sample': 'INTERESTED'}.get(variant, _CLASSIFICATION.get(variant, 'OTHER')),
            "simulated": True, "provider": "demo_response_simulator", "timestamp": _timestamp(),
        }
