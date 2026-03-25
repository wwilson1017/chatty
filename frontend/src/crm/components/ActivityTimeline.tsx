import type { CrmActivity } from '../../core/types';

const ACTIVITY_ICONS: Record<string, string> = {
  call: 'tel',
  email: '@',
  meeting: 'mtg',
  note: '#',
  follow_up: '>>',
};

export function ActivityTimeline({ activities }: { activities: CrmActivity[] }) {
  if (activities.length === 0) {
    return <p className="text-gray-500 text-sm">No activity yet.</p>;
  }

  return (
    <div className="space-y-3">
      {activities.map(a => (
        <div key={a.id} className="flex gap-3">
          <div className="w-8 h-8 rounded-full bg-gray-800 flex items-center justify-center text-xs text-gray-400 font-mono shrink-0">
            {ACTIVITY_ICONS[a.activity] || a.activity.charAt(0)}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-2">
              <span className="text-white text-sm capitalize">{a.activity.replace('_', ' ')}</span>
              {a.contact_name && (
                <span className="text-gray-500 text-xs">&middot; {a.contact_name}</span>
              )}
            </div>
            {a.note && <p className="text-gray-400 text-xs mt-0.5 truncate">{a.note}</p>}
            <p className="text-gray-600 text-xs mt-0.5">{formatDate(a.created_at)}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso + 'Z');
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) +
      ' ' + d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  } catch {
    return iso;
  }
}
