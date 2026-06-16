import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { Box, Typography, Chip } from '@mui/material';
import {
  Storage as PostgresIcon,
  TableChart as MySQLIcon,
  Description as CSVIcon,
  GridOn as ExcelIcon,
  Api as RestIcon,
} from '@mui/icons-material';

const subtypeIcons: Record<string, React.ReactNode> = {
  postgresql: <PostgresIcon fontSize="small" />,
  mysql: <MySQLIcon fontSize="small" />,
  csv: <CSVIcon fontSize="small" />,
  excel: <ExcelIcon fontSize="small" />,
  rest_api: <RestIcon fontSize="small" />,
};

const subtypeLabels: Record<string, string> = {
  postgresql: 'PostgreSQL',
  mysql: 'MySQL',
  csv: 'CSV',
  excel: 'Excel',
  rest_api: 'REST API',
};

export interface SourceNodeData {
  label: string;
  subtype: string;
  config?: Record<string, unknown>;
  hasError?: boolean;
}

function SourceNode({ data, selected }: NodeProps<SourceNodeData>) {
  return (
    <Box
      sx={{
        px: 2,
        py: 1.5,
        borderRadius: 2,
        border: data.hasError
          ? '2px solid #ef4444'
          : selected
            ? '2px solid #10b981'
            : '2px solid #065f46',
        bgcolor: '#064e3b',
        minWidth: 160,
        cursor: 'grab',
        boxShadow: selected
          ? '0 0 12px rgba(16, 185, 129, 0.4)'
          : '0 2px 8px rgba(0,0,0,0.3)',
        transition: 'box-shadow 0.2s, border-color 0.2s',
        '&:hover': {
          boxShadow: '0 4px 12px rgba(16, 185, 129, 0.3)',
        },
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
        <Chip
          label="Source"
          size="small"
          sx={{
            bgcolor: '#10b981',
            color: '#fff',
            fontSize: '0.65rem',
            height: 18,
          }}
        />
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Box sx={{ color: '#6ee7b7' }}>
          {subtypeIcons[data.subtype] || <PostgresIcon fontSize="small" />}
        </Box>
        <Typography
          variant="body2"
          sx={{ color: '#ecfdf5', fontWeight: 600, fontSize: '0.8rem' }}
        >
          {data.label || subtypeLabels[data.subtype] || data.subtype}
        </Typography>
      </Box>

      {/* Source output handle */}
      <Handle
        type="source"
        position={Position.Right}
        style={{
          background: '#10b981',
          border: '2px solid #064e3b',
          width: 10,
          height: 10,
        }}
      />
    </Box>
  );
}

export default memo(SourceNode);
