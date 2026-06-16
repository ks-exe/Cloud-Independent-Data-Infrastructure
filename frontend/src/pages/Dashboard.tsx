import { Typography, Box } from '@mui/material';

export default function Dashboard() {
  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Dashboard
      </Typography>
      <Typography color="text.secondary">
        Overview of pipeline executions, system health, and recent activity.
      </Typography>
    </Box>
  );
}
