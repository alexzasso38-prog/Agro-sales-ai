# Verifiche eseguite — 7 ottobre 2026

| Verifica | Esito |
|---|---|
| `make install` | PASS: venv e dipendenze Python; `npm ci` con lockfile e cache locale ripetibile |
| `cd backend && ../.venv/bin/python -m pytest -q` | **68 test passati**, nessun test saltato; un avviso di deprecazione interno a Starlette/AnyIO |
| `cd frontend && npm run build` | PASS: TypeScript e bundle Vite |
| `python3 scripts/api-smoke.py` | **20 controlli HTTP passati**, sia con API SQLite sia con API Docker/PostgreSQL |
| `scripts/postgres-smoke.py` su PostgreSQL 16 locale | PASS: modalità produzione, autenticazione, catalogo JSON, lead, qualificazione, approvazione, invio disabilitato, calendario fallito senza conferma, retry e audit |
| Concorrenza PostgreSQL con adattatore locale simulato | PASS: una sola chiamata al provider simulato per invio concorrente; retry senza seconda conversazione; disiscrizione durante richiesta in corso senza nuovi follow-up |
| `python -m app.worker --once`, ripetuto | PASS: una bozza generata alla scadenza, zero invii, nessuna nuova bozza alla seconda esecuzione |
| Worker su cartella/database SQLite nuovi | PASS: creazione cartella, schema e dati demo; una bozza, zero invii |
| Smoke browser Chromium con `npm run test:e2e` | PASS: login, profilo, lead, qualificazione, modifica/approvazione/invio simulato, risposta/handoff, appuntamento simulato, navigazione sezioni, viewport 1440 e 390 pixel |
| Docker Compose | PASS: immagini backend/frontend/worker costruite; PostgreSQL e API disponibili, worker avviato, SPA e proxy API funzionanti |

I test backend includono isolamento tra produttori, CSV/deduplica/fonte/data, email mancante senza invenzioni, opt-out italiani, risposte e hard bounce, stop concorrente, modifica durante invio, approvazione invalidata, timeout e idempotenza, errore worker con audit, fallimenti calendario e grounding AI. Il passaggio da database demo a produzione è rifiutato e i dati sono preservati.

Il test browser blocca richieste fuori da localhost e ha verificato assenza di errori JavaScript e di richieste esterne. I contatti di verifica sono fittizi. Lo smoke PostgreSQL crea dati di prova e va eseguito su un database locale dedicato.

## Condizioni della verifica

Python 3.12, Node.js 24, Chromium 151, PostgreSQL 16. In questo ambiente il filesystem della home è in sola lettura: la cache npm è nel repository sotto `.cache/`, esclusa da Git. La build Docker ha richiesto networking del builder verso il proxy esistente e il bundle CA fidato dell'ambiente tramite il secret opzionale `build_ca`. Non sono stati disabilitati TLS, controlli di integrità o verifica dei certificati. Le impostazioni specifiche del proxy non sono state incorporate nei file del progetto.

## Limiti

- Provider OpenAI, email, ricerca, CRM e calendario reali **non contattati e non verificati**. Richiedono account/configurazione; i connettori HTTP devono rispettare il contratto e l'idempotenza persistente descritti in INTEGRATIONS.md.
- In demo analisi/testi locali e prenotazioni/invii simulati. In produzione OpenAI seleziona prodotti e varianti consentite: il backend compone prezzi/condizioni senza accettare testo commerciale libero del modello.
- Ricezione email registrata dall'operatore/API autenticata; nessuna sincronizzazione automatica di una casella o webhook pubblico.
- Voce predisposta in un modulo separato, sempre non collegata; nessuna chiamata implementata.
- In caso di interruzione del processo dopo l'avvio dell'invio, lo stato rimane sospeso per impedire duplicati. La riconciliazione con il provider è operativa; nessun recupero automatico dei crash.
- Nessuna migrazione evolutiva dello schema, sincronizzazione CRM bidirezionale o modifica/cancellazione di eventi calendario remoti.
- Gli esiti documentano questa istanza e i comandi eseguiti. Pubblicazione dell'ambiente cloud e ripristino in un task nuovo non sono stati verificati.
