import type { ChartData, ReportOptions } from './types';

export const DEFAULT_COLORS = [
  '#6366f1', '#3b82f6', '#10b981', '#f59e0b', '#a855f7', '#14b8a6',
  '#ef4444', '#0ea5e9', '#22c55e', '#eab308', '#8b5cf6', '#06b6d4',
];

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function formatValue(value: any, options?: ReportOptions): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (typeof value !== 'number') return String(value);

  if (options?.percentage) {
    return `${value.toFixed(1)}%`;
  }
  if (options?.currency) {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  }
  if (Math.abs(value) >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`;
  }
  if (Math.abs(value) >= 1_000) {
    return `${(value / 1_000).toFixed(1)}K`;
  }
  return value.toLocaleString('en-US');
}

/**
 * Transform ChartData into the flat record format Recharts expects:
 * [{name: "Jan", "Revenue": 100, "Expenses": 80}, ...]
 */
export function toRechartsData(data: ChartData): Record<string, string | number>[] {
  return data.labels.map((label, i) => {
    const point: Record<string, string | number> = { name: label };
    data.datasets.forEach((ds) => {
      point[ds.label] = ds.values[i] ?? 0;
    });
    return point;
  });
}
