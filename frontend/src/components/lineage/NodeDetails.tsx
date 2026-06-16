import {
  Box,
  Typography,
  Paper,
  Divider,
  CircularProgress,
  Chip,
  Stack,
} from '@mui/material';
import { format } from 'date-fns';
import type { LineageNodeMetadata } from '../../services/lineage';

interface NodeDetailsProps {
  metadata: LineageNodeMetadata | null;
  loading: boolean;
  nodeName?: string;
}

/**
 * Panel displaying metadata for a selected lineage node.
 * Shows last execution timestamp, row count, and triggering user.
 */
export default function NodeDetails({ metadata, loading, nodeName }: NodeDetailsProps) {
  if (loading) {
    return (
      <Paper sx={{ p: 2, minWidth: 280 }}>
        <Box display="flex" justifyContent="center" alignItems="center" minHeight={120}>
          <CircularProgress size={24} />
        </Box>
      </Paper>
    );
  }

  if (!metadata) {
    return (
      <Paper sx={{ p: 2, minWidth: 280 }}>
        <Typography variant="body2" color="text.secondary">
          Select a node to view details.
        </Typography>
      </Paper>
    );
  }

  if (metadata.message) {
    return (
      <Paper sx={{ p: 2, minWidth: 280 }}>
        <Typography variant="subtitle2" gutterBottom>
          {nodeName || metadata.node_id}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {metadata.message}
        </Typography>
      </Paper>
    );
  }

  return (
    <Paper sx={{ p: 2, minWidth: 280 }}>
      <Typography variant="subtitle1" fontWeight={600} gutterBottom>
        Node Details
      </Typography>
      <Divider sx={{ mb: 1.5 }} />

      <Stack spacing={1.5}>
        <Box>
          <Typography variant="caption" color="text.secondary">
            Node ID
          </Typography>
          <Typography variant="body2">{metadata.node_id}</Typography>
        </Box>

        <Box>
          <Typography variant="caption" color="text.secondary">
            Last Execution
          </Typography>
          <Typography variant="body2">
            {metadata.last_execution
              ? format(new Date(metadata.last_execution), 'PPpp')
              : 'N/A'}
          </Typography>
        </Box>

        <Box>
          <Typography variant="caption" color="text.secondary">
            Row Count
          </Typography>
          <Typography variant="body2">
            {metadata.row_count != null
              ? metadata.row_count.toLocaleString()
              : 'N/A'}
          </Typography>
        </Box>

        <Box>
          <Typography variant="caption" color="text.secondary">
            Triggered By
          </Typography>
          <Typography variant="body2">
            {metadata.triggered_by_user || 'N/A'}
          </Typography>
        </Box>

        <Box>
          <Typography variant="caption" color="text.secondary">
            Total Executions
          </Typography>
          <Chip
            label={metadata.total_executions}
            size="small"
            color="primary"
            variant="outlined"
          />
        </Box>
      </Stack>
    </Paper>
  );
}
