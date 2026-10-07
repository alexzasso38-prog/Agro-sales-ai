# Automazioni AI — guida alla demo operativa

La sezione **Automazioni AI** coordina la ricerca, la qualificazione, le bozze, i follow-up e l'analisi delle risposte. CRM, conversazioni, appuntamenti e registro operazioni continuano a usare i dati del progetto esistente.

## Avvio locale

Dalla radice del repository, dopo aver installato le dipendenze indicate nel README:

```bash
make demo
```

Il comando avvia backend, frontend e worker insieme, forza `DEMO_MODE=true` e `ALLOW_EXTERNAL_INTEGRATIONS=false` e usa SQLite locale. Sul computer che esegue il comando apri **http://127.0.0.1:5173**. `Ctrl+C` arresta tutti e tre i processi. Un `localhost` di un ambiente remoto non è un link pubblico per il tuo Mac.

Entra con **Entra nella demo** oppure `demo@agrosales.test` / `DemoAgro2026!`. I dati preesistenti vengono conservati; non serve eliminare il database per aggiornare la demo.

## Una dimostrazione completa

1. Apri **Automazioni AI**, quindi **Prova lo scenario demo**. Viene preparata una campagna di 20 contatti fittizi per Milano con prodotti di esempio aggiunti al catalogo; nessun prodotto esistente viene eliminato.
2. Premi **Avvia campagna AI**. Il worker scopre progressivamente i contatti, li qualifica, salva punteggi e provenienza e prepara le bozze per quelli sopra la soglia. Live Agent Activity mostra eventi salvati nel database, aggiornati tramite polling.
3. Apri **Rivedi e approva bozza** su un lead. Puoi modificarla; la modifica annulla qualsiasi approvazione precedente. Premi **Approva bozza**, poi **Simula invio**. L'invio viene registrato come simulato nello storico e nelle metriche.
4. La prima email programma i follow-up. La sequenza predefinita è giorno 0, 3, 7 e 14; 1 giorno della sequenza vale 10 secondi demo. **Accelera tempo demo** anticipa le scadenze persistenti di 3 giorni della sequenza. Il worker continua a eseguire i job.
5. Premi **Simula risposta lead** e scegli un esempio o scrivi il testo. Sales Agent lo classifica, estrae solo le informazioni dichiarate e prepara una risposta da approvare. Il messaggio in ingresso interrompe immediatamente i follow-up.
6. Una richiesta commerciale rilevante passa in **Human Closer**. Consulta il riepilogo, prendi in carico l'opportunità, contatta il cliente, organizza un appuntamento o segna l'esito vinto/perso.
7. **Simula chiamata** registra una trascrizione fittizia nello stesso flusso di conversazione. Non compone alcun numero e il provider telefonico reale rimane non collegato.

Le campagne mock ripetute possono ritrovare gli stessi contatti: la deduplica è per produttore, e un contatto disiscritto non viene riattivato avviando una nuova campagna.

## Campagne e autonomia

**Nuova campagna AI** consente di scegliere target, zona, quantità di lead, prodotti del proprio catalogo, soglie, origine dei dati, sequenza e limiti. Il provider CSV conserva fonte e data; un recapito assente resta assente.

| Impostazione | Comportamento |
|---|---|
| Solo bozze | Gli agenti preparano comunicazioni modificabili; il worker non le invia automaticamente. |
| Approvazione prima dell'invio | Prima presentazione e risposte richiedono approvazione. |
| Automatico | Può inviare comunicazioni consentite entro i limiti della campagna; in demo ogni invio resta simulato. |
| Autonomia bassa | Ogni comunicazione richiede approvazione umana. |
| Autonomia media | Primo outreach approvato dall'umano; follow-up standard possono essere automatici. |
| Autonomia alta | Le azioni consentite possono essere automatiche; le richieste sensibili passano comunque al commerciale. |

L'autorizzazione automatica e i limiti non permettono di inventare disponibilità, prezzi, sconti, volumi o interesse del cliente. Una bozza di risposta che richiede una decisione commerciale resta da approvare.

## Controlli

- **Pausa campagna / Riprendi campagna:** sospendono e riattivano l'esecuzione dei job e gli invii collegati alla campagna.
- **Interrompi:** cancella il lavoro pendente della campagna. Non riattiva contatti sospesi e non cancella lo storico.
- Pulsante pausa nella card di un agente: sospende solo quell'agente.
- **Riprova attività:** rimette un job fallito nella coda mantenendo la sua identità persistente.
- **Non contattare:** impedisce nuovi ricontatti sul lead.
- Risposta, rifiuto, disiscrizione, hard bounce e prenotazione riuscita interrompono la sequenza.
- Il limite totale di email, il massimo di follow-up e il limite al minuto vengono applicati dal backend anche agli invii manuali collegati alla campagna.

## Componenti e persistenza

```mermaid
flowchart LR
    C[Campagna] --> L[Lead Generation]
    L --> Q[Qualification]
    Q --> S{Sopra soglia?}
    S -->|No| P[Bassa priorità]
    S -->|Sì| O[Outreach]
    O --> A[Approvazione o azione autorizzata]
    A --> F[Follow-up nel worker]
    F --> R[Risposta ricevuta]
    R --> V[Sales / Conversation]
    V --> CRM[CRM aggiornato]
    CRM --> H[Human Closer]
```

`Campaign`, `CampaignLead`, `AgentRun`, `AgentTask`, `AgentEvent`, `AutomationRule`, `FollowUpSequence` e `ConversationEvent` sono tabelle aggiuntive nello stesso database. Le tabelle CRM già presenti vengono riutilizzate. Avvio e aggiornamento non eliminano i dati preesistenti.

Il worker esegue job persistenti, con scadenze, tentativi, chiave di idempotenza e claim temporaneo. L'interfaccia legge gli stati dal backend. Le transizioni CRM registrano stato precedente, stato nuovo, motivazione, agente, campagna e timestamp. Le risposte manuali/API e le simulazioni entrano nel medesimo orchestratore.

## Reale, demo e integrazioni

| Componente | Stato |
|---|---|
| Orchestratore, worker, code, eventi, approvazioni, isolamento produttori e aggiornamenti CRM | Codice eseguito e dati persistenti; non animazioni della UI. Gli esiti dei test sono in `VALIDATION.md`. |
| Lead mock | Attività e recapiti inventati e marcati DEMO, con domini riservati; nessuna ricerca reale. |
| Qualificazione senza OpenAI | Regole locali. Per i lead mock, punteggio deterministico esplicitamente fittizio per dimostrare le soglie. Non prevede acquisti. |
| Email demo | MockEmailProvider registra un invio simulato, senza trasmissione esterna. |
| Risposte e voce demo | Messaggi/trascrizioni fittizi analizzati dallo stesso workflow; nessuna casella consultata e nessuna telefonata. |
| OpenAI, ricerca, email, CRM e calendario esterni | Richiedono credenziali/configurazione backend, autorizzazione alle integrazioni e verifica del provider. Nessun provider reale è stato contattato nello sviluppo. |

I dati acquisiti, i menu, i siti e i messaggi sono input non attendibili. L'AI può proporre prodotti del catalogo, non nuove condizioni commerciali. FACT, INFERENCE e UNKNOWN distinguono dati presenti, interpretazioni e lacune; un dato presente nella fonte non è una verifica indipendente.

La ricezione da una casella reale e i webhook dei provider richiedono un adattatore autenticato; non sono collegati automaticamente. Google Places e provider telefonici sono integrazioni future. Gli appuntamenti reali sono confermati solo dopo il successo del calendario; quelli demo sono sempre simulati.

## Test riproducibili

```bash
make test
make build
.venv/bin/python scripts/automation-smoke.py
```

Lo smoke Python usa per impostazione predefinita un database SQLite temporaneo e un produttore fittizio isolato. Verifica lo scenario di 20 lead e la persistenza al riavvio. Per un PostgreSQL **locale dedicato ai test**, nel quale rimarranno schema e dati fittizi di verifica:

```bash
AGRO_TEST_POSTGRES_URL='postgresql+psycopg://utente:password@127.0.0.1:5432/database_test' \
  .venv/bin/python scripts/automation-smoke.py
```

Per il test browser lascia `make demo` attivo in un altro terminale, installa Chromium di Playwright se necessario e avvia:

```bash
cd frontend
npx playwright install chromium
cd ..
node scripts/automation-smoke.cjs
```

Con Chromium già installato puoi impostare `AGRO_BROWSER_PATH=/percorso/chromium`. `AGRO_UI_URL` accetta solo URL HTTP locali. Lo script crea una campagna CSV con contatti fittizi unici, usa i pulsanti della UI e il worker attivo e blocca tutte le richieste browser esterne. Non utilizzare i test su dati di produzione.
