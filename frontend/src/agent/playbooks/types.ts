/**
 * Chatty — Playbook types shared by the panel, chips, slash menu, and feed.
 */

export interface PlaybookSummary {
  slug: string;
  name: string;
  description: string;
  integrations: string[];
  chip: boolean;
  created_by: 'user' | 'agent' | 'review' | 'migration';
  created_at: string;
  updated_at: string;
  archived: boolean;
  available: boolean;
  missing_integrations: string[];
  use_count: number;
  last_used_at: string | null;
  size_bytes: number;
}

export interface PlaybookDetail {
  slug: string;
  meta: {
    name: string;
    description: string;
    integrations: string[];
    chip: boolean;
    created_by: string;
    created_at?: string;
    updated_at?: string;
  };
  body: string;
  archived: boolean;
}

export interface PlaybookWrite {
  name: string;
  description: string;
  content: string;
  integrations: string[];
  chip: boolean;
}

export interface LearningEvent {
  id: number;
  event_type: 'playbook_created' | 'playbook_updated' | 'playbook_archived' | 'fact_added' | 'blocked_injection';
  source: string;
  target: string;
  title: string;
  before_preview: string | null;
  after_preview: string | null;
  conversation_id: string | null;
  created_at: string;
  reverted_at: string | null;
}

const INTEGRATION_LABELS: Record<string, string> = {
  google: 'Google',
  gmail: 'Gmail',
  calendar: 'Calendar',
  drive: 'Drive',
  quickbooks: 'QuickBooks',
  qb_csv: 'QuickBooks CSV',
  odoo: 'Odoo',
  bamboohr: 'BambooHR',
  crm_lite: 'CRM',
  telegram: 'Telegram',
  whatsapp: 'WhatsApp',
  paperclip: 'Paperclip',
  todoist: 'Todoist',
};

export function integrationLabel(id: string): string {
  return INTEGRATION_LABELS[id] || id.charAt(0).toUpperCase() + id.slice(1);
}
