import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { ArrowRight, Bot, CalendarClock, Check, ChevronDown, ChevronRight, Circle, Clock3, FileCheck2, GitBranch, Leaf, LoaderCircle, Mail, MessageSquare, Pause, Phone, Play, Plus, RefreshCw, Search, ShieldCheck, Sparkles, Square, Users, X } from "lucide-react";
import { api, post } from "./api";
import type { Draft, Profile } from "./types";
import type { AgentEvent, Campaign, CampaignConfig, CampaignLead } from "./automationTypes";

const agentInfo = [
  { id: "lead_generation", name: "Lead Generation", subtitle: "Trova opportunità", icon: Search },
  { id: "qualification", name: "Qualification", subtitle: "Valuta la compatibilità", icon: Sparkles },
  { id: "outreach", name: "Outreach", subtitle: "Prepara la prima proposta", icon: Mail },
  { id: "follow_up", name: "Follow-up", subtitle: "Coltiva la relazione", icon: CalendarClock },
  { id: "sales", name: "Sales", subtitle: "Ascolta e risponde", icon: MessageSquare },
  { id: "crm", name: "CRM", subtitle: "Aggiorna ogni opportunità", icon: Users },
];
const states: Record<string, string> = {
  CREATED: "Pronta da avviare", DRAFT: "Pronta da avviare", RUNNING: "In esecuzione", PAUSED: "In pausa", COMPLETED: "Completata", FAILED: "Errore", STOPPED: "Interrotta",
  IDLE: "Pronto", WORKING: "Al lavoro", WAITING: "In attesa", ERROR: "Errore",
  NEW: "Nuovo", DISCOVERED: "Trovato", QUALIFYING: "In valutazione", QUALIFIED: "Qualificato", OUTREACH_READY: "Bozza pronta", CONTACTED: "Contattato", FOLLOW_UP: "Follow-up", REPLIED: "Ha risposto", INTERESTED: "Interessato", MEETING: "Appuntamento", HANDOFF: "Al commerciale", WON: "Cliente", LOST: "Escluso / perso", DO_NOT_CONTACT: "Non contattare", LOW_PRIORITY: "Sotto soglia", QUEUED: "In programma", CANCELLED: "Annullata", DONE: "Completata",
};
const taskNames: Record<string, string> = { DISCOVER: "Ricerca opportunità", QUALIFY: "Analisi della compatibilità", OUTREACH: "Preparazione della proposta", FOLLOWUP: "Preparazione follow-up", SALES: "Analisi della conversazione", CRM: "Aggiornamento della pipeline" };
const actionText = (value?: string | null) => {
  if (!value) return "In attesa del workflow";
  if (taskNames[value]) return taskNames[value];
  if (value.startsWith("Job previsto ")) {
    const when = new Date(value.slice("Job previsto ".length));
    if (!Number.isNaN(when.getTime())) return `Prossima attività: ${when.toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
  }
  return value;
};
const feedback = (error: unknown) => error instanceof Error ? error.message : "Operazione non riuscita. Riprova.";
const time = (value: string) => new Date(value).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const number = (metrics: Record<string, number>, ...keys: string[]) => keys.map(key => metrics[key]).find(value => typeof value === "number") ?? 0;

function Action({ children, onClick, disabled, variant = "primary", type = "button" }: { children: ReactNode; onClick?: () => void; disabled?: boolean; variant?: string; type?: "button" | "submit" }) {
  return <button className={`button ${variant}`} type={type} disabled={disabled} onClick={onClick}>{children}</button>;
}
function Status({ value }: { value: string }) {
  const upper = value.toUpperCase();
  return <span className={`badge automation-status ${upper.toLowerCase()}`}><span className="status-dot" />{states[upper] || value}</span>;
}
function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const element = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    element.current?.querySelector<HTMLElement>("input, button")?.focus();
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab") return;
      const controls = element.current?.querySelectorAll<HTMLElement>("button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled)");
      if (!controls?.length) return;
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handler);
    return () => { document.removeEventListener("keydown", handler); previous?.focus(); };
  }, [onClose]);
  return <div className="modal-layer" onClick={onClose}><section ref={element} className="modal wide automation-modal" role="dialog" aria-modal="true" aria-label={title} onClick={event => event.stopPropagation()}><div className="modal-header"><div><span className="eyebrow">IL TUO SISTEMA COMMERCIALE</span><h2>{title}</h2></div><button className="icon-button" aria-label="Chiudi finestra" onClick={onClose}><X size={22} /></button></div>{children}</section></div>;
}

// Handles escaped quotes and multiline CSV cells; values are data, never agent instructions.
function readCsv(text: string): Record<string, string>[] {
  const rows: string[][] = [], row: string[] = [];
  let cell = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') { cell += '"'; i++; }
      else quoted = !quoted;
    } else if (!quoted && char === ",") { row.push(cell); cell = ""; }
    else if (!quoted && (char === "\n" || char === "\r")) {
      if (char === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); if (row.some(value => value.trim())) rows.push([...row]); row.length = 0; cell = "";
    } else cell += char;
  }
  if (quoted) throw new Error("CSV non valido: una cella tra virgolette non è chiusa.");
  row.push(cell); if (row.some(value => value.trim())) rows.push(row);
  const headers = (rows.shift() || []).map(value => value.trim().replace(/^\uFEFF/, ""));
  if (!headers.includes("company_name")) throw new Error("Il CSV deve avere la colonna company_name, come il file demo.");
  return rows.map(values => Object.fromEntries(headers.map((header, index) => [header, values[index]?.trim() || ""])));
}

function CampaignForm({ profile, demo, busy, onCreate }: { profile: Profile; demo: boolean; busy: boolean; onCreate: (config: CampaignConfig) => Promise<void> }) {
  const [products, setProducts] = useState(profile.catalog.map(item => item.id));
  const [provider, setProvider] = useState<CampaignConfig["provider"]>(demo ? "mock" : "configured");
  const [mode, setMode] = useState<CampaignConfig["outreach_mode"]>("APPROVAL_REQUIRED");
  const [autonomy, setAutonomy] = useState<CampaignConfig["autonomy_level"]>("LOW");
  const [csvRows, setCsvRows] = useState<Record<string, string>[]>([]);
  const [csvError, setCsvError] = useState("");
  const [followup, setFollowup] = useState(true);
  const [automatic, setAutomatic] = useState(false);
  const hasAutomatic = mode !== "DRAFT" && autonomy !== "LOW";
  const autonomyDescription = mode === "DRAFT"
    ? "Gli agenti preparano solo bozze. Nessun invio automatico, qualunque sia il livello di autonomia."
    : autonomy === "LOW"
      ? "Approvi la prima email, ogni follow-up e tutte le risposte."
      : mode === "AUTO_SEND"
        ? "Autonomia alta: prima email e follow-up standard possono essere inviati automaticamente entro i limiti autorizzati. Le risposte restano da approvare."
        : "Approvi la prima email e le risposte. I follow-up standard possono partire automaticamente entro i limiti autorizzati.";
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const days = String(values.get("sequence")).split(",").map(value => Number(value.trim()));
    if (!days.length || days[0] !== 0 || days.some((value, index) => !Number.isInteger(value) || value < 0 || value > 365 || (index > 0 && value <= days[index - 1]))) { setCsvError("La sequenza deve iniziare dal giorno 0 e contenere giorni crescenti tra 0 e 365, separati da virgola."); return; }
    await onCreate({
      name: String(values.get("name")), objective: String(values.get("objective")), target: String(values.get("target")), city: String(values.get("city")), lead_count: Number(values.get("lead_count")), product_ids: products,
      minimum_score: Number(values.get("minimum_score")), outreach_mode: mode, followup_enabled: followup, followup_days: days, handoff_threshold: Number(values.get("handoff_threshold")), autonomy_level: autonomy, provider,
      ...(provider === "csv" ? { csv_rows: csvRows } : {}), demo_day_seconds: demo ? Number(values.get("demo_day_seconds")) : 10, max_emails: Number(values.get("max_emails")), max_followups: Number(values.get("max_followups")), rate_limit_per_minute: Number(values.get("rate_limit_per_minute")), authorize_auto_send: hasAutomatic && automatic,
    });
  };
  return <form onSubmit={event => void submit(event)}>
    <label className="field"><span>Nome della campagna</span><input name="name" defaultValue="Ristoranti premium Milano" required maxLength={200} /></label>
    <label className="field"><span>Obiettivo commerciale</span><textarea name="objective" rows={2} defaultValue="Trovare clienti HORECA compatibili con i nostri prodotti e aprire nuove relazioni commerciali." required /></label>
    <div className="form-grid">
      <label className="field"><span>Target</span><select aria-label="Target" name="target" defaultValue="Ristoranti"><option>Ristoranti</option><option>Hotel</option><option>Catering</option><option>Bar</option><option>HORECA</option></select></label>
      <label className="field"><span>Zona</span><input name="city" defaultValue="Milano" required /></label>
      <label className="field"><span>Numero di lead</span><input name="lead_count" type="number" min={1} max={500} defaultValue={20} required /></label>
      <label className="field"><span>Origine dei contatti</span><select aria-label="Origine dei contatti" value={provider} onChange={event => setProvider(event.target.value as CampaignConfig["provider"])}>{demo && <option value="mock">Dataset demo · nessuna ricerca reale</option>}<option value="csv">Importazione CSV</option>{!demo && <option value="configured">Provider di ricerca configurato</option>}</select></label>
    </div>
    {provider === "csv" && <label className="field"><span>Carica il tuo CSV</span><input aria-label="Carica il tuo CSV" type="file" accept=".csv,text/csv" required onChange={event => { const file = event.target.files?.[0]; if (!file) return; void file.text().then(text => { const rows = readCsv(text); setCsvRows(rows.map(item => ({ ...item, source: item.source || `CSV: ${file.name}` }))); setCsvError(""); }).catch(error => { setCsvRows([]); setCsvError(feedback(error)); }); }} /><small>{csvRows.length ? `${csvRows.length} righe lette. Fonte e data saranno conservate dal server.` : "Stesse colonne del CSV demo: company_name, email, city, source…"}</small></label>}
    <fieldset className="automation-products"><legend>Prodotti da proporre</legend>{!profile.catalog.length && <p className="automation-autonomy-help">Aggiungi almeno un prodotto nella pagina La tua azienda prima di creare una campagna.</p>}<div>{profile.catalog.map(product => <label key={product.id} className={`product-choice ${products.includes(product.id) ? "selected" : ""}`}><input type="checkbox" checked={products.includes(product.id)} onChange={event => setProducts(previous => event.target.checked ? [...previous, product.id] : previous.filter(id => id !== product.id))} /><span><strong>{product.name}</strong><small>€ {product.price.toLocaleString("it-IT", { minimumFractionDigits: 2 })} / {product.unit}</small></span><Check size={14} /></label>)}</div></fieldset>
    <div className="form-grid">
      <label className="field"><span>Score minimo / 100</span><input type="number" name="minimum_score" defaultValue={70} min={0} max={100} required /></label>
      <label className="field"><span>Soglia passaggio al commerciale / 100</span><input type="number" name="handoff_threshold" defaultValue={85} min={0} max={100} required /></label>
      <label className="field"><span>Modalità outreach</span><select aria-label="Modalità outreach" value={mode} onChange={event => { const next = event.target.value as CampaignConfig["outreach_mode"]; setMode(next); if (next === "AUTO_SEND") setAutonomy("HIGH"); setAutomatic(false); }}><option value="DRAFT">Solo bozze</option><option value="APPROVAL_REQUIRED">Approvazione prima dell’invio</option><option value="AUTO_SEND">Automatico, entro i limiti autorizzati</option></select></label>
      <label className="field"><span>Autonomia degli agenti</span><select aria-label="Autonomia degli agenti" value={autonomy} onChange={event => { const next = event.target.value as CampaignConfig["autonomy_level"]; setAutonomy(next); if (next !== "HIGH" && mode === "AUTO_SEND") setMode("APPROVAL_REQUIRED"); setAutomatic(false); }}><option value="LOW">Bassa · approvi ogni comunicazione</option><option value="MEDIUM">Media · follow-up standard automatici</option><option value="HIGH">Alta · azioni consentite automatiche</option></select></label>
    </div>
    <p className="automation-autonomy-help">{autonomyDescription}</p>
    <div className="automation-followup"><label className="automation-checkbox"><input type="checkbox" checked={followup} onChange={event => setFollowup(event.target.checked)} /><span>Follow-up attivi</span></label><label className="field"><span>Sequenza · giorni dopo la prima email</span><input name="sequence" defaultValue="0, 3, 7, 14" required /><small>Il giorno 0 è la prima presentazione. Una risposta interrompe i ricontatti.</small></label></div>
    <details className="automation-limits"><summary><ShieldCheck size={16} /> Limiti e controllo <ChevronDown size={15} /></summary><div className="form-grid"><label className="field"><span>Massimo email per campagna</span><input type="number" name="max_emails" min={1} max={1000} defaultValue={100} required /></label><label className="field"><span>Massimo follow-up per lead</span><input type="number" name="max_followups" min={0} max={9} defaultValue={3} required /></label><label className="field"><span>Email al minuto</span><input type="number" name="rate_limit_per_minute" min={1} max={100} defaultValue={30} required /></label>{demo && <label className="field"><span>Secondi demo per 1 giorno della sequenza</span><input type="number" name="demo_day_seconds" min={1} max={3600} defaultValue={10} required /></label>}</div></details>
    {hasAutomatic && <label className="automation-checkbox automation-permission"><input type="checkbox" checked={automatic} required onChange={event => setAutomatic(event.target.checked)} /><span>{demo ? "Autorizzo gli invii automatici simulati nei limiti della campagna. Nessuna email reale." : "Autorizzo le comunicazioni automatiche consentite, con i prodotti e i limiti scelti."}</span></label>}
    {demo && <div className="info-strip"><ShieldCheck size={17} /> Demo completa: stessi workflow e database, contatti fittizi e invii simulati. Nessun servizio esterno.</div>}
    {csvError && <p className="form-error" role="alert">{csvError}</p>}
    <div className="modal-footer"><span className="muted small">Potrai avviare la campagna dopo averla creata.</span><Action type="submit" disabled={busy || !products.length || (provider === "csv" && !csvRows.length) || (hasAutomatic && !automatic)}>{busy ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />}Crea campagna AI</Action></div>
  </form>;
}

function LeadGraph({ lead, onOpen, onDraft, draft, onReply, onVoice, demo, onStop, busy }: { lead: CampaignLead; onOpen: () => void; onDraft: () => void; draft?: Draft; onReply: () => void; onVoice: () => void; demo: boolean; onStop: () => void; busy: boolean }) {
  const stage = (lead.workflow_stage || lead.stage || "NEW").toUpperCase();
  return <article className="automation-lead"><div className="automation-lead-heading"><div><button className="text-button" onClick={onOpen}>{lead.company_name}</button><span>#{lead.lead_id}{demo && " · Dato demo"}</span></div><div><span className="automation-lead-score">{lead.score == null ? "Da valutare" : `${lead.score}/100`}</span><Status value={stage} /></div></div>
    {lead.qualification?.product_fit != null && <div className="automation-lead-qualification"><span>Product fit <strong>{lead.qualification.product_fit}/100</strong></span><span>Potenziale <strong>{lead.qualification.commercial_potential ?? "—"}/100</strong></span><span>Confidenza <strong>{lead.qualification.confidence ?? "—"}/100</strong></span><span>Score totale <strong>{lead.qualification.total_score ?? lead.score ?? "—"}/100</strong></span></div>}
    <div className="workflow-graph" aria-label={`Avanzamento di ${lead.company_name}`}>{(lead.graph || []).map((step, index) => <div className={`workflow-step ${step.status}`} key={step.step}><span className="workflow-node">{step.status === "completed" ? <Check size={12} /> : step.status === "active" ? <span className="workflow-active-dot" /> : step.status === "stopped" ? <Square size={7} /> : <Circle size={8} />}</span><span>{step.label}</span>{index < (lead.graph?.length || 0) - 1 && <span className="workflow-connector" />}</div>)}</div>
    <div className="automation-lead-actions">{draft && <button className="section-link" onClick={onDraft}><FileCheck2 size={14} />{draft.status === "pending" ? "Rivedi e approva bozza" : draft.status === "approved" ? "Apri e simula invio" : "Apri messaggio"}<ArrowRight size={14} /></button>}{demo && <><button className="section-link" onClick={onReply}><MessageSquare size={14} />Simula risposta lead</button><button className="section-link" onClick={onVoice}><Phone size={14} />Simula chiamata</button></>}<button className="section-link automation-stop-link" disabled={busy || !!lead.stop_reason} onClick={onStop}>Non contattare</button></div>
  </article>;
}

function InteractionForm({ voice, busy, onSubmit }: { voice: boolean; busy: boolean; onSubmit: (body: Record<string, string>) => Promise<void> }) {
  const [preset, setPreset] = useState("interested");
  const [body, setBody] = useState("");
  return <form onSubmit={event => { event.preventDefault(); void onSubmit({ preset, ...(body.trim() ? { [voice ? "transcript" : "body"]: body.trim() } : {}) }); }}>
    <div className="info-strip"><ShieldCheck size={18} />{voice ? "Trascrizione demo, nessuna telefonata. Il Sales Agent la analizza nello stesso workflow delle risposte." : "La risposta simulata viene salvata nel database e avvia il Sales Agent. I follow-up si interrompono."}</div>
    <label className="field"><span>Scenario della risposta</span><select aria-label="Scenario della risposta" value={preset} onChange={event => setPreset(event.target.value)}><option value="interested">Interessato</option><option value="price_list">Chiede listino</option><option value="sample">Vuole campione</option><option value="price_objection">Obiezione prezzo</option><option value="not_interested">Non interessato</option><option value="meeting">Vuole appuntamento</option></select></label>
    <label className="field"><span>{voice ? "Trascrizione personalizzata (facoltativa)" : "Risposta personalizzata (facoltativa)"}</span><textarea rows={5} value={body} onChange={event => setBody(event.target.value)} placeholder={voice ? "Scrivi il contenuto della conversazione demo…" : "Oppure scrivi una risposta: sarà trattata come dato, mai come istruzione agli agenti."} /></label>
    <div className="modal-footer"><span className="badge demo">DEMO · Simulato</span><Action type="submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : voice ? <Phone size={16} /> : <MessageSquare size={16} />}{voice ? "Simula chiamata demo" : "Simula risposta"}</Action></div>
  </form>;
}

export default function AutomationCenter({ profile, drafts, demo, onRefresh, onOpenLead, onOpenDraft, onCloser, notify }: { profile: Profile; drafts: Draft[]; demo: boolean; onRefresh: () => Promise<void>; onOpenLead: (id: number) => void; onOpenDraft: (draft: Draft) => void; onCloser: () => void; notify: (message: string, error?: boolean) => void }) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [newCampaign, setNewCampaign] = useState(false);
  const [interaction, setInteraction] = useState<{ lead: CampaignLead; voice: boolean } | null>(null);
  const [tab, setTab] = useState("activity");
  const [showAllLeads, setShowAllLeads] = useState(false);
  const lastRevision = useRef<string>("");
  const activeId = useRef<number | null>(null);
  const mounted = useRef(true);
  const refresh = useCallback(async () => {
    const list = await api<Campaign[]>("/campaigns");
    if (!mounted.current) return;
    setCampaigns(list);
    const id = activeId.current || list[0]?.id;
    if (!id) { setCampaign(null); setError(""); return; }
    if (!activeId.current) { activeId.current = id; setSelectedId(id); }
    const detail = await api<Campaign>(`/campaigns/${id}`);
    if (!mounted.current || activeId.current !== id) return;
    setCampaign(detail); setError("");
    const revision = `${id}:${detail.status}:${(detail.events || []).map(event => event.id).join(",")}:${JSON.stringify(detail.metrics)}`;
    if (lastRevision.current && lastRevision.current !== revision) await onRefresh();
    lastRevision.current = revision;
  }, [onRefresh]);
  useEffect(() => {
    mounted.current = true;
    let inFlight = false;
    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      try { await refresh(); } catch (cause) { if (mounted.current) setError(feedback(cause)); } finally { inFlight = false; if (mounted.current) setLoading(false); }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    return () => { mounted.current = false; window.clearInterval(timer); };
  }, [refresh]);
  const select = async (id: number) => { activeId.current = id; setSelectedId(id); lastRevision.current = ""; setShowAllLeads(false); try { await refresh(); } catch (cause) { setError(feedback(cause)); } };
  const run = async (operation: () => Promise<unknown>, message: string) => {
    if (busy) return;
    setBusy(true);
    try { await operation(); await refresh(); await onRefresh(); notify(message); }
    catch (cause) { notify(feedback(cause), true); }
    finally { setBusy(false); }
  };
  const create = async (config?: CampaignConfig) => {
    await run(async () => {
      const item = await post<Campaign>(config ? "/campaigns" : "/campaigns/demo-scenario", config);
      activeId.current = item.id; setSelectedId(item.id); setCampaign(item); setNewCampaign(false);
    }, "Campagna creata: premi Avvia campagna AI per iniziare");
  };
  const status = campaign?.status.toUpperCase();
  const leads = campaign?.leads || [];
  const events = [...(campaign?.events || [])].sort((a, b) => b.id - a.id);
  const tasks = campaign?.tasks || [];
  const ownedDraftIds = new Set([
    ...leads.map(lead => lead.draft_id).filter((id): id is number => typeof id === "number"),
    ...tasks.map(task => task.result?.draft_id).filter((id): id is number => typeof id === "number"),
  ]);
  const campaignDrafts = drafts.filter(draft => ownedDraftIds.has(draft.id));
  const waitingDrafts = campaignDrafts.filter(draft => ["pending", "approved"].includes(draft.status));
  const closeCampaignDialog = useCallback(() => setNewCampaign(false), []);
  const closeInteraction = useCallback(() => setInteraction(null), []);
  return <div className="automation-center">
    <div className="page-header"><div><div className="eyebrow">DAL PRIMO PROSPECT ALLA RELAZIONE COMMERCIALE</div><h1>Automazioni AI</h1><p>Un team di agenti al lavoro. Tu decidi la direzione, segui ogni passo.</p></div><div className="page-actions"><Action onClick={() => setNewCampaign(true)}><Plus size={18} />Nuova campagna AI</Action></div></div>
    <section className="automation-intro"><div className="automation-intro-icon"><Bot size={31} strokeWidth={1.5} /></div><div><span className="eyebrow">IL TUO TEAM COMMERCIALE, COORDINATO</span><h2>Le opportunità prendono forma. Insieme.</h2><p>Ricerca, analisi, messaggi e follow-up: ogni passaggio lascia una traccia nella tua pipeline.</p></div><div className="automation-intro-side">{demo ? <span className="badge demo"><ShieldCheck size={12} />FULL DEMO MODE</span> : <span className="badge qualified">AMBIENTE REALE</span>}<small>{demo ? "Nessuna email o chiamata reale" : "Azioni entro i limiti autorizzati"}</small></div></section>
    {error && <div className="form-error" role="alert">{error}<button className="section-link" onClick={() => void refresh().catch(cause => setError(feedback(cause)))}>Riprova</button></div>}
    <div className="automation-section-heading"><div><h2>Le tue campagne</h2><p>Una direzione chiara, un workflow che continua in background.</p></div>{demo && <button className="section-link" disabled={busy} onClick={() => void create()}><Leaf size={15} />Prova lo scenario demo<ArrowRight size={15} /></button>}</div>
    {loading && !campaigns.length ? <div className="automation-loading"><LoaderCircle size={22} className="spin" />Carichiamo le campagne…</div> : !campaigns.length ? <section className="card automation-empty"><div className="automation-empty-symbol"><GitBranch size={32} /></div><h3>Il tuo team è pronto a partire</h3><p>Crea una campagna o prova Cascina Verde: formaggi premium, olio EVO e salumi artigianali per 20 ristoranti demo di Milano.</p><div className="button-row"><Action onClick={() => setNewCampaign(true)}><Plus size={16} />Nuova campagna AI</Action>{demo && <Action variant="secondary" disabled={busy} onClick={() => void create()}><Sparkles size={16} />Prova lo scenario demo</Action>}</div></section> : <div className="campaign-grid">{campaigns.map(item => <button key={item.id} className={`card campaign-card ${selectedId === item.id ? "selected" : ""}`} onClick={() => void select(item.id)}><div><span className="campaign-symbol"><Leaf size={18} /></span><Status value={item.status} /></div><h3>{item.name}</h3><p>{item.target} · {item.city}</p><div className="campaign-card-progress"><strong>{number(item.metrics, "leads", "discovered", "generated", "lead_count")}</strong><span>/ {item.lead_count} lead</span><ChevronRight size={16} /></div></button>)}</div>}
    {campaign && <>
      <section className="card campaign-control"><div><span className="eyebrow">CAMPAGNA SELEZIONATA</span><h2>{campaign.name}</h2><p>{campaign.objective}</p></div><div className="campaign-control-actions"><Status value={campaign.status} /><div className="button-row">{["DRAFT", "CREATED"].includes(status || "") && <Action disabled={busy} onClick={() => void run(() => post(`/campaigns/${campaign.id}/start`), "Campagna avviata: gli agenti lavorano in background")}><Play size={15} />Avvia campagna AI</Action>}{status === "RUNNING" && <Action variant="secondary" disabled={busy} onClick={() => void run(() => post(`/campaigns/${campaign.id}/pause`), "Campagna in pausa: i ricontatti sono sospesi")}><Pause size={15} />Pausa campagna</Action>}{status === "PAUSED" && <Action disabled={busy} onClick={() => void run(() => post(`/campaigns/${campaign.id}/resume`), "Campagna ripresa")}><Play size={15} />Riprendi campagna</Action>}{["RUNNING", "PAUSED", "FAILED"].includes(status || "") && <Action variant="danger" disabled={busy} onClick={() => void run(() => post(`/campaigns/${campaign.id}/stop`), "Campagna interrotta")}><Square size={13} />Interrompi</Action>}</div></div></section>
      <div className="automation-summary"><span><Users size={14} />{number(campaign.metrics, "leads", "discovered", "generated", "lead_count")} / {campaign.lead_count} lead</span><span><Sparkles size={14} />Soglia {campaign.minimum_score}/100</span><span><ShieldCheck size={14} />Autonomia {{ LOW: "bassa", MEDIUM: "media", HIGH: "alta" }[campaign.autonomy_level] || campaign.autonomy_level}</span><span><Mail size={14} />{{ DRAFT: "Solo bozze", APPROVAL_REQUIRED: "Approvazione prima dell’invio", AUTO_SEND: demo ? "Invii automatici simulati" : "Invii automatici autorizzati" }[campaign.outreach_mode]}</span>{campaign.followup_enabled && campaign.outreach_mode !== "DRAFT" && campaign.autonomy_level !== "LOW" && <span><CalendarClock size={14} />Follow-up standard automatici{demo ? " simulati" : ""}</span>}{demo && <span><Clock3 size={14} />1 giorno = {campaign.demo_day_seconds}s demo</span>}</div>
      <div className="automation-section-heading"><div><h2>Agent Control Center</h2><p>Sei agenti, una sola strategia commerciale.</p></div><span className="automation-live-indicator"><span />Stati aggiornati dal worker</span></div>
      <div className="agent-grid">{agentInfo.map(info => {
        const agent = campaign.agents?.find(item => item.agent === info.id);
        const Icon = info.icon;
        return <article className={`card agent-card ${agent?.status.toLowerCase() || "idle"}`} key={info.id}><div className="agent-card-heading"><span className="agent-symbol"><Icon size={20} /></span><Status value={agent?.status || "IDLE"} /></div><h3>{info.name} <span>Agent</span></h3><p className="agent-subtitle">{info.subtitle}</p><div className="agent-current-task"><span>ATTIVITÀ CORRENTE</span><p>{taskNames[agent?.current_task || ""] || agent?.current_task || "Nessuna attività in corso"}</p></div><dl><div><dt>Ultima azione</dt><dd>{agent?.last_action || "Nessuna azione registrata"}</dd></div><div><dt>Prossimo passo</dt><dd>{actionText(agent?.next_action)}</dd></div></dl><div className="agent-card-bottom"><span><Check size={13} />{agent?.tasks_completed || 0} completate</span><span className={agent?.error_count ? "error-text" : ""}>{agent?.error_count || 0} errori</span><button className="icon-button" aria-label={`${agent?.status === "PAUSED" ? "Riprendi" : "Metti in pausa"} ${info.name} Agent`} disabled={busy || ["STOPPED", "COMPLETED"].includes(status || "")} onClick={() => void run(() => post(`/campaigns/${campaign.id}/agents/${info.id}/${agent?.status === "PAUSED" ? "resume" : "pause"}`), agent?.status === "PAUSED" ? "Agente ripreso" : "Agente in pausa")}>{agent?.status === "PAUSED" ? <Play size={14} /> : <Pause size={14} />}</button></div></article>;
      })}</div>
      <div className="agent-handoff-flow" aria-label="Coordinamento degli agenti">{agentInfo.map(info => <span key={info.id}>{info.name}<ChevronRight size={13} /></span>)}<button onClick={onCloser}>Human Closer<ArrowRight size={14} /></button></div>
      <div className="automation-workspace-grid"><section className="card live-activity-card"><div className="card-header"><div><h3>Live Agent Activity</h3><p>Ogni evento proviene dal database della campagna.</p></div><span className="badge qualified"><span className="status-dot" />Live</span></div><div className="automation-tabs"><button className={tab === "activity" ? "active" : ""} onClick={() => setTab("activity")}>Attività <span>{events.length}</span></button><button className={tab === "tasks" ? "active" : ""} onClick={() => setTab("tasks")}>Attività programmate <span>{tasks.filter(task => ["QUEUED", "RUNNING", "PENDING", "SCHEDULED", "WAITING"].includes(task.status.toUpperCase())).length}</span></button></div>
        {tab === "activity" ? <div className="live-events" role="log" aria-live="off">{events.length ? events.slice(0, 80).map((event: AgentEvent) => <div className={`live-event ${event.event_type?.includes("error") ? "error" : ""}`} key={event.id}><span className="live-event-dot" /><time>{time(event.created_at)}</time><div><span>{agentInfo.find(info => info.id === event.agent)?.name || "Orchestratore"}</span><p>{event.message}</p>{event.lead_id && <button className="section-link" onClick={() => onOpenLead(event.lead_id!)}>Scheda lead<ChevronRight size={12} /></button>}</div></div>) : <div className="automation-small-empty"><Clock3 size={23} /><p>Avvia la campagna per vedere gli agenti al lavoro.</p></div>}</div> : <div className="agent-task-list">{tasks.length ? tasks.map(task => <article key={task.id}><div><strong>{agentInfo.find(info => info.id === task.agent)?.name || task.agent}</strong><p>{taskNames[task.kind] || task.kind.replaceAll("_", " ")} · {time(task.due_at)}</p>{task.last_error && <p className="error-text">{task.last_error}</p>}</div><Status value={task.status} />{task.status.toUpperCase() === "FAILED" && <button className="icon-button" aria-label={`Riprova attività ${task.id}`} disabled={busy} onClick={() => void run(() => post(`/agent-tasks/${task.id}/retry`), "Attività rimessa in coda")}><RefreshCw size={15} /></button>}</article>) : <div className="automation-small-empty"><p>Nessuna attività ancora. La campagna popola la coda del worker.</p></div>}</div>}
      </section><aside className="automation-side-panel">
        <section className="card automation-approval"><span className="metric-icon orange"><FileCheck2 size={21} /></span><h3>Il tuo tocco, prima dell’invio</h3><p>{waitingDrafts.length ? `${waitingDrafts.length} messaggi di questa campagna aspettano il tuo prossimo passo.` : "Le bozze appariranno qui quando i lead superano la soglia."}</p>{waitingDrafts.slice(0, 4).map(item => <button key={item.id} className="automation-draft-link" onClick={() => onOpenDraft(item)}><span><strong>{item.company_name}</strong><small>{item.status === "approved" ? "Approvata · pronta per l’invio" : "In attesa approvazione"}</small></span><ChevronRight size={16} /></button>)}</section>
        {demo && <section className="automation-time-card"><span className="metric-icon green"><Clock3 size={21} /></span><span className="eyebrow">DEMO TIME ACCELERATION</span><h3>Giorni di lavoro. In pochi secondi.</h3><p>Il worker esegue le vere scadenze della sequenza: 1 giorno equivale a {campaign.demo_day_seconds} secondi demo.</p><Action variant="secondary" disabled={busy || status !== "RUNNING"} onClick={() => void run(() => post(`/campaigns/${campaign.id}/accelerate`, { seconds: campaign.demo_day_seconds * 3 }), "Orologio demo avanzato di 3 giorni della sequenza")}><Clock3 size={15} />Accelera tempo demo</Action><small>Avanza di 3 giorni della sequenza. Non crea invii fittizi nella UI.</small></section>}
        <section className="card automation-human-card"><span className="metric-icon purple"><Users size={21} /></span><h3>Le relazioni passano a te</h3><p>L’AI raccoglie il contesto. Il commerciale decide su opportunità e condizioni.</p><button className="section-link" onClick={onCloser}>Apri Human Closer<ArrowRight size={15} /></button></section>
      </aside></div>
      <div className="automation-section-heading"><div><h2>Automation Graph</h2><p>Il percorso di ogni lead, aggiornato dalle azioni degli agenti.</p></div><span className="badge">{leads.length} lead nel workflow</span></div>
      <section className="card automation-lead-list">{leads.length ? (showAllLeads ? leads : leads.slice(0, 8)).map(item => <LeadGraph key={item.lead_id} lead={item} draft={campaignDrafts.find(draft => draft.id === item.draft_id) || campaignDrafts.find(draft => draft.lead_id === item.lead_id && ["pending", "approved"].includes(draft.status))} onOpen={() => onOpenLead(item.lead_id)} onDraft={() => { const draft = campaignDrafts.find(draft => draft.id === item.draft_id) || campaignDrafts.find(draft => draft.lead_id === item.lead_id); if (draft) onOpenDraft(draft); }} onReply={() => setInteraction({ lead: item, voice: false })} onVoice={() => setInteraction({ lead: item, voice: true })} demo={demo} busy={busy} onStop={() => void run(() => post(`/leads/${item.lead_id}/stop`, { reason: "Non contattare: richiesta del commerciale" }), "Lead escluso: ricontatti interrotti")} />) : <div className="automation-small-empty"><GitBranch size={24} /><p>I lead compariranno progressivamente dopo l’avvio della campagna.</p></div>}{leads.length > 8 && <button className="automation-show-more" onClick={() => setShowAllLeads(!showAllLeads)}>{showAllLeads ? "Mostra meno lead" : `Mostra tutti i ${leads.length} lead`}<ChevronDown size={15} /></button>}</section>
      <details className="card campaign-rules"><summary><ShieldCheck size={17} /><strong>Regole della campagna</strong><ChevronDown size={16} /></summary><dl><div><dt>Email massime</dt><dd>{campaign.max_emails}</dd></div><div><dt>Follow-up massimi per lead</dt><dd>{campaign.max_followups}</dd></div><div><dt>Limite email / minuto</dt><dd>{campaign.rate_limit_per_minute}</dd></div><div><dt>Sequenza</dt><dd>{campaign.followup_enabled ? `Giorni ${(campaign.followup_days || []).join(", ")}` : "Follow-up disattivati"}</dd></div><div><dt>Soglia commerciale</dt><dd>{campaign.handoff_threshold}/100</dd></div></dl><p>Risposta, rifiuto, disiscrizione, appuntamento e richiesta di non contattare fermano i ricontatti. Le condizioni fuori catalogo passano al commerciale.</p></details>
    </>}
    {newCampaign && <Dialog title="Nuova campagna AI" onClose={closeCampaignDialog}><CampaignForm profile={profile} demo={demo} busy={busy} onCreate={create} /></Dialog>}
    {interaction && campaign && <Dialog title={`${interaction.voice ? "Simula chiamata demo" : "Simula risposta lead"} · ${interaction.lead.company_name}`} onClose={closeInteraction}><InteractionForm voice={interaction.voice} busy={busy} onSubmit={body => run(async () => { await post(`/campaigns/${campaign.id}/leads/${interaction.lead.lead_id}/${interaction.voice ? "simulate-voice" : "simulate-response"}`, body); setInteraction(null); }, "Interazione demo registrata: il Sales Agent la analizza nel workflow")} /></Dialog>}
  </div>;
}
