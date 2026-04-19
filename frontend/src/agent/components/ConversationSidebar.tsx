import { useState, useRef, useCallback } from 'react';
import type { Conversation } from '../hooks/useConversations';
import { AgentMark } from '../../shared/AgentMark';
import { IconPlus } from '../../shared/icons';

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

const mono = (size: number, color = 'rgba(237,240,244,0.38)') => ({
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: size, letterSpacing: '0.16em',
  textTransform: 'uppercase' as const, color,
});

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
    debounceRef.current = setTimeout(() => onSearch(value), 300);
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
  const letter = agentName.charAt(0);

  if (collapsed) {
    return (
      <div style={{
        width: 48, display: 'flex', flexDirection: 'column', alignItems: 'center',
        paddingTop: 16, borderRight: '1px solid rgba(230,235,242,0.07)',
      }}>
        <div onClick={() => setCollapsed(false)} style={{ cursor: 'pointer', color: 'rgba(237,240,244,0.62)', padding: 8 }}>▶</div>
        <div onClick={onNew} style={{ cursor: 'pointer', marginTop: 8 }}>
          <IconPlus size={16} className="text-ch-ink-mute" />
        </div>
      </div>
    );
  }

  return (
    <div style={{
      width: 240, display: 'flex', flexDirection: 'column',
      borderRight: '1px solid rgba(230,235,242,0.07)',
      position: 'relative', zIndex: 2,
    }}>
      {/* Agent header */}
      <div style={{
        padding: '14px 16px', display: 'flex', alignItems: 'center', gap: 12,
        borderBottom: '1px solid rgba(230,235,242,0.07)',
      }}>
        <AgentMark letter={letter} size={36} />
        <div style={{ flex: 1 }}>
          <div style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 17, letterSpacing: '-0.01em', color: '#EDF0F4',
          }}>{agentName}</div>
        </div>
        <div onClick={() => setCollapsed(true)} style={{
          cursor: 'pointer', color: 'rgba(237,240,244,0.38)', fontSize: 12,
        }}>◀</div>
      </div>

      {/* Search */}
      <div style={{ padding: '10px 14px 4px' }}>
        <input
          value={localQuery}
          onChange={e => handleSearchChange(e.target.value)}
          placeholder="Search..."
          style={{
            width: '100%', boxSizing: 'border-box',
            background: 'rgba(34,40,48,0.55)',
            border: '1px solid rgba(230,235,242,0.07)',
            color: '#EDF0F4', borderRadius: 4,
            padding: '6px 10px', fontSize: 12,
            outline: 'none',
            fontFamily: "'Inter Tight', system-ui, sans-serif",
          }}
          onFocus={e => { e.target.style.borderColor = 'rgba(230,235,242,0.14)'; }}
          onBlur={e => { e.target.style.borderColor = 'rgba(230,235,242,0.07)'; }}
        />
      </div>

      {/* New chat */}
      <div
        onClick={onNew}
        style={{
          margin: '6px 14px 8px', padding: '7px 0',
          textAlign: 'center', fontSize: 12,
          border: '1px dashed rgba(230,235,242,0.14)',
          borderRadius: 4, color: 'rgba(237,240,244,0.62)',
          cursor: 'pointer',
        }}
      >
        + New chat
      </div>

      {/* Section label */}
      <div style={{ padding: '8px 14px 4px', ...mono(9, 'rgba(237,240,244,0.38)') }}>Today</div>

      {/* Conversation list */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {isSearching ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 16 }}>
            <div className="w-4 h-4 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
          </div>
        ) : displayList.length === 0 ? (
          <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 12, textAlign: 'center', padding: '24px 16px' }}>
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
                style={{
                  padding: '9px 14px', cursor: 'pointer',
                  background: isActive ? 'rgba(200,209,217,0.12)' : 'transparent',
                  borderLeft: isActive ? '2px solid var(--color-ch-accent, #C8D1D9)' : '2px solid transparent',
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                }}
                className="group"
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  {editingId === id ? (
                    <input
                      value={editTitle}
                      onChange={e => setEditTitle(e.target.value)}
                      onBlur={() => commitEdit(id)}
                      onKeyDown={e => { if (e.key === 'Enter') commitEdit(id); if (e.key === 'Escape') setEditingId(null); }}
                      onClick={e => e.stopPropagation()}
                      style={{
                        width: '100%', background: 'rgba(34,40,48,0.55)',
                        color: '#EDF0F4', fontSize: 12, borderRadius: 3,
                        padding: '2px 6px', border: '1px solid rgba(230,235,242,0.14)',
                        outline: 'none',
                      }}
                      autoFocus
                    />
                  ) : (
                    <>
                      <div style={{
                        fontSize: 13, lineHeight: 1.3,
                        color: isActive ? '#EDF0F4' : 'rgba(237,240,244,0.62)',
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        display: 'flex', alignItems: 'center', gap: 6,
                      }}>
                        {('source' in item && (item as Conversation).source) && (
                          <span style={{
                            fontSize: 9, fontWeight: 600, letterSpacing: '0.05em',
                            textTransform: 'uppercase',
                            padding: '1px 5px', borderRadius: 3,
                            flexShrink: 0,
                            ...((item as Conversation).source === 'telegram'
                              ? { background: 'rgba(0,136,204,0.15)', color: '#0088cc' }
                              : { background: 'rgba(37,211,102,0.15)', color: '#25D366' }),
                          }}>
                            {(item as Conversation).source === 'telegram' ? 'TG' : 'WA'}
                          </span>
                        )}
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {title}
                        </span>
                      </div>
                      {snippet && (
                        <div style={{
                          fontSize: 11, color: 'rgba(237,240,244,0.38)',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                          marginTop: 2,
                        }}>{snippet}</div>
                      )}
                    </>
                  )}
                </div>

                {!editingId && (
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition" style={{ marginLeft: 8 }}>
                    <button
                      onClick={e => startEdit(item as Conversation, e)}
                      style={{
                        background: 'none', border: 'none',
                        color: 'rgba(237,240,244,0.38)', fontSize: 12,
                        cursor: 'pointer', padding: '2px 4px',
                      }}
                    >✎</button>
                    <button
                      onClick={e => { e.stopPropagation(); onDelete(id); }}
                      style={{
                        background: 'none', border: 'none',
                        color: 'rgba(237,240,244,0.38)', fontSize: 12,
                        cursor: 'pointer', padding: '2px 4px',
                      }}
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
