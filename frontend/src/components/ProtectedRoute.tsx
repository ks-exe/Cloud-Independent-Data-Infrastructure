import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { CircularProgress, Box } from '@mui/material';
import { useAuth } from '../hooks/useAuth';
import { Role } from '../types/auth';

interface ProtectedRouteProps {
  children: React.ReactNode;
  allowedRoles?: Role[];
}

export default function ProtectedRoute({ children, allowedRoles }: ProtectedRouteProps) {
  const { isAuthenticated, isLoading, user, hasRole } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <Box
        display="flex"
        justifyContent="center"
        alignItems="center"
        minHeight="100vh"
      >
        <CircularProgress />
      </Box>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (allowedRoles && !hasRole(allowedRoles)) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}
