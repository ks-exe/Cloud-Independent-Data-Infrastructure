import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Typography,
  Box,
  Divider,
} from '@mui/material';
import {
  Dashboard as DashboardIcon,
  AccountTree as PipelineIcon,
  Storage as ConnectorIcon,
  MonitorHeart as MonitoringIcon,
  Timeline as LineageIcon,
  Security as AuditIcon,
  People as UsersIcon,
  Settings as SettingsIcon,
  Hub as LogoIcon,
} from '@mui/icons-material';
import { useAuth } from '../hooks/useAuth';
import { Role } from '../types/auth';

export const DRAWER_WIDTH = 260;

interface NavItem {
  label: string;
  path: string;
  icon: React.ReactNode;
  roles: Role[];
}

const navItems: NavItem[] = [
  {
    label: 'Dashboard',
    path: '/',
    icon: <DashboardIcon />,
    roles: ['Admin', 'Data_Engineer', 'Operator', 'Auditor', 'Viewer'],
  },
  {
    label: 'Pipelines',
    path: '/pipelines',
    icon: <PipelineIcon />,
    roles: ['Data_Engineer', 'Admin', 'Operator', 'Auditor', 'Viewer'],
  },
  {
    label: 'Connectors',
    path: '/connectors',
    icon: <ConnectorIcon />,
    roles: ['Data_Engineer', 'Admin', 'Viewer'],
  },
  {
    label: 'Monitoring',
    path: '/monitoring',
    icon: <MonitoringIcon />,
    roles: ['Operator', 'Admin', 'Viewer'],
  },
  {
    label: 'Lineage',
    path: '/lineage',
    icon: <LineageIcon />,
    roles: ['Auditor', 'Admin'],
  },
  {
    label: 'Audit Logs',
    path: '/audit',
    icon: <AuditIcon />,
    roles: ['Auditor', 'Admin'],
  },
  {
    label: 'User Management',
    path: '/users',
    icon: <UsersIcon />,
    roles: ['Admin'],
  },
  {
    label: 'Settings',
    path: '/settings',
    icon: <SettingsIcon />,
    roles: ['Admin'],
  },
];

export default function Sidebar() {
  const { hasRole } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  const visibleItems = navItems.filter((item) => hasRole(item.roles));

  return (
    <Drawer
      variant="permanent"
      sx={{
        width: DRAWER_WIDTH,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width: DRAWER_WIDTH,
          boxSizing: 'border-box',
        },
      }}
    >
      <Toolbar>
        <Box display="flex" alignItems="center" gap={1}>
          <LogoIcon sx={{ color: 'primary.main' }} />
          <Typography variant="h6" noWrap color="primary.main">
            DataPlatform
          </Typography>
        </Box>
      </Toolbar>
      <Divider />
      <List sx={{ px: 1, pt: 1 }}>
        {visibleItems.map((item) => {
          const isActive =
            item.path === '/'
              ? location.pathname === '/'
              : location.pathname.startsWith(item.path);

          return (
            <ListItem key={item.path} disablePadding sx={{ mb: 0.5 }}>
              <ListItemButton
                selected={isActive}
                onClick={() => navigate(item.path)}
                sx={{
                  borderRadius: 1,
                  '&.Mui-selected': {
                    backgroundColor: 'primary.dark',
                    '&:hover': {
                      backgroundColor: 'primary.dark',
                    },
                  },
                }}
              >
                <ListItemIcon
                  sx={{
                    color: isActive ? 'primary.light' : 'text.secondary',
                    minWidth: 40,
                  }}
                >
                  {item.icon}
                </ListItemIcon>
                <ListItemText
                  primary={item.label}
                  primaryTypographyProps={{
                    fontSize: '0.875rem',
                    fontWeight: isActive ? 600 : 400,
                  }}
                />
              </ListItemButton>
            </ListItem>
          );
        })}
      </List>
    </Drawer>
  );
}
