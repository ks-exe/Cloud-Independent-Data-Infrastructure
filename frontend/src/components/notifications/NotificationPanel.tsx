import React, { useState, useEffect, useCallback } from 'react';
import {
  IconButton,
  Badge,
  Popover,
  Box,
  Typography,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  Divider,
  Button,
  Chip,
  CircularProgress,
} from '@mui/material';
import {
  Notifications as NotificationsIcon,
  Error as ErrorIcon,
  CheckCircle as SuccessIcon,
  Warning as WarningIcon,
  Info as InfoIcon,
  VpnKey as KeyIcon,
  PersonOff as LockedIcon,
  DoneAll as MarkAllReadIcon,
} from '@mui/icons-material';
import { formatDistanceToNow } from 'date-fns';
import {
  notificationsService,
  Notification,
  NotificationEventType,
} from '../../services/notifications';

function getNotificationIcon(eventType: NotificationEventType) {
  switch (eventType) {
    case 'PIPELINE_FAILURE':
      return <ErrorIcon color="error" fontSize="small" />;
    case 'PIPELINE_SUCCESS':
      return <SuccessIcon color="success" fontSize="small" />;
    case 'CONNECTOR_HEALTH_FAILURE':
      return <WarningIcon color="warning" fontSize="small" />;
    case 'RESOURCE_THRESHOLD':
      return <WarningIcon color="warning" fontSize="small" />;
    case 'KEY_ROTATION_COMPLETE':
      return <KeyIcon color="info" fontSize="small" />;
    case 'USER_ACCOUNT_LOCKED':
      return <LockedIcon color="error" fontSize="small" />;
    default:
      return <InfoIcon color="info" fontSize="small" />;
  }
}

function getEventLabel(eventType: NotificationEventType): string {
  return eventType.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function NotificationPanel() {
  const [anchorEl, setAnchorEl] = useState<HTMLButtonElement | null>(null);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);

  const fetchUnreadCount = useCallback(async () => {
    try {
      const count = await notificationsService.getUnreadCount();
      setUnreadCount(count);
    } catch {
      // Silently fail for unread count polling
    }
  }, []);

  const fetchNotifications = useCallback(async () => {
    setLoading(true);
    try {
      const result = await notificationsService.list(1, 20);
      setNotifications(result.items);
    } catch {
      // Silently fail
    } finally {
      setLoading(false);
    }
  }, []);

  // Poll unread count every 30 seconds
  useEffect(() => {
    fetchUnreadCount();
    const interval = setInterval(fetchUnreadCount, 30000);
    return () => clearInterval(interval);
  }, [fetchUnreadCount]);

  const handleOpen = (event: React.MouseEvent<HTMLButtonElement>) => {
    setAnchorEl(event.currentTarget);
    fetchNotifications();
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const handleMarkAsRead = async (notificationId: string) => {
    try {
      await notificationsService.markAsRead(notificationId);
      setNotifications((prev) =>
        prev.map((n) => (n.id === notificationId ? { ...n, is_read: true } : n))
      );
      setUnreadCount((prev) => Math.max(0, prev - 1));
    } catch {
      // Silently fail
    }
  };

  const handleMarkAllAsRead = async () => {
    try {
      await notificationsService.markAllAsRead();
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
      setUnreadCount(0);
    } catch {
      // Silently fail
    }
  };

  const open = Boolean(anchorEl);

  return (
    <>
      <IconButton color="inherit" onClick={handleOpen} sx={{ mr: 1 }}>
        <Badge badgeContent={unreadCount} color="error">
          <NotificationsIcon />
        </Badge>
      </IconButton>

      <Popover
        open={open}
        anchorEl={anchorEl}
        onClose={handleClose}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        slotProps={{
          paper: {
            sx: { width: 380, maxHeight: 480 },
          },
        }}
      >
        <Box
          sx={{
            p: 2,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <Typography variant="h6" fontSize="1rem">
            Notifications
          </Typography>
          {unreadCount > 0 && (
            <Button
              size="small"
              startIcon={<MarkAllReadIcon />}
              onClick={handleMarkAllAsRead}
            >
              Mark all read
            </Button>
          )}
        </Box>
        <Divider />

        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={24} />
          </Box>
        ) : notifications.length === 0 ? (
          <Box sx={{ py: 4, textAlign: 'center' }}>
            <Typography color="text.secondary" variant="body2">
              No notifications
            </Typography>
          </Box>
        ) : (
          <List disablePadding sx={{ overflow: 'auto', maxHeight: 380 }}>
            {notifications.map((notification, idx) => (
              <React.Fragment key={notification.id}>
                <ListItem
                  alignItems="flex-start"
                  sx={{
                    bgcolor: notification.is_read ? 'transparent' : 'action.hover',
                    cursor: notification.is_read ? 'default' : 'pointer',
                    '&:hover': { bgcolor: 'action.selected' },
                  }}
                  onClick={() => {
                    if (!notification.is_read) {
                      handleMarkAsRead(notification.id);
                    }
                  }}
                >
                  <ListItemIcon sx={{ minWidth: 36, mt: 0.5 }}>
                    {getNotificationIcon(notification.event_type)}
                  </ListItemIcon>
                  <ListItemText
                    primary={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Chip
                          label={getEventLabel(notification.event_type)}
                          size="small"
                          variant="outlined"
                          sx={{ fontSize: '0.7rem', height: 20 }}
                        />
                        {notification.recurrence_count > 1 && (
                          <Chip
                            label={`×${notification.recurrence_count}`}
                            size="small"
                            color="warning"
                            sx={{ fontSize: '0.7rem', height: 20 }}
                          />
                        )}
                      </Box>
                    }
                    secondary={
                      <>
                        <Typography
                          component="span"
                          variant="body2"
                          color="text.primary"
                          sx={{ display: 'block', mt: 0.5 }}
                        >
                          {notification.summary}
                        </Typography>
                        <Typography
                          component="span"
                          variant="caption"
                          color="text.secondary"
                        >
                          {formatDistanceToNow(new Date(notification.created_at), {
                            addSuffix: true,
                          })}
                        </Typography>
                      </>
                    }
                  />
                </ListItem>
                {idx < notifications.length - 1 && <Divider component="li" />}
              </React.Fragment>
            ))}
          </List>
        )}
      </Popover>
    </>
  );
}
