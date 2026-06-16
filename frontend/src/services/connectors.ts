import api from './api';
import { PaginatedResponse } from '../types/api';

export type ConnectorType =
  | 'PostgreSQL'
  | 'MySQL'
  | 'MSSQL'
  | 'Oracle'
  | 'MongoDB'
  | 'S3'
  | 'HDFS'
  | 'SFTP'
  | 'REST_API'
  | 'Kafka';

export type ConnectorDirection = 'source' | 'destination' | 'bidirectional';

export type ConnectorStatus = 'active' | 'inactive' | 'error' | 'testing';

export interface Connector {
  id: string;
  name: string;
  type: ConnectorType;
  direction: ConnectorDirection;
  status: ConnectorStatus;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface ConnectorConfig {
  host: string;
  port: number;
  database_name?: string;
  username?: string;
  password?: string;
  extra_params?: Record<string, unknown>;
}

export interface CreateConnectorPayload {
  name: string;
  type: ConnectorType;
  direction: ConnectorDirection;
  config: ConnectorConfig;
}

export interface UpdateConnectorPayload {
  name?: string;
  direction?: ConnectorDirection;
  config?: Partial<ConnectorConfig>;
}

export interface ConnectionTestResult {
  success: boolean;
  message: string;
  latency_ms?: number;
}

export interface HealthStatus {
  connector_id: string;
  status: 'healthy' | 'unhealthy' | 'unknown';
  last_checked: string;
  message?: string;
}

export const connectorsService = {
  async list(page = 1, pageSize = 20): Promise<PaginatedResponse<Connector>> {
    const response = await api.get<PaginatedResponse<Connector>>('/connectors', {
      params: { page, page_size: pageSize },
    });
    return response.data;
  },

  async getById(connectorId: string): Promise<Connector> {
    const response = await api.get<Connector>(`/connectors/${connectorId}`);
    return response.data;
  },

  async create(payload: CreateConnectorPayload): Promise<Connector> {
    const response = await api.post<Connector>('/connectors', payload);
    return response.data;
  },

  async update(connectorId: string, payload: UpdateConnectorPayload): Promise<Connector> {
    const response = await api.patch<Connector>(`/connectors/${connectorId}`, payload);
    return response.data;
  },

  async delete(connectorId: string): Promise<void> {
    await api.delete(`/connectors/${connectorId}`);
  },

  async testConnection(connectorId: string): Promise<ConnectionTestResult> {
    const response = await api.post<ConnectionTestResult>(
      `/connectors/${connectorId}/test`
    );
    return response.data;
  },

  async healthCheck(connectorId: string): Promise<HealthStatus> {
    const response = await api.get<HealthStatus>(
      `/connectors/${connectorId}/health`
    );
    return response.data;
  },
};
