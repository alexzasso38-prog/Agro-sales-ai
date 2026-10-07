import {
  cloneElement,
  isValidElement,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
  type ReactElement,
} from "react";
import {
  ArrowDownLeft,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  Bell,
  CalendarDays,
  Check,
  CheckCheck,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  ClipboardList,
  Clock3,
  ExternalLink,
  FileCheck2,
  FileText,
  LayoutDashboard,
  Leaf,
  Link2,
  LoaderCircle,
  LogOut,
  Mail,
  Menu,
  MessageSquare,
  MoreHorizontal,
  Package,
  Phone,
  Plus,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Sprout,
  StopCircle,
  Trash2,
  Upload,
  Users,
  WandSparkles,
  X,
  XCircle,
} from "lucide-react";
import { api, post } from "./api";
import AutomationCenter from "./AutomationCenter";
import HumanCloser from "./HumanCloser";
import type {
  Appointment,
  Audit,
  Dashboard,
  Data,
  Draft,
  Handoff,
  Lead,
  Message,
  Meta,
  Profile,
  Task,
  User,
} from "./types";

type Page =
  | "automations"
  | "closer"
  | "dashboard"
  | "leads"
  | "drafts"
  | "conversations"
  | "tasks"
  | "appointments"
  | "handoffs"
  | "profile"
  | "integrations"
  | "audit";
type Modal = "lead" | "search" | "appointment" | "reply" | "draft" | null;
const pageNames: Record<Page, string> = {
  automations: "Automazioni AI",
  closer: "Human Closer",
  dashboard: "Panoramica",
  leads: "I tuoi lead",
  drafts: "Bozze da approvare",
  conversations: "Conversazioni",
  tasks: "Attività programmate",
  appointments: "Appuntamenti",
  handoffs: "Al commerciale",
  profile: "La tua azienda",
  integrations: "Integrazioni",
  audit: "Registro operazioni",
};
const stages: Record<string, string> = {
  new: "Nuovo",
  discovered: "Trovato",
  qualifying: "In valutazione",
  qualified: "Qualificato",
  outreach_ready: "Bozza pronta",
  contacted: "Contattato",
  follow_up: "Follow-up",
  replied: "Ha risposto",
  interested: "Interessato",
  meeting: "Incontro",
  appointment: "Appuntamento",
  handoff: "Al commerciale",
  won: "Cliente",
  lost: "Perso",
  do_not_contact: "Non contattare",
};
const statuses: Record<string, string> = {
  sending: "Invio in corso",
  booking: "Prenotazione in corso",
  pending: "Da approvare",
  approved: "Approvata",
  sent: "Inviata",
  rejected: "Rifiutata",
  cancelled: "Annullata",
  failed: "Errore",
  scheduled: "Programmata",
  processing: "In corso",
  automation_managed: "Gestita dagli agenti",
  needs_approval: "Da approvare",
  completed: "Completata",
  simulated: "Simulato",
  confirmed: "Confermato",
  open: "Da gestire",
  resolved: "Risolto",
  interested: "Interessato",
  question: "Domanda",
  rejection: "Rifiuto",
  unsubscribe: "Disiscrizione",
  hard_bounce: "Indirizzo non valido",
  other: "Da valutare",
};
const date = (value?: string, withTime = false) =>
  value
    ? new Intl.DateTimeFormat("it-IT", {
        day: "2-digit",
        month: "short",
        ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
      }).format(new Date(value))
    : "—";
const initials = (name: string) =>
  name
    .split(" ")
    .slice(0, 2)
    .map((p) => p[0])
    .join("")
    .toUpperCase();
const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Operazione non riuscita. Riprova.";

function Badge({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
function Stage({ value }: { value: string }) {
  const normalized = value.toLowerCase();
  return (
    <Badge tone={normalized}>{stages[normalized] || statuses[normalized] || value}</Badge>
  );
}
function Score({ value }: { value?: number | null }) {
  return value == null ? (
    <span className="muted">Da valutare</span>
  ) : (
    <span
      className={`score ${value >= 70 ? "high" : value >= 40 ? "medium" : "low"}`}
    >
      <span className="score-dot" />
      {value}
      <span className="score-max">/100</span>
    </span>
  );
}
function Empty({
  icon = <Sprout size={30} />,
  title = "Qui inizia una nuova opportunità",
  text = "Le informazioni appariranno qui quando saranno disponibili.",
  action,
}: {
  icon?: ReactNode;
  title?: string;
  text?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}
function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  const fieldId = useId();
  const labelId = `${fieldId}-label`;
  const hintId = `${fieldId}-hint`;
  const control = isValidElement(children)
    ? cloneElement(
        children as ReactElement<{
          id?: string;
          "aria-labelledby"?: string;
          "aria-describedby"?: string;
        }>,
        {
          id: fieldId,
          "aria-labelledby": labelId,
          ...(hint ? { "aria-describedby": hintId } : {}),
        },
      )
    : children;
  return (
    <label className="field" htmlFor={fieldId}>
      <span id={labelId}>{label}</span>
      {control}
      {hint && <small id={hintId}>{hint}</small>}
    </label>
  );
}
function Button({
  children,
  onClick,
  busy,
  variant = "primary",
  disabled = false,
  type = "button",
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  busy?: boolean;
  variant?: string;
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
}) {
  return (
    <button
      type={type}
      className={`button ${variant} ${className}`}
      onClick={onClick}
      disabled={busy || disabled}
    >
      {busy ? <LoaderCircle className="spin" size={17} /> : null}
      {children}
    </button>
  );
}
function Brand({ light = false }: { light?: boolean }) {
  return (
    <div className={`brand ${light ? "light" : ""}`}>
      <div className="brand-icon">
        <Sprout size={26} strokeWidth={1.8} />
      </div>
      <div>
        agro
        <span>
          sales <b>AI</b>
        </span>
      </div>
    </div>
  );
}

function Landscape() {
  return (
    <svg
      className="landscape"
      viewBox="0 0 480 180"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="370" cy="45" r="27" fill="#F0C986" />
      <path
        d="M0 100C60 30 140 28 230 90S388 90 480 53V180H0Z"
        fill="#ACC291"
      />
      <path
        d="M0 147C87 72 144 95 241 131S402 59 480 100V180H0Z"
        fill="#759B66"
      />
      <path
        d="M-40 171C75 137 153 95 260 116S388 189 520 109"
        stroke="#DBE6BD"
        strokeWidth="9"
      />
      <path
        d="M-35 191C80 157 158 115 265 136S393 209 525 129"
        stroke="#DBE6BD"
        strokeWidth="9"
      />
      <path
        d="M-30 211C85 177 163 135 270 156S398 229 530 149"
        stroke="#DBE6BD"
        strokeWidth="9"
      />
      <path
        d="M385 74V107M371 93c-1-14 14-16 14-16s4 13-14 16Zm14-11s-2-17 15-19c1 16-15 19-15 19Z"
        stroke="#365E42"
        strokeWidth="4"
        strokeLinecap="round"
      />
      <path
        d="M319 91V112M309 102s-1-11 10-13c2 11-10 13-10 13Z"
        stroke="#365E42"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}

function Auth({
  meta,
  onAuth,
}: {
  meta: Meta | null;
  onAuth: (token: string, user: User) => void;
}) {
  const [register, setRegister] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [email, setEmail] = useState(
    meta?.demo_mode ? "demo@agrosales.test" : "",
  );
  const [password, setPassword] = useState(
    meta?.demo_mode ? "DemoAgro2026!" : "",
  );
  useEffect(() => {
    if (meta?.demo_mode && !register) {
      setEmail("demo@agrosales.test");
      setPassword("DemoAgro2026!");
    }
  }, [meta, register]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const values = new FormData(event.currentTarget);
    try {
      const result = await post<{ access_token: string; user: User }>(
        register ? "/auth/register" : "/auth/login",
        {
          email,
          password,
          ...(register
            ? {
                name: values.get("name"),
                company_name: values.get("company_name"),
              }
            : {}),
        },
      );
      onAuth(result.access_token, result.user);
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-screen">
      <div className="auth-story">
        <Brand light />
        <div className="auth-story-content">
          <Badge tone="light-green">
            <Sparkles size={13} /> Il commerciale che coltiva opportunità
          </Badge>
          <h1>
            Dal tuo territorio.
            <br />
            Alla loro tavola.
          </h1>
          <p>
            Trova i clienti HORECA giusti, racconta il valore dei tuoi prodotti
            e fai crescere relazioni che durano.
          </p>
          <div className="auth-benefit">
            <ShieldCheck size={20} />
            <span>Il tuo controllo, a ogni passo della campagna.</span>
          </div>
        </div>
        <Landscape />
        <span className="auth-footer">Fatto per chi produce con cura.</span>
      </div>
      <div className="auth-main">
        <div className="auth-form">
          <div className="eyebrow">BENVENUTO IN AGRO SALES AI</div>
          <h2>
            {register
              ? "Coltiviamo il tuo prossimo cliente."
              : "Il tuo prossimo cliente ti aspetta."}
          </h2>
          <p className="muted">
            {register
              ? "Crea uno spazio separato per la tua azienda."
              : "Accedi al tuo spazio commerciale."}
          </p>
          {meta?.demo_mode && (
            <div className="demo-note">
              <Sprout size={20} />
              <div>
                <strong>Esplora la demo in sicurezza</strong>
                <p>
                  Dati fittizi, invii e appuntamenti simulati. Nessun contatto
                  reale.
                </p>
              </div>
            </div>
          )}
          <form onSubmit={submit}>
            {register && (
              <>
                <Field label="Il tuo nome">
                  <input
                    name="name"
                    required
                    autoComplete="name"
                    placeholder="Nome e cognome"
                  />
                </Field>
                <Field label="Azienda">
                  <input
                    name="company_name"
                    required
                    placeholder="La tua azienda agricola"
                  />
                </Field>
              </>
            )}
            <Field label="Email">
              <input
                type="email"
                required
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="nome@azienda.it"
              />
            </Field>
            <Field label="Password">
              <input
                type="password"
                required
                minLength={register ? 12 : undefined}
                autoComplete={register ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
            {error && (
              <div className="form-error" role="alert">
                <XCircle size={17} />
                {error}
              </div>
            )}
            <Button type="submit" busy={busy} className="full">
              {register
                ? "Crea il tuo account"
                : meta?.demo_mode
                  ? "Entra nella demo"
                  : "Accedi"}
              <ArrowRight size={17} />
            </Button>
          </form>
          <button
            className="auth-switch"
            onClick={() => {
              setRegister(!register);
              setError("");
              setEmail("");
              setPassword("");
            }}
          >
            {register
              ? "Hai già un account? Accedi"
              : "Nuova azienda? Crea un account"}
          </button>
          <div className="auth-security">
            <ShieldCheck size={14} /> Dati separati per azienda · Chiavi
            protette nel backend
          </div>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [token, setToken] = useState(sessionStorage.getItem("agro_token"));
  const [user, setUser] = useState<User | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [data, setData] = useState<Data | null>(null);
  const [page, setPage] = useState<Page>("dashboard");
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ text: string; error: boolean } | null>(
    null,
  );
  const [navOpen, setNavOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [stageFilter, setStageFilter] = useState("all");
  const [lead, setLead] = useState<Lead | null>(null);
  const [modal, setModal] = useState<Modal>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const notify = useCallback(
    (text: string, error = false) => setToast({ text, error }),
    [],
  );
  useEffect(() => {
    api<Meta>("/meta")
      .then(setMeta)
      .catch(() =>
        setLoadError(
          "Le API non sono raggiungibili. Verifica che il backend sia avviato sulla porta 8000.",
        ),
      );
  }, []);
  useEffect(() => {
    if (toast) {
      const timeout = setTimeout(() => setToast(null), 5500);
      return () => clearTimeout(timeout);
    }
  }, [toast]);
  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) {
        if (modal) setModal(null);
        else if (lead) setLead(null);
        else setNavOpen(false);
      }
      if (event.key === "Tab" && (modal || lead)) {
        const dialog = document.querySelector(
          modal ? ".modal" : ".lead-drawer",
        );
        const focusable = dialog?.querySelectorAll<HTMLElement>(
          "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href]",
        );
        if (focusable?.length) {
          const first = focusable[0];
          const last = focusable[focusable.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [modal, lead, busy]);
  const load = useCallback(async () => {
    const requestToken = sessionStorage.getItem("agro_token");
    const [
      dashboard,
      leads,
      drafts,
      tasks,
      conversations,
      appointments,
      handoffs,
      audit,
      profile,
      account,
    ] = await Promise.all([
      api<Dashboard>("/dashboard"),
      api<Lead[]>("/leads"),
      api<Draft[]>("/drafts"),
      api<Task[]>("/tasks"),
      api<Message[]>("/conversations"),
      api<Appointment[]>("/appointments"),
      api<Handoff[]>("/handoffs"),
      api<Audit[]>("/audit"),
      api<Profile>("/profile"),
      api<User>("/auth/me"),
    ]);
    if (requestToken !== sessionStorage.getItem("agro_token")) return;
    setData({
      dashboard,
      leads,
      drafts,
      tasks,
      conversations,
      appointments,
      handoffs,
      audit,
      profile,
    });
    setUser(account);
    setLoadError("");
  }, []);
  useEffect(() => {
    if (token) {
      setLoading(true);
      load()
        .catch((error) => setLoadError(errorText(error)))
        .finally(() => setLoading(false));
    }
  }, [token, load]);
  // Keep the existing CRM and dashboard in sync while campaign jobs run in the worker.
  // Avoid refreshing profile inputs and open editors while the user is making changes.
  useEffect(() => {
    if (!token || busy || modal || ["profile", "integrations", "automations", "closer"].includes(page)) return;
    let inFlight = false;
    const timer = window.setInterval(async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        await load();
        if (lead) setLead(await api<Lead>(`/leads/${lead.id}`));
      } catch { /* The next polling cycle can recover without replacing the open screen. */ }
      finally { inFlight = false; }
    }, 4000);
    return () => window.clearInterval(timer);
  }, [token, busy, modal, page, load, lead?.id]);
  async function action(
    fn: () => Promise<unknown>,
    success: string | ((result: unknown) => { text: string; error?: boolean }),
    close = false,
  ) {
    if (busy) return;
    setBusy(true);
    try {
      const result = await fn();
      await load();
      if (lead) setLead(await api<Lead>(`/leads/${lead.id}`));
      if (close) setModal(null);
      const feedback =
        typeof success === "function" ? success(result) : { text: success };
      notify(feedback.text, !!feedback.error);
    } catch (error) {
      try {
        await load();
        if (lead) setLead(await api<Lead>(`/leads/${lead.id}`));
      } catch {
        /* Keep the original operation error visible. */
      }
      notify(errorText(error), true);
    } finally {
      setBusy(false);
    }
  }
  async function openLead(id: number) {
    try {
      setLead(await api<Lead>(`/leads/${id}`));
    } catch (error) {
      notify(errorText(error), true);
    }
  }
  function go(next: Page) {
    setPage(next);
    setNavOpen(false);
    setLead(null);
  }
  function logout() {
    sessionStorage.removeItem("agro_token");
    setToken(null);
    setData(null);
    setUser(null);
    setLead(null);
  }
  function auth(newToken: string, account: User) {
    sessionStorage.setItem("agro_token", newToken);
    setToken(newToken);
    setUser(account);
  }
  const filteredLeads =
    data?.leads.filter(
      (item) =>
        (stageFilter === "all" || item.stage === stageFilter) &&
        `${item.company_name} ${item.city} ${item.contact_name} ${item.email}`
          .toLowerCase()
          .includes(search.toLowerCase()),
    ) || [];
  const pending =
    data?.drafts.filter((item) => item.status === "pending").length || 0;
  const navItems: { id: Page; icon: ReactNode; badge?: number }[] = [
    { id: "automations", icon: <Sparkles size={19} /> },
    { id: "closer", icon: <Users size={19} />, badge: data?.handoffs.filter(h => h.status === "open").length },
    { id: "dashboard", icon: <LayoutDashboard size={19} /> },
    { id: "leads", icon: <Users size={19} /> },
    { id: "conversations", icon: <MessageSquare size={19} /> },
    { id: "drafts", icon: <FileCheck2 size={19} />, badge: pending },
    { id: "tasks", icon: <ClipboardList size={19} /> },
    { id: "appointments", icon: <CalendarDays size={19} /> },
    {
      id: "handoffs",
      icon: <ArrowUpRight size={19} />,
      badge: data?.handoffs.filter((h) => h.status === "open").length,
    },
  ];
  if (!token)
    return (
      <>
        <Auth meta={meta} onAuth={auth} />
        {loadError && <div className="connection-error">{loadError}</div>}
      </>
    );

  return (
    <div className="app-shell">
      {navOpen && (
        <div className="nav-backdrop" onClick={() => setNavOpen(false)} />
      )}
      <aside className={`sidebar ${navOpen ? "open" : ""}`}>
        <Brand light />
        <div className="workspace-selector">
          <span className="workspace-symbol">
            <Leaf size={18} />
          </span>
          <div>
            <strong>{user?.company_name || "La tua azienda"}</strong>
            <small>Spazio commerciale</small>
          </div>
          <ChevronDown size={15} />
        </div>
        <div className="nav-label">IL TUO LAVORO</div>
        <nav>
          {navItems.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${page === item.id ? "active" : ""} ${item.id === "automations" ? "nav-automations" : ""}`}
              onClick={() => go(item.id)}
            >
              {item.icon}
              <span>{pageNames[item.id]}</span>
              {!!item.badge && <b className="nav-count">{item.badge}</b>}
            </button>
          ))}
        </nav>
        <div className="nav-label nav-label-second">LA TUA AZIENDA</div>
        <nav>
          {[
            { id: "profile" as Page, icon: <Package size={19} /> },
            { id: "integrations" as Page, icon: <Link2 size={19} /> },
            { id: "audit" as Page, icon: <ShieldCheck size={19} /> },
          ].map((item) => (
            <button
              key={item.id}
              className={`nav-item ${page === item.id ? "active" : ""}`}
              onClick={() => go(item.id)}
            >
              {item.icon}
              <span>{pageNames[item.id]}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-tip">
            <Sprout size={20} />
            <strong>Relazioni, prima di tutto.</strong>
            <p>
              Tu conosci i tuoi prodotti.
              <br />
              L’AI ti aiuta a raccontarli.
            </p>
          </div>
          <button
            className="account"
            onClick={logout}
            title="Esci dall'account"
          >
            <span className="avatar">{initials(user?.name || "Demo")}</span>
            <span>
              <strong>{user?.name || "Account"}</strong>
              <small>Produttore</small>
            </span>
            <LogOut size={17} />
          </button>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              className="icon-button mobile-menu"
              onClick={() => setNavOpen(true)}
              aria-label="Apri menu"
            >
              <Menu size={22} />
            </button>
            <span>Spazio di lavoro</span>
            <ChevronRight size={14} />
            <strong>{pageNames[page]}</strong>
          </div>
          <div className="topbar-actions">
            <span className="today">
              {new Intl.DateTimeFormat("it-IT", {
                day: "numeric",
                month: "long",
              }).format(new Date())}
            </span>
            <button
              className="icon-button notification"
              onClick={() => go("drafts")}
              aria-label="Vedi bozze da approvare"
            >
              <Bell size={19} />
              {pending > 0 && <i />}
            </button>
            <span className="top-avatar">{initials(user?.name || "Demo")}</span>
          </div>
        </header>
        {meta?.demo_mode && (
          <div className="demo-banner">
            <span>
              <span className="demo-dot" />
              <strong>Modalità demo</strong>
              <span className="demo-banner-description">
                {" "}
                · Dati fittizi. Email, appuntamenti e sincronizzazioni sono
                simulati.
              </span>
            </span>
            <Badge tone="demo">
              Nessun contatto reale <ShieldCheck size={12} />
            </Badge>
          </div>
        )}
        <main className="main">
          {loading && !data ? (
            <div className="loading">
              <LoaderCircle className="spin" size={30} />
              <p>Prepariamo il tuo spazio di lavoro…</p>
            </div>
          ) : loadError ? (
            <Empty
              icon={<XCircle size={30} />}
              title="Non riusciamo a caricare i dati"
              text={loadError}
              action={
                <>
                  <Button
                    onClick={() => {
                      setLoading(true);
                      load()
                        .catch((error) => setLoadError(errorText(error)))
                        .finally(() => setLoading(false));
                    }}
                    busy={loading}
                  >
                    Riprova
                  </Button>
                  <Button variant="secondary" onClick={logout}>
                    Torna all’accesso
                  </Button>
                </>
              }
            />
          ) : data ? (
            <>
              {page === "automations" && (
                <AutomationCenter
                  profile={data.profile}
                  drafts={data.drafts}
                  demo={!!meta?.demo_mode}
                  onRefresh={load}
                  onOpenLead={id => void openLead(id)}
                  onOpenDraft={item => { setDraft(item); setModal("draft"); }}
                  onCloser={() => go("closer")}
                  notify={notify}
                />
              )}
              {page === "closer" && (
                <HumanCloser
                  demo={!!meta?.demo_mode}
                  onRefresh={load}
                  onOpenLead={id => void openLead(id)}
                  onContact={id => void action(async () => {
                    const customer = await api<Lead>(`/leads/${id}`);
                    const item = await post<Draft>(`/leads/${id}/draft`, { kind: customer.stop_reason === "reply" ? "reply" : "outreach" });
                    setDraft(item); setModal("draft");
                  }, "Messaggio preparato: rivedilo prima di approvare")}
                  onAppointment={id => void action(async () => { setLead(await api<Lead>(`/leads/${id}`)); setModal("appointment"); }, "Verifica disponibilità e dettagli dell’incontro")}
                  notify={notify}
                />
              )}
              {page === "dashboard" && (
                <DashboardPage
                  data={data}
                  user={user}
                  go={go}
                  openLead={openLead}
                  newLead={() => setModal("lead")}
                />
              )}
              {page === "leads" && (
                <>
                  <PageHeader
                    eyebrow="OPPORTUNITÀ COMMERCIALI"
                    title="I tuoi prossimi clienti"
                    text="Contatti verificabili, relazioni da coltivare."
                    actions={
                      <>
                        <Button
                          variant="secondary"
                          onClick={() => fileRef.current?.click()}
                          busy={busy}
                        >
                          <Upload size={16} />
                          Importa CSV
                        </Button>
                        <Button onClick={() => setModal("lead")}>
                          <Plus size={17} />
                          Aggiungi lead
                        </Button>
                      </>
                    }
                  />
                  <input
                    ref={fileRef}
                    hidden
                    type="file"
                    accept=".csv,text/csv"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) {
                        const body = new FormData();
                        body.append("file", file);
                        void action(
                          async () => {
                            const result = await api<{
                              imported: number;
                              duplicates: number;
                              errors: { row: number; detail: string }[];
                            }>("/leads/import", { method: "POST", body });
                            return result;
                          },
                          (result) => {
                            const report = result as {
                              imported: number;
                              duplicates: number;
                              errors: { row: number; detail: string }[];
                            };
                            return {
                              text: `${report.imported} importati · ${report.duplicates} duplicati${report.errors.length ? ` · ${report.errors.map((e) => `riga ${e.row}: ${e.detail}`).join("; ")}` : ""}`,
                              error: !!report.errors.length,
                            };
                          },
                        );
                      }
                      event.target.value = "";
                    }}
                  />
                  <div className="card">
                    <div className="table-toolbar">
                      <div className="search-field">
                        <Search size={17} />
                        <input
                          aria-label="Cerca lead"
                          placeholder="Cerca azienda, città o contatto…"
                          value={search}
                          onChange={(e) => setSearch(e.target.value)}
                        />
                      </div>
                      <select
                        aria-label="Filtra per stato"
                        value={stageFilter}
                        onChange={(e) => setStageFilter(e.target.value)}
                      >
                        <option value="all">Tutti gli stati</option>
                        {Object.entries(stages).map(([key, label]) => (
                          <option key={key} value={key}>
                            {label}
                          </option>
                        ))}
                      </select>
                      <Button
                        variant="secondary"
                        onClick={() => setModal("search")}
                      >
                        <Sparkles size={16} />
                        Cerca opportunità
                      </Button>
                    </div>
                    <LeadTable leads={filteredLeads} openLead={openLead} />
                    <div className="table-footer">
                      <span>
                        {filteredLeads.length} contatti ·{" "}
                        {data.leads.filter((l) => l.stop_reason).length}{" "}
                        interrotti
                      </span>
                      <span>
                        Fonte e data sempre tracciate <ShieldCheck size={13} />
                      </span>
                    </div>
                  </div>
                  <p className="page-footnote">
                    <CircleHelp size={14} />
                    Il punteggio è una stima motivata di compatibilità.
                    Interesse e quantità richiedono una risposta del cliente.
                  </p>
                </>
              )}
              {page === "drafts" && (
                <>
                  <PageHeader
                    eyebrow="OUTREACH CON IL TUO CONTROLLO"
                    title="Parole giuste, prima di inviare"
                    text="Rivedi, personalizza e approva i messaggi in attesa."
                    actions={
                      <Badge tone="pending">{pending} da approvare</Badge>
                    }
                  />
                  <div className="info-strip">
                    <ShieldCheck size={18} />
                    Modificare una bozza annulla l’approvazione. Le campagne
                    seguono il livello di autonomia che hai autorizzato.
                    {meta?.demo_mode && " Gli invii qui sono simulati."}
                  </div>
                  {!data.drafts.length ? (
                    <Empty
                      icon={<FileCheck2 size={30} />}
                      title="Nessuna bozza da rivedere"
                      text="Apri un lead e genera la tua prima email personalizzata."
                      action={
                        <Button onClick={() => go("leads")}>
                          Vai ai lead
                          <ArrowRight size={16} />
                        </Button>
                      }
                    />
                  ) : (
                    <div className="draft-grid">
                      {data.drafts.map((item) => (
                        <article className="card draft-card" key={item.id}>
                          <div className="draft-card-top">
                            <span className="company-avatar">
                              <Mail size={19} />
                            </span>
                            <div>
                              <strong>{item.company_name}</strong>
                              <small>
                                {item.kind === "reply"
                                  ? "Risposta"
                                  : item.task_id != null
                                    ? "Follow-up"
                                    : "Prima presentazione"}{" "}
                                · {date(item.created_at)}
                              </small>
                            </div>
                            <Stage value={item.status} />
                          </div>
                          <h3>{item.subject}</h3>
                          <p className="draft-preview">{item.body}</p>
                          {item.error && (
                            <p className="error-text">{item.error}</p>
                          )}
                          <div className="draft-card-bottom">
                            <span className="muted">
                              {item.simulated ? "Invio simulato" : "Bozza"} #
                              {item.id}
                            </span>
                            <Button
                              variant="secondary"
                              onClick={() => {
                                setDraft(item);
                                setModal("draft");
                              }}
                            >
                              Apri bozza
                              <ArrowRight size={15} />
                            </Button>
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                </>
              )}
              {page === "conversations" && (
                <>
                  <PageHeader
                    eyebrow="RELAZIONI CHE CRESCONO"
                    title="Ogni conversazione, un passo avanti"
                    text="Storico messaggi, risposte e informazioni raccolte."
                    actions={
                      <Button
                        onClick={() => {
                          setLead(null);
                          setModal("reply");
                        }}
                      >
                        <Plus size={16} />
                        Registra risposta
                      </Button>
                    }
                  />
                  {!data.conversations.length ? (
                    <Empty
                      icon={<MessageSquare size={30} />}
                      title="Il dialogo inizia qui"
                      text="I messaggi inviati e le risposte registrate compariranno in questo storico."
                    />
                  ) : (
                    <div className="card conversation-list">
                      {data.conversations.map((item) => (
                        <article className="conversation" key={item.id}>
                          <span
                            className={`conversation-icon ${item.direction === "inbound" ? "inbound" : ""}`}
                          >
                            {item.direction === "inbound" ? (
                              <ArrowDownLeft size={19} />
                            ) : (
                              <ArrowUpRight size={19} />
                            )}
                          </span>
                          <div className="conversation-body">
                            <div className="conversation-heading">
                              <button
                                className="text-button"
                                onClick={() => void openLead(item.lead_id)}
                              >
                                {item.company_name}
                              </button>
                              <span>{date(item.created_at, true)}</span>
                            </div>
                            <div className="conversation-meta">
                              <span>
                                {item.direction === "inbound"
                                  ? "Ricevuta"
                                  : "Inviata"}
                              </span>
                              {item.simulated && (
                                <Badge tone="demo">Simulato</Badge>
                              )}
                              {item.classification && (
                                <Stage value={item.classification} />
                              )}
                            </div>
                            <h4>{item.subject || "Messaggio"}</h4>
                            <p>{item.body}</p>
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                </>
              )}
              {page === "tasks" && (
                <>
                  <PageHeader
                    eyebrow="CONTINUITÀ SENZA PRESSIONE"
                    title="Il prossimo passo, al momento giusto"
                    text="I follow-up seguono le regole della campagna. Le bozze in attesa richiedono la tua approvazione."
                    actions={
                      <Button
                        variant="secondary"
                        busy={busy}
                        onClick={() =>
                          void action(async () => {
                            const result = await post<{
                              processed: number;
                              created_drafts: number;
                              sent: number;
                              failed: number;
                            }>("/worker/run");
                            return result;
                          }, "Worker eseguito: attività e bozze aggiornate")
                        }
                      >
                        <Clock3 size={17} />
                        Esegui attività in scadenza
                      </Button>
                    }
                  />
                  <div className="info-strip">
                    <StopCircle size={18} />
                    Risposta, rifiuto, disiscrizione e indirizzo non valido
                    interrompono i ricontatti.
                  </div>
                  <div className="card">
                    {!data.tasks.length ? (
                      <Empty
                        icon={<Clock3 size={30} />}
                        title="Agenda delle attività libera"
                        text="Le scadenze vengono create dopo l’invio approvato di un messaggio."
                      />
                    ) : (
                      <div className="table-scroll">
                        <table>
                          <thead>
                            <tr>
                              <th>Cliente</th>
                              <th>Attività</th>
                              <th>Scadenza</th>
                              <th>Stato</th>
                              <th />
                            </tr>
                          </thead>
                          <tbody>
                            {data.tasks.map((item) => (
                              <tr key={item.id}>
                                <td>
                                  <button
                                    className="text-button"
                                    onClick={() => void openLead(item.lead_id)}
                                  >
                                    {item.company_name}
                                  </button>
                                  {item.last_error && (
                                    <small className="error-text">
                                      {item.last_error}
                                    </small>
                                  )}
                                </td>
                                <td>Follow-up {item.step}</td>
                                <td>{date(item.due_at, true)}</td>
                                <td>
                                  <Stage value={item.status} />
                                </td>
                                <td>
                                  {item.status === "scheduled" && (
                                    <button
                                      className="icon-button"
                                      title="Annulla attività"
                                      disabled={busy}
                                      onClick={() =>
                                        void action(
                                          () =>
                                            post(`/tasks/${item.id}/cancel`),
                                          "Attività annullata",
                                        )
                                      }
                                    >
                                      <X size={17} />
                                    </button>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </>
              )}
              {page === "appointments" && (
                <>
                  <PageHeader
                    eyebrow="INCONTRI E NUOVE POSSIBILITÀ"
                    title="Facciamo spazio alle relazioni"
                    text="Una prenotazione è confermata solo quando il calendario la accetta."
                    actions={
                      <Button onClick={() => setModal("appointment")}>
                        <Plus size={17} />
                        Nuovo appuntamento
                      </Button>
                    }
                  />
                  {meta?.demo_mode && (
                    <div className="info-strip">
                      <CalendarDays size={18} />
                      Calendario demo: le prenotazioni sono simulate e non
                      creano eventi esterni.
                    </div>
                  )}
                  {!data.appointments.length ? (
                    <Empty
                      icon={<CalendarDays size={30} />}
                      title="Il calendario è pronto"
                      text="Prenota il primo confronto con un potenziale cliente."
                      action={
                        <Button onClick={() => setModal("appointment")}>
                          Crea appuntamento
                          <Plus size={16} />
                        </Button>
                      }
                    />
                  ) : (
                    <div className="appointment-grid">
                      {data.appointments.map((item) => (
                        <article
                          className="card appointment-card"
                          key={item.id}
                        >
                          <div className="date-square">
                            <strong>{new Date(item.start_at).getDate()}</strong>
                            <span>
                              {new Intl.DateTimeFormat("it-IT", {
                                month: "short",
                              }).format(new Date(item.start_at))}
                            </span>
                          </div>
                          <div>
                            <Stage value={item.status} />
                            <h3>{item.title}</h3>
                            <button
                              className="text-button"
                              onClick={() => void openLead(item.lead_id)}
                            >
                              {item.company_name}
                            </button>
                            <p>
                              <Clock3 size={14} />
                              {date(item.start_at, true)} —{" "}
                              {new Intl.DateTimeFormat("it-IT", {
                                hour: "2-digit",
                                minute: "2-digit",
                              }).format(new Date(item.end_at))}
                            </p>
                            {item.simulated && (
                              <small className="muted">
                                Prenotazione demo · nessun evento esterno
                              </small>
                            )}
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                </>
              )}
              {page === "handoffs" && (
                <>
                  <PageHeader
                    eyebrow="IL GIUDIZIO UMANO CONTA"
                    title="Qui entra in gioco il commerciale"
                    text="Richieste, condizioni e informazioni che richiedono la tua attenzione."
                  />
                  {!data.handoffs.length ? (
                    <Empty
                      icon={<CheckCheck size={30} />}
                      title="Tutto sotto controllo"
                      text="Le richieste che richiedono una decisione commerciale appariranno qui."
                    />
                  ) : (
                    <div className="handoff-list">
                      {data.handoffs.map((item) => (
                        <article className="card handoff-card" key={item.id}>
                          <div className="handoff-top">
                            <div>
                              <Badge
                                tone={
                                  item.status === "open" ? "pending" : "won"
                                }
                              >
                                {item.status === "open"
                                  ? "Serve il commerciale"
                                  : "Gestito"}
                              </Badge>
                              <h3>{item.company_name}</h3>
                            </div>
                            <span className="muted">
                              {date(item.created_at, true)}
                            </span>
                          </div>
                          <strong>{item.reason}</strong>
                          <p>{item.summary}</p>
                          <div className="button-row">
                            <Button
                              variant="secondary"
                              onClick={() => void openLead(item.lead_id)}
                            >
                              Scheda cliente
                              <ArrowRight size={15} />
                            </Button>
                            {item.status === "open" && (
                              <Button
                                busy={busy}
                                onClick={() =>
                                  void action(
                                    () => post(`/handoffs/${item.id}/resolve`),
                                    "Richiesta segnata come gestita",
                                  )
                                }
                              >
                                <Check size={16} />
                                Segna come gestita
                              </Button>
                            )}
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                </>
              )}
              {page === "profile" && (
                <ProfilePage
                  profile={data.profile}
                  busy={busy}
                  onSave={(profile) =>
                    action(
                      () =>
                        api("/profile", {
                          method: "PUT",
                          body: JSON.stringify(profile),
                        }),
                      "Profilo produttore salvato",
                    )
                  }
                />
              )}
              {page === "integrations" && (
                <>
                  <PageHeader
                    eyebrow="UN ECOSISTEMA AL TUO SERVIZIO"
                    title="I tuoi strumenti, insieme"
                    text="Le credenziali e i provider si configurano esclusivamente nel backend."
                  />
                  <div className="integration-grid">
                    {Object.entries(meta?.integrations || {}).map(
                      ([key, item]) => {
                        const config: Record<
                          string,
                          { name: string; icon: ReactNode; desc: string }
                        > = {
                          ai: {
                            name: "Assistente AI",
                            icon: <Sparkles size={25} />,
                            desc: "Qualificazione e messaggi personalizzati. Analisi basata solo sui dati disponibili.",
                          },
                          email: {
                            name: "Email",
                            icon: <Mail size={25} />,
                            desc: "Invio approvato o autorizzato dalle regole della campagna, con protezione dai duplicati.",
                          },
                          search: {
                            name: "Ricerca lead",
                            icon: <Search size={25} />,
                            desc: "Importa contatti reali da un provider configurabile, conservando la fonte.",
                          },
                          crm: {
                            name: "CRM",
                            icon: <Users size={25} />,
                            desc: "Sincronizza le schede cliente con il tuo CRM.",
                          },
                          calendar: {
                            name: "Calendario",
                            icon: <CalendarDays size={25} />,
                            desc: "Prenotazioni confermate solo dopo il successo del provider.",
                          },
                          voice: {
                            name: "Modulo telefonico",
                            icon: <Phone size={25} />,
                            desc: "Telefonate reali non collegate. Nelle Automazioni AI puoi simulare una trascrizione demo e farla analizzare al Sales Agent.",
                          },
                        };
                        const details = config[key] || {
                          name: key,
                          icon: <Link2 size={25} />,
                          desc: "",
                        };
                        return (
                          <article key={key} className="card integration-card">
                            <div
                              className={`integration-icon ${key === "voice" ? "grey" : ""}`}
                            >
                              {details.icon}
                            </div>
                            <div className="integration-title">
                              <h3>{details.name}</h3>
                              <Badge
                                tone={
                                  item.status === "connected"
                                    ? "won"
                                    : item.status === "demo"
                                      ? "demo"
                                      : "muted-badge"
                                }
                              >
                                <span className="status-dot" />
                                {item.status === "connected"
                                  ? "Collegato"
                                  : item.status === "demo"
                                    ? "Simulato"
                                    : "Non collegato"}
                              </Badge>
                            </div>
                            <p>{details.desc}</p>
                            <div className="integration-provider">
                              {item.label}
                              <Settings2 size={15} />
                            </div>
                          </article>
                        );
                      },
                    )}
                  </div>
                  <div className="info-strip">
                    <ShieldCheck size={18} />
                    Le chiavi API restano sul server. La demo usa dati fittizi e
                    non contatta servizi esterni.
                  </div>
                </>
              )}
              {page === "audit" && (
                <>
                  <PageHeader
                    eyebrow="TRASPARENZA, SEMPRE"
                    title="Ogni operazione lascia una traccia"
                    text="Il registro della tua azienda, dal primo contatto all’ultima azione."
                  />
                  <div className="card audit-card">
                    {!data.audit.length ? (
                      <Empty
                        icon={<ShieldCheck size={30} />}
                        title="Registro vuoto"
                        text="Le azioni effettuate appariranno qui."
                      />
                    ) : (
                      data.audit.map((item) => (
                        <div className="audit-row" key={item.id}>
                          <span className="audit-icon">
                            <Check size={15} />
                          </span>
                          <div>
                            <strong>{actionName(item.action)}</strong>
                            <p>{item.detail}</p>
                          </div>
                          <time>{date(item.created_at, true)}</time>
                        </div>
                      ))
                    )}
                  </div>
                </>
              )}
            </>
          ) : null}
        </main>
        <footer className="workspace-footer">
          <span>
            <Sprout size={13} /> Agro Sales AI
          </span>
          <span>Coltiva opportunità. Costruisci relazioni.</span>
        </footer>
      </div>

      {lead && (
        <div className="drawer-layer">
          <div className="drawer-backdrop" onClick={() => setLead(null)} />
          <aside
            className="lead-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Scheda cliente"
          >
            <div className="drawer-header">
              <span className="eyebrow">SCHEDA CLIENTE</span>
              <button
                className="icon-button"
                onClick={() => setLead(null)}
                aria-label="Chiudi scheda"
              >
                <X size={22} />
              </button>
            </div>
            <div className="lead-identity">
              <div className="company-avatar large">
                {initials(lead.company_name)}
              </div>
              <div>
                <h2>{lead.company_name}</h2>
                <p>
                  {lead.business_type || "Tipologia da verificare"} ·{" "}
                  {lead.city || "Località non disponibile"}
                </p>
              </div>
            </div>
            <div className="drawer-stage">
              <Stage value={lead.stage} />
              <Score value={lead.score} />
              {lead.demo && <Badge tone="demo">Dato fittizio</Badge>}
            </div>
            {lead.stop_reason && (
              <div className="stop-warning">
                <StopCircle size={18} />
                <div>
                  <strong>Ricontatti interrotti</strong>
                  <p>{stopReason(lead.stop_reason)}</p>
                </div>
              </div>
            )}
            <div className="lead-contact">
              <p>
                <Users size={16} />
                {lead.contact_name || "Referente da individuare"}
              </p>
              <p>
                <Mail size={16} />
                {lead.email || "Email non disponibile"}
              </p>
              <p>
                <Phone size={16} />
                {lead.phone || "Telefono non disponibile"}
              </p>
              {lead.website && (
                <p>
                  <ExternalLink size={16} />
                  {safeLink(lead.website) ? (
                    <a
                      href={safeLink(lead.website)!}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {lead.website}
                    </a>
                  ) : (
                    lead.website
                  )}
                </p>
              )}
            </div>
            <div className="source-box">
              <ShieldCheck size={16} />
              <span>
                <strong>Fonte: {lead.source}</strong>
                <small>Acquisito il {date(lead.source_date, true)}</small>
              </span>
            </div>
            <div className="drawer-actions">
              <Button
                busy={busy}
                onClick={() =>
                  void action(
                    () => post(`/leads/${lead.id}/qualify`),
                    "Qualificazione aggiornata",
                  )
                }
              >
                <Sparkles size={16} />
                Qualifica
              </Button>
              <Button
                variant="secondary"
                busy={busy}
                disabled={
                  !!(lead.stop_reason && lead.stop_reason !== "reply") ||
                  !lead.email
                }
                onClick={() =>
                  void action(async () => {
                    const item = await post<Draft>(`/leads/${lead.id}/draft`, {
                      kind: lead.stop_reason === "reply" ? "reply" : "outreach",
                    });
                    setDraft(item);
                    setModal("draft");
                  }, "Bozza generata: pronta per la tua revisione")
                }
              >
                <WandSparkles size={16} />
                {lead.stop_reason === "reply"
                  ? "Prepara risposta"
                  : "Crea email"}
              </Button>
            </div>
            {!lead.email && (
              <p className="muted small">
                Serve un’email verificata per preparare un invio.
              </p>
            )}
            <section className="drawer-section">
              <h3>
                <SlidersHorizontal size={17} />
                Compatibilità motivata
              </h3>
              {lead.qualification ? (
                <>
                  {lead.qualification.product_fit != null && (
                    <div className="qualification-metrics">
                      <div><span>Product fit</span><strong>{lead.qualification.product_fit}<small>/100</small></strong></div>
                      <div><span>Potenziale commerciale</span><strong>{lead.qualification.commercial_potential ?? "—"}<small>/100</small></strong></div>
                      <div><span>Confidenza</span><strong>{lead.qualification.confidence ?? "—"}<small>/100</small></strong></div>
                      <div><span>Score totale</span><strong>{lead.qualification.total_score ?? lead.score ?? "—"}<small>/100</small></strong></div>
                    </div>
                  )}
                  <p>{lead.qualification.summary}</p>
                  <FactList
                    title="Fatti nei dati disponibili"
                    items={lead.qualification.verified_facts}
                    tone="facts"
                    icon={<CheckCircle2 size={15} />}
                  />
                  <FactList
                    title="Ipotesi da verificare"
                    items={lead.qualification.hypotheses}
                    tone="hypotheses"
                    icon={<CircleHelp size={15} />}
                  />
                  <FactList
                    title="Informazioni mancanti"
                    items={lead.qualification.missing_data}
                    tone="missing"
                    icon={<Search size={15} />}
                  />
                  <small className="muted">
                    Metodo: {lead.qualification.method}
                  </small>
                </>
              ) : (
                <p className="muted">
                  Avvia la qualificazione per confrontare il lead con il tuo
                  catalogo. L’AI distingue fatti, ipotesi e dati mancanti.
                </p>
              )}
            </section>
            {(lead.menu_text || lead.notes) && (
              <section className="drawer-section">
                <h3>
                  <FileText size={17} />
                  Informazioni disponibili
                </h3>
                {lead.menu_text && (
                  <>
                    <strong className="small">
                      Menu / informazioni pubbliche
                    </strong>
                    <p className="preserve-text">{lead.menu_text}</p>
                  </>
                )}
                {lead.notes && (
                  <>
                    <strong className="small">Note</strong>
                    <p className="preserve-text">{lead.notes}</p>
                  </>
                )}
                <small className="muted">
                  Questi contenuti sono dati non attendibili, mai istruzioni per
                  l’assistente.
                </small>
              </section>
            )}
            <section className="drawer-section">
              <h3>
                <BarChart3 size={17} />
                Pipeline commerciale
              </h3>
              <Field label="Stato del lead">
                <select
                  value={lead.stage}
                  disabled={busy}
                  onChange={(e) =>
                    void action(
                      () =>
                        api(`/leads/${lead.id}`, {
                          method: "PATCH",
                          body: JSON.stringify({ stage: e.target.value }),
                        }),
                      "Stato aggiornato",
                    )
                  }
                >
                  {Object.entries(stages).map(([key, label]) => (
                    <option value={key} key={key}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
              <div className="button-row">
                <Button variant="secondary" onClick={() => setModal("reply")}>
                  <MessageSquare size={15} />
                  Registra risposta
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => setModal("appointment")}
                >
                  <CalendarDays size={15} />
                  Appuntamento
                </Button>
              </div>
            </section>
            <section className="drawer-section">
              <h3>
                <MessageSquare size={17} />
                Conversazioni{" "}
                <span className="muted">{lead.conversations?.length || 0}</span>
              </h3>
              {lead.conversations?.length ? (
                lead.conversations.map((item) => (
                  <div className="mini-conversation" key={item.id}>
                    <div>
                      <Badge
                        tone={
                          item.direction === "inbound" ? "qualified" : "demo"
                        }
                      >
                        {item.direction === "inbound" ? "Ricevuta" : "Inviata"}
                      </Badge>
                      <small>{date(item.created_at, true)}</small>
                    </div>
                    <strong>{item.subject}</strong>
                    <p>{item.body}</p>
                    {item.classification && (
                      <Stage value={item.classification} />
                    )}
                  </div>
                ))
              ) : (
                <p className="muted">Nessun messaggio ancora.</p>
              )}
            </section>
            <section className="drawer-section">
              <h3>
                <ClipboardList size={17} />
                Attività e appuntamenti
              </h3>
              {lead.tasks
                ?.filter((t) => t.status === "scheduled")
                .map((item) => (
                  <div className="mini-task" key={item.id}>
                    <Clock3 size={16} />
                    <span>
                      Follow-up {item.step}
                      <small>{date(item.due_at, true)}</small>
                    </span>
                    <Stage value={item.status} />
                  </div>
                ))}
              {lead.appointments?.map((item) => (
                <div className="mini-task" key={item.id}>
                  <CalendarDays size={16} />
                  <span>
                    {item.title}
                    <small>{date(item.start_at, true)}</small>
                  </span>
                  <Stage value={item.status} />
                </div>
              ))}
              {!lead.tasks?.some((t) => t.status === "scheduled") &&
                !lead.appointments?.length && (
                  <p className="muted">Nessuna attività pianificata.</p>
                )}
            </section>
            <div className="drawer-bottom">
              <Button
                variant="secondary"
                busy={busy}
                onClick={() =>
                  void action(
                    () => post(`/leads/${lead.id}/crm-sync`),
                    meta?.demo_mode
                      ? "Sincronizzazione CRM simulata"
                      : "Scheda sincronizzata con il CRM",
                  )
                }
              >
                <Link2 size={15} />
                Sincronizza CRM
              </Button>
              <Button
                variant="danger"
                busy={busy}
                disabled={!!(lead.stop_reason && lead.stop_reason !== "reply")}
                onClick={() =>
                  void action(
                    () =>
                      post(`/leads/${lead.id}/stop`, {
                        reason: "Interruzione richiesta dal commerciale",
                      }),
                    "Ricontatti e bozze interrotti",
                  )
                }
              >
                <StopCircle size={15} />
                Interrompi ricontatti
              </Button>
            </div>
          </aside>
        </div>
      )}

      {modal && data && (
        <div className="modal-layer" onClick={() => !busy && setModal(null)}>
          <section
            className={`modal ${modal === "draft" ? "wide" : ""}`}
            role="dialog"
            aria-modal="true"
            aria-labelledby="modal-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <span className="eyebrow">AGRO SALES AI</span>
                <h2 id="modal-title">
                  {modal === "lead"
                    ? "Una nuova opportunità"
                    : modal === "search"
                      ? "Trova i tuoi prossimi clienti"
                      : modal === "appointment"
                        ? "Organizza un incontro"
                        : modal === "reply"
                          ? "Registra una risposta"
                          : "Il tuo messaggio, la tua voce"}
                </h2>
              </div>
              <button
                className="icon-button"
                disabled={busy}
                onClick={() => setModal(null)}
                aria-label="Chiudi finestra"
              >
                <X size={22} />
              </button>
            </div>
            {modal === "lead" && (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  const values = Object.fromEntries(
                    new FormData(event.currentTarget),
                  );
                  void action(
                    () => post("/leads", values),
                    "Lead aggiunto",
                    true,
                  );
                }}
              >
                <div className="form-grid">
                  <Field label="Nome dell’attività *">
                    <input
                      name="company_name"
                      required
                      placeholder="Es. Ristorante La Quercia"
                    />
                  </Field>
                  <Field label="Tipologia">
                    <select name="business_type">
                      <option>Ristorante</option>
                      <option>Hotel</option>
                      <option>Catering</option>
                      <option>Bar</option>
                      <option>Altro</option>
                    </select>
                  </Field>
                  <Field label="Referente">
                    <input name="contact_name" placeholder="Nome e cognome" />
                  </Field>
                  <Field label="Email verificata">
                    <input
                      name="email"
                      type="email"
                      placeholder="Solo se presente nella fonte"
                    />
                  </Field>
                  <Field label="Telefono">
                    <input name="phone" />
                  </Field>
                  <Field label="Città">
                    <input name="city" />
                  </Field>
                  <Field label="Sito web">
                    <input name="website" type="url" placeholder="https://" />
                  </Field>
                  <Field label="Fonte *">
                    <input
                      name="source"
                      required
                      placeholder="Es. fiera, sito pubblico, contatto diretto"
                    />
                  </Field>
                </div>
                <Field label="Menu o informazioni disponibili">
                  <textarea
                    name="menu_text"
                    rows={3}
                    placeholder="Incolla solo informazioni effettivamente disponibili"
                  />
                </Field>
                <Field label="Note">
                  <textarea name="notes" rows={2} />
                </Field>
                <div className="modal-footer">
                  <span className="muted small">
                    Fonte e data verranno conservate.
                  </span>
                  <Button type="submit" busy={busy}>
                    <Plus size={16} />
                    Aggiungi lead
                  </Button>
                </div>
              </form>
            )}
            {modal === "search" && (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  const body = Object.fromEntries(
                    new FormData(event.currentTarget),
                  );
                  void action(
                    async () => {
                      const result = await post<{
                        imported: number;
                        duplicates: number;
                        errors: unknown[];
                      }>("/leads/search", body);
                      return result;
                    },
                    (result) => {
                      const report = result as {
                        imported: number;
                        duplicates: number;
                        errors: unknown[];
                      };
                      return {
                        text: `${meta?.demo_mode ? "Ricerca demo" : "Ricerca"}: ${report.imported} importati · ${report.duplicates} duplicati · ${report.errors.length} errori`,
                        error: !!report.errors.length,
                      };
                    },
                    true,
                  );
                }}
              >
                <div className="info-strip">
                  <Search size={18} />
                  {meta?.demo_mode
                    ? "La demo importa solo un elenco fittizio. Nessuna ricerca esterna."
                    : "La ricerca usa il provider configurato nel backend."}
                </div>
                <Field label="Cosa cerchi?">
                  <input
                    name="query"
                    required
                    placeholder="Es. ristoranti con cucina del territorio"
                  />
                </Field>
                <Field label="Città / zona">
                  <input name="city" required placeholder="Es. Firenze" />
                </Field>
                <div className="modal-footer">
                  <span className="muted small">
                    I duplicati vengono esclusi.
                  </span>
                  <Button type="submit" busy={busy}>
                    <Search size={16} />
                    Cerca opportunità
                  </Button>
                </div>
              </form>
            )}
            {modal === "appointment" && (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  const values = new FormData(event.currentTarget);
                  void action(
                    () =>
                      post("/appointments", {
                        lead_id: Number(values.get("lead_id")),
                        title: values.get("title"),
                        start_at: new Date(
                          String(values.get("start_at")),
                        ).toISOString(),
                        end_at: new Date(
                          String(values.get("end_at")),
                        ).toISOString(),
                      }),
                    meta?.demo_mode
                      ? "Appuntamento simulato creato"
                      : "Appuntamento confermato dal calendario",
                    true,
                  );
                }}
              >
                <Field label="Cliente">
                  <select name="lead_id" defaultValue={lead?.id} required>
                    <option value="">Scegli un lead</option>
                    {data.leads.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.company_name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Titolo">
                  <input
                    name="title"
                    required
                    placeholder="Es. Presentazione catalogo e degustazione"
                  />
                </Field>
                <div className="form-grid">
                  <Field label="Inizio (ora locale)">
                    <input name="start_at" type="datetime-local" required />
                  </Field>
                  <Field label="Fine (ora locale)">
                    <input name="end_at" type="datetime-local" required />
                  </Field>
                </div>
                <div className="info-strip">
                  <CalendarDays size={18} />
                  {meta?.demo_mode
                    ? "L’appuntamento sarà indicato come simulato, senza contattare un calendario esterno."
                    : "La conferma avviene solo dopo la prenotazione riuscita sul calendario."}
                </div>
                <div className="modal-footer">
                  <span />
                  <Button type="submit" busy={busy}>
                    <CalendarDays size={16} />
                    {meta?.demo_mode
                      ? "Simula prenotazione"
                      : "Prenota sul calendario"}
                  </Button>
                </div>
              </form>
            )}
            {modal === "reply" && (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  const values = new FormData(event.currentTarget);
                  void action(
                    async () => {
                      const result = await post<{
                        classification: string;
                        handoff_required: boolean;
                        extracted: {
                          needs: string;
                          quantity: string;
                          timing: string;
                        };
                      }>(`/leads/${values.get("lead_id")}/reply`, {
                        body: values.get("body"),
                        subject: values.get("subject"),
                        event: values.get("event"),
                      });
                      return result;
                    },
                    (result) => ({
                      text: (result as { handoff_required: boolean })
                        .handoff_required
                        ? "Risposta registrata: follow-up interrotti. Serve l’attenzione del commerciale."
                        : "Risposta registrata: follow-up interrotti",
                    }),
                    true,
                  );
                }}
              >
                <div className="info-strip">
                  <StopCircle size={18} />
                  Registrare una risposta interrompe i follow-up. L’assistente
                  analizza il contenuto come dato, mai come istruzione.
                </div>
                <Field label="Cliente">
                  <select name="lead_id" defaultValue={lead?.id} required>
                    <option value="">Scegli un lead</option>
                    {data.leads.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.company_name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Tipo di evento">
                  <select name="event">
                    <option value="reply">Risposta ricevuta</option>
                    <option value="rejection">Rifiuto</option>
                    <option value="unsubscribe">
                      Richiesta di disiscrizione
                    </option>
                    <option value="hard_bounce">
                      Errore permanente dell’indirizzo
                    </option>
                  </select>
                </Field>
                <Field label="Oggetto">
                  <input
                    name="subject"
                    placeholder="Es. Re: Presentazione prodotti"
                  />
                </Field>
                <Field label="Testo della risposta">
                  <textarea
                    name="body"
                    required
                    rows={6}
                    placeholder="Incolla il messaggio ricevuto dal cliente…"
                  />
                </Field>
                <div className="modal-footer">
                  <span className="muted small">
                    Inserimento manuale · nessun invio
                  </span>
                  <Button type="submit" busy={busy}>
                    <Check size={16} />
                    Registra e analizza
                  </Button>
                </div>
              </form>
            )}
            {modal === "draft" && draft && (
              <DraftEditor
                draft={data.drafts.find((d) => d.id === draft.id) || draft}
                busy={busy}
                demo={!!meta?.demo_mode}
                onAction={action}
              />
            )}
          </section>
        </div>
      )}
      {toast && (
        <div className={`toast ${toast.error ? "error" : ""}`} role="status">
          {toast.error ? <XCircle size={20} /> : <CheckCircle2 size={20} />}
          <span>{toast.text}</span>
          <button onClick={() => setToast(null)} aria-label="Chiudi notifica">
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

function stopReason(reason: string) {
  return (
    (
      {
        reply:
          "Il cliente ha risposto. Il dialogo continua, i follow-up sono sospesi.",
        rejection: "Il cliente ha rifiutato la proposta.",
        unsubscribe: "Il cliente ha richiesto la disiscrizione.",
        hard_bounce: "Errore permanente dell’indirizzo email.",
      } as Record<string, string>
    )[reason] || reason
  );
}
function safeLink(value: string) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}
function FactList({
  title,
  items,
  tone,
  icon,
}: {
  title: string;
  items: string[];
  tone: string;
  icon: ReactNode;
}) {
  return (
    <div className={`fact-list ${tone}`}>
      <h4>
        {icon}
        {title}
      </h4>
      {items?.length ? (
        <ul>
          {items.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      ) : (
        <p>Nessun elemento disponibile.</p>
      )}
    </div>
  );
}
function PageHeader({
  eyebrow,
  title,
  text,
  actions,
}: {
  eyebrow: string;
  title: string;
  text: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{text}</p>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}
function LeadTable({
  leads,
  openLead,
}: {
  leads: Lead[];
  openLead: (id: number) => void;
}) {
  return !leads.length ? (
    <Empty
      title="Nessun lead trovato"
      text="Aggiungi un contatto, importa un CSV o modifica i filtri."
    />
  ) : (
    <div className="table-scroll">
      <table className="lead-table">
        <thead>
          <tr>
            <th>Attività</th>
            <th>Località</th>
            <th>Compatibilità</th>
            <th>Stato</th>
            <th>Fonte</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {leads.map((lead, index) => (
            <tr key={lead.id} onClick={() => openLead(lead.id)}>
              <td>
                <div className="company-cell">
                  <span className={`company-avatar color-${index % 4}`}>
                    {initials(lead.company_name)}
                  </span>
                  <div>
                    <strong>{lead.company_name}</strong>
                    <small>
                      {lead.business_type || "Tipologia da verificare"}
                      {lead.demo && " · Demo"}
                    </small>
                  </div>
                </div>
              </td>
              <td>{lead.city || "—"}</td>
              <td>
                <Score value={lead.score} />
              </td>
              <td>
                <Stage value={lead.stage} />
                {lead.stop_reason && (
                  <small className="stopped-label">Ricontatti interrotti</small>
                )}
              </td>
              <td>
                <div className="source-cell">
                  <span>{lead.source}</span>
                  <small>{date(lead.source_date)}</small>
                </div>
              </td>
              <td>
                <button
                  className="icon-button"
                  aria-label={`Apri ${lead.company_name}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    openLead(lead.id);
                  }}
                >
                  <ChevronRight size={18} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DashboardPage({
  data,
  user,
  go,
  openLead,
  newLead,
}: {
  data: Data;
  user: User | null;
  go: (page: Page) => void;
  openLead: (id: number) => void;
  newLead: () => void;
}) {
  const m = data.dashboard.metrics;
  const pipeline = Object.keys(stages).filter(stage =>
    ["new", "qualified", "contacted", "interested", "appointment", "won", "lost"].includes(stage) ||
    data.dashboard.pipeline.some(item => item.stage === stage && item.count > 0)
  ).map((stage) => ({
    stage,
    count:
      data.dashboard.pipeline.find((item) => item.stage === stage)?.count || 0,
  }));
  const total = data.dashboard.pipeline.reduce((sum, p) => sum + p.count, 0);
  const metricCards = [
    {
      label: "Lead nel tuo spazio",
      value: m.leads,
      icon: <Users size={21} />,
      hint: `${m.qualified} con compatibilità valutata`,
      color: "green",
    },
    {
      label: "Bozze da gestire",
      value: m.pending_drafts,
      icon: <FileCheck2 size={21} />,
      hint: "Il tuo controllo, prima dell’invio",
      color: "orange",
    },
    {
      label: "Risposte ricevute",
      value: m.replies,
      icon: <MessageSquare size={21} />,
      hint: `${m.sent_real} email reali · ${m.sent_demo} simulate`,
      color: "blue",
    },
    {
      label: "Appuntamenti",
      value: m.appointments,
      icon: <CalendarDays size={21} />,
      hint: `${m.scheduled_tasks} attività programmate`,
      color: "purple",
    },
  ];
  return (
    <>
      <PageHeader
        eyebrow="OGNI RELAZIONE INIZIA DA QUI"
        title={`Buongiorno, ${user?.name?.split(" ")[0] || "produttore"} ☀`}
        text="Ecco come crescono le tue opportunità commerciali."
        actions={
          <Button onClick={newLead}>
            <Plus size={17} />
            Nuovo lead
          </Button>
        }
      />
      <section className="welcome-banner">
        <div>
          <Badge tone="light-green">
            <Sprout size={13} /> DAL CAMPO, A NUOVE OPPORTUNITÀ
          </Badge>
          <h2>
            Il tuo prodotto merita
            <br />
            la tavola giusta.
          </h2>
          <p>
            Trova attività in linea con la tua offerta.
            <br />A ogni messaggio, aggiungi il tuo tocco.
          </p>
          <button onClick={() => go("leads")}>
            Coltiva nuove relazioni
            <ArrowRight size={17} />
          </button>
        </div>
        <Landscape />
        <div className="welcome-tag">
          <span className="welcome-tag-icon">
            <Leaf size={20} />
          </span>
          <span>
            Prodotti autentici.
            <br />
            <strong>Relazioni di valore.</strong>
          </span>
        </div>
      </section>
      <section className="dashboard-automation-callout">
        <span className="dashboard-automation-icon"><Sparkles size={27} strokeWidth={1.5} /></span>
        <div><span className="eyebrow">IL TUO SISTEMA COMMERCIALE AI</span><h3>Guarda il tuo team di agenti al lavoro.</h3><p>Avvia una campagna, segui le opportunità e intervieni quando la relazione passa a te.</p></div>
        <Button onClick={() => go("automations")}><Sparkles size={16} />Apri Automazioni AI<ArrowRight size={16} /></Button>
      </section>
      <div className="metric-grid">
        {metricCards.map((item) => (
          <div className="card metric-card" key={item.label}>
            <div className="metric-top">
              <span>{item.label}</span>
              <span className={`metric-icon ${item.color}`}>{item.icon}</span>
            </div>
            <strong className="metric-value">{item.value}</strong>
            <span className="metric-hint">{item.hint}</span>
          </div>
        ))}
      </div>
      <div className="dashboard-middle">
        <section className="card pipeline-card">
          <div className="card-header">
            <div>
              <h3>La tua pipeline</h3>
              <p>Dall’incontro alla relazione commerciale</p>
            </div>
            <button
              className="icon-button"
              onClick={() => go("leads")}
              aria-label="Apri pipeline"
            >
              <MoreHorizontal size={21} />
            </button>
          </div>
          <div className="pipeline-total">
            <strong>{total}</strong>
            <span>opportunità nel tuo spazio</span>
          </div>
          <div className="pipeline-bars">
            {pipeline.map((item, index) => (
              <div className="pipeline-bar-item" key={item.stage}>
                <div className="bar-space">
                  <div
                    className={`pipeline-bar pipeline-${index}`}
                    style={{
                      height: `${Math.max(8, total ? (item.count / Math.max(...pipeline.map((p) => p.count), 1)) * 100 : 8)}%`,
                    }}
                  >
                    <span>{item.count}</span>
                  </div>
                </div>
                <span>{stages[item.stage] || item.stage}</span>
              </div>
            ))}
          </div>
          <div className="pipeline-bottom">
            <span className="status-dot" />
            Dati aggiornati dalle tue attività
          </div>
        </section>
        <section className="card next-card">
          <div className="card-header">
            <div>
              <h3>Il prossimo passo</h3>
              <p>Piccole azioni, nuove possibilità</p>
            </div>
            <span className="metric-icon orange">
              <Clock3 size={19} />
            </span>
          </div>
          {m.pending_drafts > 0 && (
            <button className="next-action" onClick={() => go("drafts")}>
              <span className="next-action-icon">
                <FileCheck2 size={19} />
              </span>
              <span>
                <strong>{m.pending_drafts} bozze aspettano la tua voce</strong>
                <small>Rivedi, approva o invia i messaggi</small>
              </span>
              <ChevronRight size={17} />
            </button>
          )}
          {data.dashboard.upcoming_tasks.slice(0, 3).map((item) => (
            <button
              className="next-action"
              key={item.id}
              onClick={() => go("tasks")}
            >
              <span className="next-action-icon green">
                <Clock3 size={19} />
              </span>
              <span>
                <strong>{item.company_name}</strong>
                <small>
                  Follow-up {item.step} · {date(item.due_at, true)}
                </small>
              </span>
              <ChevronRight size={17} />
            </button>
          ))}
          {!m.pending_drafts && !data.dashboard.upcoming_tasks.length && (
            <div className="small-empty">
              <CheckCircle2 size={28} />
              <strong>Hai tutto sotto controllo</strong>
              <p>Le prossime azioni appariranno qui.</p>
            </div>
          )}
          <div className="next-tip">
            <Sparkles size={17} />
            <p>
              Un buon messaggio parte da ciò che sai.
              <br />
              <strong>Le informazioni mancanti si chiedono.</strong>
            </p>
          </div>
        </section>
      </div>
      <section className="card dashboard-leads">
        <div className="card-header">
          <div>
            <h3>Opportunità da coltivare</h3>
            <p>I contatti più recenti nel tuo spazio</p>
          </div>
          <button className="section-link" onClick={() => go("leads")}>
            Vedi tutti i lead
            <ArrowRight size={16} />
          </button>
        </div>
        <LeadTable leads={data.leads.slice(0, 5)} openLead={openLead} />
      </section>
      <div className="dashboard-bottom">
        <section className="card">
          <div className="card-header">
            <div>
              <h3>Attività recenti</h3>
              <p>La storia del tuo lavoro, in tempo reale</p>
            </div>
            <button className="section-link" onClick={() => go("audit")}>
              Registro
              <ArrowRight size={15} />
            </button>
          </div>
          {data.dashboard.recent_activity.slice(0, 4).map((item) => (
            <div className="audit-row compact" key={item.id}>
              <span className="audit-icon">
                <Check size={14} />
              </span>
              <div>
                <strong>{actionName(item.action)}</strong>
                <p>{item.detail}</p>
              </div>
              <time>{date(item.created_at, true)}</time>
            </div>
          ))}
          {!data.dashboard.recent_activity.length && (
            <p className="empty-inline">Nessuna attività ancora.</p>
          )}
        </section>
        <section className="catalog-preview">
          <div className="catalog-preview-icon">
            <Package size={25} />
          </div>
          <span className="eyebrow">IL TUO VALORE, IN PRIMO PIANO</span>
          <h3>Tutto parte dai tuoi prodotti.</h3>
          <p>
            {data.profile.catalog.length} prodotti in catalogo.
            <br />
            Un profilo completo rende ogni proposta più pertinente.
          </p>
          <button className="section-link" onClick={() => go("profile")}>
            Rivedi il tuo catalogo
            <ArrowRight size={16} />
          </button>
        </section>
      </div>
    </>
  );
}

function actionName(value: string) {
  const map: Record<string, string> = {
    "lead.creato": "Nuovo lead aggiunto",
    "lead.qualificato": "Compatibilità valutata",
    "bozza.creata": "Bozza generata",
    "bozza.approvata": "Bozza approvata",
    "bozza.modificata": "Bozza modificata",
    "bozza.rifiutata": "Bozza rifiutata",
    "invio.simulato": "Invio email simulato",
    "email.inviata": "Email inviata",
    "invio.errore": "Errore nell’invio",
    "risposta.registrata": "Risposta registrata",
    "profilo.aggiornato": "Profilo aggiornato",
    "ricontatti.interrotti": "Ricontatti interrotti",
    "appuntamento.simulato": "Appuntamento simulato",
    "appuntamento.confermato": "Appuntamento confermato",
    "crm.simulato": "Sincronizzazione CRM simulata",
    "crm.sincronizzato": "Scheda sincronizzata",
    "commerciale.coinvolto": "Richiesta al commerciale",
    "commerciale.risolto": "Richiesta gestita",
    "import.completato": "Importazione completata",
    "ricerca.completata": "Ricerca completata",
    "sequenza.programmata": "Follow-up programmati",
    "attività.annullata": "Attività annullata",
    "accesso.eseguito": "Accesso effettuato",
    "account.creato": "Account creato",
    "lead.aggiornato": "Scheda lead aggiornata",
    lead_created: "Nuovo lead aggiunto",
    lead_qualified: "Compatibilità valutata",
    draft_created: "Bozza generata",
    draft_approved: "Bozza approvata",
    draft_sent: "Messaggio inviato",
    email_sent_demo: "Invio email simulato",
    reply_received: "Risposta registrata",
    profile_updated: "Profilo aggiornato",
    lead_stopped: "Ricontatti interrotti",
    appointment_created: "Appuntamento creato",
    crm_synced: "Scheda sincronizzata",
    lead_imported: "Lead importato",
    draft_updated: "Bozza modificata",
    handoff_created: "Richiesta al commerciale",
    task_cancelled: "Attività annullata",
    worker_run: "Worker eseguito",
  };
  return map[value] || value.replaceAll("_", " ").replaceAll(".", " ");
}

function DraftEditor({
  draft,
  busy,
  demo,
  onAction,
}: {
  draft: Draft;
  busy: boolean;
  demo: boolean;
  onAction: (
    fn: () => Promise<unknown>,
    success: string,
    close?: boolean,
  ) => Promise<void>;
}) {
  const [subject, setSubject] = useState(draft.subject);
  const [body, setBody] = useState(draft.body);
  useEffect(() => {
    setSubject(draft.subject);
    setBody(draft.body);
  }, [draft.id, draft.subject, draft.body]);
  const dirty = subject !== draft.subject || body !== draft.body;
  const editable =
    ["pending", "approved", "failed"].includes(draft.status) && !draft.error;
  const retryable = draft.status === "failed";
  return (
    <>
      <div className="draft-editor-meta">
        <span>
          <strong>{draft.company_name}</strong> ·{" "}
          {draft.kind === "reply"
            ? "Risposta"
            : draft.task_id != null
              ? "Follow-up"
              : "Email commerciale"}
        </span>
        <Stage value={draft.status} />
      </div>
      <Field label="Oggetto">
        <input
          value={subject}
          disabled={!editable || busy}
          onChange={(e) => setSubject(e.target.value)}
        />
      </Field>
      <Field label="Messaggio">
        <textarea
          rows={13}
          value={body}
          disabled={!editable || busy}
          onChange={(e) => setBody(e.target.value)}
        />
      </Field>
      {draft.error && (
        <div className="form-error">
          {draft.error}
          <br />
          Il testo è bloccato dopo il tentativo di invio. Riapprova per
          riprovare con la stessa chiave, senza duplicare il messaggio.
        </div>
      )}
      <div className="info-strip">
        <ShieldCheck size={18} />
        {demo
          ? "Invio simulato: nessun messaggio lascerà la demo."
          : "La bozza viene inviata solo dopo la tua approvazione esplicita."}
      </div>
      <div className="modal-footer draft-actions">
        <div>
          {editable && (
            <Button
              variant="danger"
              busy={busy}
              onClick={() =>
                void onAction(
                  () => post(`/drafts/${draft.id}/reject`),
                  "Bozza rifiutata",
                  true,
                )
              }
            >
              <X size={15} />
              Rifiuta
            </Button>
          )}
        </div>
        <div className="button-row">
          {editable && (
            <Button
              variant="secondary"
              busy={busy}
              disabled={!dirty || !subject.trim() || !body.trim()}
              onClick={() =>
                void onAction(
                  () =>
                    api(`/drafts/${draft.id}`, {
                      method: "PATCH",
                      body: JSON.stringify({ subject, body }),
                    }),
                  "Modifiche salvate: la bozza richiede approvazione",
                )
              }
            >
              <Check size={15} />
              Salva modifiche
            </Button>
          )}
          {(draft.status === "pending" || retryable) && (
            <Button
              busy={busy}
              disabled={dirty}
              onClick={() =>
                void onAction(
                  () => post(`/drafts/${draft.id}/approve`),
                  "Bozza approvata",
                )
              }
            >
              <CheckCheck size={16} />
              {retryable ? "Riapprova per ritentare" : "Approva bozza"}
            </Button>
          )}
          {draft.status === "approved" && (
            <Button
              busy={busy}
              disabled={dirty}
              onClick={() =>
                void onAction(
                  () => post(`/drafts/${draft.id}/send`),
                  demo ? "Invio simulato completato" : "Messaggio inviato",
                  true,
                )
              }
            >
              <Send size={16} />
              {demo ? "Simula invio" : "Invia email"}
            </Button>
          )}
        </div>
      </div>
      {dirty && (
        <p className="muted small">
          Salva le modifiche prima di approvare o inviare.
        </p>
      )}
    </>
  );
}

function ProfilePage({
  profile,
  busy,
  onSave,
}: {
  profile: Profile;
  busy: boolean;
  onSave: (profile: Profile) => Promise<void>;
}) {
  const [form, setForm] = useState(profile);
  const [areas, setAreas] = useState(profile.service_areas.join(", "));
  const [days, setDays] = useState(profile.followup_days.join(", "));
  useEffect(() => {
    setForm(profile);
    setAreas(profile.service_areas.join(", "));
    setDays(profile.followup_days.join(", "));
  }, [profile]);
  const change = (key: keyof Profile, value: unknown) =>
    setForm((prev) => ({ ...prev, [key]: value }));
  return (
    <>
      <PageHeader
        eyebrow="LA TUA IDENTITÀ COMMERCIALE"
        title="Il valore che porti in tavola"
        text="L’assistente usa questi dati per proposte coerenti con la tua offerta."
      />
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const steps = days
            .split(",")
            .map(Number)
            .filter((n) => Number.isInteger(n) && n > 0);
          void onSave({
            ...form,
            service_areas: areas
              .split(",")
              .map((v) => v.trim())
              .filter(Boolean),
            followup_days: steps,
          });
        }}
      >
        <div className="profile-grid">
          <section className="card profile-card">
            <h3>
              <Sprout size={19} />
              La tua azienda
            </h3>
            <Field label="Ragione sociale">
              <input
                required
                value={form.company_name}
                onChange={(e) => change("company_name", e.target.value)}
              />
            </Field>
            <Field label="Descrizione">
              <textarea
                rows={4}
                value={form.description}
                onChange={(e) => change("description", e.target.value)}
                placeholder="La tua storia, la tua produzione, ciò che ti rende speciale"
              />
            </Field>
            <div className="form-grid">
              <Field label="Referente commerciale">
                <input
                  value={form.contact_name}
                  onChange={(e) => change("contact_name", e.target.value)}
                />
              </Field>
              <Field label="Email commerciale">
                <input
                  type="email"
                  value={form.contact_email}
                  onChange={(e) => change("contact_email", e.target.value)}
                />
              </Field>
            </div>
            <Field label="Telefono">
              <input
                value={form.phone}
                onChange={(e) => change("phone", e.target.value)}
              />
            </Field>
          </section>
          <section className="card profile-card">
            <h3>
              <Package size={19} />
              Condizioni di vendita
            </h3>
            <div className="form-grid">
              <Field label="Ordine minimo">
                <input
                  placeholder="Es. € 120 oppure 10 kg"
                  value={form.minimum_order}
                  onChange={(e) => change("minimum_order", e.target.value)}
                />
              </Field>
              <Field label="Zone servite" hint="Separate da virgola">
                <input
                  value={areas}
                  onChange={(e) => setAreas(e.target.value)}
                />
              </Field>
            </div>
            <Field label="Consegna">
              <textarea
                rows={3}
                value={form.delivery_terms}
                onChange={(e) => change("delivery_terms", e.target.value)}
              />
            </Field>
            <Field label="Pagamento">
              <textarea
                rows={3}
                value={form.payment_terms}
                onChange={(e) => change("payment_terms", e.target.value)}
              />
            </Field>
            <Field
              label="Follow-up: giorni dopo il primo invio"
              hint="Es. 3, 7. Ogni scadenza crea una bozza da approvare."
            >
              <input
                value={days}
                pattern="\s*\d+\s*(,\s*\d+\s*)*"
                onChange={(e) => setDays(e.target.value)}
              />
            </Field>
          </section>
        </div>
        <section className="card catalog-card">
          <div className="card-header">
            <div>
              <h3>Il tuo catalogo</h3>
              <p>Prezzi e disponibilità: la base delle tue proposte</p>
            </div>
            <Button
              variant="secondary"
              onClick={() =>
                change("catalog", [
                  ...form.catalog,
                  {
                    id: crypto.randomUUID(),
                    name: "",
                    category: "",
                    unit: "kg",
                    price: 0,
                    description: "",
                  },
                ])
              }
            >
              <Plus size={16} />
              Aggiungi prodotto
            </Button>
          </div>
          {form.catalog.length ? (
            form.catalog.map((product, index) => (
              <div className="catalog-product" key={product.id}>
                <span className="product-icon">
                  <Leaf size={22} />
                </span>
                <div className="catalog-fields">
                  <div className="form-grid product-grid">
                    <Field label="Prodotto">
                      <input
                        required
                        value={product.name}
                        onChange={(e) =>
                          change(
                            "catalog",
                            form.catalog.map((p, i) =>
                              i === index ? { ...p, name: e.target.value } : p,
                            ),
                          )
                        }
                      />
                    </Field>
                    <Field label="Categoria">
                      <input
                        value={product.category}
                        onChange={(e) =>
                          change(
                            "catalog",
                            form.catalog.map((p, i) =>
                              i === index
                                ? { ...p, category: e.target.value }
                                : p,
                            ),
                          )
                        }
                      />
                    </Field>
                    <Field label="Prezzo (€)">
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        required
                        value={product.price}
                        onChange={(e) =>
                          change(
                            "catalog",
                            form.catalog.map((p, i) =>
                              i === index
                                ? { ...p, price: Number(e.target.value) }
                                : p,
                            ),
                          )
                        }
                      />
                    </Field>
                    <Field label="Unità">
                      <input
                        required
                        value={product.unit}
                        onChange={(e) =>
                          change(
                            "catalog",
                            form.catalog.map((p, i) =>
                              i === index ? { ...p, unit: e.target.value } : p,
                            ),
                          )
                        }
                      />
                    </Field>
                  </div>
                  <Field label="Descrizione">
                    <input
                      value={product.description}
                      onChange={(e) =>
                        change(
                          "catalog",
                          form.catalog.map((p, i) =>
                            i === index
                              ? { ...p, description: e.target.value }
                              : p,
                          ),
                        )
                      }
                    />
                  </Field>
                </div>
                <button
                  type="button"
                  className="icon-button danger"
                  aria-label={`Rimuovi ${product.name || "prodotto"}`}
                  onClick={() =>
                    change(
                      "catalog",
                      form.catalog.filter((_, i) => i !== index),
                    )
                  }
                >
                  <Trash2 size={17} />
                </button>
              </div>
            ))
          ) : (
            <Empty
              icon={<Package size={30} />}
              title="Il catalogo è ancora vuoto"
              text="Aggiungi i tuoi prodotti per generare proposte pertinenti."
            />
          )}
        </section>
        <div className="profile-save">
          <span>
            <ShieldCheck size={16} />
            L’AI non può offrire condizioni diverse senza il commerciale.
          </span>
          <Button type="submit" busy={busy}>
            <Check size={17} />
            Salva il profilo
          </Button>
        </div>
      </form>
    </>
  );
}
