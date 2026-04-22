export const STAGE_ORDER = ['lead', 'qualified', 'proposal', 'negotiation', 'won', 'lost'];

export const STAGE_COLORS: Record<string, { color: string; bg: string }> = {
  lead: { color: '#7B9EC4', bg: 'rgba(123,158,196,0.10)' },
  qualified: { color: '#C8D1D9', bg: 'rgba(200,209,217,0.10)' },
  proposal: { color: '#D4A85A', bg: 'rgba(212,168,90,0.10)' },
  negotiation: { color: '#D4855A', bg: 'rgba(212,133,90,0.10)' },
  won: { color: '#8EA589', bg: 'rgba(142,165,137,0.10)' },
  lost: { color: '#D97757', bg: 'rgba(217,119,87,0.10)' },
};
