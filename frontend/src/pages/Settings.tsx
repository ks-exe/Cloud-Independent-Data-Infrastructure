import { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Paper,
  Button,
  Alert,
  CircularProgress,
  Divider,
  List,
  ListItem,
  ListItemText,
  Stack,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Chip,
} from '@mui/material';
import {
  VpnKey as KeyIcon,
  Schedule as RetentionIcon,
  Refresh as RotateIcon,
} from '@mui/icons-material';
import api from '../services/api';

interface SystemSetting {
  id: string;
  key: string;
  value: unknown;
  category: string;
  updated_at: string;
}

interface KeyRotationStatus {
  last_rotation: string | null;
  next_scheduled: string | null;
  status: 'idle' | 'in_progress' | 'failed';
}

export default function Settings() {
  const [settings, setSettings] = useState<SystemSetting[]>([]);
  const [keyRotationStatus, setKeyRotationStatus] = useState<KeyRotationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [rotateDialogOpen, setRotateDialogOpen] = useState(false);
  const [rotating, setRotating] = useState(false);

  useEffect(() => {
    fetchSettings();
  }, []);

  const fetchSettings = async () => {
    setLoading(true);
    try {
      const [settingsRes, keyStatusRes] = await Promise.all([
        api.get<{ items: SystemSetting[] }>('/settings'),
        api.get<KeyRotationStatus>('/settings/key-rotation-status'),
      ]);
      setSettings(settingsRes.data.items || []);
      setKeyRotationStatus(keyStatusRes.data);
    } catch {
      setError('Failed to load settings');
    } finally {
      setLoading(false);
    }
  };

  const handleKeyRotation = async () => {
    setRotating(true);
    setRotateDialogOpen(false);
    try {
      await api.post('/settings/rotate-key');
      setSuccess('Key rotation initiated successfully');
      fetchSettings();
    } catch {
      setError('Key rotation failed. Check system logs for details.');
    } finally {
      setRotating(false);
    }
  };

  const retentionSettings = settings.filter((s) => s.category === 'retention');
  const securitySettings = settings.filter((s) => s.category === 'security');

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        System Settings
      </Typography>

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

      {/* Key Rotation Section */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
          <KeyIcon color="primary" />
          <Typography variant="h6">Encryption Key Rotation</Typography>
        </Stack>
        <Divider sx={{ mb: 2 }} />

        {keyRotationStatus && (
          <Stack spacing={2}>
            <Box sx={{ display: 'flex', gap: 4 }}>
              <Box>
                <Typography variant="body2" color="text.secondary">
                  Status
                </Typography>
                <Chip
                  label={keyRotationStatus.status.replace('_', ' ')}
                  size="small"
                  color={
                    keyRotationStatus.status === 'idle'
                      ? 'success'
                      : keyRotationStatus.status === 'in_progress'
                      ? 'warning'
                      : 'error'
                  }
                  sx={{ mt: 0.5 }}
                />
              </Box>
              <Box>
                <Typography variant="body2" color="text.secondary">
                  Last Rotation
                </Typography>
                <Typography variant="body1">
                  {keyRotationStatus.last_rotation
                    ? new Date(keyRotationStatus.last_rotation).toLocaleString()
                    : 'Never'}
                </Typography>
              </Box>
              <Box>
                <Typography variant="body2" color="text.secondary">
                  Next Scheduled
                </Typography>
                <Typography variant="body1">
                  {keyRotationStatus.next_scheduled
                    ? new Date(keyRotationStatus.next_scheduled).toLocaleString()
                    : 'Not scheduled'}
                </Typography>
              </Box>
            </Box>

            <Box>
              <Button
                variant="outlined"
                color="warning"
                startIcon={rotating ? <CircularProgress size={16} /> : <RotateIcon />}
                onClick={() => setRotateDialogOpen(true)}
                disabled={rotating || keyRotationStatus.status === 'in_progress'}
              >
                Rotate Key Now
              </Button>
            </Box>
          </Stack>
        )}
      </Paper>

      {/* Retention Settings */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
          <RetentionIcon color="primary" />
          <Typography variant="h6">Data Retention</Typography>
        </Stack>
        <Divider sx={{ mb: 2 }} />

        {retentionSettings.length === 0 ? (
          <Typography color="text.secondary">No retention settings configured</Typography>
        ) : (
          <List disablePadding>
            {retentionSettings.map((setting) => (
              <ListItem key={setting.id} disableGutters divider>
                <ListItemText
                  primary={setting.key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                  secondary={`Value: ${JSON.stringify(setting.value)} • Updated: ${new Date(setting.updated_at).toLocaleString()}`}
                />
              </ListItem>
            ))}
          </List>
        )}
      </Paper>

      {/* Security Settings Display */}
      {securitySettings.length > 0 && (
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Security
          </Typography>
          <Divider sx={{ mb: 2 }} />
          <List disablePadding>
            {securitySettings.map((setting) => (
              <ListItem key={setting.id} disableGutters divider>
                <ListItemText
                  primary={setting.key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                  secondary={`Value: ${JSON.stringify(setting.value)}`}
                />
              </ListItem>
            ))}
          </List>
        </Paper>
      )}

      {/* Rotate Key Confirmation Dialog */}
      <Dialog open={rotateDialogOpen} onClose={() => setRotateDialogOpen(false)}>
        <DialogTitle>Confirm Key Rotation</DialogTitle>
        <DialogContent>
          <Typography>
            This will rotate the master encryption key and re-encrypt all stored credentials.
            This operation may take a few minutes. Are you sure you want to proceed?
          </Typography>
          <Alert severity="warning" sx={{ mt: 2 }}>
            Ensure no pipeline executions are in progress before rotating keys.
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRotateDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleKeyRotation} color="warning" variant="contained">
            Rotate Key
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
