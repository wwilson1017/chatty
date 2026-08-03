import { inputStyle } from '../../shared/styles';

interface Props {
  search: string;
  onSearch: (v: string) => void;
  /** Omit context/onContext to render a search-only bar (e.g. Projects). */
  context?: string;
  onContext?: (v: string) => void;
  contexts?: string[];
  isMobile: boolean;
  placeholder?: string;
}

/** Search box + optional context dropdown for client-side list filtering. */
export function ListFilterBar({
  search, onSearch, context, onContext, contexts = [], isMobile,
  placeholder = 'Search...',
}: Props) {
  return (
    <div style={{ display: 'flex', gap: 8, marginBottom: isMobile ? 16 : 24 }}>
      <input
        value={search}
        onChange={e => onSearch(e.target.value)}
        placeholder={placeholder}
        style={{ ...inputStyle, flex: 1, padding: '7px 12px' }}
      />
      {onContext && (
        <select
          value={context || ''}
          onChange={e => onContext(e.target.value)}
          style={{ ...inputStyle, width: 'auto', maxWidth: isMobile ? 140 : 200, padding: '7px 12px' }}
        >
          <option value="">All contexts</option>
          {contexts.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      )}
    </div>
  );
}
