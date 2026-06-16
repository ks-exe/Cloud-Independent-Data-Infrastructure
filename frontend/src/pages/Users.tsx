import React, { useState, useEffect, useCallback } from 'react';
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
} from '@mui/material';
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  Block as BlockIcon,
  CheckCircle as EnableIcon,
  LockReset as ResetPasswordIcon,
} from '@mui/icons-material';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { usersService, CreateUserPayload, UpdateUserPayload } from '../services/users';
import { User, Role } from '../types/auth';

const ROLES: Role[] = ['Admin', 'Data_Engineer', 'Operator', 'Auditor', 'Viewer'];

const createUserSchema = z.object({
  username: z
    .string()
    .min(3, 'Username must be at least 3 characters')
    .max(64, 'Username must be at most 64 characters')
    .regex(/^[a-zA-Z0-9_]+$/, 'Only alphanumeric characters and underscores'),
  email: z.string().email('Invalid email address'),
  display_name: z.string().min(1, 'Display name is required').max(128),
  password: z
    .string()
    .min(8, 'Password must be at least 8 characters')
    .max(128),
  role: z.enum(['Admin', 'Data_Engineer', 'Operator', 'Auditor', 'Viewer']),
});

const editUserSchema = z.object({
  email: z.string().email('Invalid email address'),
  display_name: z.string().min(1, 'Display name is required').max(128),
  role: z.enum(['Admin', 'Data_Engineer', 'Operator', 'Auditor', 'Viewer']),
});

type CreateUserForm = z.infer<typeof createUserSchema>;
type EditUserForm = z.infer<typeof editUserSchema>;

export default function Users() {
  const [users, setUsers] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(20);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await usersService.list(page + 1, rowsPerPage);
      setUsers(result.items);
      setTotal(result.total);
    } catch {
      setError('Failed to load users');
    } finally {
      setLoading(false);
    }
  }, [page, rowsPerPage]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  // Create form
  const createForm = useForm<CreateUserForm>({
    resolver: zodResolver(createUserSchema),
    defaultValues: { username: '', email: '', display_name: '', password: '', role: 'Viewer' },
  });

  // Edit form
  const editForm = useForm<EditUserForm>({
    resolver: zodResolver(editUserSchema),
  });

  const handleCreate = async (data: CreateUserForm) => {
    try {
      await usersService.create(data as CreateUserPayload);
      setCreateDialogOpen(false);
      createForm.reset();
      fetchUsers();
    } catch {
      setError('Failed to create user');
    }
  };

  const handleEdit = async (data: EditUserForm) => {
    if (!selectedUser) return;
    try {
      await usersService.update(selectedUser.id, data as UpdateUserPayload);
      setEditDialogOpen(false);
      setSelectedUser(null);
      fetchUsers();
    } catch {
      setError('Failed to update user');
    }
  };

  const handleDelete = async () => {
    if (!selectedUser) return;
    try {
      await usersService.delete(selectedUser.id);
      setDeleteDialogOpen(false);
      setSelectedUser(null);
      fetchUsers();
    } catch {
      setError('Failed to delete user');
    }
  };

  const handleToggleActive = async (user: User) => {
    try {
      if (user.is_active) {
        await usersService.disable(user.id);
      } else {
        await usersService.enable(user.id);
      }
      fetchUsers();
    } catch {
      setError('Failed to update user status');
    }
  };

  const handleResetPassword = async (user: User) => {
    try {
      await usersService.resetPassword(user.id);
      setError(null);
    } catch {
      setError('Failed to initiate password reset');
    }
  };

  const openEditDialog = (user: User) => {
    setSelectedUser(user);
    editForm.reset({ email: user.email, display_name: user.display_name, role: user.role });
    setEditDialogOpen(true);
  };

  const openDeleteDialog = (user: User) => {
    setSelectedUser(user);
    setDeleteDialogOpen(true);
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">User Management</Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setCreateDialogOpen(true)}
        >
          Create User
        </Button>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Username</TableCell>
              <TableCell>Email</TableCell>
              <TableCell>Display Name</TableCell>
              <TableCell>Role</TableCell>
              <TableCell>Status</TableCell>
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
            ) : users.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} align="center" sx={{ py: 4 }}>
                  <Typography color="text.secondary">No users found</Typography>
                </TableCell>
              </TableRow>
            ) : (
              users.map((user) => (
                <TableRow key={user.id} hover>
                  <TableCell>{user.username}</TableCell>
                  <TableCell>{user.email}</TableCell>
                  <TableCell>{user.display_name}</TableCell>
                  <TableCell>
                    <Chip
                      label={user.role.replace('_', ' ')}
                      size="small"
                      color={user.role === 'Admin' ? 'error' : 'default'}
                      variant="outlined"
                    />
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={user.is_active ? 'Active' : 'Disabled'}
                      size="small"
                      color={user.is_active ? 'success' : 'default'}
                    />
                  </TableCell>
                  <TableCell align="right">
                    <Tooltip title="Edit">
                      <IconButton size="small" onClick={() => openEditDialog(user)}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title={user.is_active ? 'Disable' : 'Enable'}>
                      <IconButton size="small" onClick={() => handleToggleActive(user)}>
                        {user.is_active ? (
                          <BlockIcon fontSize="small" />
                        ) : (
                          <EnableIcon fontSize="small" />
                        )}
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Reset Password">
                      <IconButton size="small" onClick={() => handleResetPassword(user)}>
                        <ResetPasswordIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Delete">
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() => openDeleteDialog(user)}
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
          onPageChange={(_, newPage) => setPage(newPage)}
          rowsPerPage={rowsPerPage}
          onRowsPerPageChange={(e) => {
            setRowsPerPage(parseInt(e.target.value, 10));
            setPage(0);
          }}
          rowsPerPageOptions={[10, 20, 50]}
        />
      </TableContainer>

      {/* Create User Dialog */}
      <Dialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <form onSubmit={createForm.handleSubmit(handleCreate)}>
          <DialogTitle>Create User</DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
            <Controller
              name="username"
              control={createForm.control}
              render={({ field, fieldState }) => (
                <TextField
                  {...field}
                  label="Username"
                  error={!!fieldState.error}
                  helperText={fieldState.error?.message}
                  fullWidth
                  margin="dense"
                />
              )}
            />
            <Controller
              name="email"
              control={createForm.control}
              render={({ field, fieldState }) => (
                <TextField
                  {...field}
                  label="Email"
                  type="email"
                  error={!!fieldState.error}
                  helperText={fieldState.error?.message}
                  fullWidth
                  margin="dense"
                />
              )}
            />
            <Controller
              name="display_name"
              control={createForm.control}
              render={({ field, fieldState }) => (
                <TextField
                  {...field}
                  label="Display Name"
                  error={!!fieldState.error}
                  helperText={fieldState.error?.message}
                  fullWidth
                  margin="dense"
                />
              )}
            />
            <Controller
              name="password"
              control={createForm.control}
              render={({ field, fieldState }) => (
                <TextField
                  {...field}
                  label="Password"
                  type="password"
                  error={!!fieldState.error}
                  helperText={fieldState.error?.message}
                  fullWidth
                  margin="dense"
                />
              )}
            />
            <Controller
              name="role"
              control={createForm.control}
              render={({ field }) => (
                <FormControl fullWidth margin="dense">
                  <InputLabel>Role</InputLabel>
                  <Select {...field} label="Role">
                    {ROLES.map((role) => (
                      <MenuItem key={role} value={role}>
                        {role.replace('_', ' ')}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              )}
            />
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setCreateDialogOpen(false)}>Cancel</Button>
            <Button type="submit" variant="contained">
              Create
            </Button>
          </DialogActions>
        </form>
      </Dialog>

      {/* Edit User Dialog */}
      <Dialog
        open={editDialogOpen}
        onClose={() => setEditDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <form onSubmit={editForm.handleSubmit(handleEdit)}>
          <DialogTitle>Edit User: {selectedUser?.username}</DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
            <Controller
              name="email"
              control={editForm.control}
              render={({ field, fieldState }) => (
                <TextField
                  {...field}
                  label="Email"
                  type="email"
                  error={!!fieldState.error}
                  helperText={fieldState.error?.message}
                  fullWidth
                  margin="dense"
                />
              )}
            />
            <Controller
              name="display_name"
              control={editForm.control}
              render={({ field, fieldState }) => (
                <TextField
                  {...field}
                  label="Display Name"
                  error={!!fieldState.error}
                  helperText={fieldState.error?.message}
                  fullWidth
                  margin="dense"
                />
              )}
            />
            <Controller
              name="role"
              control={editForm.control}
              render={({ field }) => (
                <FormControl fullWidth margin="dense">
                  <InputLabel>Role</InputLabel>
                  <Select {...field} label="Role">
                    {ROLES.map((role) => (
                      <MenuItem key={role} value={role}>
                        {role.replace('_', ' ')}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              )}
            />
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setEditDialogOpen(false)}>Cancel</Button>
            <Button type="submit" variant="contained">
              Save Changes
            </Button>
          </DialogActions>
        </form>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)}>
        <DialogTitle>Delete User</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete user <strong>{selectedUser?.username}</strong>? This
            action cannot be undone.
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
