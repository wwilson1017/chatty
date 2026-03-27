import { useRef, useCallback, useState } from 'react';
import type { ReportSection, ChartData, TableData, MetricData } from './types';
import BarChartSection from './components/BarChartSection';
import LineChartSection from './components/LineChartSection';
import PieChartSection from './components/PieChartSection';
import TableSection from './components/TableSection';
import MetricSection from './components/MetricSection';

interface Props {
  report: { title: string; subtitle?: string; sections: ReportSection[] | unknown[] };
  compact?: boolean;
}

function renderSection(section: ReportSection) {
  switch (section.chart_type) {
    case 'bar':
      return <BarChartSection data={section.data as ChartData} options={section.options} variant="vertical" />;
    case 'horizontal_bar':
      return <BarChartSection data={section.data as ChartData} options={section.options} variant="horizontal" />;
    case 'stacked_bar':
      return <BarChartSection data={section.data as ChartData} options={section.options} variant="stacked" />;
    case 'grouped_bar':
      return <BarChartSection data={section.data as ChartData} options={section.options} variant="grouped" />;
    case 'line':
      return <LineChartSection data={section.data as ChartData} options={section.options} variant="line" />;
    case 'area':
      return <LineChartSection data={section.data as ChartData} options={section.options} variant="area" />;
    case 'pie':
      return <PieChartSection data={section.data as ChartData} options={section.options} variant="pie" />;
    case 'donut':
      return <PieChartSection data={section.data as ChartData} options={section.options} variant="donut" />;
    case 'table':
      return <TableSection data={section.data as TableData} options={section.options} title={section.title} />;
    case 'metric':
      return <MetricSection data={section.data as MetricData} options={section.options} />;
    default:
      return <p className="text-sm text-gray-500">Unsupported chart type: {section.chart_type}</p>;
  }
}

export default function ReportRenderer({ report, compact }: Props) {
  const reportRef = useRef<HTMLDivElement>(null);
  const [downloading, setDownloading] = useState(false);

  const handleDownloadPdf = useCallback(async () => {
    if (!reportRef.current || downloading) return;
    setDownloading(true);
    try {
      const html2pdf = (await import('html2pdf.js')).default;
      const filename = report.title.replace(/[^a-zA-Z0-9 _-]/g, '').replace(/\s+/g, '_') || 'report';
      await html2pdf()
        .set({
          margin: [10, 10, 10, 10],
          filename: `${filename}.pdf`,
          image: { type: 'jpeg', quality: 0.95 },
          html2canvas: { scale: 2, useCORS: true },
          jsPDF: { unit: 'mm', format: 'a4', orientation: 'landscape' },
        })
        .from(reportRef.current)
        .save();
    } catch (err) {
      console.error('PDF download failed:', err);
    } finally {
      setDownloading(false);
    }
  }, [report.title, downloading]);

  return (
    <div className={`bg-gray-900 rounded-xl border border-gray-700 shadow-sm overflow-hidden ${compact ? '' : 'my-3'}`}>
      <div className="px-4 py-3 border-b border-gray-700 flex items-start justify-between">
        <div>
          <h3 className="text-sm font-bold text-white">{report.title}</h3>
          {report.subtitle && (
            <p className="text-xs text-gray-400 mt-0.5">{report.subtitle}</p>
          )}
        </div>
        <button
          onClick={handleDownloadPdf}
          disabled={downloading}
          className="ml-2 p-1.5 text-gray-500 hover:text-white transition-colors rounded-lg hover:bg-gray-800 disabled:opacity-50"
          title="Download PDF"
        >
          {downloading ? (
            <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : (
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
            </svg>
          )}
        </button>
      </div>
      <div ref={reportRef} className="p-4 space-y-4">
        {(report.sections as ReportSection[]).map((section, i) => (
          <div key={i}>
            {section.title && (
              <h4 className="text-xs font-semibold text-gray-300 mb-2 uppercase tracking-wider">
                {section.title}
              </h4>
            )}
            {renderSection(section)}
          </div>
        ))}
      </div>
    </div>
  );
}
