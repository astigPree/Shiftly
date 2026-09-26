from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from attendance.models import AttendanceSession, BreakSession
from attendance.services import clock_in, clock_out, start_break, end_break, attendance_state, last_activity
from timesheets.calculations import calculate_timesheet, TimesheetCalculationError
from timesheets.models import Timesheet, TimesheetApproval
from timesheets.services import generate_timesheet, review_timesheet
from .factories import workspace, employee, shift, completed, DAY


class AttendanceTests(TestCase):
    def setUp(self):
        self.org, self.owner = workspace()
        self.emp = employee(self.org)
        self.work = shift(self.org, self.emp)

    def clock(self, offset=0):
        return clock_in(shift=self.work, employee=self.emp, actor=self.emp.user,
                        at=self.work.scheduled_start + timedelta(minutes=offset))

    def test_clock_window_boundaries(self):
        for moment in (self.work.scheduled_start - timedelta(minutes=30, seconds=1), self.work.scheduled_end):
            with self.subTest(moment=moment), self.assertRaises(ValidationError):
                clock_in(shift=self.work, employee=self.emp, actor=self.emp.user, at=moment)
        session = self.clock(-30)
        self.assertEqual(session.clock_in_at, self.work.scheduled_start - timedelta(minutes=30))

    def test_duplicate_clock_in_is_rejected_once(self):
        self.clock()
        with self.assertRaises(ValidationError):
            self.clock()
        self.assertEqual(AttendanceSession.objects.count(), 1)

    def test_another_employee_and_employer_cannot_clock(self):
        other = employee(self.org, "b")
        for emp, actor in ((other, other.user), (self.emp, other.user), (self.emp, self.owner)):
            with self.subTest(actor=actor.pk), self.assertRaises(PermissionDenied):
                clock_in(shift=self.work, employee=emp, actor=actor, at=self.work.scheduled_start)

    def test_cancelled_and_inactive_shift_block_clocking(self):
        self.work.status = "CANCELLED"
        self.work.save()
        with self.assertRaises(ValidationError):
            self.clock()
        self.work.status = "SCHEDULED"
        self.work.save()
        self.emp.status = "INACTIVE"
        self.emp.save()
        with self.assertRaises(PermissionDenied):
            self.clock()

    def test_complete_workflow_multiple_breaks_and_one_timesheet(self):
        session = self.clock(5)
        for hour in (2, 5):
            at = self.work.scheduled_start + timedelta(hours=hour)
            start_break(session=session, employee=self.emp, actor=self.emp.user, at=at)
            session.refresh_from_db()
            self.assertEqual(session.status, "ON_BREAK")
            with self.assertRaises(ValidationError):
                start_break(session=session, employee=self.emp, actor=self.emp.user, at=at)
            with self.assertRaises(ValidationError):
                clock_out(session=session, employee=self.emp, actor=self.emp.user, at=at)
            end_break(session=session, employee=self.emp, actor=self.emp.user, at=at + timedelta(minutes=15))
        session = clock_out(session=session, employee=self.emp, actor=self.emp.user,
                            at=self.work.scheduled_end - timedelta(minutes=10))
        sheet = self.work.timesheet
        self.assertEqual((sheet.worked_minutes, sheet.break_minutes, sheet.late_minutes, sheet.undertime_minutes),
                         (495, 30, 5, 10))
        self.assertEqual(sheet.payable_minutes, 495)
        self.assertEqual(sheet.status, "PENDING")
        self.assertEqual(generate_timesheet(session).pk, sheet.pk)
        with self.assertRaises(ValidationError):
            clock_out(session=session, employee=self.emp, actor=self.emp.user, at=self.work.scheduled_end)
        self.assertEqual(Timesheet.objects.count(), 1)
        self.assertEqual(last_activity(session), session.clock_out_at)

    def test_break_end_requires_positive_duration(self):
        session = self.clock()
        with self.assertRaises(ValidationError):
            end_break(session=session, employee=self.emp, actor=self.emp.user)
        at = self.work.scheduled_start + timedelta(hours=1)
        start_break(session=session, employee=self.emp, actor=self.emp.user, at=at)
        with self.assertRaises(ValidationError):
            end_break(session=session, employee=self.emp, actor=self.emp.user, at=at)

    def test_break_seconds_are_summed_before_flooring(self):
        session = self.clock()
        for hour in (1, 2):
            at = self.work.scheduled_start + timedelta(hours=hour)
            start_break(session=session, employee=self.emp, actor=self.emp.user, at=at)
            end_break(session=session, employee=self.emp, actor=self.emp.user, at=at + timedelta(seconds=40))
        clock_out(session=session, employee=self.emp, actor=self.emp.user, at=self.work.scheduled_end)
        self.assertEqual(self.work.timesheet.break_minutes, 1)
        self.assertEqual(self.work.timesheet.worked_minutes, 538)

    def test_attendance_states_and_missing_clockout(self):
        for when, state in ((self.work.scheduled_start - timedelta(seconds=1), "SCHEDULED"),
                            (self.work.scheduled_start, "LATE"), (self.work.scheduled_end, "ABSENT")):
            self.assertEqual(attendance_state(self.work, at=when)["code"], state)
        session = self.clock()
        self.work.refresh_from_db()
        state = attendance_state(self.work, at=self.work.scheduled_end)
        self.assertEqual(state["code"], "WORKING")
        self.assertTrue(state["missing_clock_out"])
        self.assertEqual(Timesheet.objects.count(), 0)
        self.assertEqual(last_activity(session), session.clock_in_at)

    def test_clock_timestamps_are_immutable(self):
        session = self.clock()
        session.clock_in_at += timedelta(minutes=1)
        with self.assertRaises(ValidationError):
            session.save()

    def test_overnight_2200_to_0300_preserves_original_work_date(self):
        work, session, sheet = completed(self.org, self.emp, DAY + timedelta(days=1), 22, 3, 30)
        self.assertTrue(work.is_overnight)
        self.assertEqual(sheet.worked_minutes, 270)
        self.assertEqual(sheet.shift.work_date, DAY + timedelta(days=1))
        self.assertEqual(session.breaks.count(), 1)

    def test_invalid_completed_data_needs_review(self):
        session = self.clock()
        # Simulate damaged imported data without going through clock services.
        BreakSession.objects.create(attendance_session=session,
            started_at=self.work.scheduled_start - timedelta(hours=1), ended_at=self.work.scheduled_start)
        session.clock_out_at = self.work.scheduled_end
        session.status = "COMPLETED"
        session.save()
        sheet = generate_timesheet(session)
        self.assertEqual(sheet.status, "NEEDS_REVIEW")
        with self.assertRaises(ValidationError):
            review_timesheet(timesheet=sheet, reviewer=self.owner, action="APPROVED")
        sheet, _ = review_timesheet(timesheet=sheet, reviewer=self.owner, action="REJECTED", comment="Invalid break")
        self.assertEqual(sheet.status, "REJECTED")

    def test_review_permissions_and_terminal_decisions(self):
        session = self.clock()
        clock_out(session=session, employee=self.emp, actor=self.emp.user, at=self.work.scheduled_end)
        sheet = self.work.timesheet
        _, stranger = workspace("b")
        for actor in (stranger, self.emp.user):
            with self.assertRaises(PermissionDenied):
                review_timesheet(timesheet=sheet, reviewer=actor, action="APPROVED")
        with self.assertRaises(ValidationError):
            review_timesheet(timesheet=sheet, reviewer=self.owner, action="REJECTED", comment=" ")
        sheet, approval = review_timesheet(timesheet=sheet, reviewer=self.owner, action="APPROVED")
        self.assertEqual(approval.reviewer, self.owner)
        with self.assertRaises(ValidationError):
            review_timesheet(timesheet=sheet, reviewer=self.owner, action="REJECTED", comment="Again")
        self.assertEqual(TimesheetApproval.objects.count(), 1)
