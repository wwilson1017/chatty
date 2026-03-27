import type { MetricData, ReportOptions } from '../types';
import { formatValue } from '../chartUtils';

interface Props {
  data: MetricData;
  options?: ReportOptions;
}

export default function MetricSection({ data, options }: Props) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
      {data.metrics.map((metric, i) => {
        const isPositive = metric.change?.startsWith('+') || metric.change?.startsWith('\u2191');
        const isNegative = metric.change?.startsWith('-') || metric.change?.startsWith('\u2193');

        return (
          <div
            key={i}
            className="bg-gray-800 rounded-xl border border-gray-700 p-4"
          >
            <p className="text-xs text-gray-400 font-medium uppercase tracking-wider mb-1">
              {metric.label}
            </p>
            <p
              className="text-xl font-bold tabular-nums"
              style={{ color: metric.color || '#f3f4f6' }}
            >
              {typeof metric.value === 'number'
                ? formatValue(metric.value, options)
                : metric.value}
            </p>
            {metric.change && (
              <p
                className={`text-xs mt-1 font-medium ${
                  isPositive
                    ? 'text-emerald-400'
                    : isNegative
                    ? 'text-red-400'
                    : 'text-gray-500'
                }`}
              >
                {metric.change}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
