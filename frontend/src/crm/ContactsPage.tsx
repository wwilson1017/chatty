import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import type { CrmContact } from '../core/types';
import { ContactForm } from './components/ContactForm';
import { SmartImportModal } from './components/SmartImportModal';

const STATUS_TABS = ['all', 'active', 'inactive', 'archived'] as const;

export function ContactsPage() {
  const [contacts, setContacts] = useState<CrmContact[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<string>('all');
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (search) params.set('q', search);
    if (status !== 'all') params.set('status', status);
    params.set('limit', '100');
    const data = await api<{ contacts: CrmContact[]; total: number }>(`/api/crm/contacts?${params}`);
    setContacts(data.contacts);
    setTotal(data.total);
    setLoading(false);
  }, [search, status]);

  useEffect(() => {
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, search]);

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Contacts</h1>
        <div className="flex gap-2">
          <button
            onClick={() => setShowImport(true)}
            className="bg-gray-800 text-gray-300 px-4 py-2 rounded-lg text-sm hover:bg-gray-700 transition"
          >
            Import Contacts
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="bg-brand text-white font-medium px-4 py-2 rounded-lg text-sm hover:opacity-90 transition"
          >
            + Add Contact
          </button>
        </div>
      </div>

      {/* Search + filter */}
      <div className="flex gap-3 mb-6">
        <input
          type="text"
          placeholder="Search contacts..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="flex-1 bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-indigo-500"
        />
        <div className="flex bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
          {STATUS_TABS.map(tab => (
            <button
              key={tab}
              onClick={() => setStatus(tab)}
              className={`px-3 py-2 text-xs font-medium capitalize transition ${
                status === tab ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-white'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : contacts.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-gray-500">
            {search ? 'No contacts match your search.' : 'No contacts yet. Add your first one!'}
          </p>
        </div>
      ) : (
        <>
          <p className="text-gray-500 text-xs mb-3">{total} contact{total !== 1 ? 's' : ''}</p>
          <div className="bg-gray-900 rounded-2xl border border-gray-800 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-800 text-xs text-gray-500 uppercase tracking-wide">
                  <th className="text-left px-4 py-3">Name</th>
                  <th className="text-left px-4 py-3">Company</th>
                  <th className="text-left px-4 py-3">Email</th>
                  <th className="text-left px-4 py-3">Phone</th>
                  <th className="text-left px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {contacts.map(c => (
                  <tr
                    key={c.id}
                    onClick={() => navigate(`/crm/contacts/${c.id}`)}
                    className="border-b border-gray-800/50 hover:bg-gray-800/50 cursor-pointer transition"
                  >
                    <td className="px-4 py-3">
                      <p className="text-white text-sm">{c.name}</p>
                      {c.title && <p className="text-gray-500 text-xs">{c.title}</p>}
                    </td>
                    <td className="px-4 py-3 text-gray-300 text-sm">{c.company || '—'}</td>
                    <td className="px-4 py-3 text-gray-300 text-sm">{c.email || '—'}</td>
                    <td className="px-4 py-3 text-gray-300 text-sm">{c.phone || '—'}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={c.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {showCreate && (
        <ContactForm
          onClose={() => setShowCreate(false)}
          onSaved={() => { setShowCreate(false); load(); }}
        />
      )}

      {showImport && (
        <SmartImportModal
          onClose={() => setShowImport(false)}
          onImported={() => { setShowImport(false); load(); }}
        />
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    active: 'bg-green-900/50 text-green-400',
    inactive: 'bg-gray-700/50 text-gray-400',
    archived: 'bg-red-900/50 text-red-400',
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full capitalize ${colors[status] || 'bg-gray-700 text-gray-400'}`}>
      {status}
    </span>
  );
}
