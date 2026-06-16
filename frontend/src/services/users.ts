import api from './api';
import { PaginatedResponse } from '../types/api';
import { User, Role } from '../types/auth';

export interface CreateUserPayload {
  username: string;
  email: string;
  display_name: string;
  password: string;
  role: Role;
}

export interface UpdateUserPayload {
  email?: string;
  display_name?: string;
  role?: Role;
  is_active?: boolean;
}

export const usersService = {
  async list(page = 1, pageSize = 20): Promise<PaginatedResponse<User>> {
    const response = await api.get<PaginatedResponse<User>>('/users', {
      params: { page, page_size: pageSize },
    });
    return response.data;
  },

  async getById(userId: string): Promise<User> {
    const response = await api.get<User>(`/users/${userId}`);
    return response.data;
  },

  async create(payload: CreateUserPayload): Promise<User> {
    const response = await api.post<User>('/users', payload);
    return response.data;
  },

  async update(userId: string, payload: UpdateUserPayload): Promise<User> {
    const response = await api.patch<User>(`/users/${userId}`, payload);
    return response.data;
  },

  async delete(userId: string): Promise<void> {
    await api.delete(`/users/${userId}`);
  },

  async disable(userId: string): Promise<User> {
    const response = await api.patch<User>(`/users/${userId}`, { is_active: false });
    return response.data;
  },

  async enable(userId: string): Promise<User> {
    const response = await api.patch<User>(`/users/${userId}`, { is_active: true });
    return response.data;
  },

  async resetPassword(userId: string): Promise<{ message: string }> {
    const response = await api.post<{ message: string }>(`/users/${userId}/reset-password`);
    return response.data;
  },
};
