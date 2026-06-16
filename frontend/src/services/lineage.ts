import api from './api';

export interface LineageGraphNode {
  id: string;
  name: string;
  type: 'table' | 'system' | 'transformation';
  system: string | null;
  table_name: string | null;
  metadata: Record<string, unknown> | null;
}

export interface LineageGraphEdge {
  source_id: string;
  target_id: string;
  pipeline_name: string | null;
  last_execution: string | null;
}

export interface LineageGraph {
  nodes: LineageGraphNode[];
  edges: LineageGraphEdge[];
  table_name: string;
  depth: number;
  message: string | null;
}

export interface LineageNodeMetadata {
  node_id: string;
  last_execution: string | null;
  row_count: number | null;
  triggered_by_user: string | null;
  total_executions: number;
  message: string | null;
}

export interface LineageEvent {
  id: string;
  pipeline_id: string;
  execution_id: string;
  source_system: string;
  source_table: string;
  destination_system: string;
  destination_table: string;
  transformation_node: string | null;
  triggered_by: string;
  timestamp: string;
}

/**
 * Fetch the lineage graph for a specific table.
 * @param tableName - The table to query lineage for
 * @param depth - Traversal depth (1-10), defaults to 10
 */
export async function getLineageGraph(
  tableName: string,
  depth: number = 10
): Promise<LineageGraph> {
  const response = await api.get<LineageGraph>(
    `/lineage/graph/${encodeURIComponent(tableName)}`,
    { params: { depth } }
  );
  return response.data;
}

/**
 * Get metadata for a specific lineage node.
 * @param nodeId - The node identifier (e.g., "system.table")
 */
export async function getNodeMetadata(
  nodeId: string
): Promise<LineageNodeMetadata> {
  const response = await api.get<LineageNodeMetadata>(
    `/lineage/node/${encodeURIComponent(nodeId)}`
  );
  return response.data;
}

/**
 * Query lineage events within a time range.
 * @param start - Start of time range (ISO 8601)
 * @param end - End of time range (ISO 8601)
 */
export async function queryLineageByTimeRange(
  start: string,
  end: string
): Promise<LineageEvent[]> {
  const response = await api.get<LineageEvent[]>('/lineage/query', {
    params: { start, end },
  });
  return response.data;
}
