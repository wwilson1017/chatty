import {
  LineChart,
  AreaChart,
  Line,
  Area,
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
  variant?: 'line' | 'area';
}

export default function LineChartSection({ data, options, variant = 'line' }: Props) {
  const chartData = toRechartsData(data);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const formatter = (value: any) => formatValue(value, options);

  const tooltipStyle = {
    backgroundColor: '#1f2937',
    border: '1px solid #374151',
    borderRadius: '8px',
    color: '#f3f4f6',
  };

  if (variant === 'area') {
    return (
      <ResponsiveContainer width="100%" height={300}>
        <AreaChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#9ca3af' }} />
          <YAxis tickFormatter={formatter} tick={{ fontSize: 12, fill: '#9ca3af' }} />
          <Tooltip
            formatter={formatter}
            contentStyle={tooltipStyle}
            labelStyle={{ color: '#d1d5db' }}
            itemStyle={{ color: '#e5e7eb' }}
          />
          {(options?.show_legend !== false && data.datasets.length > 1) && (
            <Legend wrapperStyle={{ color: '#d1d5db' }} />
          )}
          {data.datasets.map((ds, i) => (
            <Area
              key={ds.label}
              type="monotone"
              dataKey={ds.label}
              stroke={ds.color || DEFAULT_COLORS[i % DEFAULT_COLORS.length]}
              fill={ds.color || DEFAULT_COLORS[i % DEFAULT_COLORS.length]}
              fillOpacity={0.15}
              strokeWidth={2}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
        <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#9ca3af' }} />
        <YAxis tickFormatter={formatter} tick={{ fontSize: 12, fill: '#9ca3af' }} />
        <Tooltip
          formatter={formatter}
          contentStyle={tooltipStyle}
          labelStyle={{ color: '#d1d5db' }}
          itemStyle={{ color: '#e5e7eb' }}
        />
        {(options?.show_legend !== false && data.datasets.length > 1) && (
          <Legend wrapperStyle={{ color: '#d1d5db' }} />
        )}
        {data.datasets.map((ds, i) => (
          <Line
            key={ds.label}
            type="monotone"
            dataKey={ds.label}
            stroke={ds.color || DEFAULT_COLORS[i % DEFAULT_COLORS.length]}
            strokeWidth={2}
            dot={{ r: 3 }}
            activeDot={{ r: 5 }}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
