import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { Box, Typography, Chip } from '@mui/material';
import {
  ViewColumn as SelectIcon,
  FilterList as FilterIcon,
  TextFields as RenameIcon,
  Functions as AggregateIcon,
  MergeType as JoinIcon,
} from '@mui/icons-material';

const subtypeIcons: Record<string, React.ReactNode> = {
  select_columns: <SelectIcon fontSize="small" />,
  filter_rows: <FilterIcon fontSize="small" />,
  rename_columns: <RenameIcon fontSize="small" />,
  aggregate: <AggregateIcon fontSize="small" />,
  join: <JoinIcon fontSize="small" />,
};

const subtypeLabels: Record<string, string> = {
  select_columns: 'Select Columns',
  filter_rows: 'Filter Rows',
  rename_columns: 'Rename Columns',
  aggregate: 'Aggregate',
  join: 'Join',
};

export interface TransformNodeData {
  label: string;
  subtype: string;
  config?: Record<string, unknown>;
  hasError?: boolean;
}

function TransformNode({ data, selected }: NodeProps<TransformNodeData>) {
  return (
    <Box
      sx={{
        px: 2,
        py: 1.5,
        borderRadius: 2,
        border: data.hasError
          ? '2px solid #ef4444'
          : selected
            ? '2px solid #3b82f6'
            : '2px solid #1e40af',
        bgcolor: '#1e3a5f',
        minWidth: 160,
        cursor: 'grab',
        boxShadow: selected
          ? '0 0 12px rgba(59, 130, 246, 0.4)'
          : '0 2px 8px rgba(0,0,0,0.3)',
        transition: 'box-shadow 0.2s, border-color 0.2s',
        '&:hover': {
          boxShadow: '0 4px 12px rgba(59, 130, 246, 0.3)',
        },
      }}
    >
      {/* Input handle */}
      <Handle
        type="target"
        position={Position.Left}
        style={{
          background: '#3b82f6',
          border: '2px solid #1e3a5f',
          width: 10,
          height: 10,
        }}
      />

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
        <Chip
          label="Transform"
          size="small"
          sx={{
            bgcolor: '#3b82f6',
            color: '#fff',
            fontSize: '0.65rem',
            height: 18,
          }}
        />
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Box sx={{ color: '#93c5fd' }}>
          {subtypeIcons[data.subtype] || <SelectIcon fontSize="small" />}
        </Box>
        <Typography
          variant="body2"
          sx={{ color: '#eff6ff', fontWeight: 600, fontSize: '0.8rem' }}
        >
          {data.label || subtypeLabels[data.subtype] || data.subtype}
        </Typography>
      </Box>

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Right}
        style={{
          background: '#3b82f6',
          border: '2px solid #1e3a5f',
          width: 10,
          height: 10,
        }}
      />
    </Box>
  );
}

export default memo(TransformNode);
