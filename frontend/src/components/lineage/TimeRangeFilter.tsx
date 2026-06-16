import { useState } from 'react';
import { Box, TextField, Button, Stack } from '@mui/material';
import { format, subDays } from 'date-fns';

interface TimeRangeFilterProps {
  onApply: (start: string, end: string) => void;
  loading?: boolean;
}

/**
 * Date range picker for filtering lineage events by time range.
 * Provides start/end date inputs and an Apply button.
 */
export default function TimeRangeFilter({ onApply, loading }: TimeRangeFilterProps) {
  const [startDate, setStartDate] = useState<string>(
    format(subDays(new Date(), 30), 'yyyy-MM-dd')
  );
  const [endDate, setEndDate] = useState<string>(
    format(new Date(), 'yyyy-MM-dd')
  );

  const handleApply = () => {
    const start = new Date(startDate).toISOString();
    const end = new Date(endDate + 'T23:59:59').toISOString();
    onApply(start, end);
  };

  return (
    <Box>
      <Stack direction="row" spacing={2} alignItems="center">
        <TextField
          label="Start Date"
          type="date"
          size="small"
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
          InputLabelProps={{ shrink: true }}
          inputProps={{ max: endDate }}
        />
        <TextField
          label="End Date"
          type="date"
          size="small"
          value={endDate}
          onChange={(e) => setEndDate(e.target.value)}
          InputLabelProps={{ shrink: true }}
          inputProps={{ min: startDate }}
        />
        <Button
          variant="contained"
          size="small"
          onClick={handleApply}
          disabled={loading || !startDate || !endDate}
        >
          Apply Filter
        </Button>
      </Stack>
    </Box>
  );
}
