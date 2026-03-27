import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import type { ChartData, ReportOptions } from '../types';
import { DEFAULT_COLORS, formatValue, toRechartsData } from '../chartUtils';

interface Props {
  data: ChartData;
  options?: ReportOptions;
  variant?: 'vertical' | 'horizontal' | 'stacked' | 'grouped';
}

export default function BarChartSection({ data, options, variant = 'vertical' }: Props) {
  const isHorizontal = variant === 'horizontal';
  const isStacked = variant === 'stacked' || options?.stacked;
  const chartData = toRechartsData(data);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const formatter = (value: any) => formatValue(value, options);

  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart
        data={chartData}
        layout={isHorizontal ? 'vertical' : 'horizontal'}
        margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
        {isHorizontal ? (
          <>
            <XAxis type="number" tickFormatter={formatter} tick={{ fontSize: 12, fill: '#9ca3af' }} />
            <YAxis dataKey="name" type="category" width={120} tick={{ fontSize: 12, fill: '#9ca3af' }} />
          </>
        ) : (
          <>
            <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#9ca3af' }} />
            <YAxis tickFormatter={formatter} tick={{ fontSize: 12, fill: '#9ca3af' }} />
          </>
        )}
        <Tooltip
          formatter={formatter}
          contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', color: '#f3f4f6' }}
          labelStyle={{ color: '#d1d5db' }}
          itemStyle={{ color: '#e5e7eb' }}
        />
        {(options?.show_legend !== false && data.datasets.length > 1) && (
          <Legend wrapperStyle={{ color: '#d1d5db' }} />
        )}
        {data.datasets.map((ds, i) => (
          <Bar
            key={ds.label}
            dataKey={ds.label}
            fill={ds.color || DEFAULT_COLORS[i % DEFAULT_COLORS.length]}
            stackId={isStacked ? 'stack' : undefined}
            radius={isStacked ? undefined : [2, 2, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
