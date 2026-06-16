import { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Paper,
  Typography,
  TextField,
  Pagination,
  Chip,
  CircularProgress,
  Alert,
} from '@mui/material';
import { getExecutionLogs, LogEntry, LogQueryResponse } from '../../services/monitoring';

interface LogViewerProps {
  executionId?: string;
}

const levelColors: Record<string, 'error' | 'warning' | 'info' | 'default'> = {
  ERROR: 'error',
  WARNING: 'warning',
  INFO: 'info',
  DEBUG: 'default',
};

/**
 * Scrollable log display with pagination (100 entries per page).
 * Shows chronological log entries with level, timestamp, source, and message.
 */
export default function LogViewer({ executionId: propExecutionId }: LogViewerProps) {
  const [executionId, setExecutionId] = useState(propExecutionId || '');
  const [inputValue, setInputValue] = useState(propExecutionId || '');
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchLogs = useCallback(async (execId: string, pageNum: number) => {
    if (!execId) return;
    setLoading(true);
    setError(null);
    try {
      const data: LogQueryResponse = await getExecutionLogs(execId, pageNum);
      setLogs(data.items);
      setTotalPages(data.pages);
      setTotal(data.total);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to fetch logs';
      setError(message);
      setLogs([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (executionId) {
      fetchLogs(executionId, page);
    }
  }, [executionId, page, fetchLogs]);

  const handleSearch = () => {
    if (inputValue.trim()) {
      setExecutionId(inputValue.trim());
      setPage(1);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  const formatTimestamp = (ts: string) => {
    try {
      return new Date(ts).toLocaleString();
    } catch {
      return ts;
    }
  };

  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="h6" gutterBottom>
        Execution Logs
      </Typography>

      <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
        <TextField
          size="small"
          label="Execution ID"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Enter execution ID..."
          fullWidth
          sx={{ maxWidth: 500 }}
        />
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}

      {!loading && logs.length === 0 && executionId && !error && (
        <Typography color="text.secondary" sx={{ py: 2 }}>
          No log entries found for this execution.
        </Typography>
      )}

      {!loading && logs.length > 0 && (
        <>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Showing page {page} of {totalPages} ({total} total entries)
          </Typography>

          <Box
            sx={{
              maxHeight: 500,
              overflowY: 'auto',
              fontFamily: 'monospace',
              fontSize: '0.8rem',
              border: '1px solid',
              borderColor: 'divider',
              borderRadius: 1,
            }}
          >
            {logs.map((entry) => (
              <Box
                key={entry.id}
                sx={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 1,
                  py: 0.5,
                  px: 1,
                  borderBottom: '1px solid',
                  borderColor: 'divider',
                  '&:hover': {
                    bgcolor: 'action.hover',
                  },
                }}
              >
                <Chip
                  label={entry.level}
                  size="small"
                  color={levelColors[entry.level] || 'default'}
                  sx={{ minWidth: 70, fontSize: '0.7rem' }}
                />
                <Typography
                  variant="caption"
                  sx={{
                    minWidth: 160,
                    color: 'text.secondary',
                    fontFamily: 'monospace',
                  }}
                >
                  {formatTimestamp(entry.timestamp)}
                </Typography>
                <Chip
                  label={entry.source}
                  size="small"
                  variant="outlined"
                  sx={{ fontSize: '0.65rem', minWidth: 60 }}
                />
                <Typography
                  variant="body2"
                  sx={{
                    flex: 1,
                    fontFamily: 'monospace',
                    fontSize: '0.8rem',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {entry.message}
                </Typography>
              </Box>
            ))}
          </Box>

          {totalPages > 1 && (
            <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
              <Pagination
                count={totalPages}
                page={page}
                onChange={(_e, value) => setPage(value)}
                color="primary"
                size="small"
              />
            </Box>
          )}
        </>
      )}
    </Paper>
  );
}
