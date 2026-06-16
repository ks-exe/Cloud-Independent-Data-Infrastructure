import api from './api';
import { TokenPair, User } from '../types/auth';

const TOKEN_KEY = 'access_token';
const REFRESH_KEY = 'refresh_token';

export const authService = {
  async login(username: string, password: string): Promise<{ user: User; tokens: TokenPair }> {
    const response = await api.post<{ user: User } & TokenPair>('/auth/login', {
      username,
      password,
    });

    const { access_token, refresh_token, token_type, user } = response.data;
    const tokens: TokenPair = { access_token, refresh_token, token_type };

    localStorage.setItem(TOKEN_KEY, access_token);
    localStorage.setItem(REFRESH_KEY, refresh_token);

    return { user, tokens };
  },

  async logout(): Promise<void> {
    const refreshToken = localStorage.getItem(REFRESH_KEY);
    try {
      await api.post('/auth/logout', { refresh_token: refreshToken });
    } finally {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(REFRESH_KEY);
    }
  },

  async refreshToken(): Promise<TokenPair> {
    const refreshToken = localStorage.getItem(REFRESH_KEY);
    if (!refreshToken) {
      throw new Error('No refresh token available');
    }

    const response = await api.post<TokenPair>('/auth/refresh', {
      refresh_token: refreshToken,
    });

    const { access_token, refresh_token } = response.data;
    localStorage.setItem(TOKEN_KEY, access_token);
    localStorage.setItem(REFRESH_KEY, refresh_token);

    return response.data;
  },

  async getCurrentUser(): Promise<User> {
    const response = await api.get<User>('/auth/me');
    return response.data;
  },

  getAccessToken(): string | null {
    return localStorage.getItem(TOKEN_KEY);
  },

  isLoggedIn(): boolean {
    return !!localStorage.getItem(TOKEN_KEY);
  },
};
