export interface Report {
  id: string;
  title: string;
  subtitle?: string;
  sections: ReportSection[];
  created_at: string;
}

export interface ReportSection {
  chart_type: ChartType;
  title?: string;
  data: ChartData | TableData | MetricData;
  options?: ReportOptions;
}

export type ChartType =
  | 'bar'
  | 'horizontal_bar'
  | 'stacked_bar'
  | 'grouped_bar'
  | 'line'
  | 'area'
  | 'pie'
  | 'donut'
  | 'table'
  | 'metric';

export interface ChartData {
  labels: string[];
  datasets: Dataset[];
}

export interface Dataset {
  label: string;
  values: number[];
  color?: string;
}

export interface TableData {
  headers: string[];
  rows: (string | number)[][];
}

export interface MetricData {
  metrics: MetricItem[];
}

export interface MetricItem {
  label: string;
  value: number | string;
  change?: string;
  color?: string;
}

export interface ReportOptions {
  currency?: boolean;
  percentage?: boolean;
  stacked?: boolean;
  show_legend?: boolean;
}

export interface ReportSummary {
  id: string;
  title: string;
  subtitle?: string;
  section_count: number;
  created_at: string;
}
