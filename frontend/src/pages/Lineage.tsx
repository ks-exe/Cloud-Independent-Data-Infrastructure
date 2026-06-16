import { useState, useCallback } from 'react';
import {
  Box,
  Typography,
  TextField,
  InputAdornment,
  Alert,
  Paper,
  Stack,
  Chip,
  CircularProgress,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import LineageGraph from '../components/lineage/LineageGraph';
import NodeDetails from '../components/lineage/NodeDetails';
import TimeRangeFilter from '../components/lineage/TimeRangeFilter';
import {
  getLineageGraph,
  getNodeMetadata,
  queryLineageByTimeRange,
  type LineageGraph as LineageGraphType,
  type LineageNodeMetadata,
} from '../services/lineage';

/**
 * Data Lineage page.
 * Provides table search, D3.js directed graph visualization,
 * node metadata panel, and time-range filtering.
 *
 * Requirements: 9.2, 9.3, 9.4, 9.6, 9.7
 */
export default function Lineage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [graph, setGraph] = useState<LineageGraphType | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [nodeMetadata, setNodeMetadata] = useState<LineageNodeMetadata | null>(null);
  const [metadataLoading, setMetadataLoading] = useState(false);

  const [timeFilterActive, setTimeFilterActive] = useState(false);

  /** Search lineage graph for a specific table */
  const handleSearch = useCallback(async () => {
    const tableName = searchQuery.trim();
    if (!tableName) return;

    setLoading(true);
    setError(null);
    setSelectedNodeId(null);
    setNodeMetadata(null);
    setTimeFilterActive(false);

    try {
      const result = await getLineageGraph(tableName);
      setGraph(result);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to fetch lineage data';
      setError(message);
      setGraph(null);
    } finally {
      setLoading(false);
    }
  }, [searchQuery]);

  /** Handle Enter key press in search input */
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  /** Select a node and fetch its metadata */
  const handleNodeSelect = useCallback(async (nodeId: string) => {
    setSelectedNodeId(nodeId);
    setMetadataLoading(true);

    try {
      const metadata = await getNodeMetadata(nodeId);
      setNodeMetadata(metadata);
    } catch {
      setNodeMetadata({
        node_id: nodeId,
        last_execution: null,
        row_count: null,
        triggered_by_user: null,
        total_executions: 0,
        message: 'Unable to load metadata for this node.',
      });
    } finally {
      setMetadataLoading(false);
    }
  }, []);

  /** Apply time range filter */
  const handleTimeRangeApply = useCallback(
    async (start: string, end: string) => {
      setLoading(true);
      setError(null);
      setTimeFilterActive(true);

      try {
        const events = await queryLineageByTimeRange(start, end);

        if (events.length === 0) {
          setGraph({
            nodes: [],
            edges: [],
            table_name: searchQuery || 'time-range-query',
            depth: 10,
            message: 'No lineage events found in the specified time range.',
          });
          return;
        }

        // Build a graph from the time-range events
        const nodeMap = new Map<string, { id: string; name: string; type: 'table' | 'system' | 'transformation'; system: string | null; table_name: string | null }>();
        const edgeSet = new Set<string>();
        const graphEdges: { source_id: string; target_id: string; pipeline_name: string | null; last_execution: string | null }[] = [];

        for (const event of events) {
          const sourceId = `${event.source_system}.${event.source_table}`;
          const destId = `${event.destination_system}.${event.destination_table}`;

          if (!nodeMap.has(sourceId)) {
            nodeMap.set(sourceId, {
              id: sourceId,
              name: event.source_table,
              type: 'system',
              system: event.source_system,
              table_name: event.source_table,
            });
          }

          if (!nodeMap.has(destId)) {
            nodeMap.set(destId, {
              id: destId,
              name: event.destination_table,
              type: 'table',
              system: event.destination_system,
              table_name: event.destination_table,
            });
          }

          if (event.transformation_node) {
            const transformId = `transform.${event.transformation_node}`;
            if (!nodeMap.has(transformId)) {
              nodeMap.set(transformId, {
                id: transformId,
                name: event.transformation_node,
                type: 'transformation',
                system: null,
                table_name: null,
              });
            }

            const edgeKey1 = `${sourceId}->${transformId}`;
            if (!edgeSet.has(edgeKey1)) {
              edgeSet.add(edgeKey1);
              graphEdges.push({
                source_id: sourceId,
                target_id: transformId,
                pipeline_name: null,
                last_execution: event.timestamp,
              });
            }

            const edgeKey2 = `${transformId}->${destId}`;
            if (!edgeSet.has(edgeKey2)) {
              edgeSet.add(edgeKey2);
              graphEdges.push({
                source_id: transformId,
                target_id: destId,
                pipeline_name: null,
                last_execution: event.timestamp,
              });
            }
          } else {
            const edgeKey = `${sourceId}->${destId}`;
            if (!edgeSet.has(edgeKey)) {
              edgeSet.add(edgeKey);
              graphEdges.push({
                source_id: sourceId,
                target_id: destId,
                pipeline_name: null,
                last_execution: event.timestamp,
              });
            }
          }
        }

        setGraph({
          nodes: Array.from(nodeMap.values()).map((n) => ({ ...n, metadata: null })),
          edges: graphEdges,
          table_name: searchQuery || 'time-range-query',
          depth: 10,
          message: null,
        });
      } catch (err: unknown) {
        const message =
          err instanceof Error ? err.message : 'Failed to query lineage by time range';
        setError(message);
      } finally {
        setLoading(false);
      }
    },
    [searchQuery]
  );

  const isEmpty = graph && graph.nodes.length === 0;
  const hasData = graph && graph.nodes.length > 0;

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 2 }}>
      {/* Header */}
      <Box>
        <Typography variant="h4" gutterBottom>
          Data Lineage
        </Typography>
        <Typography color="text.secondary" gutterBottom>
          Visualize data flow and dependencies across pipelines.
        </Typography>
      </Box>

      {/* Controls row: Search + Time Filter */}
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="flex-start">
        <TextField
          placeholder="Search table name…"
          size="small"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          sx={{ minWidth: 280 }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
          }}
        />
        <TimeRangeFilter onApply={handleTimeRangeApply} loading={loading} />
        {timeFilterActive && (
          <Chip
            label="Time filter active"
            color="info"
            size="small"
            onDelete={() => {
              setTimeFilterActive(false);
              if (searchQuery.trim()) handleSearch();
            }}
          />
        )}
      </Stack>

      {/* Error */}
      {error && (
        <Alert severity="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Loading */}
      {loading && (
        <Box display="flex" justifyContent="center" alignItems="center" flex={1}>
          <CircularProgress />
        </Box>
      )}

      {/* Empty state (Requirement 9.7) */}
      {!loading && isEmpty && (
        <Paper
          sx={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            py: 8,
            px: 4,
            flex: 1,
          }}
        >
          <AccountTreeIcon sx={{ fontSize: 64, color: 'text.disabled', mb: 2 }} />
          <Typography variant="h6" color="text.secondary" gutterBottom>
            No Lineage Data Available
          </Typography>
          <Typography variant="body2" color="text.secondary" textAlign="center">
            {graph?.message ||
              'No lineage data is available for the specified table. Run a pipeline to generate lineage events.'}
          </Typography>
        </Paper>
      )}

      {/* Graph + Details panel */}
      {!loading && hasData && (
        <Box sx={{ display: 'flex', gap: 2, flex: 1, minHeight: 0 }}>
          {/* Graph area */}
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <LineageGraph
              nodes={graph.nodes}
              edges={graph.edges}
              onNodeSelect={handleNodeSelect}
              selectedNodeId={selectedNodeId}
            />
          </Box>

          {/* Node details sidebar */}
          <Box sx={{ width: 300, flexShrink: 0 }}>
            <NodeDetails
              metadata={nodeMetadata}
              loading={metadataLoading}
              nodeName={
                selectedNodeId
                  ? graph.nodes.find((n) => n.id === selectedNodeId)?.name
                  : undefined
              }
            />
          </Box>
        </Box>
      )}

      {/* Initial state: no search yet */}
      {!loading && !graph && !error && (
        <Paper
          sx={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            py: 8,
            px: 4,
            flex: 1,
          }}
        >
          <AccountTreeIcon sx={{ fontSize: 64, color: 'text.disabled', mb: 2 }} />
          <Typography variant="h6" color="text.secondary" gutterBottom>
            Explore Data Lineage
          </Typography>
          <Typography variant="body2" color="text.secondary" textAlign="center">
            Enter a table name above to view its upstream and downstream data lineage,
            or use the time range filter to explore lineage events within a period.
          </Typography>
        </Paper>
      )}
    </Box>
  );
}
