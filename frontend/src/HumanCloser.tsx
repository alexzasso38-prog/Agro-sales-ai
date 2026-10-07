import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, CalendarDays, Check, CheckCircle2, ChevronRight, CircleHelp, Handshake, LoaderCircle, Mail, MessageSquare, Package, Phone, ShieldCheck, UserCheck, Users, X } from "lucide-react";
import { api, post } from "./api";
import type { CloserDetail } from "./automationTypes";

const statusNames: Record<string, string> = { open: "Da prendere in carico", in_progress: "In carico", taken: "In carico", owned: "In carico", contacted: "Contatto annotato", resolved: "Gestito", won: "Cliente acquisito", lost: "Opportunità persa" };
const date = (value: string) => new Date(value).toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
const message = (error: unknown) => error instanceof Error ? error.message : "Operazione non riuscita. Riprova.";
const readable = (value: unknown): string => value == null || value === "" ? "Non dichiarato" : Array.isArray(value) ? value.map(readable).join(", ") : typeof value === "object" ? Object.values(value as Record<string, unknown>).map(readable).join(" · ") : String(value);

export default function HumanCloser({ demo, onRefresh, onOpenLead, onContact, onAppointment, notify }: { demo: boolean; onRefresh: () => Promise<void>; onOpenLead: (id: number) => void; onContact: (id: number) => void; onAppointment: (id: number) => void; notify: (text: string, error?: boolean) => void }) {
  const [items, setItems] = useState<CloserDetail[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selected, setSelected] = useState<CloserDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("active");
  const [note, setNote] = useState("");
  const activeId = useRef<number | null>(null);
  const mounted = useRef(true);
  const revision = useRef("");
  const refresh = useCallback(async () => {
    const list = await api<CloserDetail[]>("/human-closer");
    if (!mounted.current) return;
    setItems(list); setError("");
    const id = activeId.current || list.find(item => !["resolved", "won", "lost"].includes(item.status.toLowerCase()))?.id || list[0]?.id;
    if (!id) { setSelected(null); return; }
    if (!activeId.current) { activeId.current = id; setSelectedId(id); }
    const detail = await api<CloserDetail>(`/human-closer/${id}`);
    if (!mounted.current || id !== activeId.current) return;
    setSelected(detail);
    const current = JSON.stringify(list.map(item => [item.id, item.status, item.summary]));
    if (revision.current && revision.current !== current) await onRefresh();
    revision.current = current;
  }, [onRefresh]);
  useEffect(() => {
    mounted.current = true;
    let inFlight = false;
    const poll = async () => { if (inFlight) return; inFlight = true; try { await refresh(); } catch (cause) { if (mounted.current) setError(message(cause)); } finally { inFlight = false; if (mounted.current) setLoading(false); } };
    void poll();
    const timer = window.setInterval(() => void poll(), 2500);
    return () => { mounted.current = false; window.clearInterval(timer); };
  }, [refresh]);
  async function select(id: number) { activeId.current = id; setSelectedId(id); setNote(""); try { await refresh(); } catch (cause) { setError(message(cause)); } }
  async function action(kind: string, text: string) {
    if (!selected || busy) return;
    setBusy(true);
    try { await post(`/human-closer/${selected.id}/${kind}`, { note }); await refresh(); await onRefresh(); notify(text); setNote(""); }
    catch (cause) { notify(message(cause), true); }
    finally { setBusy(false); }
  }
  const activeItems = items.filter(item => !["resolved", "won", "lost"].includes(item.status.toLowerCase()));
  const displayed = filter === "all" ? items : activeItems;
  const closed = selected && ["resolved", "won", "lost"].includes(selected.status.toLowerCase());
  const extractionLabels: Record<string, string> = { needs: "Esigenze", products: "Prodotti dichiarati", product_ids: "Prodotti dichiarati", quantity: "Quantità", quantities: "Quantità dichiarate", budget: "Budget", budgets: "Budget dichiarati", timing: "Tempistiche", timings: "Tempistiche dichiarate", objections: "Obiezioni", questions: "Domande", availability: "Disponibilità appuntamento", meeting_availability: "Disponibilità appuntamento" };
  return <div className="human-closer">
    <div className="page-header"><div><div className="eyebrow">QUANDO L’OPPORTUNITÀ MERITA UNA RELAZIONE</div><h1>Human Closer</h1><p>Il tuo team AI raccoglie il contesto. Tu costruisci il prossimo passo.</p></div><span className="badge pending">{activeItems.length} opportunità da gestire</span></div>
    <section className="closer-intro"><span><Handshake size={28} strokeWidth={1.5} /></span><div><h2>Arrivi alla conversazione con tutto il contesto.</h2><p>Interesse dichiarato, esigenze e decisioni commerciali: le opportunità passano a te con una storia chiara.</p></div>{demo && <span className="badge demo">DEMO · Dati fittizi</span>}</section>
    {error && <div className="form-error" role="alert">{error}<button className="section-link" onClick={() => void refresh().catch(cause => setError(message(cause)))}>Riprova</button></div>}
    {loading && !items.length ? <div className="automation-loading"><LoaderCircle className="spin" size={23} />Prepariamo le opportunità…</div> : !items.length ? <div className="card automation-empty"><div className="automation-empty-symbol"><Users size={32} /></div><h3>Le prossime relazioni nascono qui</h3><p>Avvia una campagna e registra una risposta. Le opportunità interessanti, le richieste di campioni e le decisioni fuori catalogo arrivano in questa inbox.</p></div> : <div className="closer-grid">
      <section className="card closer-inbox"><div className="closer-inbox-header"><h3>Opportunità da chiudere</h3><select aria-label="Filtra opportunità" value={filter} onChange={event => setFilter(event.target.value)}><option value="active">Da gestire</option><option value="all">Tutte</option></select></div>{displayed.length ? displayed.map(item => <button key={item.id} className={`closer-inbox-item ${selectedId === item.id ? "selected" : ""}`} onClick={() => void select(item.id)}><div><strong>{item.company_name}</strong><span className={`badge ${item.status.toLowerCase() === "open" ? "pending" : "qualified"}`}>{statusNames[item.status.toLowerCase()] || item.status}</span></div><p>{item.reason}</p><small>{item.score == null ? "Score non disponibile" : `${item.score}/100 compatibilità`} · {date(item.created_at)}</small><ChevronRight size={16} /></button>) : <div className="automation-small-empty"><CheckCircle2 size={27} /><p>Tutte le opportunità sono state gestite.</p></div>}</section>
      {selected && <article className="card closer-detail"><div className="closer-detail-header"><div><span className="eyebrow">SCHEDA PER IL COMMERCIALE</span><h2>{selected.company_name}</h2><p>{selected.campaign_name || "Opportunità dal tuo spazio commerciale"}</p></div><span className="closer-score">{selected.score == null ? "—" : selected.score}<small>/100</small></span></div>
        <div className="closer-contacts"><span><Users size={14} />{selected.contact_name || "Referente da individuare"}</span><span><Mail size={14} />{selected.email || "Email non disponibile"}</span><span><Phone size={14} />{selected.phone || "Telefono non disponibile"}</span></div>
        <section className="closer-section"><h3><Sparkle />Perché è interessante</h3><p>{selected.reason}</p><p className="muted">{selected.summary}</p></section>
        <div className="closer-context-grid"><section className="closer-section"><h3><Package size={16} />Prodotti compatibili</h3>{selected.compatible_products?.length ? <div className="closer-product-tags">{selected.compatible_products.map(product => <span key={product} className="badge qualified">{product}</span>)}</div> : <p className="muted">Compatibilità da verificare con il catalogo e le esigenze dichiarate.</p>}</section><section className="closer-section"><h3><CircleHelp size={16} />Valore potenziale</h3><p>{selected.potential_value == null ? "Non dichiarato. Nessun valore stimato automaticamente." : readable(selected.potential_value)}</p></section></div>
        <section className="closer-section"><h3><MessageSquare size={16} />Ultima risposta</h3>{selected.last_reply ? <blockquote>{selected.last_reply}</blockquote> : <p className="muted">Nessuna risposta disponibile nella scheda.</p>}</section>
        {selected.extracted && <section className="closer-section"><h3><FileFacts />Esigenze raccolte</h3><dl className="closer-extracted">{Object.entries(selected.extracted).map(([key, value]) => <div key={key}><dt>{extractionLabels[key] || key.replaceAll("_", " ")}</dt><dd>{readable(value)}</dd></div>)}</dl></section>}
        {!!selected.objections?.length && <section className="closer-section"><h3><CircleHelp size={16} />Obiezioni da affrontare</h3><ul>{selected.objections.map((objection, index) => <li key={index}>{objection}</li>)}</ul></section>}
        <section className="closer-next-action"><UserCheck size={21} /><div><span>PROSSIMA AZIONE CONSIGLIATA</span><p>{selected.recommended_action || selected.next_action || "Verifica il contesto e contatta il referente per definire il prossimo passo."}</p></div></section>
        {!!selected.timeline?.length && <section className="closer-section"><h3><CheckCircle2 size={16} />Cosa è successo</h3><div className="closer-timeline">{selected.timeline.map((entry, index) => <div key={index}><span className="status-dot" /><div><p>{entry.message || entry.reason || "Aggiornamento del workflow"}</p><small>{entry.agent && `${entry.agent} · `}{date(entry.created_at)}</small></div></div>)}</div></section>}
        <section className="closer-actions"><div className="closer-owner"><span className={`badge ${closed ? "qualified" : "pending"}`}>{statusNames[selected.status.toLowerCase()] || selected.status}</span>{selected.owner_name && <span>In carico a {selected.owner_name}</span>}</div><label className="field"><span>Nota del commerciale (facoltativa)</span><textarea rows={2} maxLength={3000} value={note} onChange={event => setNote(event.target.value)} placeholder="Aggiungi contesto alla presa in carico o all’esito…" disabled={!!closed} /></label><div className="button-row">{selected.status.toLowerCase() === "open" && <button className="button primary" disabled={busy} onClick={() => void action("take", "Opportunità presa in carico")}><UserCheck size={16} />Prendi in carico</button>}<button className="button secondary" disabled={busy || !!closed} onClick={() => onContact(selected.lead_id)}><Mail size={16} />Contatta</button><button className="button secondary" disabled={busy || !!closed} onClick={() => onAppointment(selected.lead_id)}><CalendarDays size={16} />Fissa appuntamento</button><button className="button secondary" disabled={busy || !!closed} onClick={() => void action("won", "Cliente acquisito: pipeline aggiornata")}><Check size={16} />Segna won</button><button className="button danger" disabled={busy || !!closed} onClick={() => void action("lost", "Opportunità persa: pipeline aggiornata")}><X size={16} />Segna lost</button></div><button className="section-link" onClick={() => onOpenLead(selected.lead_id)}>Apri scheda e cronologia completa<ArrowRight size={15} /></button><p><ShieldCheck size={13} />{demo ? "Email e appuntamenti restano simulati." : "Il contatto apre una bozza da approvare."} La prenotazione viene confermata solo dopo il successo del calendario.</p></section>
      </article>}
    </div>}
  </div>;
}
function Sparkle() { return <CheckCircle2 size={16} />; }
function FileFacts() { return <ShieldCheck size={16} />; }
