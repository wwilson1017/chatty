import { useCallback } from 'react';
import type { TableData, ReportOptions } from '../types';
import { formatValue } from '../chartUtils';

interface Props {
  data: TableData;
  options?: ReportOptions;
  title?: string;
}

function escapeCsvCell(val: string | number): string {
  const s = String(val);
  if (s.includes(',') || s.includes('"') || s.includes('\n')) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

export default function TableSection({ data, options, title }: Props) {
  const isNumeric = (val: string | number) => typeof val === 'number';

  const formatCell = (val: string | number) => {
    if (typeof val === 'number') {
      return formatValue(val, options);
    }
    return val;
  };

  const handleExportCsv = useCallback(() => {
    const headerRow = data.headers.map(escapeCsvCell).join(',');
    const dataRows = data.rows.map(row => row.map(escapeCsvCell).join(','));
    const csv = [headerRow, ...dataRows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(title || 'table').replace(/[^a-zA-Z0-9 _-]/g, '').replace(/\s+/g, '_')}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [data, title]);

  return (
    <div className="overflow-x-auto">
      <div className="flex justify-end mb-1">
        <button
          onClick={handleExportCsv}
          className="flex items-center gap-1 px-2 py-1 text-xs text-gray-500 hover:text-white transition-colors rounded hover:bg-gray-800"
          title="Export CSV"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
          </svg>
          CSV
        </button>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b-2 border-gray-600">
            {data.headers.map((h, i) => (
              <th
                key={i}
                className="px-3 py-2 text-left font-semibold text-gray-300 text-xs uppercase tracking-wider"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, ri) => (
            <tr
              key={ri}
              className={`border-b border-gray-700 ${ri % 2 === 0 ? 'bg-gray-800/40' : 'bg-gray-800/80'}`}
            >
              {row.map((cell, ci) => (
                <td
                  key={ci}
                  className={`px-3 py-2 text-gray-200 ${isNumeric(cell) ? 'text-right tabular-nums' : 'text-left'}`}
                >
                  {formatCell(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
