import { useState, useEffect, useCallback } from 'react';
import { api } from '../core/api/client';
import type { CrmTask } from '../core/types';
import { TaskForm } from './components/TaskForm';
import { IconPlus, IconCheck } from '../shared/icons';
import { useIsMobile } from '../shared/useIsMobile';

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
  const [selectedTask, setSelectedTask] = useState<CrmTask | null>(null);
  const [editTask, setEditTask] = useState<CrmTask | null>(null);
  const isMobile = useIsMobile();

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
    if (filter === 'due_today') filtered = filtered.filter(t => t.due_date === today);
    else if (filter === 'overdue') filtered = filtered.filter(t => t.due_date && t.due_date < today);
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
    { key: 'completed', label: 'Done' },
  ];

  return (
    <div style={{ padding: isMobile ? '20px 16px' : '32px 44px', maxWidth: 900 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: isMobile ? 16 : 24 }}>
        <h1 style={{
          fontFamily: "'Fraunces', Georgia, serif",
          fontSize: isMobile ? 24 : 32, fontWeight: 400, letterSpacing: '-0.02em',
          color: '#EDF0F4', margin: 0,
        }}>Tasks</h1>
        <button onClick={() => setShowCreate(true)} style={{
          background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
          border: 'none', padding: '7px 14px', borderRadius: 4,
          fontSize: 13, fontWeight: 500, cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <IconPlus size={13} strokeWidth={2.25} /> {isMobile ? 'Add' : 'Add Task'}
        </button>
      </div>

      {/* Filter tabs */}
      <div style={{
        display: 'flex', border: '1px solid rgba(230,235,242,0.07)',
        borderRadius: 4, overflow: 'hidden', marginBottom: isMobile ? 16 : 24,
        overflowX: isMobile ? 'auto' : undefined,
        WebkitOverflowScrolling: 'touch' as const,
      }}>
        {FILTER_TABS.map(tab => (
          <button key={tab.key} onClick={() => setFilter(tab.key)} style={{
            padding: isMobile ? '6px 10px' : '6px 14px', fontSize: 11, fontWeight: 500,
            color: filter === tab.key ? '#0E1013' : 'rgba(237,240,244,0.62)',
            background: filter === tab.key ? 'var(--color-ch-accent, #C8D1D9)' : 'transparent',
            border: 'none', cursor: 'pointer', whiteSpace: 'nowrap',
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
        isMobile ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {tasks.map(task => (
              <div key={task.id}
                onClick={() => setSelectedTask(task)}
                style={{
                  padding: '12px 14px', cursor: 'pointer',
                  background: 'rgba(20,24,30,0.78)',
                  border: '1px solid rgba(230,235,242,0.07)',
                  borderRadius: 6,
                  opacity: task.completed ? 0.5 : 1,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <span style={{
                    fontSize: 14, color: task.completed ? 'rgba(237,240,244,0.38)' : '#EDF0F4',
                    textDecoration: task.completed ? 'line-through' : 'none',
                  }}>{task.title}</span>
                  <PriorityBadge priority={task.priority} />
                </div>
                <div style={{ display: 'flex', gap: 12, fontSize: 12, color: 'rgba(237,240,244,0.38)', flexWrap: 'wrap' }}>
                  {task.contact_name && <span>{task.contact_name}</span>}
                  {task.due_date && (
                    <span style={{
                      color: !task.completed && task.due_date < today ? '#D97757' : undefined,
                      fontWeight: !task.completed && task.due_date < today ? 600 : undefined,
                    }}>{task.due_date}</span>
                  )}
                  {task.completed && <span style={{ color: '#8EA589' }}>Completed</span>}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ borderTop: '1px solid rgba(230,235,242,0.07)' }}>
            {tasks.map(task => (
              <div key={task.id} onClick={() => setSelectedTask(task)} style={{
                display: 'flex', alignItems: 'center', gap: 12,
                padding: '12px 16px', cursor: 'pointer',
                borderBottom: '1px solid rgba(230,235,242,0.07)',
                opacity: task.completed ? 0.5 : 1,
              }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(200,209,217,0.04)'; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
              >
                <button onClick={e => { e.stopPropagation(); toggleComplete(task); }} style={{
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
        )
      )}

      {showCreate && <TaskForm onClose={() => setShowCreate(false)} onSaved={() => { setShowCreate(false); load(); }} />}
      {editTask && <TaskForm task={editTask} onClose={() => setEditTask(null)} onSaved={() => { setEditTask(null); setSelectedTask(null); load(); }} />}

      {/* Task detail sheet */}
      {selectedTask && (
        <div
          onClick={() => setSelectedTask(null)}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
            zIndex: 50, display: 'flex',
            alignItems: isMobile ? 'flex-end' : 'center',
            justifyContent: 'center',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              background: '#11141A',
              borderRadius: isMobile ? '12px 12px 0 0' : 8,
              border: '1px solid rgba(230,235,242,0.14)',
              borderBottom: isMobile ? 'none' : undefined,
              padding: isMobile ? '20px 20px 28px' : 28,
              width: '100%', maxWidth: 480, margin: isMobile ? 0 : '0 16px',
              boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
            }}
          >
            {/* Drag handle (mobile) */}
            {isMobile && (
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
                <div style={{ width: 36, height: 4, borderRadius: 2, background: 'rgba(230,235,242,0.14)' }} />
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
              <h3 style={{
                fontFamily: "'Fraunces', Georgia, serif",
                fontSize: 20, fontWeight: 400, letterSpacing: '-0.01em',
                color: '#EDF0F4', margin: 0, flex: 1,
              }}>{selectedTask.title}</h3>
              <PriorityBadge priority={selectedTask.priority} />
            </div>

            {selectedTask.description && (
              <p style={{ fontSize: 14, color: 'rgba(237,240,244,0.62)', marginBottom: 16, lineHeight: 1.5 }}>
                {selectedTask.description}
              </p>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 20 }}>
              {selectedTask.contact_name && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ ...mono(9), color: 'rgba(237,240,244,0.38)' }}>Contact</span>
                  <span style={{ fontSize: 13, color: '#EDF0F4' }}>{selectedTask.contact_name}</span>
                </div>
              )}
              {selectedTask.deal_title && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ ...mono(9), color: 'rgba(237,240,244,0.38)' }}>Deal</span>
                  <span style={{ fontSize: 13, color: '#EDF0F4' }}>{selectedTask.deal_title}</span>
                </div>
              )}
              {selectedTask.due_date && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ ...mono(9), color: 'rgba(237,240,244,0.38)' }}>Due</span>
                  <span style={{
                    fontSize: 13,
                    color: !selectedTask.completed && selectedTask.due_date < today ? '#D97757' : '#EDF0F4',
                    fontWeight: !selectedTask.completed && selectedTask.due_date < today ? 600 : 400,
                  }}>{selectedTask.due_date}</span>
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={() => setSelectedTask(null)}
                style={{
                  padding: '10px 16px', borderRadius: 6,
                  border: '1px solid rgba(230,235,242,0.14)', background: 'transparent',
                  color: 'rgba(237,240,244,0.62)', fontSize: 13, cursor: 'pointer',
                }}
              >Close</button>
              <button
                onClick={() => setEditTask(selectedTask)}
                style={{
                  padding: '10px 16px', borderRadius: 6,
                  border: '1px solid rgba(230,235,242,0.14)', background: 'transparent',
                  color: '#EDF0F4', fontSize: 13, cursor: 'pointer',
                }}
              >Edit</button>
              <button
                onClick={async () => {
                  await toggleComplete(selectedTask);
                  setSelectedTask(null);
                }}
                style={{
                  flex: 1, padding: '10px 16px', borderRadius: 6,
                  background: selectedTask.completed ? 'rgba(230,235,242,0.08)' : '#8EA589',
                  color: selectedTask.completed ? '#EDF0F4' : '#0E1013',
                  border: 'none', fontWeight: 500, fontSize: 13, cursor: 'pointer',
                }}
              >{selectedTask.completed ? 'Mark Incomplete' : 'Mark Complete'}</button>
            </div>
          </div>
        </div>
      )}
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
