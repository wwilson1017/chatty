import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import type { ChartData, ReportOptions } from '../types';
import { DEFAULT_COLORS, formatValue } from '../chartUtils';

interface Props {
  data: ChartData;
  options?: ReportOptions;
  variant?: 'pie' | 'donut';
}

export default function PieChartSection({ data, options, variant = 'pie' }: Props) {
  // For pie/donut, use first dataset
  const dataset = data.datasets[0];
  if (!dataset) return null;

  const chartData = data.labels.map((label, i) => ({
    name: label,
    value: dataset.values[i] ?? 0,
  }));

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const formatter = (value: any) => formatValue(value, options);
  const innerRadius = variant === 'donut' ? '55%' : 0;

  return (
    <ResponsiveContainer width="100%" height={300}>
      <PieChart>
        <Pie
          data={chartData}
          cx="50%"
          cy="50%"
          innerRadius={innerRadius}
          outerRadius="80%"
          paddingAngle={2}
          dataKey="value"
          label={({ name, percent }: { name?: string; percent?: number }) =>
            `${name ?? ''} ${((percent ?? 0) * 100).toFixed(0)}%`
          }
          labelLine={{ strokeWidth: 1, stroke: '#6b7280' }}
        >
          {chartData.map((_entry, i) => (
            <Cell
              key={`cell-${i}`}
              fill={DEFAULT_COLORS[i % DEFAULT_COLORS.length]}
            />
          ))}
        </Pie>
        <Tooltip
          formatter={formatter}
          contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', color: '#f3f4f6' }}
          itemStyle={{ color: '#e5e7eb' }}
        />
        {options?.show_legend !== false && (
          <Legend wrapperStyle={{ color: '#d1d5db' }} />
        )}
      </PieChart>
    </ResponsiveContainer>
  );
}
