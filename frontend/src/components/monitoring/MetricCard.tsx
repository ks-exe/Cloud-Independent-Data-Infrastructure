import { Card, CardContent, Typography, Box } from '@mui/material';
import { ReactNode } from 'react';

interface MetricCardProps {
  title: string;
  value: string | number;
  icon?: ReactNode;
  subtitle?: string;
  color?: string;
}

/**
 * Reusable metric display card for the monitoring dashboard.
 * Shows a title, large value, optional icon, and optional subtitle.
 */
export default function MetricCard({
  title,
  value,
  icon,
  subtitle,
  color,
}: MetricCardProps) {
  return (
    <Card
      sx={{
        height: '100%',
        borderLeft: color ? `4px solid ${color}` : undefined,
      }}
    >
      <CardContent>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            mb: 1,
          }}
        >
          <Typography variant="body2" color="text.secondary">
            {title}
          </Typography>
          {icon && (
            <Box sx={{ color: color || 'text.secondary' }}>{icon}</Box>
          )}
        </Box>
        <Typography
          variant="h4"
          sx={{ fontWeight: 700, color: color || 'text.primary' }}
        >
          {value}
        </Typography>
        {subtitle && (
          <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>
            {subtitle}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}
