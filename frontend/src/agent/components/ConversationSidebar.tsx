/**
 * Chatty — ConversationSidebar.
 * Collapsible sidebar with conversation list and search.
 */

import { useState, useRef, useCallback } from 'react';
import type { Conversation } from '../hooks/useConversations';

interface Props {
  agentName: string;
  conversations: Conversation[];
  activeId: string | null;
  searchQuery: string;
  searchResults: { id: string; title: string; snippet: string }[];
  isSearching: boolean;
  onNew: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onSearch: (q: string) => void;
  onRename: (id: string, title: string) => void;
}

export function ConversationSidebar({
  agentName, conversations, activeId, searchQuery, searchResults, isSearching,
  onNew, onSelect, onDelete, onSearch, onRename,
}: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [localQuery, setLocalQuery] = useState(searchQuery);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const handleSearchChange = useCallback((value: string) => {
    setLocalQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      onSearch(value);
    }, 300);
  }, [onSearch]);

  function startEdit(conv: Conversation, e: React.MouseEvent) {
    e.stopPropagation();
    setEditingId(conv.id);
    setEditTitle(conv.title);
  }

  function commitEdit(id: string) {
    if (editTitle.trim()) onRename(id, editTitle.trim());
    setEditingId(null);
  }

  const displayList = searchQuery.trim() ? searchResults : conversations;

  if (collapsed) {
    return (
      <div className="w-12 flex flex-col items-center py-4 border-r border-gray-800 bg-gray-950">
        <button onClick={() => setCollapsed(false)} className="text-gray-400 hover:text-white transition p-2 rounded-lg hover:bg-gray-800" title="Expand">
          ▶
        </button>
        <button onClick={onNew} className="mt-3 text-indigo-400 hover:text-white transition p-2 rounded-lg hover:bg-gray-800" title="New chat">
          ✎
        </button>
      </div>
    );
  }

  return (
    <div className="w-72 flex flex-col border-r border-gray-800 bg-gray-950">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <span className="text-white font-semibold text-sm truncate">{agentName}</span>
        <button onClick={() => setCollapsed(true)} className="text-gray-500 hover:text-white transition p-1 rounded" title="Collapse">
          ◀
        </button>
      </div>

      {/* Search */}
      <div className="px-3 py-2">
        <input
          value={localQuery}
          onChange={e => handleSearchChange(e.target.value)}
          placeholder="Search conversations..."
          className="w-full bg-gray-800 border border-gray-700 text-sm text-white rounded-lg px-3 py-2 focus:outline-none focus:border-indigo-500"
        />
      </div>

      {/* New chat button */}
      <button
        onClick={onNew}
        className="mx-3 mb-2 py-2 text-sm text-center rounded-lg border border-dashed border-gray-700 text-gray-400 hover:border-indigo-500 hover:text-indigo-400 transition"
      >
        + New chat
      </button>

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto">
        {isSearching ? (
          <div className="flex justify-center py-4">
            <div className="w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : displayList.length === 0 ? (
          <p className="text-gray-600 text-xs text-center py-6 px-4">
            {searchQuery ? 'No results found' : 'No conversations yet'}
          </p>
        ) : (
          displayList.map((item: Conversation | { id: string; title: string; snippet?: string }) => {
            const id = item.id;
            const title = item.title || 'New conversation';
            const snippet = 'snippet' in item ? item.snippet : undefined;
            const isActive = id === activeId;

            return (
              <div
                key={id}
                onClick={() => onSelect(id)}
                className={`group flex items-center justify-between px-3 py-2.5 cursor-pointer transition ${
                  isActive ? 'bg-indigo-900/30 border-l-2 border-indigo-500' : 'hover:bg-gray-800/50 border-l-2 border-transparent'
                }`}
              >
                <div className="flex-1 min-w-0">
                  {editingId === id ? (
                    <input
                      value={editTitle}
                      onChange={e => setEditTitle(e.target.value)}
                      onBlur={() => commitEdit(id)}
                      onKeyDown={e => { if (e.key === 'Enter') commitEdit(id); if (e.key === 'Escape') setEditingId(null); }}
                      onClick={e => e.stopPropagation()}
                      className="w-full bg-gray-700 text-white text-xs rounded px-2 py-1 focus:outline-none"
                      autoFocus
                    />
                  ) : (
                    <>
                      <p className="text-sm text-gray-200 truncate">{title}</p>
                      {snippet && <p className="text-xs text-gray-500 truncate mt-0.5">{snippet}</p>}
                    </>
                  )}
                </div>

                {!editingId && (
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition ml-2">
                    <button
                      onClick={e => startEdit(item as Conversation, e)}
                      className="text-gray-500 hover:text-gray-300 p-1 rounded transition text-xs"
                      title="Rename"
                    >✎</button>
                    <button
                      onClick={e => { e.stopPropagation(); onDelete(id); }}
                      className="text-gray-500 hover:text-red-400 p-1 rounded transition text-xs"
                      title="Delete"
                    >×</button>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
