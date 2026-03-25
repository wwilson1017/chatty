import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import type { CrmContact } from '../core/types';
import { ContactForm } from './components/ContactForm';
import { DealForm } from './components/DealForm';
import { TaskForm } from './components/TaskForm';
import { ActivityTimeline } from './components/ActivityTimeline';

const STAGE_COLORS: Record<string, string> = {
  lead: 'bg-gray-600', qualified: 'bg-blue-600', proposal: 'bg-yellow-600',
  negotiation: 'bg-orange-600', won: 'bg-green-600', lost: 'bg-red-600',
};

export function ContactDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [contact, setContact] = useState<CrmContact | null>(null);
  const [loading, setLoading] = useState(true);
  const [showEdit, setShowEdit] = useState(false);
  const [showAddDeal, setShowAddDeal] = useState(false);
  const [showAddTask, setShowAddTask] = useState(false);
  const [logActivity, setLogActivity] = useState('');
  const [logNote, setLogNote] = useState('');
  const [logging, setLogging] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const data = await api<CrmContact>(`/api/crm/contacts/${id}`);
      setContact(data);
    } catch {
      setContact(null);
    }
    setLoading(false);
  }

  useEffect(() => { load(); }, [id]);

  async function handleLogActivity() {
    if (!logActivity) return;
    setLogging(true);
    await api('/api/crm/activity', {
      method: 'POST',
      body: JSON.stringify({ activity: logActivity, note: logNote, contact_id: Number(id) }),
    });
    setLogActivity('');
    setLogNote('');
    setLogging(false);
    load();
  }

  async function handleDelete() {
    if (!confirm('Delete this contact? This cannot be undone.')) return;
    await api(`/api/crm/contacts/${id}`, { method: 'DELETE' });
    navigate('/crm/contacts');
  }

  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!contact) {
    return <p className="text-gray-400 p-8">Contact not found.</p>;
  }

  return (
    <div className="p-8 max-w-4xl">
      {/* Header */}
      <button onClick={() => navigate('/crm/contacts')} className="text-gray-500 text-sm hover:text-gray-300 mb-4 block">
        &larr; Back to Contacts
      </button>

      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-white">{contact.name}</h1>
          {contact.title && <p className="text-gray-400 mt-0.5">{contact.title}{contact.company ? ` at ${contact.company}` : ''}</p>}
          {!contact.title && contact.company && <p className="text-gray-400 mt-0.5">{contact.company}</p>}
          <div className="flex gap-3 mt-2 text-sm text-gray-400">
            {contact.email && <span>{contact.email}</span>}
            {contact.phone && <span>{contact.phone}</span>}
          </div>
          {contact.tags && (
            <div className="flex gap-1.5 mt-2">
              {contact.tags.split(',').map(t => t.trim()).filter(Boolean).map(tag => (
                <span key={tag} className="text-xs bg-gray-800 text-gray-300 px-2 py-0.5 rounded">{tag}</span>
              ))}
            </div>
          )}
        </div>
        <div className="flex gap-2">
          <button onClick={() => setShowEdit(true)} className="bg-gray-800 text-gray-300 px-3 py-1.5 rounded-lg text-sm hover:bg-gray-700 transition">Edit</button>
          <button onClick={handleDelete} className="bg-gray-800 text-red-400 px-3 py-1.5 rounded-lg text-sm hover:bg-gray-700 transition">Delete</button>
        </div>
      </div>

      {contact.notes && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 mb-6">
          <p className="text-gray-500 text-xs uppercase mb-1">Notes</p>
          <p className="text-gray-300 text-sm whitespace-pre-wrap">{contact.notes}</p>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Deals */}
        <div className="bg-gray-900 rounded-2xl border border-gray-800 p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-white font-semibold text-sm">Deals</h2>
            <button onClick={() => setShowAddDeal(true)} className="text-indigo-400 text-xs hover:text-indigo-300">+ Add</button>
          </div>
          {!contact.deals?.length ? (
            <p className="text-gray-500 text-xs">No deals yet.</p>
          ) : (
            <div className="space-y-2">
              {contact.deals.map(d => (
                <div key={d.id} className="flex items-center justify-between bg-gray-800/50 rounded-lg px-3 py-2">
                  <div>
                    <p className="text-white text-sm">{d.title}</p>
                    <span className={`text-xs px-1.5 py-0.5 rounded capitalize text-white ${STAGE_COLORS[d.stage] || 'bg-gray-700'}`}>{d.stage}</span>
                  </div>
                  <span className="text-white text-sm font-medium">${d.value.toLocaleString()}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Tasks */}
        <div className="bg-gray-900 rounded-2xl border border-gray-800 p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-white font-semibold text-sm">Tasks</h2>
            <button onClick={() => setShowAddTask(true)} className="text-indigo-400 text-xs hover:text-indigo-300">+ Add</button>
          </div>
          {!contact.tasks?.length ? (
            <p className="text-gray-500 text-xs">No tasks yet.</p>
          ) : (
            <div className="space-y-2">
              {contact.tasks.map(t => (
                <div key={t.id} className={`flex items-center gap-2 bg-gray-800/50 rounded-lg px-3 py-2 ${t.completed ? 'opacity-50' : ''}`}>
                  <span className={`w-2 h-2 rounded-full shrink-0 ${t.completed ? 'bg-green-500' : isOverdue(t.due_date) ? 'bg-red-500' : 'bg-gray-500'}`} />
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm truncate ${t.completed ? 'text-gray-500 line-through' : 'text-white'}`}>{t.title}</p>
                    {t.due_date && <p className={`text-xs ${isOverdue(t.due_date) && !t.completed ? 'text-red-400' : 'text-gray-500'}`}>{t.due_date}</p>}
                  </div>
                  <PriorityBadge priority={t.priority} />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Log activity */}
      <div className="bg-gray-900 rounded-2xl border border-gray-800 p-5 mt-6">
        <h2 className="text-white font-semibold text-sm mb-3">Log Activity</h2>
        <div className="flex gap-2 mb-2">
          {['call', 'email', 'meeting', 'note'].map(type => (
            <button
              key={type}
              onClick={() => setLogActivity(type)}
              className={`px-3 py-1 rounded-lg text-xs capitalize transition ${
                logActivity === type ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              {type}
            </button>
          ))}
        </div>
        {logActivity && (
          <div className="flex gap-2 mt-2">
            <input
              placeholder="Add a note..."
              value={logNote}
              onChange={e => setLogNote(e.target.value)}
              className="flex-1 bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
            />
            <button
              onClick={handleLogActivity}
              disabled={logging}
              className="bg-brand text-white px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
            >
              {logging ? 'Saving...' : 'Log'}
            </button>
          </div>
        )}
      </div>

      {/* Activity timeline */}
      <div className="bg-gray-900 rounded-2xl border border-gray-800 p-5 mt-6">
        <h2 className="text-white font-semibold text-sm mb-3">Activity History</h2>
        <ActivityTimeline activities={contact.activity || []} />
      </div>

      {showEdit && <ContactForm contact={contact} onClose={() => setShowEdit(false)} onSaved={() => { setShowEdit(false); load(); }} />}
      {showAddDeal && <DealForm contactId={contact.id} onClose={() => setShowAddDeal(false)} onSaved={() => { setShowAddDeal(false); load(); }} />}
      {showAddTask && <TaskForm contactId={contact.id} onClose={() => setShowAddTask(false)} onSaved={() => { setShowAddTask(false); load(); }} />}
    </div>
  );
}

function PriorityBadge({ priority }: { priority: string }) {
  const colors: Record<string, string> = {
    high: 'text-red-400', medium: 'text-yellow-400', low: 'text-gray-500',
  };
  return <span className={`text-xs ${colors[priority] || 'text-gray-500'}`}>{priority}</span>;
}

function isOverdue(date: string): boolean {
  if (!date) return false;
  return new Date(date) < new Date(new Date().toISOString().split('T')[0]);
}
