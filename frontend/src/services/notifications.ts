import api from './api';
import { PaginatedResponse } from '../types/api';

export type NotificationEventType =
  | 'PIPELINE_FAILURE'
  | 'PIPELINE_SUCCESS'
  | 'CONNECTOR_HEALTH_FAILURE'
  | 'RESOURCE_THRESHOLD'
  | 'KEY_ROTATION_COMPLETE'
  | 'USER_ACCOUNT_LOCKED';

export interface Notification {
  id: string;
  user_id: string;
  event_type: NotificationEventType;
  source_resource_id: string;
  summary: string;
  is_read: boolean;
  recurrence_count: number;
  created_at: string;
  expires_at: string;
}

export const notificationsService = {
  async list(page = 1, pageSize = 20): Promise<PaginatedResponse<Notification>> {
    const response = await api.get<PaginatedResponse<Notification>>('/notifications', {
      params: { page, page_size: pageSize },
    });
    return response.data;
  },

  async getUnreadCount(): Promise<number> {
    const response = await api.get<{ count: number }>('/notifications/unread-count');
    return response.data.count;
  },

  async markAsRead(notificationId: string): Promise<void> {
    await api.patch(`/notifications/${notificationId}/read`);
  },

  async markAllAsRead(): Promise<void> {
    await api.patch('/notifications/read-all');
  },
};
