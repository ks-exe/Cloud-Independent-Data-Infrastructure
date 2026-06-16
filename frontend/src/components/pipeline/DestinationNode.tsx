import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { Box, Typography, Chip } from '@mui/material';
import {
  Storage as PostgresIcon,
  Speed as ClickHouseIcon,
} from '@mui/icons-material';

const subtypeIcons: Record<string, React.ReactNode> = {
  postgresql: <PostgresIcon fontSize="small" />,
  clickhouse: <ClickHouseIcon fontSize="small" />,
};

const subtypeLabels: Record<string, string> = {
  postgresql: 'PostgreSQL',
  clickhouse: 'ClickHouse',
};

export interface DestinationNodeData {
  label: string;
  subtype: string;
  config?: Record<string, unknown>;
  hasError?: boolean;
}

function DestinationNode({ data, selected }: NodeProps<DestinationNodeData>) {
  return (
    <Box
      sx={{
        px: 2,
        py: 1.5,
        borderRadius: 2,
        border: data.hasError
          ? '2px solid #ef4444'
          : selected
            ? '2px solid #f59e0b'
            : '2px solid #92400e',
        bgcolor: '#78350f',
        minWidth: 160,
        cursor: 'grab',
        boxShadow: selected
          ? '0 0 12px rgba(245, 158, 11, 0.4)'
          : '0 2px 8px rgba(0,0,0,0.3)',
        transition: 'box-shadow 0.2s, border-color 0.2s',
        '&:hover': {
          boxShadow: '0 4px 12px rgba(245, 158, 11, 0.3)',
        },
      }}
    >
      {/* Input handle */}
      <Handle
        type="target"
        position={Position.Left}
        style={{
          background: '#f59e0b',
          border: '2px solid #78350f',
          width: 10,
          height: 10,
        }}
      />

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
        <Chip
          label="Destination"
          size="small"
          sx={{
            bgcolor: '#f59e0b',
            color: '#000',
            fontSize: '0.65rem',
            height: 18,
          }}
        />
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Box sx={{ color: '#fcd34d' }}>
          {subtypeIcons[data.subtype] || <PostgresIcon fontSize="small" />}
        </Box>
        <Typography
          variant="body2"
          sx={{ color: '#fef3c7', fontWeight: 600, fontSize: '0.8rem' }}
        >
          {data.label || subtypeLabels[data.subtype] || data.subtype}
        </Typography>
      </Box>
    </Box>
  );
}

export default memo(DestinationNode);
