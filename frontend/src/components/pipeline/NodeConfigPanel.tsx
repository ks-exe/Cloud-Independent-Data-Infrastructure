import { Box, Typography, TextField, IconButton, Divider, Button } from '@mui/material';
import { Close as CloseIcon, Delete as DeleteIcon } from '@mui/icons-material';
import { Node } from 'reactflow';
import { useCallback, useEffect, useState } from 'react';

interface NodeConfigPanelProps {
  node: Node;
  onClose: () => void;
  onUpdate: (nodeId: string, data: Record<string, unknown>) => void;
  onDelete: (nodeId: string) => void;
}

// Configuration fields per node subtype
const configFields: Record<string, { key: string; label: string; type: string; required?: boolean }[]> = {
  // Sources
  'source-postgresql': [
    { key: 'connector_id', label: 'Connector', type: 'text', required: true },
    { key: 'schema', label: 'Schema', type: 'text' },
    { key: 'table', label: 'Table Name', type: 'text', required: true },
    { key: 'query', label: 'Custom Query (optional)', type: 'multiline' },
  ],
  'source-mysql': [
    { key: 'connector_id', label: 'Connector', type: 'text', required: true },
    { key: 'schema', label: 'Schema', type: 'text' },
    { key: 'table', label: 'Table Name', type: 'text', required: true },
    { key: 'query', label: 'Custom Query (optional)', type: 'multiline' },
  ],
  'source-csv': [
    { key: 'file_path', label: 'File Path', type: 'text', required: true },
    { key: 'delimiter', label: 'Delimiter', type: 'text' },
    { key: 'has_header', label: 'Has Header (true/false)', type: 'text' },
    { key: 'encoding', label: 'Encoding', type: 'text' },
  ],
  'source-excel': [
    { key: 'file_path', label: 'File Path', type: 'text', required: true },
    { key: 'sheet_name', label: 'Sheet Name', type: 'text' },
    { key: 'header_row', label: 'Header Row', type: 'text' },
  ],
  'source-rest_api': [
    { key: 'connector_id', label: 'Connector', type: 'text', required: true },
    { key: 'endpoint', label: 'Endpoint URL', type: 'text', required: true },
    { key: 'method', label: 'HTTP Method', type: 'text' },
    { key: 'response_path', label: 'Response JSON Path', type: 'text' },
  ],
  // Transforms
  'transform-select_columns': [
    { key: 'columns', label: 'Columns (comma-separated)', type: 'text', required: true },
  ],
  'transform-filter_rows': [
    { key: 'condition', label: 'Filter Condition (SQL WHERE)', type: 'multiline', required: true },
  ],
  'transform-rename_columns': [
    { key: 'mappings', label: 'Rename Mappings (old:new, per line)', type: 'multiline', required: true },
  ],
  'transform-aggregate': [
    { key: 'group_by', label: 'Group By (comma-separated)', type: 'text', required: true },
    { key: 'aggregations', label: 'Aggregations (col:func, per line)', type: 'multiline', required: true },
  ],
  'transform-join': [
    { key: 'join_type', label: 'Join Type (inner/left/right/full)', type: 'text', required: true },
    { key: 'join_condition', label: 'Join Condition', type: 'multiline', required: true },
  ],
  // Destinations
  'destination-postgresql': [
    { key: 'connector_id', label: 'Connector', type: 'text', required: true },
    { key: 'schema', label: 'Schema', type: 'text' },
    { key: 'table', label: 'Target Table', type: 'text', required: true },
    { key: 'write_mode', label: 'Write Mode (append/overwrite/upsert)', type: 'text' },
  ],
  'destination-clickhouse': [
    { key: 'connector_id', label: 'Connector', type: 'text', required: true },
    { key: 'database', label: 'Database', type: 'text' },
    { key: 'table', label: 'Target Table', type: 'text', required: true },
    { key: 'engine', label: 'Table Engine', type: 'text' },
  ],
};

export default function NodeConfigPanel({ node, onClose, onUpdate, onDelete }: NodeConfigPanelProps) {
  const nodeData = node.data as Record<string, unknown>;
  const nodeType = nodeData.node_type as string || node.type || '';
  const nodeSubtype = nodeData.subtype as string || '';
  const configKey = `${nodeType}-${nodeSubtype}`;
  const fields = configFields[configKey] || [];

  const [localConfig, setLocalConfig] = useState<Record<string, string>>({});
  const [label, setLabel] = useState<string>((nodeData.label as string) || '');

  useEffect(() => {
    const config = (nodeData.config as Record<string, string>) || {};
    setLocalConfig({ ...config });
    setLabel((nodeData.label as string) || '');
  }, [node.id, nodeData]);

  const handleFieldChange = useCallback((key: string, value: string) => {
    setLocalConfig((prev) => ({ ...prev, [key]: value }));
  }, []);

  const handleApply = useCallback(() => {
    onUpdate(node.id, { ...nodeData, label, config: localConfig });
  }, [node.id, nodeData, label, localConfig, onUpdate]);

  const handleDelete = useCallback(() => {
    onDelete(node.id);
    onClose();
  }, [node.id, onDelete, onClose]);

  const typeColor =
    nodeType === 'source' ? '#10b981' :
    nodeType === 'transform' ? '#3b82f6' :
    '#f59e0b';

  return (
    <Box
      sx={{
        width: 300,
        height: '100%',
        bgcolor: 'background.paper',
        borderLeft: '1px solid',
        borderColor: 'divider',
        p: 2,
        overflowY: 'auto',
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700, color: typeColor }}>
          Configure Node
        </Typography>
        <IconButton size="small" onClick={onClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      <Divider sx={{ mb: 2 }} />

      {/* Node label */}
      <TextField
        label="Node Label"
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        size="small"
        fullWidth
        sx={{ mb: 2 }}
      />

      {/* Type info */}
      <Typography variant="caption" color="text.secondary" sx={{ mb: 1.5, display: 'block' }}>
        Type: {nodeType} / {nodeSubtype}
      </Typography>

      <Divider sx={{ mb: 2 }} />

      {/* Configuration fields */}
      {fields.length > 0 ? (
        fields.map((field) => (
          <TextField
            key={field.key}
            label={field.label}
            value={localConfig[field.key] || ''}
            onChange={(e) => handleFieldChange(field.key, e.target.value)}
            size="small"
            fullWidth
            required={field.required}
            multiline={field.type === 'multiline'}
            rows={field.type === 'multiline' ? 3 : undefined}
            sx={{ mb: 1.5 }}
          />
        ))
      ) : (
        <Typography variant="body2" color="text.secondary">
          No configuration fields available for this node type.
        </Typography>
      )}

      <Box sx={{ mt: 'auto', pt: 2 }}>
        <Button
          variant="contained"
          fullWidth
          onClick={handleApply}
          sx={{ mb: 1 }}
        >
          Apply Changes
        </Button>
        <Button
          variant="outlined"
          color="error"
          fullWidth
          startIcon={<DeleteIcon />}
          onClick={handleDelete}
        >
          Delete Node
        </Button>
      </Box>
    </Box>
  );
}
