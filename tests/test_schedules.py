import json
from datetime import date, datetime, timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, SimpleTestCase

from schedules.forms import ShiftForm
from schedules.models import Shift
from schedules.services import create_shift, create_shifts, update_shift, cancel_shift
from schedules.timeutils import local_datetime_to_utc
from attendance.services import clock_in
from .factories import workspace, employee, shift, instant, DAY


class TimezoneTests(SimpleTestCase):
    def test_iana_conversion(self):
        self.assertEqual(local_datetime_to_utc(datetime(2026, 9, 21, 22), "Asia/Manila").hour, 14)

    def test_dst_ambiguous_and_nonexistent_times_rejected(self):
        for wall in (datetime(2026, 3, 8, 2, 30), datetime(2026, 11, 1, 1, 30)):
            with self.subTest(wall=wall), self.assertRaises(ValidationError):
                local_datetime_to_utc(wall, "America/New_York")

    def test_elapsed_time_across_dst_change(self):
        start = local_datetime_to_utc(datetime(2026, 3, 8, 0), "America/New_York")
        end = local_datetime_to_utc(datetime(2026, 3, 8, 4), "America/New_York")
        self.assertEqual((end - start).total_seconds(), 3 * 3600)


class SchedulingTests(TestCase):
    def setUp(self):
        self.org, self.owner = workspace()
        self.emp = employee(self.org)

    def form_data(self, **updates):
        data = {"employees": json.dumps([self.emp.pk]), "work_dates": json.dumps([DAY.isoformat()]),
                "start_time": "22:00", "end_time": "03:00", "scheduled_break_minutes": "30"}
        data.update(updates)
        return data

    def test_multi_employee_multi_date_overnight_form(self):
        second = employee(self.org, "b")
        form = ShiftForm(self.form_data(employees=json.dumps([self.emp.pk, second.pk]),
            work_dates=json.dumps([DAY.isoformat(), (DAY + timedelta(days=1)).isoformat()])), organization=self.org)
        self.assertTrue(form.is_valid(), form.errors)
        created = create_shifts(organization=self.org, employees=form.cleaned_data["employees"],
            shift_intervals=form.cleaned_data["shift_intervals"], scheduled_break_minutes=30, actor=self.owner)
        self.assertEqual(len(created), 4)
        self.assertTrue(all(item.scheduled_minutes == 270 for item in created))

    def test_invalid_selections_return_validation_errors(self):
        for ids in ('["not-an-id"]', '[true]', '[{}]', 'null', '[]', '[999999999999999999999999999]'):
            with self.subTest(ids=ids):
                form = ShiftForm(self.form_data(employees=ids), organization=self.org)
                self.assertFalse(form.is_valid())

    def test_invalid_dates_times_and_breaks(self):
        for update in ({"work_dates": '["2026-02-30"]'}, {"start_time": "03:00"},
                       {"scheduled_break_minutes": "301"}, {"scheduled_break_minutes": "-1"},
                       {"work_dates": "[]"}, {"work_dates": "{}"}):
            with self.subTest(update=update):
                form = ShiftForm(self.form_data(**update), organization=self.org)
                self.assertFalse(form.is_valid())

    def test_foreign_and_inactive_employee_cannot_be_selected(self):
        other_org, _ = workspace("other")
        other = employee(other_org, "other")
        inactive = employee(self.org, "inactive", active=False)
        for person in (other, inactive):
            form = ShiftForm(self.form_data(employees=json.dumps([person.pk])), organization=self.org)
            self.assertFalse(form.is_valid())

    def test_conflicts_and_batch_atomicity(self):
        shift(self.org, self.emp)
        other = employee(self.org, "b")
        interval = {"work_date": DAY, "scheduled_start": instant(), "scheduled_end": instant(hour=18)}
        with self.assertRaises(ValidationError):
            create_shifts(organization=self.org, employees=[other, self.emp], shift_intervals=[interval],
                          scheduled_break_minutes=0, actor=self.owner)
        self.assertEqual(Shift.objects.count(), 1)

    def test_overlap_across_dates_rejected(self):
        shift(self.org, self.emp, start=22, end=6, allowance=0)
        with self.assertRaises(ValidationError):
            shift(self.org, self.emp, DAY + timedelta(days=1), start=5, end=8, allowance=0)

    def test_edit_and_cancel_only_before_attendance(self):
        work = shift(self.org, self.emp)
        updated = update_shift(work, organization=self.org, employee=self.emp, work_date=DAY,
            scheduled_start=instant(hour=10), scheduled_end=instant(hour=18), scheduled_break_minutes=0, actor=self.owner)
        self.assertEqual(updated.scheduled_minutes, 480)
        clock_in(shift=updated, employee=self.emp, actor=self.emp.user, at=updated.scheduled_start)
        with self.assertRaises(ValidationError):
            cancel_shift(updated, organization=self.org, actor=self.owner)
        with self.assertRaises(ValidationError):
            update_shift(updated, organization=self.org, employee=self.emp, work_date=DAY,
                scheduled_start=instant(), scheduled_end=instant(hour=18), scheduled_break_minutes=0, actor=self.owner)

    def test_cancel_is_idempotent(self):
        work = shift(self.org, self.emp)
        for _ in range(2):
            work = cancel_shift(work, organization=self.org, actor=self.owner)
        self.assertEqual(work.status, "CANCELLED")

    def test_organization_timezone_locks_after_shift(self):
        self.org.timezone = "UTC"
        self.org.save()
        shift(self.org, self.emp)
        self.org.timezone = "Asia/Manila"
        with self.assertRaises(ValidationError):
            self.org.save()
