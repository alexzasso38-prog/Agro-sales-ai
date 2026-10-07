export type Integration = {
  status: "demo" | "connected" | "not_connected";
  label: string;
};
export type Meta = {
  demo_mode: boolean;
  app_name: string;
  integrations: Record<string, Integration>;
};
export type User = {
  id: number;
  name: string;
  email: string;
  company_name: string;
};
export type Qualification = {
  score: number;
  summary: string;
  verified_facts: string[];
  hypotheses: string[];
  missing_data: string[];
  method: string;
  product_fit?: number;
  commercial_potential?: number;
  confidence?: number;
  total_score?: number;
};
export type Lead = {
  id: number;
  company_name: string;
  contact_name?: string;
  email?: string;
  phone?: string;
  city?: string;
  business_type?: string;
  website?: string;
  menu_text?: string;
  notes?: string;
  source: string;
  source_date: string;
  stage: string;
  score?: number;
  qualification?: Qualification;
  stop_reason?: string;
  created_at: string;
  demo: boolean;
  conversations?: Message[];
  drafts?: Draft[];
  tasks?: Task[];
  activities?: Audit[];
  appointments?: Appointment[];
};
export type Draft = {
  id: number;
  task_id?: number | null;
  lead_id: number;
  company_name: string;
  kind: string;
  subject: string;
  body: string;
  status: string;
  created_at: string;
  approved_at?: string;
  sent_at?: string;
  simulated: boolean;
  error?: string;
};
export type Message = {
  id: number;
  lead_id: number;
  company_name: string;
  direction: string;
  subject: string;
  body: string;
  classification?: string;
  created_at: string;
  simulated: boolean;
};
export type Task = {
  id: number;
  lead_id: number;
  company_name: string;
  kind: string;
  due_at: string;
  status: string;
  step: number;
  last_error?: string;
  created_at: string;
};
export type Audit = {
  id: number;
  lead_id?: number;
  action: string;
  detail: string;
  created_at: string;
};
export type Appointment = {
  id: number;
  lead_id: number;
  company_name: string;
  title: string;
  start_at: string;
  end_at: string;
  status: string;
  provider_event_id?: string;
  simulated: boolean;
};
export type Handoff = {
  id: number;
  lead_id: number;
  company_name: string;
  reason: string;
  summary: string;
  status: string;
  created_at: string;
};
export type Profile = {
  company_name: string;
  description: string;
  contact_name: string;
  contact_email: string;
  phone: string;
  minimum_order: string;
  service_areas: string[];
  delivery_terms: string;
  payment_terms: string;
  catalog: {
    id: string;
    name: string;
    category: string;
    unit: string;
    price: number;
    description: string;
  }[];
  followup_days: number[];
};
export type Dashboard = {
  metrics: {
    leads: number;
    qualified: number;
    pending_drafts: number;
    scheduled_tasks: number;
    appointments: number;
    sent_real: number;
    sent_demo: number;
    replies: number;
  };
  recent_activity: Audit[];
  pipeline: { stage: string; count: number }[];
  upcoming_tasks: Task[];
};
export type Data = {
  dashboard: Dashboard;
  leads: Lead[];
  drafts: Draft[];
  tasks: Task[];
  conversations: Message[];
  appointments: Appointment[];
  handoffs: Handoff[];
  audit: Audit[];
  profile: Profile;
};
