import { useState, useEffect, useCallback } from 'react';
import { api } from '../core/api/client';
import type { CrmTask } from '../core/types';
import { TaskForm } from './components/TaskForm';
import { IconPlus, IconCheck } from '../shared/icons';

type Filter = 'all' | 'pending' | 'due_today' | 'overdue' | 'completed';

const mono = (size: number, color = 'rgba(237,240,244,0.38)') => ({
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: size, letterSpacing: '0.16em',
  textTransform: 'uppercase' as const, color,
});

export function TasksPage() {
  const [tasks, setTasks] = useState<CrmTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>('pending');
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    const today = new Date().toISOString().split('T')[0];
    if (filter === 'pending') params.set('completed', 'false');
    else if (filter === 'completed') params.set('completed', 'true');
    else if (filter === 'due_today') { params.set('completed', 'false'); params.set('due_before', today); }
    else if (filter === 'overdue') { params.set('completed', 'false'); params.set('due_before', today); }
    params.set('limit', '100');
    const data = await api<{ tasks: CrmTask[] }>(`/api/crm/tasks?${params}`);
    let filtered = data.tasks;
    if (filter === 'overdue') filtered = filtered.filter(t => t.due_date && t.due_date < today);
    setTasks(filtered);
    setLoading(false);
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  async function toggleComplete(task: CrmTask) {
    if (task.completed) {
      await api(`/api/crm/tasks/${task.id}`, { method: 'PUT', body: JSON.stringify({ completed: 0 }) });
    } else {
      await api(`/api/crm/tasks/${task.id}/complete`, { method: 'PUT' });
    }
    load();
  }

  const today = new Date().toISOString().split('T')[0];

  const FILTER_TABS: { key: Filter; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'pending', label: 'Pending' },
    { key: 'due_today', label: 'Due Today' },
    { key: 'overdue', label: 'Overdue' },
    { key: 'completed', label: 'Completed' },
  ];

  return (
    <div style={{ padding: '32px 44px', maxWidth: 900 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <h1 style={{
          fontFamily: "'Fraunces', Georgia, serif",
          fontSize: 32, fontWeight: 400, letterSpacing: '-0.02em',
          color: '#EDF0F4', margin: 0,
        }}>Tasks</h1>
        <button onClick={() => setShowCreate(true)} style={{
          background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
          border: 'none', padding: '7px 14px', borderRadius: 4,
          fontSize: 13, fontWeight: 500, cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <IconPlus size={13} strokeWidth={2.25} /> Add Task
        </button>
      </div>

      {/* Filter tabs */}
      <div style={{
        display: 'inline-flex', border: '1px solid rgba(230,235,242,0.07)',
        borderRadius: 4, overflow: 'hidden', marginBottom: 24,
      }}>
        {FILTER_TABS.map(tab => (
          <button key={tab.key} onClick={() => setFilter(tab.key)} style={{
            padding: '6px 14px', fontSize: 11, fontWeight: 500,
            color: filter === tab.key ? '#0E1013' : 'rgba(237,240,244,0.62)',
            background: filter === tab.key ? 'var(--color-ch-accent, #C8D1D9)' : 'transparent',
            border: 'none', cursor: 'pointer',
          }}>{tab.label}</button>
        ))}
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '48px 0' }}>
          <div className="w-6 h-6 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
        </div>
      ) : tasks.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 0' }}>
          <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 14 }}>
            {filter === 'all' ? 'No tasks yet.' : `No ${filter.replace('_', ' ')} tasks.`}
          </p>
        </div>
      ) : (
        <div style={{ borderTop: '1px solid rgba(230,235,242,0.07)' }}>
          {tasks.map(task => (
            <div key={task.id} style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '12px 16px',
              borderBottom: '1px solid rgba(230,235,242,0.07)',
              opacity: task.completed ? 0.5 : 1,
            }}>
              <button onClick={() => toggleComplete(task)} style={{
                width: 20, height: 20, borderRadius: 4, flexShrink: 0,
                border: `1.5px solid ${task.completed ? '#8EA589' : 'rgba(230,235,242,0.14)'}`,
                background: task.completed ? 'rgba(142,165,137,0.2)' : 'transparent',
                cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: '#8EA589',
              }}>
                {task.completed && <IconCheck size={12} strokeWidth={2.5} />}
              </button>

              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{
                  fontSize: 14, margin: 0,
                  color: task.completed ? 'rgba(237,240,244,0.38)' : '#EDF0F4',
                  textDecoration: task.completed ? 'line-through' : 'none',
                }}>{task.title}</p>
                <div style={{ display: 'flex', gap: 12, marginTop: 2 }}>
                  {task.contact_name && <span style={{ fontSize: 12, color: 'rgba(237,240,244,0.38)' }}>{task.contact_name}</span>}
                  {task.deal_title && <span style={{ fontSize: 12, color: 'rgba(237,240,244,0.38)' }}>{task.deal_title}</span>}
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
                <PriorityBadge priority={task.priority} />
                {task.due_date && (
                  <span style={{
                    ...mono(10, !task.completed && task.due_date < today ? '#D97757' : 'rgba(237,240,244,0.38)'),
                    fontWeight: !task.completed && task.due_date < today ? 600 : 400,
                  }}>{task.due_date}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {showCreate && <TaskForm onClose={() => setShowCreate(false)} onSaved={() => { setShowCreate(false); load(); }} />}
    </div>
  );
}

function PriorityBadge({ priority }: { priority: string }) {
  const colors: Record<string, { bg: string; color: string }> = {
    high: { bg: 'rgba(217,119,87,0.1)', color: '#D97757' },
    medium: { bg: 'rgba(212,168,90,0.08)', color: '#D4A85A' },
    low: { bg: 'rgba(230,235,242,0.06)', color: 'rgba(237,240,244,0.38)' },
  };
  const c = colors[priority] || colors.medium;
  return (
    <span style={{
      fontSize: 10, padding: '2px 8px', borderRadius: 3,
      background: c.bg, color: c.color, textTransform: 'capitalize',
      fontFamily: "'JetBrains Mono', ui-monospace, monospace",
      letterSpacing: '0.1em',
    }}>{priority}</span>
  );
}
