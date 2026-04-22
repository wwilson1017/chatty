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
  gmail_send_enabled?: boolean;
  calendar_enabled: boolean;
  calendar_write_enabled?: boolean;
  drive_enabled?: boolean;
  drive_write_enabled?: boolean;
  whatsapp_session_id?: string;
  telegram_enabled: boolean;
  telegram_bot_token?: string;
  telegram_bot_username?: string;
  telegram_group_enabled: boolean;
  telegram_respond_to_bots: boolean;
  telegram_max_bot_turns: number;
  created_at: string;
  updated_at: string;
}

export type GmailScopeLevel = 'none' | 'read' | 'send';
export type CalendarScopeLevel = 'none' | 'read' | 'full';
export type DriveScopeLevel = 'none' | 'file' | 'readonly' | 'full';

export interface GoogleScopeGrants {
  gmail: GmailScopeLevel;
  calendar: CalendarScopeLevel;
  drive: DriveScopeLevel;
}

export interface Conversation {
  id: string;
  title: string;
  title_edited_by_user: boolean;
  source?: string | null;
  pinned?: number;
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
  always_on?: boolean;
  connection_status?: string;
  tool_mode?: string;
  email?: string;
  scope_grants?: GoogleScopeGrants;
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
  is_railway?: boolean;
  profiles: Record<string, {
    type: string;
    configured: boolean;
    key_preview?: string;
    expired?: boolean;
    base_url?: string;
  }>;
}

// Context usage (returned from SSE 'usage' event)
export interface ContextUsage {
  inputTokens: number;
  contextWindow: number;
}

// Tool mode for 3-tier tool permissions
export type ToolMode = 'read-only' | 'normal' | 'power';

// Training type for onboarding vs improve flows
export type TrainingType = 'topic' | 'improve' | null;

// SSE event types
export type SSEEvent =
  | { type: 'conversation_id'; id: string }
  | { type: 'text'; text: string }
  | { type: 'tool_start'; tool: string; tool_use_id: string }
  | { type: 'tool_args'; tool: string; tool_use_id: string; args: Record<string, unknown>; description?: string }
  | { type: 'tool_end'; tool: string; tool_use_id: string; result: unknown; elapsed_ms?: number; duration_ms?: number }
  | { type: 'confirm'; tool: string; args: Record<string, unknown>; tool_use_id: string; description: string }
  | { type: 'plan_ready'; plan: string }
  | { type: 'usage'; input_tokens: number; context_window: number }
  | { type: 'report'; report: { id: string; title: string; subtitle?: string; sections: unknown[]; created_at: string } }
  | { type: 'title_update'; title: string; conversation_id: string }
  | { type: 'done' }
  | { type: 'error'; error: string };
