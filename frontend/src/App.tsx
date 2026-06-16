import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { BrowserRouter } from 'react-router-dom';
import { ThemeProvider } from '@mui/material/styles';
import { CssBaseline } from '@mui/material';
import theme from './theme';
import AppRouter from './router';
import { AuthContext, AuthContextType } from './hooks/useAuth';
import { authService } from './services/auth';
import { User, Role } from './types/auth';

function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const isAuthenticated = !!user;

  useEffect(() => {
    const initAuth = async () => {
      if (authService.isLoggedIn()) {
        try {
          const currentUser = await authService.getCurrentUser();
          setUser(currentUser);
        } catch {
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
        }
      }
      setIsLoading(false);
    };

    initAuth();
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const { user: loggedInUser } = await authService.login(username, password);
    setUser(loggedInUser);
  }, []);

  const logout = useCallback(async () => {
    await authService.logout();
    setUser(null);
  }, []);

  const hasRole = useCallback(
    (roles: Role[]): boolean => {
      if (!user) return false;
      return roles.includes(user.role);
    },
    [user]
  );

  const contextValue: AuthContextType = useMemo(
    () => ({
      user,
      isAuthenticated,
      isLoading,
      login,
      logout,
      hasRole,
    }),
    [user, isAuthenticated, isLoading, login, logout, hasRole]
  );

  return (
    <AuthContext.Provider value={contextValue}>
      {children}
    </AuthContext.Provider>
  );
}

export default function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <BrowserRouter>
        <AuthProvider>
          <AppRouter />
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
