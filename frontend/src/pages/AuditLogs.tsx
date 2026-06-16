import { useState, useEffect, useCallback } from 'react';
import type React from 'react';
import {
  Box,
  Typography,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Chip,
  Select,
  SelectChangeEvent,
  MenuItem,
  FormControl,
  InputLabel,
  TextField,
  Alert,
  TablePagination,
  CircularProgress,
  Stack,
  ButtonGroup,
} from '@mui/material';
import {
  Download as DownloadIcon,
  Search as SearchIcon,
  Clear as ClearIcon,
} from '@mui/icons-material';
import { format } from 'date-fns';
import {
  auditService,
  AuditLog,
  AuditFilter,
  AuditEventType,
  AuditResult,
  ExportFormat,
} from '../services/audit';

const EVENT_TYPES: AuditEventType[] = [
  'USER_LOGIN',
  'USER_LOGOUT',
  'USER_CREATE',
  'USER_UPDATE',
  'USER_DELETE',
  'CONNECTOR_CREATE',
  'CONNECTOR_UPDATE',
  'CONNECTOR_DELETE',
  'PIPELINE_CREATE',
  'PIPELINE_EXECUTE',
  'PIPELINE_DELETE',
  'SCHEDULE_CREATE',
  'SCHEDULE_UPDATE',
  'SETTINGS_UPDATE',
  'KEY_ROTATION',
];

const RESULT_OPTIONS: AuditResult[] = ['success', 'failure', 'denied'];

function getResultColor(result: AuditResult): 'success' | 'error' | 'warning' {
  switch (result) {
    case 'success':
      return 'success';
    case 'failure':
      return 'error';
    case 'denied':
      return 'warning';
  }
}

export default function AuditLogs() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(100);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  // Filter state
  const [filters, setFilters] = useState<AuditFilter>({});
  const [eventType, setEventType] = useState<AuditEventType | ''>('');
  const [user, setUser] = useState('');
  const [result, setResult] = useState<AuditResult | ''>('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await auditService.search(filters, page + 1, rowsPerPage);
      setLogs(data.items);
      setTotal(data.total);
    } catch {
      setError('Failed to load audit logs');
    } finally {
      setLoading(false);
    }
  }, [filters, page, rowsPerPage]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  const applyFilters = () => {
    const newFilters: AuditFilter = {};
    if (eventType) newFilters.event_type = eventType;
    if (user) newFilters.user = user;
    if (result) newFilters.result = result;
    if (startDate) newFilters.start_date = startDate;
    if (endDate) newFilters.end_date = endDate;
    setFilters(newFilters);
    setPage(0);
  };

  const clearFilters = () => {
    setEventType('');
    setUser('');
    setResult('');
    setStartDate('');
    setEndDate('');
    setFilters({});
    setPage(0);
  };

  const handleExport = async (fmt: ExportFormat) => {
    setExporting(true);
    try {
      const blob = await auditService.export(filters, fmt);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `audit_logs_${format(new Date(), 'yyyyMMdd_HHmmss')}.${fmt}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch {
      setError('Failed to export audit logs');
    } finally {
      setExporting(false);
    }
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">Audit Logs</Typography>
        <ButtonGroup variant="outlined" disabled={exporting}>
          <Button startIcon={<DownloadIcon />} onClick={() => handleExport('csv')}>
            Export CSV
          </Button>
          <Button startIcon={<DownloadIcon />} onClick={() => handleExport('json')}>
            Export JSON
          </Button>
        </ButtonGroup>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Filter Controls */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="flex-end">
          <FormControl sx={{ minWidth: 180 }} size="small">
            <InputLabel>Event Type</InputLabel>
            <Select
              value={eventType}
              label="Event Type"
              onChange={(e) => setEventType(e.target.value as AuditEventType | '')}
            >
              <MenuItem value="">All</MenuItem>
              {EVENT_TYPES.map((type) => (
                <MenuItem key={type} value={type}>
                  {type.replace(/_/g, ' ')}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <TextField
            label="User"
            size="small"
            value={user}
            onChange={(e) => setUser(e.target.value)}
            placeholder="Username or ID"
            sx={{ minWidth: 150 }}
          />

          <FormControl sx={{ minWidth: 120 }} size="small">
            <InputLabel>Result</InputLabel>
            <Select
              value={result}
              label="Result"
              onChange={(e) => setResult(e.target.value as AuditResult | '')}
            >
              <MenuItem value="">All</MenuItem>
              {RESULT_OPTIONS.map((r) => (
                <MenuItem key={r} value={r} sx={{ textTransform: 'capitalize' }}>
                  {r}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <TextField
            label="Start Date"
            type="datetime-local"
            size="small"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            InputLabelProps={{ shrink: true }}
            sx={{ minWidth: 200 }}
          />

          <TextField
            label="End Date"
            type="datetime-local"
            size="small"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            InputLabelProps={{ shrink: true }}
            sx={{ minWidth: 200 }}
          />

          <Button variant="contained" startIcon={<SearchIcon />} onClick={applyFilters}>
            Search
          </Button>
          <Button variant="outlined" startIcon={<ClearIcon />} onClick={clearFilters}>
            Clear
          </Button>
        </Stack>
      </Paper>

      {/* Data Table */}
      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Timestamp</TableCell>
              <TableCell>Event</TableCell>
              <TableCell>User</TableCell>
              <TableCell>Resource</TableCell>
              <TableCell>Result</TableCell>
              <TableCell>IP Address</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={6} align="center" sx={{ py: 4 }}>
                  <CircularProgress size={32} />
                </TableCell>
              </TableRow>
            ) : logs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} align="center" sx={{ py: 4 }}>
                  <Typography color="text.secondary">No audit logs found</Typography>
                </TableCell>
              </TableRow>
            ) : (
              logs.map((log) => (
                <TableRow key={log.id} hover>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>
                    {format(new Date(log.timestamp), 'yyyy-MM-dd HH:mm:ss')}
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={log.event_type.replace(/_/g, ' ')}
                      size="small"
                      variant="outlined"
                    />
                  </TableCell>
                  <TableCell>{log.actor_username || log.actor_id}</TableCell>
                  <TableCell>
                    <Typography variant="body2" noWrap sx={{ maxWidth: 200 }}>
                      {log.target_resource_type}: {log.target_resource_id}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={log.result}
                      size="small"
                      color={getResultColor(log.result)}
                    />
                  </TableCell>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
                    {log.ip_address}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
        <TablePagination
          component="div"
          count={total}
          page={page}
          onPageChange={(_: unknown, newPage: number) => setPage(newPage)}
          rowsPerPage={rowsPerPage}
          onRowsPerPageChange={(e: React.ChangeEvent<HTMLInputElement>) => {
            setRowsPerPage(parseInt(e.target.value, 10));
            setPage(0);
          }}
          rowsPerPageOptions={[50, 100, 200]}
        />
      </TableContainer>
    </Box>
  );
}
