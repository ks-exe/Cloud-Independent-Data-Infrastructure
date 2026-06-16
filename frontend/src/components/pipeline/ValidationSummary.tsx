import { Box, Alert, AlertTitle, List, ListItem, ListItemIcon, ListItemText } from '@mui/material';
import { ErrorOutline as ErrorIcon } from '@mui/icons-material';
import { ValidationError } from '../../services/pipeline';

interface ValidationSummaryProps {
  errors: ValidationError[];
  onClose: () => void;
}

export default function ValidationSummary({ errors, onClose }: ValidationSummaryProps) {
  if (errors.length === 0) return null;

  return (
    <Box
      sx={{
        position: 'absolute',
        bottom: 16,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 1000,
        maxWidth: 500,
        width: '90%',
      }}
    >
      <Alert
        severity="error"
        onClose={onClose}
        sx={{
          bgcolor: '#1e293b',
          border: '1px solid #ef4444',
          '& .MuiAlert-icon': { color: '#ef4444' },
        }}
      >
        <AlertTitle sx={{ fontWeight: 700 }}>
          Pipeline Validation Failed ({errors.length} {errors.length === 1 ? 'error' : 'errors'})
        </AlertTitle>
        <List dense disablePadding>
          {errors.map((error, index) => (
            <ListItem key={index} disableGutters sx={{ py: 0.25 }}>
              <ListItemIcon sx={{ minWidth: 28 }}>
                <ErrorIcon sx={{ fontSize: 16, color: '#ef4444' }} />
              </ListItemIcon>
              <ListItemText
                primary={error.message}
                secondary={
                  error.node_id
                    ? `Node: ${error.node_id}`
                    : error.edge_id
                      ? `Edge: ${error.edge_id}`
                      : undefined
                }
                primaryTypographyProps={{ fontSize: '0.8rem' }}
                secondaryTypographyProps={{ fontSize: '0.7rem', color: 'text.secondary' }}
              />
            </ListItem>
          ))}
        </List>
      </Alert>
    </Box>
  );
}
