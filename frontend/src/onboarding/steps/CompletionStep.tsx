interface SetupResult {
  provider: string;
  pendingMessaging: string[];
  pendingIntegrations: string[];
}

interface Props {
  result: SetupResult;
  onComplete: () => void;
}

const PROVIDER_NAMES: Record<string, string> = {
  anthropic: 'Anthropic (Claude)',
  openai: 'OpenAI (GPT)',
  google: 'Google (Gemini)',
};

const INTEGRATION_NAMES: Record<string, string> = {
  telegram: 'Telegram',
  whatsapp: 'WhatsApp',
  odoo: 'Odoo',
  quickbooks: 'QuickBooks',
  bamboohr: 'BambooHR',
  crm_lite: 'CRM',
};

export function CompletionStep({ result, onComplete }: Props) {
  const allPending = [...result.pendingMessaging, ...result.pendingIntegrations];

  return (
    <div className="text-center">
      <div className="w-16 h-16 bg-green-500/20 rounded-full flex items-center justify-center mx-auto mb-6">
        <svg className="w-8 h-8 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </div>

      <h2 className="text-xl font-bold text-white mb-2">You're all set!</h2>
      <p className="text-gray-400 text-sm mb-8">
        Here's your setup summary:
      </p>

      <div className="bg-gray-800 rounded-xl border border-gray-700 p-5 mb-8 text-left">
        <div className="space-y-3">
          {/* Provider — always completed */}
          <div className="flex items-center gap-3">
            <div className="w-5 h-5 bg-green-500 rounded-full flex items-center justify-center flex-shrink-0">
              <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <span className="text-gray-300 text-sm">
              AI Provider: <span className="text-white font-medium">{PROVIDER_NAMES[result.provider] || result.provider}</span>
            </span>
          </div>

          {/* Pending integrations — agent will help */}
          {allPending.map(id => (
            <div key={id} className="flex items-center gap-3">
              <div className="w-5 h-5 bg-amber-500/20 border border-amber-500/40 rounded-full flex items-center justify-center flex-shrink-0">
                <svg className="w-3 h-3 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <circle cx="12" cy="12" r="1" fill="currentColor" />
                  <path d="M12 6v4M12 14v.01" />
                </svg>
              </div>
              <span className="text-gray-300 text-sm">
                {INTEGRATION_NAMES[id] || id} <span className="text-amber-400/80 text-xs ml-1">— your agent will help you set this up</span>
              </span>
            </div>
          ))}

          {allPending.length === 0 && (
            <p className="text-gray-500 text-xs ml-8">
              No integrations selected — you can add them anytime from Settings.
            </p>
          )}
        </div>
      </div>

      {allPending.length > 0 && (
        <p className="text-gray-500 text-xs mb-6">
          When you create your first agent, it will walk you through setting these up conversationally.
        </p>
      )}

      <button
        onClick={onComplete}
        className="w-full py-3 bg-brand text-white font-semibold rounded-xl hover:opacity-90 transition"
      >
        Go to Chatty
      </button>
    </div>
  );
}
