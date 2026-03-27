import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { api } from '../../core/api/client';
import type { Report, ReportSummary } from './types';
import ReportRenderer from './ReportRenderer';

interface ReportsPanelProps {
  apiPrefix: string;
}

export default function ReportsPanel({ apiPrefix }: ReportsPanelProps) {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedReport, setExpandedReport] = useState<Report | null>(null);
  const [loadingReport, setLoadingReport] = useState(false);
  const [search, setSearch] = useState('');

  const loadReports = useCallback(async () => {
    try {
      const data = await api<{ reports: ReportSummary[] }>(`${apiPrefix}/reports`);
      setReports(data.reports);
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  }, [apiPrefix]);

  useEffect(() => {
    loadReports();
  }, [loadReports]);

  const expandIdRef = useRef<string | null>(null);

  const handleExpand = async (id: string) => {
    if (expandedId === id) {
      setExpandedId(null);
      setExpandedReport(null);
      expandIdRef.current = null;
      return;
    }
    setExpandedId(id);
    expandIdRef.current = id;
    setLoadingReport(true);
    try {
      const report = await api<Report>(`${apiPrefix}/reports/${id}`);
      // Guard against stale responses from rapid clicks
      if (expandIdRef.current === id) {
        setExpandedReport(report);
      }
    } catch {
      if (expandIdRef.current === id) {
        setExpandedReport(null);
      }
    } finally {
      if (expandIdRef.current === id) {
        setLoadingReport(false);
      }
    }
  };

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Delete this report?')) return;
    try {
      await api(`${apiPrefix}/reports/${id}`, { method: 'DELETE' });
      setReports(prev => prev.filter(r => r.id !== id));
      if (expandedId === id) {
        setExpandedId(null);
        setExpandedReport(null);
      }
    } catch {
      // silently fail
    }
  };

  const formatDate = (iso: string) => {
    try {
      return new Date(iso).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      });
    } catch {
      return iso;
    }
  };

  const filtered = useMemo(() => {
    if (!search.trim()) return reports;
    const q = search.toLowerCase();
    return reports.filter(
      r => r.title.toLowerCase().includes(q) || (r.subtitle || '').toLowerCase().includes(q)
    );
  }, [reports, search]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 text-sm">
        Loading reports...
      </div>
    );
  }

  if (reports.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-400 px-6">
        <svg className="w-12 h-12 mb-3 opacity-30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        <p className="text-sm font-medium text-gray-300">No reports yet</p>
        <p className="text-xs mt-1 text-gray-500">Ask the agent to create one!</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4">
      {/* Search */}
      {reports.length > 1 && (
        <div className="mb-3">
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search reports..."
            className="w-full px-3 py-2 text-sm border border-gray-700 rounded-lg bg-gray-800 text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
          />
        </div>
      )}
      <div className="space-y-2">
        {filtered.map(r => (
          <div key={r.id}>
            <button
              onClick={() => handleExpand(r.id)}
              className={`w-full text-left px-4 py-3 rounded-xl border transition-colors ${
                expandedId === r.id
                  ? 'border-indigo-500/40 bg-gray-800 shadow-sm'
                  : 'border-gray-700 bg-gray-800/60 hover:border-gray-600 hover:bg-gray-800'
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-semibold text-white truncate">
                    {r.title}
                  </h3>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-xs text-gray-400">{formatDate(r.created_at)}</span>
                    <span className="text-xs text-gray-500">
                      {r.section_count} section{r.section_count !== 1 ? 's' : ''}
                    </span>
                  </div>
                </div>
                <button
                  onClick={(e) => handleDelete(r.id, e)}
                  className="ml-2 p-1 text-gray-600 hover:text-red-400 transition-colors"
                  title="Delete report"
                >
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </button>
            {expandedId === r.id && (
              <div className="mt-2 mb-2">
                {loadingReport ? (
                  <div className="text-center py-6 text-gray-400 text-sm">Loading report...</div>
                ) : expandedReport ? (
                  <ReportRenderer report={expandedReport} />
                ) : (
                  <div className="text-center py-6 text-gray-500 text-sm">Failed to load report</div>
                )}
              </div>
            )}
          </div>
        ))}
        {filtered.length === 0 && search.trim() && (
          <div className="text-center py-8 text-gray-500 text-sm">
            No reports matching &quot;{search}&quot;
          </div>
        )}
      </div>
    </div>
  );
}
