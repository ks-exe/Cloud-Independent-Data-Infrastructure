import { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Typography,
  Grid,
  Paper,
  Alert,
  CircularProgress,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import TimerIcon from '@mui/icons-material/Timer';
import QueueIcon from '@mui/icons-material/Queue';
import ReplayIcon from '@mui/icons-material/Replay';
import MonitorHeartIcon from '@mui/icons-material/MonitorHeart';

import MetricCard from '../components/monitoring/MetricCard';
import HealthIndicator from '../components/monitoring/HealthIndicator';
import LogViewer from '../components/monitoring/LogViewer';
import {
  getDashboardMetrics,
  DashboardMetrics,
  HealthStatus,
} from '../services/monitoring';

const POLL_INTERVAL_MS = 10_000;

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

export default function Monitoring() {
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchMetrics = useCallback(async () => {
    try {
      const data = await getDashboardMetrics();
      setMetrics(data);
      setError(null);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to fetch metrics';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    fetchMetrics();
  }, [fetchMetrics]);

  // Poll every 10 seconds for real-time updates (Requirement 8.3)
  useEffect(() => {
    const interval = setInterval(fetchMetrics, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchMetrics]);

  if (loading && !metrics) {
    return (
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '50vh',
        }}
      >
        <CircularProgress />
      </Box>
    );
  }

  const healthStatus: HealthStatus = metrics?.system_health || 'unhealthy';

  return (
    <Box>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          mb: 3,
        }}
      >
        <Box>
          <Typography variant="h4" gutterBottom>
            Monitoring Dashboard
          </Typography>
          <Typography color="text.secondary">
            Real-time pipeline execution monitoring and system health.
          </Typography>
        </Box>
        <HealthIndicator status={healthStatus} />
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {/* Metric Cards Grid */}
      <Grid container spacing={2} sx={{ mb: 4 }}>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Running Pipelines"
            value={metrics?.running_count ?? 0}
            icon={<PlayArrowIcon />}
            color="#6366f1"
            subtitle="Currently executing"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Failed (24h)"
            value={metrics?.failed_24h ?? 0}
            icon={<ErrorOutlineIcon />}
            color="#ef4444"
            subtitle="Updates within 10s"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Succeeded (24h)"
            value={metrics?.succeeded_24h ?? 0}
            icon={<CheckCircleOutlineIcon />}
            color="#10b981"
            subtitle="Last 24 hours"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Avg Execution Time"
            value={formatDuration(metrics?.avg_execution_time_ms ?? 0)}
            icon={<TimerIcon />}
            color="#06b6d4"
            subtitle="Last 24 hours"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Queue Size"
            value={metrics?.queue_size ?? 0}
            icon={<QueueIcon />}
            color="#f59e0b"
            subtitle="Pending tasks"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Retries (24h)"
            value={metrics?.retry_count_24h ?? 0}
            icon={<ReplayIcon />}
            color="#8b5cf6"
            subtitle="Last 24 hours"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="System Health"
            value={healthStatus.charAt(0).toUpperCase() + healthStatus.slice(1)}
            icon={<MonitorHeartIcon />}
            color={
              healthStatus === 'healthy'
                ? '#10b981'
                : healthStatus === 'degraded'
                  ? '#f59e0b'
                  : '#ef4444'
            }
            subtitle="All services status"
          />
        </Grid>
      </Grid>

      {/* System Health Details */}
      <Paper sx={{ p: 2, mb: 4 }}>
        <Typography variant="h6" gutterBottom>
          System Status
        </Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <HealthIndicator status={healthStatus} />
          <Typography variant="body2" color="text.secondary">
            {healthStatus === 'healthy'
              ? 'All services responding normally'
              : healthStatus === 'degraded'
                ? 'One or more non-critical services are unresponsive'
                : 'A critical service is unresponsive'}
          </Typography>
        </Box>
      </Paper>

      {/* Log Viewer */}
      <LogViewer />
    </Box>
  );
}
