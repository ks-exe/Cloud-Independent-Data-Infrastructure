import { Chip } from '@mui/material';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import type { HealthStatus } from '../../services/monitoring';

interface HealthIndicatorProps {
  status: HealthStatus;
}

const statusConfig: Record<
  HealthStatus,
  { label: string; color: 'success' | 'warning' | 'error' }
> = {
  healthy: { label: 'Healthy', color: 'success' },
  degraded: { label: 'Degraded', color: 'warning' },
  unhealthy: { label: 'Unhealthy', color: 'error' },
};

/**
 * Color-coded health status badge.
 * Green = healthy, Yellow = degraded, Red = unhealthy.
 */
export default function HealthIndicator({ status }: HealthIndicatorProps) {
  const config = statusConfig[status] || statusConfig.unhealthy;

  return (
    <Chip
      icon={<FiberManualRecordIcon sx={{ fontSize: 12 }} />}
      label={config.label}
      color={config.color}
      size="small"
      variant="outlined"
      sx={{
        fontWeight: 600,
        '& .MuiChip-icon': {
          animation: status === 'healthy' ? undefined : 'pulse 1.5s infinite',
        },
        '@keyframes pulse': {
          '0%, 100%': { opacity: 1 },
          '50%': { opacity: 0.4 },
        },
      }}
    />
  );
}
