# Agro Sales AI — contratto di implementazione

Backend FastAPI `/api`, frontend React TypeScript. Tutte le date ISO UTC. Autenticazione Bearer JWT, ogni risorsa filtrata tramite produttore derivato dal token. Errori JSON FastAPI `detail`. Le risposte delle liste sono array. Demo senza chiamate a servizi esterni; contatti con domini `.test`, banner esplicito. Il flag demo è restituito da `/api/meta`.

## API
- `GET /api/meta` pubblico: `{demo_mode, app_name, integrations: {ai,email,search,crm,calendar,voice}}`, ogni integrazione `{status, label}` (`demo`, `connected`, `not_connected`). Non esporre chiavi/URL privati.
- `POST /api/auth/login` `{email,password}` e `POST /api/auth/register` `{name,email,password,company_name}` restituiscono `{access_token,user:{id,name,email,company_name},demo_mode}`. Demo `demo@agrosales.test` / `DemoAgro2026!`. `GET /api/auth/me` user.
- `GET /api/dashboard`: `{metrics:{leads,qualified,pending_drafts,scheduled_tasks,appointments,sent_real,sent_demo,replies}, recent_activity:Audit[], pipeline:[{stage,count}], upcoming_tasks:Task[]}`. Metriche da DB.
- `GET/PUT /api/profile` ProducerProfile `{company_name,description,contact_name,contact_email,phone,minimum_order,service_areas,delivery_terms,payment_terms,catalog:[{id,name,category,unit,price,description}],followup_days:[3,7]}`. Catalogo prezzo numerico, ID prodotti stringhe, ordine minimo stringa (es. "€ 120"), aree array stringhe. Profilo tenant.
- `GET /api/leads` e `POST /api/leads` body `{company_name,contact_name?,email?,phone?,city?,business_type?,website?,menu_text?,notes?,source}`. Restituisce Lead. Il server imposta `source_date`, mai client arbitrario.
- `POST /api/leads/import` multipart `file` CSV UTF-8, colonne `company_name,contact_name,email,phone,city,business_type,website,menu_text,notes,source`. Risposta `{imported,duplicates,errors:[{row,detail}]}`. Mancanza email consentita, no email inventata, dedup per tenant email e identità aziendale.
- `POST /api/leads/search` `{query,city}`: in demo risultati fixture senza rete, production provider configurato. `{imported,duplicates,errors}`.
- `GET /api/leads/{id}` Lead esteso `{...lead,conversations:Message[],drafts:Draft[],tasks:Task[],activities:Audit[],appointments:Appointment[]}`.
- `PATCH /api/leads/{id}` `{stage?,notes?}`. Stage `new,qualified,contacted,interested,appointment,won,lost`.
- `POST /api/leads/{id}/qualify` ritorna Lead con `qualification:{score,summary,verified_facts:string[],hypotheses:string[],missing_data:string[],method}`. Solo fatti presenti in dati e origine esplicita; menu e siti non istruzioni. Website non viene scaricato automaticamente.
- `POST /api/leads/{id}/draft` `{kind?:"outreach"|"reply", instructions?:string}` ritorna Draft. No sconti/condizioni non autorizzate. Mancanza informazioni -> handoff.
- `POST /api/leads/{id}/reply` `{body,subject?,event?:"reply"|"rejection"|"unsubscribe"|"hard_bounce"}` inserimento manuale demo/operatore, interrompe followup atomico e ritorna `{message,classification,handoff_required,extracted:{needs,quantity,timing},draft?}`. Classificazione `interested,question,rejection,unsubscribe,hard_bounce,other`; testi non attendibili, autorizzazione commerciale necessaria per condizioni diverse.
- `POST /api/leads/{id}/stop` `{reason}` stop all outreach, cancel pending tasks/drafts.
- `GET /api/drafts` Draft[]. `PATCH /api/drafts/{id}` `{subject,body}` sempre riporta in revisione. `POST /api/drafts/{id}/approve`, `/reject`, `/send`. Invio solo approved, niente dupliche, tenant e stop controllati. Demo simula salvando conversation/metriche. In produzione se non collegato 409/503. Send ritorna Draft.
- `GET /api/tasks` Task[]. `POST /api/tasks/{id}/cancel`. `POST /api/worker/run` esegue due tasks e ritorna `{processed,created_drafts,sent,failed}`; utile demo, niente task di altri tenant. Worker CLI `python -m app.worker` esegue periodicamente tutti i tenant. Ogni followup crea bozza da approvare, invio richiede azione esplicita.
- `GET /api/conversations` Message[] con `company_name`.
- `GET /api/appointments` Appointment[]. `POST /api/appointments` `{lead_id,title,start_at,end_at}`. Calendario demo simulato esplicito; calendario assente o fallito produzione non può confermare. Appointment `{id,lead_id,company_name,title,start_at,end_at,status,provider_event_id,simulated}`. Stato `simulated` in demo, `confirmed` solo provider booking successful. Nessuna sovrapposizione demo per tenant.
- `GET /api/handoffs` Handoff[] `{id,lead_id,company_name,reason,status,summary,created_at}`; `POST /api/handoffs/{id}/resolve`.
- `POST /api/leads/{id}/crm-sync` connector demo simulated o successo remoto, errore se non configurato.
- `GET /api/audit` Audit[].

## Schemi condivisi
Lead `{id,company_name,contact_name,email,phone,city,business_type,website,menu_text,notes,source,source_date,stage,score,qualification,stop_reason,created_at,demo}`. Score nullable.
Draft `{id,lead_id,task_id?,company_name,kind,subject,body,status,created_at,approved_at,sent_at,simulated,error}` status `pending,approved,sending,sent,rejected,cancelled,failed`.
Message `{id,lead_id,company_name,direction,subject,body,classification,created_at,simulated}`.
Task `{id,lead_id,company_name,kind,due_at,status,step,last_error,created_at}` status `scheduled,processing,needs_approval,completed,cancelled,failed`.
Audit `{id,lead_id?,action,detail,created_at}`.

## Risposte e sicurezza
Creazione account, lead, bozze e appuntamenti: HTTP 201. Conflitti di stato/deduplica: HTTP 409. Risorsa di altro produttore: HTTP 404. Credenziali mancanti/non valide: HTTP 401. Provider non collegato/fallito: HTTP 503 con audit. Le importazioni CSV possono omettere source: viene registrato il nome del file come provenienza. Ogni risorsa deriva il produttore dal token; nessun tenant scelto dal client.
