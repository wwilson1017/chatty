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

// SSE event types
export type SSEEvent =
  | { type: 'conversation_id'; id: string }
  | { type: 'text'; text: string }
  | { type: 'tool_start'; tool: string; tool_use_id: string }
  | { type: 'tool_args'; tool: string; tool_use_id: string; args: Record<string, unknown> }
  | { type: 'tool_end'; tool: string; tool_use_id: string; result: unknown; elapsed_ms: number }
  | { type: 'title_update'; title: string; conversation_id: string }
  | { type: 'done' }
  | { type: 'error'; error: string };
