import api from './api';

// ─── Types ───────────────────────────────────────────────────────────────────

export interface PipelineNode {
  id: string;
  node_type: 'source' | 'transform' | 'destination';
  node_subtype: string;
  config: Record<string, unknown>;
  position_x: number;
  position_y: number;
}

export interface PipelineEdge {
  id: string;
  source_node_id: string;
  target_node_id: string;
}

export interface PipelineDefinition {
  nodes: PipelineNode[];
  edges: PipelineEdge[];
}

export interface Pipeline {
  id: string;
  name: string;
  description: string;
  status: string;
  current_version: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface PipelineVersion {
  id: string;
  pipeline_id: string;
  version_number: number;
  definition_snapshot: PipelineDefinition;
  created_by: string;
  created_at: string;
}

export interface ValidationError {
  node_id?: string;
  edge_id?: string;
  message: string;
  error_code: string;
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationError[];
}

export interface PipelineCreate {
  name: string;
  description?: string;
  definition: PipelineDefinition;
}

export interface PipelineUpdate {
  name?: string;
  description?: string;
  definition?: PipelineDefinition;
}

export interface PipelineRun {
  id: string;
  pipeline_id: string;
  pipeline_version: number;
  status: string;
  trigger_type: string;
  triggered_by: string;
  retry_count: number;
  started_at: string;
  completed_at?: string;
  duration_ms?: number;
}

// ─── API Service ─────────────────────────────────────────────────────────────

const pipelineService = {
  // List all pipelines
  async list(): Promise<Pipeline[]> {
    const response = await api.get('/pipelines');
    return response.data;
  },

  // Get single pipeline
  async get(pipelineId: string): Promise<Pipeline> {
    const response = await api.get(`/pipelines/${pipelineId}`);
    return response.data;
  },

  // Create a new pipeline
  async create(data: PipelineCreate): Promise<Pipeline> {
    const response = await api.post('/pipelines', data);
    return response.data;
  },

  // Update pipeline
  async update(pipelineId: string, data: PipelineUpdate): Promise<Pipeline> {
    const response = await api.put(`/pipelines/${pipelineId}`, data);
    return response.data;
  },

  // Delete pipeline
  async delete(pipelineId: string): Promise<void> {
    await api.delete(`/pipelines/${pipelineId}`);
  },

  // Validate pipeline DAG
  async validate(definition: PipelineDefinition): Promise<ValidationResult> {
    const response = await api.post('/pipelines/validate', definition);
    return response.data;
  },

  // Execute pipeline
  async execute(pipelineId: string): Promise<PipelineRun> {
    const response = await api.post(`/pipelines/${pipelineId}/execute`);
    return response.data;
  },

  // Retry failed execution
  async retry(runId: string): Promise<PipelineRun> {
    const response = await api.post(`/pipelines/runs/${runId}/retry`);
    return response.data;
  },

  // Get execution status
  async getRunStatus(runId: string): Promise<PipelineRun> {
    const response = await api.get(`/pipelines/runs/${runId}`);
    return response.data;
  },

  // Get pipeline versions
  async getVersions(pipelineId: string): Promise<PipelineVersion[]> {
    const response = await api.get(`/pipelines/${pipelineId}/versions`);
    return response.data;
  },

  // Get specific version
  async getVersion(pipelineId: string, version: number): Promise<PipelineVersion> {
    const response = await api.get(`/pipelines/${pipelineId}/versions/${version}`);
    return response.data;
  },
};

export default pipelineService;
