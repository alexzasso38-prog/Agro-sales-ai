# Agro Sales AI

Applicazione in italiano per aiutare produttori agroalimentari a organizzare l'acquisizione di clienti HORECA: catalogo, lead, qualificazione, email da approvare, follow-up, conversazioni, passaggio al commerciale e appuntamenti.

La **demo funziona senza credenziali esterne**. Aziende, persone e contatti precaricati sono fittizi; gli indirizzi usano `.test`. Nessuna email o telefonata viene inviata. Invii e prenotazioni simulati sono indicati nell'interfaccia e separati nelle metriche.

## Avvio rapido

Requisiti: Python 3.11+ e Node.js 20.19+ (oppure 22.12+). Comandi dalla radice del repository.

```bash
cp .env.example .env
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
cd frontend
npm ci --cache ../.cache/npm
cd ..
```

Apri tre terminali:

```bash
# Terminale 1: API
cd backend
../.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
# Terminale 2: interfaccia
cd frontend
npm run dev -- --host 127.0.0.1
```

```bash
# Terminale 3: attività programmate
cd backend
../.venv/bin/python -m app.worker
```

Apri `http://localhost:5173`. Entra con **demo@agrosales.test** / **DemoAgro2026!**, oppure usa il pulsante della demo. L'API espone la documentazione interattiva su `http://localhost:8000/docs` e il controllo di disponibilità su `/health`.

In alternativa, dopo l'installazione: `make backend`, `make frontend` e `make worker`, ciascuno in un terminale. Su Windows usa `.venv\Scripts\python.exe` e `.venv\Scripts\uvicorn.exe` al posto dei percorsi Unix.

### PostgreSQL locale con Docker

Richiede Docker Compose 2.24+ e BuildKit.

```bash
docker compose up --build
```

L'interfaccia è su `http://localhost:8080`. Il database persiste nel volume `postgres_data`; `docker compose down` ferma i servizi senza cancellare i dati. Questa configurazione rimane **demo**, anche se `.env` contiene chiavi. Le credenziali del database nel compose sono esclusivamente per uso locale.

## Prova i flussi

1. Nel profilo modifica catalogo, prezzi, ordine minimo, zone, consegna, pagamento e giorni dei follow-up.
2. Aggiungi un lead o importa `demo/leads.csv`. Le colonne sono documentate in quel file; `company_name` è necessario. Se `source` manca nel CSV, il server registra il nome del file come origine; indicare la fonte originale quando disponibile. L'email può mancare: non viene inventata. Origine e data di acquisizione sono salvate, i duplicati segnalati.
3. Qualifica un lead. Il risultato distingue informazioni registrate, ipotesi e lacune. Un menu importato non certifica fatturato, volumi, fornitori o interesse.
4. Genera una bozza, modificala, approvala e simula l'invio. Modificare una bozza già approvata richiede nuova approvazione.
5. Il worker prepara una bozza di follow-up alla scadenza. **Ogni follow-up richiede approvazione e invio espliciti**; il worker non invia automaticamente messaggi.
6. Registra una risposta, un rifiuto, una disiscrizione o un errore permanente. Le attività di ricontatto si fermano; una risposta può produrre una nuova bozza pertinente e una richiesta al commerciale.
7. Prenota un appuntamento demo e consulta storico, attività, pipeline e metriche. Una prenotazione demo rimane “simulata”.

Puoi registrare un altro produttore per verificare la separazione di profilo, lead e conversazioni. Non serve creare account esterni.

## Architettura e integrazioni

- **Backend:** FastAPI, SQLAlchemy, SQLite per demo e PostgreSQL tramite psycopg; JWT, password hashate, filtro per produttore su ogni risorsa.
- **Interfaccia:** React, TypeScript e Vite; chiavi dei provider soltanto nel backend.
- **Worker:** processo separato con attività persistenti, prenotazione atomica dei lavori, scadenze, blocco dei ricontatti e audit.
- **AI:** analisi deterministica esplicitamente segnalata nella demo; OpenAI configurabile in produzione per selezionare prodotti e formulazioni da blocchi autorizzati. Siti, menu ed email sono dati non attendibili, mai istruzioni per l'agente. Nessuna visita automatica ai siti dei lead.
- **Email, ricerca, CRM e calendario:** adattatori HTTP configurabili; richiedono endpoint e account esterni conformi al contratto del connettore. Non sono integrazioni native con qualsiasi provider.
- **Voce:** modulo separato predisposto; nessuna telefonata implementata. Stato “non collegato”.

Il contratto delle API è in [docs/API_CONTRACT.md](docs/API_CONTRACT.md). Configurazione, sicurezza e contratti dei connettori sono descritti in [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md).

## Configurazione

`.env.example` non contiene segreti. La configurazione viene letta dal backend dalla radice del repository. SQLite viene creato in `backend/data/` ed escluso da Git. La demo usa un segreto JWT esclusivamente locale; in produzione `JWT_SECRET` deve essere un valore casuale di almeno 32 caratteri.

Per un ambiente reale occorrono un database PostgreSQL dedicato e privo di account demo, `DEMO_MODE=false`, un segreto JWT robusto e i provider necessari. `ALLOW_EXTERNAL_INTEGRATIONS=false` blocca per impostazione predefinita le chiamate ai provider. Attivalo soltanto dopo aver configurato e validato gli endpoint. Non impostare chiavi come variabili `VITE_*`: entrerebbero nel bundle del browser.

Il passaggio a produzione richiede inoltre HTTPS, restrizioni CORS coerenti con il dominio, backup, gestione dei segreti e monitoraggio. Il compose fornito è locale e non sostituisce questa configurazione. L'inizializzazione crea lo schema; per successive modifiche strutturali occorre una migrazione, non cancellare il database.

## Verifiche

```bash
# Test backend, inclusi isolamento e flussi di invio
cd backend
../.venv/bin/python -m pytest -q
cd ..

# TypeScript e build dell'interfaccia
cd frontend
npm run build
```

Con il backend demo avviato puoi eseguire anche `python3 scripts/api-smoke.py`: verifica i flussi via HTTP e crea due produttori di prova isolati. Per un database PostgreSQL **locale di test**: `AGRO_TEST_POSTGRES_URL=postgresql+psycopg://utente:password@127.0.0.1:5432/database .venv/bin/python scripts/postgres-smoke.py` (crea tabelle e dati di prova; usare un database dedicato).

Smoke dell'interfaccia con backend e frontend demo già avviati:

```bash
cd frontend
npx playwright install chromium
npm run test:e2e
```

Se Chromium è già installato, puoi usare `AGRO_BROWSER_PATH=/percorso/chromium npm run test:e2e`. Il test accetta solo URL locali, verifica la modalità demo, crea dati fittizi e blocca tutte le richieste fuori da localhost. `AGRO_UI_URL=http://localhost:8080` permette di testare l'interfaccia Docker.

Gli esiti eseguiti e i limiti sono in [docs/VALIDATION.md](docs/VALIDATION.md).

La verifica delle integrazioni remote va effettuata separatamente con account di test: durante lo sviluppo non sono stati contattati provider AI, email, lead, CRM, calendario o voce. I test con adattatori simulati non dimostrano il funzionamento di un account remoto.
