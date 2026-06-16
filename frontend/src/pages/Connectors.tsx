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
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Alert,
  TablePagination,
  Tooltip,
  CircularProgress,
  Stack,
} from '@mui/material';
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  PlayArrow as TestIcon,
  CheckCircle as HealthyIcon,
  Error as UnhealthyIcon,
  HelpOutline as UnknownIcon,
} from '@mui/icons-material';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import {
  connectorsService,
  Connector,
  ConnectorType,
  ConnectorDirection,
  ConnectorStatus,
  CreateConnectorPayload,
  ConnectionTestResult,
} from '../services/connectors';

const CONNECTOR_TYPES: ConnectorType[] = [
  'PostgreSQL',
  'MySQL',
  'MSSQL',
  'Oracle',
  'MongoDB',
  'S3',
  'HDFS',
  'SFTP',
  'REST_API',
  'Kafka',
];

const CONNECTOR_DIRECTIONS: ConnectorDirection[] = ['source', 'destination', 'bidirectional'];

const createConnectorSchema = z.object({
  name: z.string().min(1, 'Name is required').max(128),
  type: z.enum([
    'PostgreSQL',
    'MySQL',
    'MSSQL',
    'Oracle',
    'MongoDB',
    'S3',
    'HDFS',
    'SFTP',
    'REST_API',
    'Kafka',
  ]),
  direction: z.enum(['source', 'destination', 'bidirectional']),
  host: z.string().min(1, 'Host is required'),
  port: z.coerce.number().int().min(1).max(65535),
  database_name: z.string().optional(),
  username: z.string().optional(),
  password: z.string().optional(),
});

type CreateConnectorForm = z.infer<typeof createConnectorSchema>;

function getStatusColor(status: ConnectorStatus): 'success' | 'error' | 'warning' | 'default' {
  switch (status) {
    case 'active':
      return 'success';
    case 'error':
      return 'error';
    case 'testing':
      return 'warning';
    case 'inactive':
    default:
      return 'default';
  }
}

function HealthIndicator({ status }: { status?: 'healthy' | 'unhealthy' | 'unknown' }) {
  switch (status) {
    case 'healthy':
      return <HealthyIcon color="success" fontSize="small" />;
    case 'unhealthy':
      return <UnhealthyIcon color="error" fontSize="small" />;
    default:
      return <UnknownIcon color="disabled" fontSize="small" />;
  }
}

export default function Connectors() {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(20);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedConnector, setSelectedConnector] = useState<Connector | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);
  const [healthStatuses, setHealthStatuses] = useState<Record<string, 'healthy' | 'unhealthy' | 'unknown'>>({});

  const fetchConnectors = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await connectorsService.list(page + 1, rowsPerPage);
      setConnectors(result.items);
      setTotal(result.total);
    } catch {
      setError('Failed to load connectors');
    } finally {
      setLoading(false);
    }
  }, [page, rowsPerPage]);

  useEffect(() => {
    fetchConnectors();
  }, [fetchConnectors]);

  const createForm = useForm<CreateConnectorForm>({
    resolver: zodResolver(createConnectorSchema),
    defaultValues: {
      name: '',
      type: 'PostgreSQL',
      direction: 'source',
      host: '',
      port: 5432,
      database_name: '',
      username: '',
      password: '',
    },
  });

  const handleCreate = async (data: CreateConnectorForm) => {
    try {
      const payload: CreateConnectorPayload = {
        name: data.name,
        type: data.type,
        direction: data.direction,
        config: {
          host: data.host,
          port: data.port,
          database_name: data.database_name || undefined,
          username: data.username || undefined,
          password: data.password || undefined,
        },
      };
      await connectorsService.create(payload);
      setCreateDialogOpen(false);
      createForm.reset();
      fetchConnectors();
      setSuccess('Connector created successfully');
    } catch {
      setError('Failed to create connector');
    }
  };

  const handleDelete = async () => {
    if (!selectedConnector) return;
    try {
      await connectorsService.delete(selectedConnector.id);
      setDeleteDialogOpen(false);
      setSelectedConnector(null);
      fetchConnectors();
      setSuccess('Connector deleted');
    } catch {
      setError('Failed to delete connector. It may be referenced by active pipelines.');
    }
  };

  const handleTestConnection = async (connector: Connector) => {
    setTestingId(connector.id);
    setTestResult(null);
    try {
      const result = await connectorsService.testConnection(connector.id);
      setTestResult(result);
      if (result.success) {
        setHealthStatuses((prev) => ({ ...prev, [connector.id]: 'healthy' }));
      } else {
        setHealthStatuses((prev) => ({ ...prev, [connector.id]: 'unhealthy' }));
      }
    } catch {
      setTestResult({ success: false, message: 'Connection test failed' });
      setHealthStatuses((prev) => ({ ...prev, [connector.id]: 'unhealthy' }));
    } finally {
      setTestingId(null);
    }
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">Connectors</Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setCreateDialogOpen(true)}
        >
          Create Connector
        </Button>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      {success && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccess(null)}>
          {success}
        </Alert>
      )}
      {testResult && (
        <Alert
          severity={testResult.success ? 'success' : 'error'}
          sx={{ mb: 2 }}
          onClose={() => setTestResult(null)}
        >
          {testResult.message}
          {testResult.latency_ms && ` (${testResult.latency_ms}ms)`}
        </Alert>
      )}

      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              <TableCell>Type</TableCell>
              <TableCell>Direction</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Health</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={6} align="center" sx={{ py: 4 }}>
                  <CircularProgress size={32} />
                </TableCell>
              </TableRow>
            ) : connectors.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} align="center" sx={{ py: 4 }}>
                  <Typography color="text.secondary">No connectors configured</Typography>
                </TableCell>
              </TableRow>
            ) : (
              connectors.map((connector) => (
                <TableRow key={connector.id} hover>
                  <TableCell>{connector.name}</TableCell>
                  <TableCell>
                    <Chip label={connector.type} size="small" variant="outlined" />
                  </TableCell>
                  <TableCell sx={{ textTransform: 'capitalize' }}>{connector.direction}</TableCell>
                  <TableCell>
                    <Chip
                      label={connector.status}
                      size="small"
                      color={getStatusColor(connector.status)}
                    />
                  </TableCell>
                  <TableCell>
                    <HealthIndicator status={healthStatuses[connector.id]} />
                  </TableCell>
                  <TableCell align="right">
                    <Tooltip title="Test Connection">
                      <IconButton
                        size="small"
                        onClick={() => handleTestConnection(connector)}
                        disabled={testingId === connector.id}
                      >
                        {testingId === connector.id ? (
                          <CircularProgress size={18} />
                        ) : (
                          <TestIcon fontSize="small" />
                        )}
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Edit">
                      <IconButton size="small">
                        <EditIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Delete">
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() => {
                          setSelectedConnector(connector);
                          setDeleteDialogOpen(true);
                        }}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
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
          rowsPerPageOptions={[10, 20, 50]}
        />
      </TableContainer>

      {/* Create Connector Dialog */}
      <Dialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <form onSubmit={createForm.handleSubmit(handleCreate)}>
          <DialogTitle>Create Connector</DialogTitle>
          <DialogContent>
            <Stack spacing={2} sx={{ pt: 1 }}>
              <Controller
                name="name"
                control={createForm.control}
                render={({ field, fieldState }) => (
                  <TextField
                    {...field}
                    label="Name"
                    error={!!fieldState.error}
                    helperText={fieldState.error?.message}
                    fullWidth
                  />
                )}
              />
              <Controller
                name="type"
                control={createForm.control}
                render={({ field }) => (
                  <FormControl fullWidth>
                    <InputLabel>Type</InputLabel>
                    <Select {...field} label="Type">
                      {CONNECTOR_TYPES.map((type) => (
                        <MenuItem key={type} value={type}>
                          {type}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                )}
              />
              <Controller
                name="direction"
                control={createForm.control}
                render={({ field }) => (
                  <FormControl fullWidth>
                    <InputLabel>Direction</InputLabel>
                    <Select {...field} label="Direction">
                      {CONNECTOR_DIRECTIONS.map((dir) => (
                        <MenuItem key={dir} value={dir} sx={{ textTransform: 'capitalize' }}>
                          {dir}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                )}
              />
              <Controller
                name="host"
                control={createForm.control}
                render={({ field, fieldState }) => (
                  <TextField
                    {...field}
                    label="Host"
                    error={!!fieldState.error}
                    helperText={fieldState.error?.message}
                    fullWidth
                  />
                )}
              />
              <Controller
                name="port"
                control={createForm.control}
                render={({ field, fieldState }) => (
                  <TextField
                    {...field}
                    label="Port"
                    type="number"
                    error={!!fieldState.error}
                    helperText={fieldState.error?.message}
                    fullWidth
                  />
                )}
              />
              <Controller
                name="database_name"
                control={createForm.control}
                render={({ field }) => (
                  <TextField {...field} label="Database Name" fullWidth />
                )}
              />
              <Controller
                name="username"
                control={createForm.control}
                render={({ field }) => (
                  <TextField {...field} label="Username" fullWidth />
                )}
              />
              <Controller
                name="password"
                control={createForm.control}
                render={({ field }) => (
                  <TextField {...field} label="Password" type="password" fullWidth />
                )}
              />
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setCreateDialogOpen(false)}>Cancel</Button>
            <Button type="submit" variant="contained">
              Create
            </Button>
          </DialogActions>
        </form>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)}>
        <DialogTitle>Delete Connector</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete connector{' '}
            <strong>{selectedConnector?.name}</strong>? Active pipelines using this connector
            will be affected.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleDelete} color="error" variant="contained">
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
