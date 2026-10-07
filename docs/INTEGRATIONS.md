# Configurazione e integrazioni

## Modalità operative

| Modalità | AI | Email | Ricerca | Calendario / CRM | Voce |
|---|---|---|---|---|---|
| `DEMO_MODE=true` | Analisi e testi deterministici, indicati come demo | Solo registrazione simulata | Fixture fittizie | Simulazioni esplicite | Non collegato |
| Produzione, integrazioni disabilitate | Fallback locale indicato | Invio bloccato | Errore di configurazione | Nessuna conferma remota | Non collegato |
| Produzione, provider configurati e abilitati | OpenAI | Adattatore HTTP | Adattatore HTTP | Adattatori HTTP | Predisposizione, nessuna chiamata |

In demo nessun adattatore remoto viene invocato, anche con chiavi presenti. Fuori dalla demo, le chiamate richiedono **anche** `ALLOW_EXTERNAL_INTEGRATIONS=true`. Una configurazione presente non dimostra la validità di un account: la prima operazione può fallire e viene mostrato l'errore.

## OpenAI

Configurare `OPENAI_API_KEY` e, facoltativamente, `OPENAI_MODEL` (default `gpt-4.1-mini`). L'adattatore usa la Responses API, JSON con schema vincolato e `store: false`. Menu, schede e risposte sono racchiusi come dati non attendibili; non possono autorizzare condizioni, approvare bozze, inviare messaggi o usare strumenti.

Le proposte OpenAI usano piani strutturati: possono selezionare solo ID del catalogo e varianti di introduzione consentite. Il backend assembla prezzi e condizioni dal profilo; non accetta un corpo email libero generato dal modello. La qualificazione conserva origine e limiti dei dati. I “fatti verificati” sono riscontri nei dati acquisiti, con provenienza dichiarata: non certificano che una fonte o un menu sia aggiornato. Volumi, fornitori e interesse non sono dedotti. Quantità e tempistiche vengono raccolte dalle risposte e portate al commerciale. Una bozza AI resta sempre soggetta a revisione umana.

La configurazione dei provider resta nel backend. Non è presente alcuna chiave nel frontend o nei dati demo. Non registrare token, contenuti completi di `.env` o header Authorization nei log.

## Contratto dei connettori HTTP

Gli URL sono configurazione dell'amministratore, non input dei lead. In produzione devono essere HTTPS. Non viene implementata una navigazione automatica dei siti dei contatti.

Ogni adattatore effettua `POST` JSON all'URL completo configurato, con `Authorization: Bearer <API_KEY>`. I connettori che producono effetti esterni ricevono `Idempotency-Key`: **il servizio remoto deve supportare idempotenza persistente**, restituendo lo stesso risultato per la stessa chiave. Non collegare un endpoint che ignora questo header. Il controllo locale impedisce invii concorrenti della stessa bozza; l'idempotenza remota è necessaria anche se la risposta si perde dopo un invio riuscito.

Questi sono contratti di un adattatore/gateway: l'API di un fornitore specifico potrebbe richiedere una mappatura. Non vengono dichiarate integrazioni native non implementate.

### Email

Variabili: `EMAIL_PROVIDER_URL`, `EMAIL_API_KEY`, `EMAIL_FROM`.

Richiesta:

```json
{
  "from": "vendite@example.com",
  "to": "destinatario@example.com",
  "subject": "Oggetto approvato",
  "body": "Testo approvato"
}
```

Il connettore deve restituire HTTP 2xx con `id`, `message_id` o `provider_message_id`. Un esito dichiarato fallito o privo di identificatore non viene segnato come inviato. Risposte HTTP 400/422 con `code` (anche dentro `error`) uguale a `invalid_recipient`, `hard_bounce` o `recipient_not_found` sono errori permanenti e interrompono i ricontatti. L'endpoint di invio controlla stato approvato, destinatario, produttore, eventuale blocco dei ricontatti e chiave di idempotenza.

L'importazione delle risposte avviene tramite registrazione autenticata nell'app/API. **Non è implementata la sincronizzazione di una casella email né un webhook pubblico di ricezione.** Un'integrazione inbound deve autenticare la provenienza, associare il messaggio al produttore corretto e deduplicarlo prima di usare l'API. Rifiuto, disiscrizione ed errore permanente arrestano il ricontatto.

### Ricerca lead

Variabili: `SEARCH_PROVIDER_URL`, `SEARCH_API_KEY`.

Richiesta: `{"query":"ristoranti","city":"Bologna"}`. Risposta: un array di contatti, oppure `{"leads":[...]}` o `{"results":[...]}`.

Ogni contatto deve avere `company_name` e `source`; campi opzionali: `contact_name`, `email`, `phone`, `city`, `business_type`, `website`, `menu_text`, `notes`. Un'email assente rimane assente. La data di acquisizione è assegnata dal server. I contatti importati vengono deduplicati per produttore sia per email normalizzata sia per identità aziendale.

Non c'è scraping dei siti, acquisto automatico di liste o generazione di indirizzi presunti. Fonte mancante e record invalidi sono errori da correggere.

### Calendario

Variabili: `CALENDAR_PROVIDER_URL`, `CALENDAR_API_KEY`.

Il connettore riceve titolo, inizio/fine ISO UTC e riferimenti alla richiesta. Deve prenotare realmente la disponibilità, applicare la propria politica sui conflitti e restituire HTTP 2xx con `id`, `event_id` o `provider_event_id`. Risposte `failed`, `pending`, `tentative`, `cancelled` o senza ID non confermano l'appuntamento.

La demo esegue un controllo locale delle sovrapposizioni e salva lo stato `simulated`. In produzione lo stato `confirmed` viene assegnato soltanto dopo il successo remoto. Le disponibilità di un calendario reale, inviti ai partecipanti e modifica/cancellazione degli eventi dipendono dal servizio esterno; non sono simulate come prenotazioni reali.

### CRM

Variabili: `CRM_PROVIDER_URL`, `CRM_API_KEY`.

Il connettore riceve la scheda del lead/produttore e deve restituire HTTP 2xx con `id`, `record_id` o `provider_id`. La pipeline interna funziona senza un CRM esterno. Non viene implementata una sincronizzazione bidirezionale né un mapping specifico Salesforce/HubSpot.

### Voce

`VOICE_PROVIDER_URL` e `VOICE_API_KEY` sono predisposti per una futura integrazione. Il modulo rimane **non collegato** e non effettua telefonate, anche se i campi sono impostati. Non è implementata una conversazione vocale.

## Sicurezza e responsabilità operative

- JWT con scadenza; password con hash PBKDF2 e salt casuale. Ogni accesso dati usa il produttore dell'utente autenticato; il client non sceglie un tenant arbitrario.
- Le bozze sono modificabili prima dell'approvazione. Ogni modifica invalida l'approvazione precedente. Il worker non approva e non invia autonomamente email.
- Una risposta arresta la sequenza di outreach. Risposte a richieste lecite possono essere preparate come nuove bozze; disiscrizione, rifiuto ed errore permanente impediscono ulteriore contatto.
- Un errore provider consente una nuova approvazione e un retry con stesso testo e chiave; il testo già tentato rimane immutabile. Se il processo si interrompe dopo aver iniziato l’invio, la bozza resta sospesa in “invio in corso”: serve riconciliare l’esito con il provider prima di qualsiasi recupero operativo. Non è implementato un recupero automatico dei crash.
- Audit e stato delle attività persistono nel database. Gli errori provider vengono restituiti senza includere credenziali.
- CORS va limitato ai domini dell'interfaccia in produzione. Il proxy HTTP locale di Vite/nginx evita la necessità di esporre chiavi al browser.
- Prima dell'uso reale configurare HTTPS, backup, segreti, monitoraggio, limiti di utilizzo e politiche di conservazione dei dati. Registrazione pubblica e gestione accessi amministrativi richiedono una valutazione per il proprio deployment.

Nessun provider remoto è stato contattato durante sviluppo o test. Il comportamento locale e i fallimenti degli adattatori sono verificati con simulazioni; le credenziali reali e la semantica di idempotenza del proprio gateway vanno validate in un ambiente di test dedicato.

## Build dietro un proxy aziendale

I Dockerfile supportano il secret BuildKit opzionale `build_ca` per un bundle di certificati CA fidati. Il certificato viene montato soltanto durante `pip install` / `npm ci`, senza disattivare TLS. In un ambiente con proxy, fornire anche gli argomenti di build `HTTP_PROXY`, `HTTPS_PROXY` e `NO_PROXY` tramite le variabili già configurate; non incorporare credenziali nel Dockerfile o nel repository. Se il nome del proxy non è risolvibile nel builder, configurare il networking/DNS del builder. Il comando Compose standard usa il normale trust store quando questo secret non è fornito.

Per la produzione utilizzare un database pulito dedicato: l'API rifiuta l'avvio se trova l'account demo con password pubblica. Cambiare soltanto `DEMO_MODE` sul database della demo non converte i dati in produzione e non elimina alcun record.
