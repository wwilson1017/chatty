import { useState, useEffect, useCallback } from 'react';
import { api } from '../core/api/client';
import type { CrmTask } from '../core/types';
import { TaskForm } from './components/TaskForm';

type Filter = 'all' | 'pending' | 'due_today' | 'overdue' | 'completed';

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
    if (filter === 'overdue') {
      filtered = filtered.filter(t => t.due_date && t.due_date < today);
    }

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
    <div className="p-8 max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Tasks</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="bg-brand text-white font-medium px-4 py-2 rounded-lg text-sm hover:opacity-90 transition"
        >
          + Add Task
        </button>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 mb-6 bg-gray-800 rounded-lg border border-gray-700 p-1 inline-flex">
        {FILTER_TABS.map(tab => (
          <button
            key={tab.key}
            onClick={() => setFilter(tab.key)}
            className={`px-3 py-1.5 rounded text-xs font-medium transition ${
              filter === tab.key ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-white'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : tasks.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-gray-500">{filter === 'all' ? 'No tasks yet.' : `No ${filter.replace('_', ' ')} tasks.`}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {tasks.map(task => (
            <div
              key={task.id}
              className={`bg-gray-900 rounded-xl border border-gray-800 px-4 py-3 flex items-center gap-3 ${task.completed ? 'opacity-50' : ''}`}
            >
              <button
                onClick={() => toggleComplete(task)}
                className={`w-5 h-5 rounded border-2 shrink-0 flex items-center justify-center transition ${
                  task.completed
                    ? 'bg-green-600 border-green-600 text-white'
                    : 'border-gray-600 hover:border-gray-400'
                }`}
              >
                {task.completed ? '✓' : ''}
              </button>

              <div className="flex-1 min-w-0">
                <p className={`text-sm ${task.completed ? 'text-gray-500 line-through' : 'text-white'}`}>
                  {task.title}
                </p>
                <div className="flex gap-3 mt-0.5">
                  {task.contact_name && <span className="text-gray-500 text-xs">{task.contact_name}</span>}
                  {task.deal_title && <span className="text-gray-500 text-xs">{task.deal_title}</span>}
                  {task.description && <span className="text-gray-600 text-xs truncate">{task.description}</span>}
                </div>
              </div>

              <div className="flex items-center gap-3 shrink-0">
                <PriorityBadge priority={task.priority} />
                {task.due_date && (
                  <span className={`text-xs ${
                    !task.completed && task.due_date < today ? 'text-red-400 font-medium' : 'text-gray-500'
                  }`}>
                    {task.due_date}
                  </span>
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
  const styles: Record<string, string> = {
    high: 'bg-red-900/50 text-red-400',
    medium: 'bg-yellow-900/50 text-yellow-400',
    low: 'bg-gray-700/50 text-gray-400',
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded capitalize ${styles[priority] || styles.medium}`}>
      {priority}
    </span>
  );
}
