import { useCallback, useRef, useState, useMemo } from 'react';
import ReactFlow, {
  ReactFlowProvider,
  Controls,
  Background,
  MiniMap,
  Node,
  Edge,
  Connection,
  addEdge,
  useNodesState,
  useEdgesState,
  ReactFlowInstance,
  BackgroundVariant,
  NodeChange,
  EdgeChange,
} from 'reactflow';
import 'reactflow/dist/style.css';
import {
  Box,
  Button,
  TextField,
  Typography,
  IconButton,
  Tooltip,
  CircularProgress,
  Drawer,
  List,
  ListItemButton,
  ListItemText,
  Divider,
  Snackbar,
  Alert,
} from '@mui/material';
import {
  Save as SaveIcon,
  PlayArrow as RunIcon,
  History as HistoryIcon,
  CheckCircle as ValidIcon,
} from '@mui/icons-material';

import SourceNode from '../components/pipeline/SourceNode';
import TransformNode from '../components/pipeline/TransformNode';
import DestinationNode from '../components/pipeline/DestinationNode';
import NodePalette from '../components/pipeline/NodePalette';
import NodeConfigPanel from '../components/pipeline/NodeConfigPanel';
import ValidationSummary from '../components/pipeline/ValidationSummary';
import pipelineService, {
  ValidationError,
  PipelineVersion,
} from '../services/pipeline';

// Register custom node types
const nodeTypes = {
  source: SourceNode,
  transform: TransformNode,
  destination: DestinationNode,
};

// Max limits per requirement 5.13
const MAX_NODES = 50;
const MAX_EDGES = 100;

let nodeIdCounter = 0;
function getNextNodeId() {
  nodeIdCounter += 1;
  return `node_${Date.now()}_${nodeIdCounter}`;
}

export default function PipelineBuilder() {
  return (
    <ReactFlowProvider>
      <PipelineBuilderInner />
    </ReactFlowProvider>
  );
}

function PipelineBuilderInner() {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // UI state
  const [pipelineName, setPipelineName] = useState('Untitled Pipeline');
  const [pipelineId, setPipelineId] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [validationErrors, setValidationErrors] = useState<ValidationError[]>([]);
  const [saving, setSaving] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [showVersions, setShowVersions] = useState(false);
  const [versions, setVersions] = useState<PipelineVersion[]>([]);
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' | 'info' }>({
    open: false,
    message: '',
    severity: 'info',
  });

  // Validation: highlight invalid nodes
  const invalidNodeIds = useMemo(() => {
    return new Set(validationErrors.filter((e) => e.node_id).map((e) => e.node_id!));
  }, [validationErrors]);

  // Update node data to include error highlighting
  const nodesWithErrors = useMemo(() => {
    return nodes.map((n) => ({
      ...n,
      data: { ...n.data, hasError: invalidNodeIds.has(n.id) },
    }));
  }, [nodes, invalidNodeIds]);

  // ─── Connection Validation ──────────────────────────────────────────────────

  const isValidConnection = useCallback(
    (connection: Connection) => {
      const sourceNode = nodes.find((n) => n.id === connection.source);
      const targetNode = nodes.find((n) => n.id === connection.target);
      if (!sourceNode || !targetNode) return false;

      const sourceType = sourceNode.type;
      const targetType = targetNode.type;

      // Destination nodes cannot have outgoing connections
      if (sourceType === 'destination') return false;

      // Source can connect to transform or destination
      if (sourceType === 'source' && (targetType === 'transform' || targetType === 'destination')) return true;

      // Transform can connect to transform or destination
      if (sourceType === 'transform' && (targetType === 'transform' || targetType === 'destination')) return true;

      return false;
    },
    [nodes]
  );

  // Cycle detection using DFS
  const wouldCreateCycle = useCallback(
    (source: string, target: string) => {
      const adjacency = new Map<string, string[]>();
      edges.forEach((e) => {
        if (!adjacency.has(e.source)) adjacency.set(e.source, []);
        adjacency.get(e.source)!.push(e.target);
      });
      // Add the proposed edge
      if (!adjacency.has(source)) adjacency.set(source, []);
      adjacency.get(source)!.push(target);

      // DFS from target to check if we can reach source
      const visited = new Set<string>();
      const stack = [target];
      while (stack.length > 0) {
        const current = stack.pop()!;
        if (current === source) return true;
        if (visited.has(current)) continue;
        visited.add(current);
        const neighbors = adjacency.get(current) || [];
        stack.push(...neighbors);
      }
      return false;
    },
    [edges]
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;

      // Check edge limit
      if (edges.length >= MAX_EDGES) {
        setSnackbar({ open: true, message: `Maximum of ${MAX_EDGES} edges reached.`, severity: 'error' });
        return;
      }

      // Validate flow direction
      if (!isValidConnection(connection)) {
        setSnackbar({ open: true, message: 'Invalid connection: check flow direction rules.', severity: 'error' });
        return;
      }

      // Check for cycles
      if (wouldCreateCycle(connection.source, connection.target)) {
        setSnackbar({ open: true, message: 'Connection rejected: would create a cycle.', severity: 'error' });
        return;
      }

      setEdges((eds) => addEdge({ ...connection, type: 'smoothstep', animated: true }, eds));
      setValidationErrors([]);
    },
    [edges.length, isValidConnection, wouldCreateCycle, setEdges]
  );

  // ─── Drag & Drop from Palette ───────────────────────────────────────────────

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const dataStr = event.dataTransfer.getData('application/reactflow');
      if (!dataStr || !reactFlowInstance || !reactFlowWrapper.current) return;

      // Check node limit
      if (nodes.length >= MAX_NODES) {
        setSnackbar({ open: true, message: `Maximum of ${MAX_NODES} nodes reached.`, severity: 'error' });
        return;
      }

      const nodeDef = JSON.parse(dataStr);
      const bounds = reactFlowWrapper.current.getBoundingClientRect();
      const position = reactFlowInstance.project({
        x: event.clientX - bounds.left,
        y: event.clientY - bounds.top,
      });

      const newNode: Node = {
        id: getNextNodeId(),
        type: nodeDef.node_type,
        position,
        data: {
          label: nodeDef.label,
          subtype: nodeDef.node_subtype,
          node_type: nodeDef.node_type,
          config: {},
          hasError: false,
        },
      };

      setNodes((nds) => [...nds, newNode]);
      setSelectedNode(newNode);
      setValidationErrors([]);
    },
    [reactFlowInstance, nodes.length, setNodes]
  );

  // ─── Node Selection ─────────────────────────────────────────────────────────

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNode(node);
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  // ─── Node/Edge Deletion with Keyboard ───────────────────────────────────────

  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      onNodesChange(changes);
      // If a node is removed, also clear selection
      const removals = changes.filter((c) => c.type === 'remove');
      if (removals.length > 0 && selectedNode) {
        const removedIds = new Set(removals.map((c) => (c as { id: string }).id));
        if (removedIds.has(selectedNode.id)) {
          setSelectedNode(null);
        }
      }
    },
    [onNodesChange, selectedNode]
  );

  const handleEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      onEdgesChange(changes);
    },
    [onEdgesChange]
  );

  // ─── Node Config Updates ────────────────────────────────────────────────────

  const handleNodeUpdate = useCallback(
    (nodeId: string, data: Record<string, unknown>) => {
      setNodes((nds) =>
        nds.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...data } } : n))
      );
      // Update selectedNode reference
      setSelectedNode((prev) => (prev && prev.id === nodeId ? { ...prev, data: { ...prev.data, ...data } } : prev));
    },
    [setNodes]
  );

  const handleNodeDelete = useCallback(
    (nodeId: string) => {
      setNodes((nds) => nds.filter((n) => n.id !== nodeId));
      setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
      if (selectedNode?.id === nodeId) {
        setSelectedNode(null);
      }
    },
    [setNodes, setEdges, selectedNode]
  );

  // ─── Save / Validate ───────────────────────────────────────────────────────

  const buildDefinition = useCallback(() => {
    return {
      nodes: nodes.map((n) => ({
        id: n.id,
        node_type: (n.data.node_type || n.type) as 'source' | 'transform' | 'destination',
        node_subtype: n.data.subtype as string,
        config: (n.data.config || {}) as Record<string, unknown>,
        position_x: n.position.x,
        position_y: n.position.y,
      })),
      edges: edges.map((e) => ({
        id: e.id,
        source_node_id: e.source,
        target_node_id: e.target,
      })),
    };
  }, [nodes, edges]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setValidationErrors([]);

    try {
      const definition = buildDefinition();

      // Validate first
      const validation = await pipelineService.validate(definition);
      if (!validation.valid) {
        setValidationErrors(validation.errors);
        setSnackbar({ open: true, message: 'Validation failed. See errors below.', severity: 'error' });
        setSaving(false);
        return;
      }

      // Save or create
      if (pipelineId) {
        await pipelineService.update(pipelineId, {
          name: pipelineName,
          definition,
        });
        setSnackbar({ open: true, message: 'Pipeline saved (new version created).', severity: 'success' });
      } else {
        const created = await pipelineService.create({
          name: pipelineName,
          definition,
        });
        setPipelineId(created.id);
        setSnackbar({ open: true, message: 'Pipeline created successfully.', severity: 'success' });
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to save pipeline.';
      setSnackbar({ open: true, message, severity: 'error' });
    } finally {
      setSaving(false);
    }
  }, [buildDefinition, pipelineId, pipelineName]);

  // ─── Execute ────────────────────────────────────────────────────────────────

  const handleExecute = useCallback(async () => {
    if (!pipelineId) {
      setSnackbar({ open: true, message: 'Save the pipeline before executing.', severity: 'error' });
      return;
    }
    setExecuting(true);
    try {
      const run = await pipelineService.execute(pipelineId);
      setSnackbar({ open: true, message: `Execution started (Run ID: ${run.id}).`, severity: 'success' });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to execute pipeline.';
      setSnackbar({ open: true, message, severity: 'error' });
    } finally {
      setExecuting(false);
    }
  }, [pipelineId]);

  // ─── Version History ────────────────────────────────────────────────────────

  const handleToggleVersions = useCallback(async () => {
    if (!pipelineId) {
      setSnackbar({ open: true, message: 'Save the pipeline first to see version history.', severity: 'info' });
      return;
    }
    if (showVersions) {
      setShowVersions(false);
      return;
    }
    try {
      const versionList = await pipelineService.getVersions(pipelineId);
      setVersions(versionList);
      setShowVersions(true);
    } catch {
      setSnackbar({ open: true, message: 'Failed to load version history.', severity: 'error' });
    }
  }, [pipelineId, showVersions]);

  const handleLoadVersion = useCallback(
    (version: PipelineVersion) => {
      const def = version.definition_snapshot;
      const loadedNodes: Node[] = def.nodes.map((n) => ({
        id: n.id,
        type: n.node_type,
        position: { x: n.position_x, y: n.position_y },
        data: {
          label: n.node_subtype,
          subtype: n.node_subtype,
          node_type: n.node_type,
          config: n.config || {},
          hasError: false,
        },
      }));
      const loadedEdges: Edge[] = def.edges.map((e) => ({
        id: e.id,
        source: e.source_node_id,
        target: e.target_node_id,
        type: 'smoothstep',
        animated: true,
      }));
      setNodes(loadedNodes);
      setEdges(loadedEdges);
      setShowVersions(false);
      setSelectedNode(null);
      setValidationErrors([]);
      setSnackbar({ open: true, message: `Loaded version ${version.version_number}.`, severity: 'info' });
    },
    [setNodes, setEdges]
  );

  return (
    <Box sx={{ display: 'flex', height: 'calc(100vh - 64px)', overflow: 'hidden' }}>
      {/* Left Sidebar — Node Palette */}
      <NodePalette />

      {/* Center — Canvas */}
      <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', position: 'relative' }}>
        {/* Toolbar */}
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1.5,
            px: 2,
            py: 1,
            borderBottom: '1px solid',
            borderColor: 'divider',
            bgcolor: 'background.paper',
          }}
        >
          <TextField
            value={pipelineName}
            onChange={(e) => setPipelineName(e.target.value)}
            variant="standard"
            size="small"
            sx={{ minWidth: 200 }}
            inputProps={{ style: { fontWeight: 600, fontSize: '1rem' } }}
          />
          <Box sx={{ flex: 1 }} />
          <Tooltip title="Version History">
            <IconButton onClick={handleToggleVersions} size="small">
              <HistoryIcon />
            </IconButton>
          </Tooltip>
          <Button
            variant="outlined"
            size="small"
            startIcon={saving ? <CircularProgress size={16} /> : <SaveIcon />}
            onClick={handleSave}
            disabled={saving}
          >
            Save
          </Button>
          <Button
            variant="contained"
            size="small"
            startIcon={executing ? <CircularProgress size={16} color="inherit" /> : <RunIcon />}
            onClick={handleExecute}
            disabled={executing || !pipelineId}
            color="success"
          >
            Execute
          </Button>
        </Box>

        {/* React Flow Canvas */}
        <Box ref={reactFlowWrapper} sx={{ flex: 1 }}>
          <ReactFlow
            nodes={nodesWithErrors}
            edges={edges}
            onNodesChange={handleNodesChange}
            onEdgesChange={handleEdgesChange}
            onConnect={onConnect}
            onInit={setReactFlowInstance}
            onDrop={onDrop}
            onDragOver={onDragOver}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            isValidConnection={isValidConnection}
            nodeTypes={nodeTypes}
            deleteKeyCode={['Backspace', 'Delete']}
            fitView
            snapToGrid
            snapGrid={[16, 16]}
            defaultEdgeOptions={{
              type: 'smoothstep',
              animated: true,
              style: { stroke: '#6366f1', strokeWidth: 2 },
            }}
            proOptions={{ hideAttribution: true }}
          >
            <Controls
              style={{ bottom: 60, left: 10 }}
            />
            <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#334155" />
            <MiniMap
              nodeColor={(node) => {
                if (node.type === 'source') return '#10b981';
                if (node.type === 'transform') return '#3b82f6';
                return '#f59e0b';
              }}
              maskColor="rgba(15, 23, 42, 0.8)"
              style={{ bottom: 10, right: 10 }}
            />
          </ReactFlow>

          {/* Empty state */}
          {nodes.length === 0 && (
            <Box
              sx={{
                position: 'absolute',
                top: '50%',
                left: '50%',
                transform: 'translate(-50%, -50%)',
                textAlign: 'center',
                pointerEvents: 'none',
              }}
            >
              <ValidIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 1 }} />
              <Typography variant="h6" color="text.secondary">
                Drag nodes from the palette to get started
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Connect nodes to build your data pipeline
              </Typography>
            </Box>
          )}

          {/* Validation Errors */}
          <ValidationSummary
            errors={validationErrors}
            onClose={() => setValidationErrors([])}
          />
        </Box>
      </Box>

      {/* Right Sidebar — Config Panel */}
      {selectedNode && (
        <NodeConfigPanel
          node={selectedNode}
          onClose={() => setSelectedNode(null)}
          onUpdate={handleNodeUpdate}
          onDelete={handleNodeDelete}
        />
      )}

      {/* Version History Drawer */}
      <Drawer
        anchor="right"
        open={showVersions}
        onClose={() => setShowVersions(false)}
        PaperProps={{ sx: { width: 320, bgcolor: 'background.paper' } }}
      >
        <Box sx={{ p: 2 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 2 }}>
            Version History
          </Typography>
          <Divider sx={{ mb: 1 }} />
          {versions.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
              No versions saved yet.
            </Typography>
          ) : (
            <List disablePadding>
              {versions.map((v) => (
                <ListItemButton
                  key={v.id}
                  onClick={() => handleLoadVersion(v)}
                  sx={{ borderRadius: 1, mb: 0.5 }}
                >
                  <ListItemText
                    primary={`Version ${v.version_number}`}
                    secondary={new Date(v.created_at).toLocaleString()}
                    primaryTypographyProps={{ fontWeight: 600, fontSize: '0.85rem' }}
                    secondaryTypographyProps={{ fontSize: '0.75rem' }}
                  />
                </ListItemButton>
              ))}
            </List>
          )}
        </Box>
      </Drawer>

      {/* Snackbar notifications */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <Alert
          onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
          severity={snackbar.severity}
          variant="filled"
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}
