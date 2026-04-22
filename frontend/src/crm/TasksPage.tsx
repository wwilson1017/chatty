import { useState, useEffect, useCallback } from 'react';
import { api } from '../core/api/client';
import type { CrmTask } from '../core/types';
import { TaskForm } from './components/TaskForm';
import { PriorityBadge } from './components/badges';
import { IconPlus, IconCheck } from '../shared/icons';
import { useIsMobile } from '../shared/useIsMobile';
import {
  INK, INK_MUTE, INK_SOFT, INK_DIM, LINE, LINE_STRONG,
  CORAL, SAGE, ACCENT_INK,
  FONT_DISPLAY, mono,
} from '../shared/styles';
import {
  pageHeading, filterBar, filterTab,
  btnPrimary, cardStyle,
  modalOverlay, modalContent, mobileDragHandle,
  btnSecondary,
} from './styles';

type Filter = 'all' | 'pending' | 'due_today' | 'overdue' | 'completed';

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

  // eslint-disable-next-line react-hooks/set-state-in-effect
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
        <h1 style={pageHeading(isMobile)}>Tasks</h1>
        <button onClick={() => setShowCreate(true)} style={{
          ...btnPrimary,
          padding: '7px 14px', fontSize: 13,
        }}>
          <IconPlus size={13} strokeWidth={2.25} /> {isMobile ? 'Add' : 'Add Task'}
        </button>
      </div>

      {/* Filter tabs */}
      <div style={filterBar(isMobile)}>
        {FILTER_TABS.map(tab => {
          const isActive = filter === tab.key;
          return (
            <button key={tab.key} onClick={() => setFilter(tab.key)} style={filterTab(isMobile, isActive)}>{tab.label}</button>
          );
        })}
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '48px 0' }}>
          <div className="w-6 h-6 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
        </div>
      ) : tasks.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 0' }}>
          <p style={{ color: INK_DIM, fontSize: 14 }}>
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
                  ...cardStyle,
                  opacity: task.completed ? 0.5 : 1,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <span style={{
                    fontSize: 16, color: task.completed ? INK_DIM : INK,
                    textDecoration: task.completed ? 'line-through' : 'none',
                  }}>{task.title}</span>
                  <PriorityBadge priority={task.priority} />
                </div>
                <div style={{ display: 'flex', gap: 12, fontSize: 14, color: INK_SOFT, flexWrap: 'wrap' }}>
                  {task.contact_name && <span>{task.contact_name}</span>}
                  {task.due_date && (
                    <span style={{
                      color: !task.completed && task.due_date < today ? CORAL : undefined,
                      fontWeight: !task.completed && task.due_date < today ? 600 : undefined,
                    }}>{task.due_date}</span>
                  )}
                  {task.completed && <span style={{ color: SAGE }}>Completed</span>}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ borderTop: `1px solid ${LINE}` }}>
            {tasks.map(task => (
              <div key={task.id} onClick={() => setSelectedTask(task)} style={{
                display: 'flex', alignItems: 'center', gap: 12,
                padding: '12px 16px', cursor: 'pointer',
                borderBottom: `1px solid ${LINE}`,
                opacity: task.completed ? 0.5 : 1,
              }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(200,209,217,0.04)'; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
              >
                <button onClick={e => { e.stopPropagation(); toggleComplete(task); }} style={{
                  width: 20, height: 20, borderRadius: 4, flexShrink: 0,
                  border: `1.5px solid ${task.completed ? SAGE : LINE_STRONG}`,
                  background: task.completed ? 'rgba(142,165,137,0.2)' : 'transparent',
                  cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: SAGE,
                }}>
                  {task.completed && <IconCheck size={12} strokeWidth={2.5} />}
                </button>

                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{
                    fontSize: 16, margin: 0,
                    color: task.completed ? INK_DIM : INK,
                    textDecoration: task.completed ? 'line-through' : 'none',
                  }}>{task.title}</p>
                  <div style={{ display: 'flex', gap: 12, marginTop: 3 }}>
                    {task.contact_name && <span style={{ fontSize: 14, color: INK_SOFT }}>{task.contact_name}</span>}
                    {task.deal_title && <span style={{ fontSize: 14, color: INK_SOFT }}>{task.deal_title}</span>}
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
                  <PriorityBadge priority={task.priority} />
                  {task.due_date && (
                    <span style={{
                      ...mono(12, !task.completed && task.due_date < today ? CORAL : INK_SOFT),
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
          style={modalOverlay(isMobile)}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={modalContent(isMobile)}
          >
            {/* Drag handle (mobile) */}
            {isMobile && (
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
                <div style={mobileDragHandle} />
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
              <h3 style={{
                fontFamily: FONT_DISPLAY,
                fontSize: 20, fontWeight: 400, letterSpacing: '-0.01em',
                color: INK, margin: 0, flex: 1,
              }}>{selectedTask.title}</h3>
              <PriorityBadge priority={selectedTask.priority} />
            </div>

            {selectedTask.description && (
              <p style={{ fontSize: 14, color: INK_MUTE, marginBottom: 16, lineHeight: 1.5 }}>
                {selectedTask.description}
              </p>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 20 }}>
              {selectedTask.contact_name && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ ...mono(10), color: INK_DIM }}>Contact</span>
                  <span style={{ fontSize: 13, color: INK }}>{selectedTask.contact_name}</span>
                </div>
              )}
              {selectedTask.deal_title && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ ...mono(10), color: INK_DIM }}>Deal</span>
                  <span style={{ fontSize: 13, color: INK }}>{selectedTask.deal_title}</span>
                </div>
              )}
              {selectedTask.due_date && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ ...mono(10), color: INK_DIM }}>Due</span>
                  <span style={{
                    fontSize: 13,
                    color: !selectedTask.completed && selectedTask.due_date < today ? CORAL : INK,
                    fontWeight: !selectedTask.completed && selectedTask.due_date < today ? 600 : 400,
                  }}>{selectedTask.due_date}</span>
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={() => setSelectedTask(null)}
                style={{
                  ...btnSecondary,
                  padding: '10px 16px', borderRadius: 6, fontSize: 13,
                }}
              >Close</button>
              <button
                onClick={() => setEditTask(selectedTask)}
                style={{
                  padding: '10px 16px', borderRadius: 6,
                  border: `1px solid ${LINE_STRONG}`, background: 'transparent',
                  color: INK, fontSize: 13, cursor: 'pointer',
                }}
              >Edit</button>
              <button
                onClick={async () => {
                  await toggleComplete(selectedTask);
                  setSelectedTask(null);
                }}
                style={{
                  flex: 1, padding: '10px 16px', borderRadius: 6,
                  background: selectedTask.completed ? 'rgba(230,235,242,0.08)' : SAGE,
                  color: selectedTask.completed ? INK : ACCENT_INK,
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
