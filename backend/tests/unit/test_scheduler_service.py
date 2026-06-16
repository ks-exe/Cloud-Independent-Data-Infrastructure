"""Unit tests for SchedulerService.

Tests cover:
- Cron expression validation (5-field format, min interval >= 1 minute)
- Schedule CRUD operations (create, update, pause, resume, delete)
- Dagster integration (mock client calls)
- Concurrency handling (queue when previous execution running)
- Skip logic (deleted pipeline, invalid DAG)

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.schemas.schedule import CronValidationResult, ScheduleResponse
from backend.app.services.scheduler_service import (
    DagsterScheduleClient,
    InvalidCronExpressionError,
    PipelineNotFoundForScheduleError,
    ScheduleNotFoundError,
    SchedulerService,
    SchedulerServiceError,
    validate_cron,
)


# --- Helpers ---


def _make_schedule_model(
    schedule_id=None,
    pipeline_id=None,
    cron_expression="0 * * * *",
    status="active",
    dagster_schedule_name=None,
    user_id=None,
):
    """Create a mock PipelineSchedule model."""
    if schedule_id is None:
        schedule_id = uuid.uuid4()
    if pipeline_id is None:
        pipeline_id = uuid.uuid4()
    if user_id is None:
        user_id = uuid.uuid4()
    if dagster_schedule_name is None:
        dagster_schedule_name = f"schedule_{pipeline_id}_{uuid.uuid4().hex[:8]}"

    schedule = MagicMock()
    schedule.id = schedule_id
    schedule.pipeline_id = pipeline_id
    schedule.cron_expression = cron_expression
    schedule.status = status
    schedule.dagster_schedule_name = dagster_schedule_name
    schedule.created_by = user_id
    schedule.created_at = datetime.now(timezone.utc)
    schedule.updated_at = datetime.now(timezone.utc)
    return schedule


def _make_pipeline_model(pipeline_id=None, status="active"):
    """Create a mock Pipeline model."""
    if pipeline_id is None:
        pipeline_id = uuid.uuid4()
    pipeline = MagicMock()
    pipeline.id = pipeline_id
    pipeline.status = status
    return pipeline


def _make_run_model(run_id=None, pipeline_id=None, status="running"):
    """Create a mock PipelineRun model."""
    if run_id is None:
        run_id = uuid.uuid4()
    if pipeline_id is None:
        pipeline_id = uuid.uuid4()
    run = MagicMock()
    run.id = run_id
    run.pipeline_id = pipeline_id
    run.status = status
    return run


# --- Cron Validation Tests ---


class TestCronValidation:
    """Tests for the validate_cron function.

    Requirement 7.1: Validate cron as standard 5-field format, minimum interval >= 1 minute.
    Requirement 7.7: Reject invalid cron and return error indicating syntax violation.
    """

    def test_valid_every_minute(self):
        """'* * * * *' runs every minute — minimum interval is exactly 1 minute."""
        result = validate_cron("* * * * *")
        assert result.valid is True
        assert result.minimum_interval_seconds == 60

    def test_valid_every_5_minutes(self):
        """'*/5 * * * *' runs every 5 minutes."""
        result = validate_cron("*/5 * * * *")
        assert result.valid is True

    def test_valid_hourly(self):
        """'0 * * * *' runs at minute 0 of every hour."""
        result = validate_cron("0 * * * *")
        assert result.valid is True

    def test_valid_daily_at_midnight(self):
        """'0 0 * * *' runs at midnight daily."""
        result = validate_cron("0 0 * * *")
        assert result.valid is True

    def test_valid_weekly_on_monday(self):
        """'0 9 * * 1' runs at 9 AM every Monday."""
        result = validate_cron("0 9 * * 1")
        assert result.valid is True

    def test_valid_specific_day_and_month(self):
        """'30 14 1 6 *' runs at 14:30 on June 1st."""
        result = validate_cron("30 14 1 6 *")
        assert result.valid is True

    def test_valid_range_in_hour(self):
        """'0 9-17 * * *' runs every hour between 9 AM and 5 PM."""
        result = validate_cron("0 9-17 * * *")
        assert result.valid is True

    def test_valid_list_in_day_of_week(self):
        """'0 9 * * 1,3,5' runs at 9 AM on Mon, Wed, Fri."""
        result = validate_cron("0 9 * * 1,3,5")
        assert result.valid is True

    def test_valid_step_in_minute(self):
        """'*/15 * * * *' runs every 15 minutes."""
        result = validate_cron("*/15 * * * *")
        assert result.valid is True

    def test_valid_range_with_step(self):
        """'0 9-17/2 * * *' runs at 9, 11, 13, 15, 17."""
        result = validate_cron("0 9-17/2 * * *")
        assert result.valid is True

    def test_invalid_empty_expression(self):
        result = validate_cron("")
        assert result.valid is False
        assert "empty" in result.error.lower()

    def test_invalid_too_few_fields(self):
        result = validate_cron("* * *")
        assert result.valid is False
        assert "5 fields" in result.error

    def test_invalid_too_many_fields(self):
        result = validate_cron("* * * * * *")
        assert result.valid is False
        assert "5 fields" in result.error

    def test_invalid_minute_out_of_range(self):
        result = validate_cron("60 * * * *")
        assert result.valid is False
        assert "minute" in result.error.lower()

    def test_invalid_hour_out_of_range(self):
        result = validate_cron("0 24 * * *")
        assert result.valid is False
        assert "hour" in result.error.lower()

    def test_invalid_day_of_month_zero(self):
        result = validate_cron("0 0 0 * *")
        assert result.valid is False
        assert "day_of_month" in result.error.lower()

    def test_invalid_day_of_month_32(self):
        result = validate_cron("0 0 32 * *")
        assert result.valid is False
        assert "day_of_month" in result.error.lower()

    def test_invalid_month_zero(self):
        result = validate_cron("0 0 * 0 *")
        assert result.valid is False
        assert "month" in result.error.lower()

    def test_invalid_month_13(self):
        result = validate_cron("0 0 * 13 *")
        assert result.valid is False
        assert "month" in result.error.lower()

    def test_invalid_weekday_8(self):
        result = validate_cron("0 0 * * 8")
        assert result.valid is False
        assert "day_of_week" in result.error.lower()

    def test_invalid_non_numeric_value(self):
        result = validate_cron("abc * * * *")
        assert result.valid is False
        assert "minute" in result.error.lower()

    def test_invalid_range_start_exceeds_end(self):
        result = validate_cron("0 17-9 * * *")
        assert result.valid is False
        assert "range" in result.error.lower()

    def test_invalid_step_zero(self):
        result = validate_cron("*/0 * * * *")
        assert result.valid is False
        assert "step" in result.error.lower()

    def test_invalid_step_non_numeric(self):
        result = validate_cron("*/abc * * * *")
        assert result.valid is False
        assert "step" in result.error.lower()

    def test_description_generated_for_valid_cron(self):
        result = validate_cron("0 9 * * 1")
        assert result.valid is True
        assert result.description is not None
        assert len(result.description) > 0

    def test_whitespace_trimming(self):
        """Leading/trailing whitespace is trimmed."""
        result = validate_cron("  0 * * * *  ")
        assert result.valid is True

    def test_day_of_week_7_is_valid(self):
        """Day of week 7 represents Sunday (same as 0)."""
        result = validate_cron("0 0 * * 7")
        assert result.valid is True


# --- Scheduler Service Tests ---


class TestCreateSchedule:
    """Tests for SchedulerService.create_schedule."""

    @pytest.mark.asyncio
    async def test_create_schedule_success(self):
        """Successfully create a schedule with valid cron expression."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        dagster_client = AsyncMock(spec=DagsterScheduleClient)
        dagster_client.create_schedule = AsyncMock(return_value="schedule_test_abc123")

        service = SchedulerService(db=db, dagster_client=dagster_client)

        pipeline_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Mock pipeline lookup
        pipeline = _make_pipeline_model(pipeline_id)
        service._get_pipeline = AsyncMock(return_value=pipeline)

        # Mock the PipelineSchedule creation
        with patch("backend.app.services.scheduler_service.PipelineSchedule") as MockSchedule:
            mock_schedule = _make_schedule_model(
                pipeline_id=pipeline_id,
                cron_expression="0 * * * *",
                user_id=user_id,
            )
            MockSchedule.return_value = mock_schedule

            result = await service.create_schedule(pipeline_id, "0 * * * *", user_id)

        assert result.pipeline_id == pipeline_id
        assert result.cron_expression == "0 * * * *"
        assert result.status == "active"
        dagster_client.create_schedule.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_schedule_invalid_cron_raises(self):
        """Creating a schedule with invalid cron should raise."""
        db = AsyncMock()
        dagster_client = AsyncMock(spec=DagsterScheduleClient)
        service = SchedulerService(db=db, dagster_client=dagster_client)

        with pytest.raises(InvalidCronExpressionError):
            await service.create_schedule(
                uuid.uuid4(), "invalid cron", uuid.uuid4()
            )

    @pytest.mark.asyncio
    async def test_create_schedule_nonexistent_pipeline_raises(self):
        """Creating a schedule for a pipeline that doesn't exist should raise."""
        db = AsyncMock()
        dagster_client = AsyncMock(spec=DagsterScheduleClient)
        service = SchedulerService(db=db, dagster_client=dagster_client)

        pipeline_id = uuid.uuid4()
        service._get_pipeline = AsyncMock(
            side_effect=PipelineNotFoundForScheduleError(pipeline_id)
        )

        with pytest.raises(PipelineNotFoundForScheduleError):
            await service.create_schedule(pipeline_id, "0 * * * *", uuid.uuid4())


class TestUpdateSchedule:
    """Tests for SchedulerService.update_schedule."""

    @pytest.mark.asyncio
    async def test_update_schedule_success(self):
        """Successfully update a schedule's cron expression."""
        db = AsyncMock()
        db.flush = AsyncMock()

        dagster_client = AsyncMock(spec=DagsterScheduleClient)
        dagster_client.update_schedule = AsyncMock(return_value="schedule_name")

        service = SchedulerService(db=db, dagster_client=dagster_client)

        schedule = _make_schedule_model(cron_expression="0 * * * *")
        service._get_schedule_model = AsyncMock(return_value=schedule)

        result = await service.update_schedule(schedule.id, "*/15 * * * *")

        assert result.cron_expression == "*/15 * * * *"
        dagster_client.update_schedule.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_schedule_invalid_cron_raises(self):
        """Updating with invalid cron should raise."""
        db = AsyncMock()
        dagster_client = AsyncMock(spec=DagsterScheduleClient)
        service = SchedulerService(db=db, dagster_client=dagster_client)

        with pytest.raises(InvalidCronExpressionError):
            await service.update_schedule(uuid.uuid4(), "bad cron")

    @pytest.mark.asyncio
    async def test_update_schedule_not_found_raises(self):
        """Updating a nonexistent schedule should raise."""
        db = AsyncMock()
        dagster_client = AsyncMock(spec=DagsterScheduleClient)
        service = SchedulerService(db=db, dagster_client=dagster_client)

        schedule_id = uuid.uuid4()
        service._get_schedule_model = AsyncMock(
            side_effect=ScheduleNotFoundError(schedule_id)
        )

        with pytest.raises(ScheduleNotFoundError):
            await service.update_schedule(schedule_id, "0 * * * *")


class TestPauseSchedule:
    """Tests for SchedulerService.pause_schedule.

    Requirement 7.3: Pausing deactivates the schedule in Dagster.
    """

    @pytest.mark.asyncio
    async def test_pause_schedule_success(self):
        """Pausing should deactivate in Dagster and set status=paused."""
        db = AsyncMock()
        db.flush = AsyncMock()

        dagster_client = AsyncMock(spec=DagsterScheduleClient)
        dagster_client.deactivate_schedule = AsyncMock()

        service = SchedulerService(db=db, dagster_client=dagster_client)

        schedule = _make_schedule_model(status="active")
        service._get_schedule_model = AsyncMock(return_value=schedule)

        result = await service.pause_schedule(schedule.id)

        assert result.status == "paused"
        dagster_client.deactivate_schedule.assert_called_once_with(
            schedule.dagster_schedule_name
        )

    @pytest.mark.asyncio
    async def test_pause_schedule_not_found_raises(self):
        """Pausing a nonexistent schedule should raise."""
        db = AsyncMock()
        dagster_client = AsyncMock(spec=DagsterScheduleClient)
        service = SchedulerService(db=db, dagster_client=dagster_client)

        schedule_id = uuid.uuid4()
        service._get_schedule_model = AsyncMock(
            side_effect=ScheduleNotFoundError(schedule_id)
        )

        with pytest.raises(ScheduleNotFoundError):
            await service.pause_schedule(schedule_id)


class TestResumeSchedule:
    """Tests for SchedulerService.resume_schedule.

    Requirement 7.4: Resuming re-activates the schedule in Dagster.
    """

    @pytest.mark.asyncio
    async def test_resume_schedule_success(self):
        """Resuming should activate in Dagster and set status=active."""
        db = AsyncMock()
        db.flush = AsyncMock()

        dagster_client = AsyncMock(spec=DagsterScheduleClient)
        dagster_client.activate_schedule = AsyncMock()

        service = SchedulerService(db=db, dagster_client=dagster_client)

        schedule = _make_schedule_model(status="paused")
        service._get_schedule_model = AsyncMock(return_value=schedule)

        result = await service.resume_schedule(schedule.id)

        assert result.status == "active"
        dagster_client.activate_schedule.assert_called_once_with(
            schedule.dagster_schedule_name
        )

    @pytest.mark.asyncio
    async def test_resume_schedule_not_found_raises(self):
        """Resuming a nonexistent schedule should raise."""
        db = AsyncMock()
        dagster_client = AsyncMock(spec=DagsterScheduleClient)
        service = SchedulerService(db=db, dagster_client=dagster_client)

        schedule_id = uuid.uuid4()
        service._get_schedule_model = AsyncMock(
            side_effect=ScheduleNotFoundError(schedule_id)
        )

        with pytest.raises(ScheduleNotFoundError):
            await service.resume_schedule(schedule_id)


class TestDeleteSchedule:
    """Tests for SchedulerService.delete_schedule."""

    @pytest.mark.asyncio
    async def test_delete_schedule_success(self):
        """Deleting should remove from Dagster and database."""
        db = AsyncMock()
        db.delete = AsyncMock()
        db.flush = AsyncMock()

        dagster_client = AsyncMock(spec=DagsterScheduleClient)
        dagster_client.delete_schedule = AsyncMock()

        service = SchedulerService(db=db, dagster_client=dagster_client)

        schedule = _make_schedule_model()
        service._get_schedule_model = AsyncMock(return_value=schedule)

        await service.delete_schedule(schedule.id)

        dagster_client.delete_schedule.assert_called_once_with(
            schedule.dagster_schedule_name
        )
        db.delete.assert_called_once_with(schedule)

    @pytest.mark.asyncio
    async def test_delete_schedule_not_found_raises(self):
        """Deleting a nonexistent schedule should raise."""
        db = AsyncMock()
        dagster_client = AsyncMock(spec=DagsterScheduleClient)
        service = SchedulerService(db=db, dagster_client=dagster_client)

        schedule_id = uuid.uuid4()
        service._get_schedule_model = AsyncMock(
            side_effect=ScheduleNotFoundError(schedule_id)
        )

        with pytest.raises(ScheduleNotFoundError):
            await service.delete_schedule(schedule_id)


class TestConcurrencyHandling:
    """Tests for scheduled execution concurrency handling.

    Requirement 7.5: If previous execution still running, queue new execution.
    Requirement 7.6: Skip execution if pipeline fails validation.
    """

    @pytest.mark.asyncio
    async def test_queue_when_previous_running(self):
        """New execution should be queued if previous is still running."""
        db = AsyncMock()
        dagster_client = AsyncMock(spec=DagsterScheduleClient)
        service = SchedulerService(db=db, dagster_client=dagster_client)

        schedule = _make_schedule_model()
        service._get_schedule_model = AsyncMock(return_value=schedule)

        # Pipeline exists
        pipeline = _make_pipeline_model(pipeline_id=schedule.pipeline_id)
        service._get_pipeline_or_none = AsyncMock(return_value=pipeline)

        # Previous execution is running
        running_run = _make_run_model(pipeline_id=schedule.pipeline_id, status="running")
        service._get_running_execution = AsyncMock(return_value=running_run)

        result = await service.handle_scheduled_trigger(schedule.id)
        assert result == "queued"

    @pytest.mark.asyncio
    async def test_skip_when_pipeline_deleted(self):
        """Execution should be skipped if pipeline was deleted."""
        db = AsyncMock()
        dagster_client = AsyncMock(spec=DagsterScheduleClient)
        service = SchedulerService(db=db, dagster_client=dagster_client)

        schedule = _make_schedule_model()
        service._get_schedule_model = AsyncMock(return_value=schedule)

        # Pipeline no longer exists
        service._get_pipeline_or_none = AsyncMock(return_value=None)
        service._record_skip = AsyncMock()

        result = await service.handle_scheduled_trigger(schedule.id)
        assert result == "skipped"
        service._record_skip.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_when_pipeline_invalid(self):
        """Execution should be skipped if pipeline has invalid DAG."""
        db = AsyncMock()
        dagster_client = AsyncMock(spec=DagsterScheduleClient)
        service = SchedulerService(db=db, dagster_client=dagster_client)

        schedule = _make_schedule_model()
        service._get_schedule_model = AsyncMock(return_value=schedule)

        # Pipeline exists but is invalid
        pipeline = _make_pipeline_model(
            pipeline_id=schedule.pipeline_id, status="invalid"
        )
        service._get_pipeline_or_none = AsyncMock(return_value=pipeline)
        service._record_skip = AsyncMock()

        result = await service.handle_scheduled_trigger(schedule.id)
        assert result == "skipped"
        service._record_skip.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_when_no_running_execution(self):
        """Execution should start if no previous execution is running."""
        db = AsyncMock()
        dagster_client = AsyncMock(spec=DagsterScheduleClient)
        service = SchedulerService(db=db, dagster_client=dagster_client)

        schedule = _make_schedule_model()
        service._get_schedule_model = AsyncMock(return_value=schedule)

        # Pipeline exists and is valid
        pipeline = _make_pipeline_model(pipeline_id=schedule.pipeline_id)
        service._get_pipeline_or_none = AsyncMock(return_value=pipeline)

        # No running execution
        service._get_running_execution = AsyncMock(return_value=None)

        result = await service.handle_scheduled_trigger(schedule.id)
        assert result == "started"


class TestDagsterScheduleClient:
    """Tests for DagsterScheduleClient interface (mock implementation)."""

    @pytest.mark.asyncio
    async def test_create_schedule_returns_name(self):
        """Create schedule should return the schedule name."""
        client = DagsterScheduleClient()
        result = await client.create_schedule(
            "test_schedule", uuid.uuid4(), "0 * * * *"
        )
        assert result == "test_schedule"

    @pytest.mark.asyncio
    async def test_update_schedule_returns_name(self):
        """Update schedule should return the schedule name."""
        client = DagsterScheduleClient()
        result = await client.update_schedule("test_schedule", "*/5 * * * *")
        assert result == "test_schedule"

    @pytest.mark.asyncio
    async def test_deactivate_schedule_no_error(self):
        """Deactivate schedule should not raise."""
        client = DagsterScheduleClient()
        await client.deactivate_schedule("test_schedule")

    @pytest.mark.asyncio
    async def test_activate_schedule_no_error(self):
        """Activate schedule should not raise."""
        client = DagsterScheduleClient()
        await client.activate_schedule("test_schedule")

    @pytest.mark.asyncio
    async def test_delete_schedule_no_error(self):
        """Delete schedule should not raise."""
        client = DagsterScheduleClient()
        await client.delete_schedule("test_schedule")


class TestScheduleServiceErrors:
    """Tests for error handling in the scheduler service."""

    def test_scheduler_service_error_has_code(self):
        """Base error should carry an error code."""
        error = SchedulerServiceError("something failed", code="TEST_ERROR")
        assert error.message == "something failed"
        assert error.code == "TEST_ERROR"

    def test_schedule_not_found_error(self):
        """ScheduleNotFoundError should contain the schedule ID in the message."""
        sid = uuid.uuid4()
        error = ScheduleNotFoundError(sid)
        assert str(sid) in error.message
        assert error.code == "SCHEDULE_NOT_FOUND"

    def test_invalid_cron_expression_error(self):
        """InvalidCronExpressionError should contain expression and reason."""
        error = InvalidCronExpressionError("bad", "not valid")
        assert "bad" in error.message
        assert "not valid" in error.message
        assert error.code == "INVALID_CRON_EXPRESSION"

    def test_pipeline_not_found_for_schedule_error(self):
        """PipelineNotFoundForScheduleError should contain the pipeline ID."""
        pid = uuid.uuid4()
        error = PipelineNotFoundForScheduleError(pid)
        assert str(pid) in error.message
        assert error.code == "PIPELINE_NOT_FOUND"
