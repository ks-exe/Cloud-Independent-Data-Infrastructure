import api from './api';
import { PaginatedResponse } from '../types/api';

export type AuditEventType =
  | 'USER_LOGIN'
  | 'USER_LOGOUT'
  | 'USER_CREATE'
  | 'USER_UPDATE'
  | 'USER_DELETE'
  | 'CONNECTOR_CREATE'
  | 'CONNECTOR_UPDATE'
  | 'CONNECTOR_DELETE'
  | 'PIPELINE_CREATE'
  | 'PIPELINE_EXECUTE'
  | 'PIPELINE_DELETE'
  | 'SCHEDULE_CREATE'
  | 'SCHEDULE_UPDATE'
  | 'SETTINGS_UPDATE'
  | 'KEY_ROTATION';

export type AuditResult = 'success' | 'failure' | 'denied';

export interface AuditLog {
  id: string;
  event_type: AuditEventType;
  actor_id: string;
  actor_username?: string;
  target_resource_id: string;
  target_resource_type: string;
  result: AuditResult;
  ip_address: string;
  timestamp: string;
}

export interface AuditFilter {
  event_type?: AuditEventType;
  user?: string;
  start_date?: string;
  end_date?: string;
  result?: AuditResult;
}

export type ExportFormat = 'csv' | 'json';

export const auditService = {
  async search(
    filters: AuditFilter,
    page = 1,
    pageSize = 100
  ): Promise<PaginatedResponse<AuditLog>> {
    const response = await api.get<PaginatedResponse<AuditLog>>('/audit', {
      params: {
        ...filters,
        page,
        page_size: pageSize,
      },
    });
    return response.data;
  },

  async export(filters: AuditFilter, format: ExportFormat): Promise<Blob> {
    const response = await api.get(`/audit/export`, {
      params: { ...filters, format },
      responseType: 'blob',
    });
    return response.data;
  },
};
