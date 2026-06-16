import api from './api';

export interface ComponentHealthInfo {
  name: string;
  status: string;
  latency_ms: number;
  error: string | null;
}

export type HealthStatus = 'healthy' | 'degraded' | 'unhealthy';

export interface SystemHealth {
  status: HealthStatus;
  components: ComponentHealthInfo[];
  checked_at: string;
}

export interface DashboardMetrics {
  running_count: number;
  failed_24h: number;
  succeeded_24h: number;
  avg_execution_time_ms: number;
  queue_size: number;
  retry_count_24h: number;
  system_health: HealthStatus;
}

export interface LogEntry {
  id: string;
  timestamp: string;
  level: string;
  message: string;
  source: string;
  execution_id: string;
  node_id: string | null;
  metadata: Record<string, unknown> | null;
}

export interface LogQueryResponse {
  items: LogEntry[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  execution_id: string;
}

/**
 * Fetch dashboard metrics (running, failed, succeeded, avg time, queue, retries, health).
 */
export async function getDashboardMetrics(): Promise<DashboardMetrics> {
  const response = await api.get<DashboardMetrics>('/monitoring/dashboard');
  return response.data;
}

/**
 * Fetch detailed system health status with per-component breakdown.
 */
export async function getSystemHealth(): Promise<SystemHealth> {
  const response = await api.get<SystemHealth>('/monitoring/health');
  return response.data;
}

/**
 * Fetch execution logs with pagination (100 per page).
 */
export async function getExecutionLogs(
  executionId: string,
  page: number = 1
): Promise<LogQueryResponse> {
  const response = await api.get<LogQueryResponse>(
    `/monitoring/logs/${executionId}`,
    { params: { page } }
  );
  return response.data;
}
