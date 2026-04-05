// Chatty — shared TypeScript types

export interface Agent {
  id: string;
  slug: string;
  agent_name: string;
  avatar_url: string;
  personality: string;
  onboarding_complete: boolean;
  provider_override: string;
  model_override: string;
  gmail_enabled: boolean;
  calendar_enabled: boolean;
  whatsapp_session_id?: string;
  created_at: string;
  updated_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  title_edited_by_user: boolean;
  created_at: string;
  updated_at: string;
  message_count?: number;
  preview?: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  seq: number;
}

export interface Provider {
  id: string;
  name: string;
  connected: boolean;
  active: boolean;
  model?: string;
}

export interface BrandingConfig {
  company_name: string;
  accent_color: string;
  has_logo: boolean;
}

export interface Integration {
  id: string;
  name: string;
  description: string;
  icon: string;
  auth_type: string;
  enabled: boolean;
  configured: boolean;
}

// CRM types

export interface CrmContact {
  id: number;
  name: string;
  email: string;
  phone: string;
  company: string;
  title: string;
  source: string;
  status: string;
  tags: string;
  notes: string;
  created_at: string;
  updated_at: string;
  // Detail view extras
  deals?: CrmDeal[];
  tasks?: CrmTask[];
  activity?: CrmActivity[];
}

export interface CrmDeal {
  id: number;
  contact_id: number | null;
  contact_name?: string;
  title: string;
  stage: string;
  value: number;
  notes: string;
  expected_close_date: string;
  probability: number;
  currency: string;
  created_at: string;
  updated_at: string;
  activity?: CrmActivity[];
}

export interface CrmTask {
  id: number;
  contact_id: number | null;
  deal_id: number | null;
  contact_name?: string;
  deal_title?: string;
  title: string;
  description: string;
  due_date: string;
  completed: number;
  priority: string;
  created_at: string;
  updated_at: string;
}

export interface CrmActivity {
  id: number;
  contact_id: number | null;
  deal_id: number | null;
  contact_name?: string;
  deal_title?: string;
  activity: string;
  note: string;
  created_at: string;
}

export interface CrmDashboard {
  total_contacts: number;
  contacts_by_status: Record<string, number>;
  pipeline_by_stage: { stage: string; count: number; total_value: number }[];
  total_pipeline_value: number;
  overdue_tasks: number;
  pending_tasks: number;
  recent_activity: CrmActivity[];
  top_deals: CrmDeal[];
}

// Provider status (from GET /api/providers)
export interface ProviderStatus {
  active_provider: string;
  active_model: string;
  profiles: Record<string, {
    type: string;
    configured: boolean;
    key_preview?: string;
    expired?: boolean;
  }>;
}

// SSE event types
export type SSEEvent =
  | { type: 'conversation_id'; id: string }
  | { type: 'text'; text: string }
  | { type: 'tool_start'; tool: string; tool_use_id: string }
  | { type: 'tool_args'; tool: string; tool_use_id: string; args: Record<string, unknown> }
  | { type: 'tool_end'; tool: string; tool_use_id: string; result: unknown; elapsed_ms: number }
  | { type: 'confirm'; tool: string; args: Record<string, unknown>; tool_use_id: string; description: string }
  | { type: 'title_update'; title: string; conversation_id: string }
  | { type: 'done' }
  | { type: 'error'; error: string };
