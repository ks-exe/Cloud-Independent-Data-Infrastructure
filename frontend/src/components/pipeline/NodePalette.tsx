import { Box, Typography, Divider } from '@mui/material';
import {
  Storage as PostgresIcon,
  TableChart as MySQLIcon,
  Description as CSVIcon,
  GridOn as ExcelIcon,
  Api as RestIcon,
  ViewColumn as SelectIcon,
  FilterList as FilterIcon,
  TextFields as RenameIcon,
  Functions as AggregateIcon,
  MergeType as JoinIcon,
  Speed as ClickHouseIcon,
} from '@mui/icons-material';
import React from 'react';

export interface PaletteNodeDefinition {
  node_type: 'source' | 'transform' | 'destination';
  node_subtype: string;
  label: string;
  icon: React.ReactNode;
}

const sourceNodes: PaletteNodeDefinition[] = [
  { node_type: 'source', node_subtype: 'postgresql', label: 'PostgreSQL Source', icon: <PostgresIcon fontSize="small" /> },
  { node_type: 'source', node_subtype: 'mysql', label: 'MySQL Source', icon: <MySQLIcon fontSize="small" /> },
  { node_type: 'source', node_subtype: 'csv', label: 'CSV Source', icon: <CSVIcon fontSize="small" /> },
  { node_type: 'source', node_subtype: 'excel', label: 'Excel Source', icon: <ExcelIcon fontSize="small" /> },
  { node_type: 'source', node_subtype: 'rest_api', label: 'REST Source', icon: <RestIcon fontSize="small" /> },
];

const transformNodes: PaletteNodeDefinition[] = [
  { node_type: 'transform', node_subtype: 'select_columns', label: 'Select Columns', icon: <SelectIcon fontSize="small" /> },
  { node_type: 'transform', node_subtype: 'filter_rows', label: 'Filter Rows', icon: <FilterIcon fontSize="small" /> },
  { node_type: 'transform', node_subtype: 'rename_columns', label: 'Rename Columns', icon: <RenameIcon fontSize="small" /> },
  { node_type: 'transform', node_subtype: 'aggregate', label: 'Aggregate', icon: <AggregateIcon fontSize="small" /> },
  { node_type: 'transform', node_subtype: 'join', label: 'Join', icon: <JoinIcon fontSize="small" /> },
];

const destinationNodes: PaletteNodeDefinition[] = [
  { node_type: 'destination', node_subtype: 'postgresql', label: 'PostgreSQL Destination', icon: <PostgresIcon fontSize="small" /> },
  { node_type: 'destination', node_subtype: 'clickhouse', label: 'ClickHouse Destination', icon: <ClickHouseIcon fontSize="small" /> },
];

interface NodeGroupProps {
  title: string;
  color: string;
  nodes: PaletteNodeDefinition[];
}

function NodeGroup({ title, color, nodes }: NodeGroupProps) {
  const onDragStart = (event: React.DragEvent, nodeDef: PaletteNodeDefinition) => {
    event.dataTransfer.setData('application/reactflow', JSON.stringify(nodeDef));
    event.dataTransfer.effectAllowed = 'move';
  };

  return (
    <Box sx={{ mb: 2 }}>
      <Typography
        variant="caption"
        sx={{
          color,
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          mb: 1,
          display: 'block',
        }}
      >
        {title}
      </Typography>
      {nodes.map((nodeDef) => (
        <Box
          key={`${nodeDef.node_type}-${nodeDef.node_subtype}`}
          draggable
          onDragStart={(e) => onDragStart(e, nodeDef)}
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1,
            px: 1.5,
            py: 1,
            mb: 0.5,
            borderRadius: 1,
            border: `1px solid ${color}33`,
            bgcolor: `${color}11`,
            cursor: 'grab',
            transition: 'all 0.15s ease',
            '&:hover': {
              bgcolor: `${color}22`,
              borderColor: `${color}66`,
              transform: 'translateX(2px)',
            },
            '&:active': {
              cursor: 'grabbing',
              transform: 'scale(0.97)',
            },
          }}
        >
          <Box sx={{ color, display: 'flex', alignItems: 'center' }}>
            {nodeDef.icon}
          </Box>
          <Typography variant="body2" sx={{ fontSize: '0.75rem', fontWeight: 500 }}>
            {nodeDef.label}
          </Typography>
        </Box>
      ))}
    </Box>
  );
}

export default function NodePalette() {
  return (
    <Box
      sx={{
        width: 220,
        height: '100%',
        bgcolor: 'background.paper',
        borderRight: '1px solid',
        borderColor: 'divider',
        p: 2,
        overflowY: 'auto',
        flexShrink: 0,
      }}
    >
      <Typography variant="subtitle2" sx={{ mb: 1.5, fontWeight: 700 }}>
        Node Palette
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ mb: 2, display: 'block' }}>
        Drag nodes onto the canvas
      </Typography>
      <Divider sx={{ mb: 2 }} />

      <NodeGroup title="Sources" color="#10b981" nodes={sourceNodes} />
      <NodeGroup title="Transforms" color="#3b82f6" nodes={transformNodes} />
      <NodeGroup title="Destinations" color="#f59e0b" nodes={destinationNodes} />
    </Box>
  );
}
