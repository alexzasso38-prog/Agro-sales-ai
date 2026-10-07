# Agro Sales AI

Sistema commerciale in italiano per produttori agroalimentari: campagne AI, agenti coordinati da un orchestratore persistente e CRM alimentato dal loro lavoro. Dashboard, catalogo, lead, conversazioni, bozze e appuntamenti rimangono disponibili.

La **demo funziona senza credenziali esterne**. Aziende, persone e contatti precaricati sono fittizi; gli indirizzi usano `.test`. Nessuna email o telefonata viene inviata. Invii e prenotazioni simulati sono indicati nell'interfaccia e separati nelle metriche.

## Prova gli agenti

Apri **Automazioni AI**, premi **Prova lo scenario demo** e poi **Avvia campagna AI**. Lo scenario propone 20 ristoranti fittizi a Milano e prodotti demo del catalogo Cascina Verde: formaggi premium, olio e salumi. I prodotti demo mancanti vengono aggiunti soltanto scegliendo questo scenario, senza cancellare il catalogo esistente.

Il worker scopre progressivamente i lead, li qualifica, applica la soglia e prepara le email. Le sei card mostrano il lavoro degli agenti; l'attività live viene letta dal database ogni pochi secondi. Non è una sequenza animata del frontend.

1. Apri una bozza, modificala, approvala e premi **Simula invio**.
2. Il Follow-up Agent programma la sequenza giorni 3, 7 e 14. In demo, un giorno vale 10 secondi; puoi anche avanzare il tempo dalla campagna.
3. Simula una risposta interessata, una richiesta di listino/campione, un'obiezione o una richiesta di appuntamento. Puoi anche scrivere il testo.
4. Il Sales Agent analizza la risposta, interrompe i ricontatti, aggiorna il CRM e prepara la scheda **Human Closer** quando serve un commerciale.
5. Prendi in carico l'opportunità, apri una bozza, prenota un appuntamento demo o segna il risultato. Il refresh conserva campagne, eventi e stato dei job.

La modalità predefinita è **approvazione umana**. In demo puoi provare anche autonomia media/alta e invii automatici simulati. Pausa, ripresa, stop, pausa agente, retry, esclusione del lead, tetto email e limite di frequenza sono controlli backend. Disiscrizione, rifiuto, errore permanente e appuntamento arrestano i follow-up. Una risposta simulata e una risposta registrata nell'API entrano nello stesso flusso.

**Simula chiamata** genera soltanto una trascrizione demo e la passa al Sales Agent. Il provider telefonico resta **non collegato**: nessuna telefonata viene effettuata.

## Avvio rapido

Requisiti: Python 3.11+ e Node.js 20.19+ (oppure 22.12+). Comandi dalla radice del repository.

Su **Mac**, consigliamo Python 3.12 e Node 22. Con Homebrew già disponibile:

```bash
brew install python@3.12 node@22 git
export PATH="$(brew --prefix node@22)/bin:$PATH"
git clone --branch codex/agro-sales-ai-app --single-branch \
  https://github.com/alexzasso38-prog/Agro-sales-ai.git "$HOME/Agro-sales-ai"
cd "$HOME/Agro-sales-ai"
make install PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
make demo
```

Se Git o `make` mancano, esegui `xcode-select --install` e completa l'installazione degli strumenti Apple. Homebrew: <https://brew.sh/>. `make install` crea `.env` soltanto se manca. `make demo` avvia API, interfaccia e worker, forza SQLite e modalità demo senza integrazioni esterne e ferma tutti e tre con `Ctrl+C`. Apri **http://127.0.0.1:5173 sul Mac che esegue il comando**. Non è l'indirizzo di un'anteprima cloud. Le porte occupate vengono segnalate senza scegliere silenziosamente un altro URL.

Se hai già clonato il progetto, conserva le modifiche locali e passa al branch `codex/agro-sales-ai-app`; dopo l'aggiornamento esegui installazione e `make demo`. Non cancellare `.env` o il database per aggiornare: vengono aggiunte nuove tabelle compatibili, senza ricostruire quelle esistenti.

Per installazione senza Homebrew o avvio separato:

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
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
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
5. Fuori dalle campagne il worker prepara una bozza di follow-up alla scadenza e richiede approvazione/invio espliciti. Nelle campagne applica l'autonomia scelta; in demo ogni invio resta simulato.
6. Registra una risposta, un rifiuto, una disiscrizione o un errore permanente. Le attività di ricontatto si fermano; una risposta può produrre una nuova bozza pertinente e una richiesta al commerciale.
7. Prenota un appuntamento demo e consulta storico, attività, pipeline e metriche. Una prenotazione demo rimane “simulata”.

Puoi registrare un altro produttore per verificare la separazione di profilo, lead e conversazioni. Non serve creare account esterni.

## Architettura e integrazioni

- **Backend:** FastAPI, SQLAlchemy, SQLite per demo e PostgreSQL tramite psycopg; JWT, password hashate, filtro per produttore su ogni risorsa.
- **Interfaccia:** React, TypeScript e Vite; chiavi dei provider soltanto nel backend.
- **Worker:** processo separato condiviso dai flussi esistenti e dalle campagne; job, run degli agenti, lease, eventi, sequenze, controlli e audit persistenti. Tick di un secondo in demo, 30 secondi fuori dalla demo.
- **AI:** analisi deterministica esplicitamente segnalata nella demo; OpenAI configurabile in produzione per selezionare prodotti e formulazioni da blocchi autorizzati. Siti, menu ed email sono dati non attendibili, mai istruzioni per l'agente. Nessuna visita automatica ai siti dei lead.
- **Email, ricerca, CRM e calendario:** adattatori HTTP configurabili; richiedono endpoint e account esterni conformi al contratto del connettore. Non sono integrazioni native con qualsiasi provider.
- **Voce:** interfaccia provider separata e trascrizione simulata analizzata dal Sales Agent; telefonia reale non implementata. Stato “non collegato”.

Il contratto delle API è in [docs/API_CONTRACT.md](docs/API_CONTRACT.md). Configurazione, sicurezza e contratti dei connettori sono descritti in [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md).

Workflow, controlli e distinzione fra esecuzione reale dei job e dati simulati sono in [docs/AUTOMATIONS.md](docs/AUTOMATIONS.md).

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
