import React, { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { CircularProgress, Box } from '@mui/material';
import Layout from './components/Layout';
import ProtectedRoute from './components/ProtectedRoute';
import { Role } from './types/auth';

// Lazy-loaded page components
const Login = lazy(() => import('./pages/Login'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Pipelines = lazy(() => import('./pages/Pipelines'));
const PipelineBuilder = lazy(() => import('./pages/PipelineBuilder'));
const Connectors = lazy(() => import('./pages/Connectors'));
const Monitoring = lazy(() => import('./pages/Monitoring'));
const Lineage = lazy(() => import('./pages/Lineage'));
const AuditLogs = lazy(() => import('./pages/AuditLogs'));
const Users = lazy(() => import('./pages/Users'));
const Settings = lazy(() => import('./pages/Settings'));

function PageLoader() {
  return (
    <Box display="flex" justifyContent="center" alignItems="center" minHeight="60vh">
      <CircularProgress />
    </Box>
  );
}

function withSuspense(Component: React.LazyExoticComponent<React.ComponentType>) {
  return (
    <Suspense fallback={<PageLoader />}>
      <Component />
    </Suspense>
  );
}

const ALL_ROLES: Role[] = ['Admin', 'Data_Engineer', 'Operator', 'Auditor', 'Viewer'];

export default function AppRouter() {
  return (
    <Routes>
      <Route path="/login" element={withSuspense(Login)} />

      {/* Protected routes with layout */}
      <Route
        path="/"
        element={
          <ProtectedRoute allowedRoles={ALL_ROLES}>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={withSuspense(Dashboard)} />
        <Route
          path="pipelines"
          element={
            <ProtectedRoute allowedRoles={['Data_Engineer', 'Admin', 'Operator', 'Auditor', 'Viewer']}>
              {withSuspense(Pipelines)}
            </ProtectedRoute>
          }
        />
        <Route
          path="pipelines/builder"
          element={
            <ProtectedRoute allowedRoles={['Data_Engineer', 'Admin']}>
              {withSuspense(PipelineBuilder)}
            </ProtectedRoute>
          }
        />
        <Route
          path="connectors"
          element={
            <ProtectedRoute allowedRoles={['Data_Engineer', 'Admin', 'Viewer']}>
              {withSuspense(Connectors)}
            </ProtectedRoute>
          }
        />
        <Route
          path="monitoring"
          element={
            <ProtectedRoute allowedRoles={['Operator', 'Admin', 'Viewer']}>
              {withSuspense(Monitoring)}
            </ProtectedRoute>
          }
        />
        <Route
          path="lineage"
          element={
            <ProtectedRoute allowedRoles={['Auditor', 'Admin']}>
              {withSuspense(Lineage)}
            </ProtectedRoute>
          }
        />
        <Route
          path="audit"
          element={
            <ProtectedRoute allowedRoles={['Auditor', 'Admin']}>
              {withSuspense(AuditLogs)}
            </ProtectedRoute>
          }
        />
        <Route
          path="users"
          element={
            <ProtectedRoute allowedRoles={['Admin']}>
              {withSuspense(Users)}
            </ProtectedRoute>
          }
        />
        <Route
          path="settings"
          element={
            <ProtectedRoute allowedRoles={['Admin']}>
              {withSuspense(Settings)}
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
