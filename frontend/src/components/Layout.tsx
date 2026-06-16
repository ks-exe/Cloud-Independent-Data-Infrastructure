import React from 'react';
import { Outlet } from 'react-router-dom';
import {
  Box,
  AppBar,
  Toolbar,
  Typography,
  IconButton,
  Avatar,
  Menu,
  MenuItem,
  Divider,
} from '@mui/material';
import {
  Logout as LogoutIcon,
  Person as PersonIcon,
} from '@mui/icons-material';
import Sidebar, { DRAWER_WIDTH } from './Sidebar';
import NotificationPanel from './notifications/NotificationPanel';
import { useAuth } from '../hooks/useAuth';

export default function Layout() {
  const { user, logout } = useAuth();
  const [anchorEl, setAnchorEl] = React.useState<null | HTMLElement>(null);

  const handleMenuOpen = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleMenuClose = () => {
    setAnchorEl(null);
  };

  const handleLogout = async () => {
    handleMenuClose();
    await logout();
  };

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar />

      <Box sx={{ flexGrow: 1, display: 'flex', flexDirection: 'column' }}>
        <AppBar
          position="fixed"
          elevation={0}
          sx={{
            width: `calc(100% - ${DRAWER_WIDTH}px)`,
            ml: `${DRAWER_WIDTH}px`,
          }}
        >
          <Toolbar>
            <Box sx={{ flexGrow: 1 }} />

            {/* Notifications */}
            <NotificationPanel />

            {/* User menu */}
            <IconButton onClick={handleMenuOpen} sx={{ p: 0.5 }}>
              <Avatar
                sx={{
                  width: 32,
                  height: 32,
                  bgcolor: 'primary.main',
                  fontSize: '0.875rem',
                }}
              >
                {user?.display_name?.charAt(0).toUpperCase() || 'U'}
              </Avatar>
            </IconButton>

            <Menu
              anchorEl={anchorEl}
              open={Boolean(anchorEl)}
              onClose={handleMenuClose}
              anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
              transformOrigin={{ vertical: 'top', horizontal: 'right' }}
            >
              <MenuItem disabled>
                <Box>
                  <Typography variant="body2" fontWeight={600}>
                    {user?.display_name}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {user?.role}
                  </Typography>
                </Box>
              </MenuItem>
              <Divider />
              <MenuItem onClick={handleMenuClose}>
                <PersonIcon fontSize="small" sx={{ mr: 1 }} />
                Profile
              </MenuItem>
              <MenuItem onClick={handleLogout}>
                <LogoutIcon fontSize="small" sx={{ mr: 1 }} />
                Logout
              </MenuItem>
            </Menu>
          </Toolbar>
        </AppBar>

        {/* Main content area */}
        <Box
          component="main"
          sx={{
            flexGrow: 1,
            p: 3,
            mt: '64px', // Toolbar height
            overflow: 'auto',
          }}
        >
          <Outlet />
        </Box>
      </Box>
    </Box>
  );
}
