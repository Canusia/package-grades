"""Last date of attendance with a final grade (EWU Zendesk #3222)."""
from datetime import date, timedelta
from unittest.mock import MagicMock

from ..models import FinalGradeAttendance, GradeSISSync
from ..services import last_attendance, sis_push
from ..services.grade_csv import grades_csv_response
from ..services.grade_grid import build_formset, build_grid
from ..services.scales import current_campus
from ..services.sis_push import GradePushResult
from .base import GradesTestCase
from .sis_fixtures import SISFixtureMixin
from .test_grade_scales import make_scale
from . import factories as f

RECORD = '3b300cc1-bcf1-496a-a0a1-d451bd52be42'
YESTERDAY = date.today() - timedelta(days=1)


def _post(formset_initial, rows):
    """Bound POST data for a one-period formset. rows: [(grade, date or '')]."""
    data = {'form-TOTAL_FORMS': str(len(rows)), 'form-INITIAL_FORMS': str(len(rows)),
            'form-MIN_NUM_FORMS': '1', 'form-MAX_NUM_FORMS': str(len(rows))}
    for i, (init, (grade, when)) in enumerate(zip(formset_initial, rows)):
        data[f'form-{i}-student_id'] = str(init['student_id'])
        data[f'form-{i}-student'] = init['student']
        data[f'form-{i}-grade'] = grade
        data[f'form-{i}-last_attendance'] = when.isoformat() if when else ''
    return data


class _GridBase(GradesTestCase):
    def setUp(self):
        f.grades_setting(grades='A,B,F')
        campus = current_campus()
        self.std = make_scale('Std', ['A', 'B', 'F'], campus=campus, is_default=True,
                              last_attendance=['F'])
        self.term = f.term()
        today = date.today()
        self.mid = f.period(self.term, 'Mid', today - timedelta(days=60),
                            today - timedelta(days=50))
        self.final = f.period(self.term, 'Final', today - timedelta(days=5),
                              today + timedelta(days=5), sequence=2, is_final=True)
        self.section = f.section(self.term, f.teacher())
        self.reg = f.registration(self.section)

    def formset(self, period, rows=None, draft=False):
        initial_fs = build_formset(self.section, period, [self.reg], {})
        data = _post(initial_fs.initial, rows) if rows is not None else None
        fs = build_formset(self.section, period, [self.reg], {}, data=data)
        if draft:
            for form in fs.forms:
                form.fields['grade'].required = False
                form.require_last_attendance = False
        return fs


class FormTests(_GridBase):
    def test_only_the_final_period_asks(self):
        self.assertIn('last_attendance', self.formset(self.final).forms[0].fields)
        self.assertNotIn('last_attendance', self.formset(self.mid).forms[0].fields)

    def test_no_field_when_no_letter_asks(self):
        self.std.entries.update(asks_last_attendance=False)
        self.assertNotIn('last_attendance', self.formset(self.final).forms[0].fields)

    def test_submit_needs_the_date_for_a_flagged_grade(self):
        fs = self.formset(self.final, [('F', None)])
        self.assertFalse(fs.is_valid())
        self.assertIn('Enter the last date of attendance for grade F.',
                      fs.forms[0].errors['last_attendance'])

    def test_refused_submit_names_the_student(self):
        from ..views.grade_entry import _invalid_message
        fs = self.formset(self.final, [('F', None)])
        fs.is_valid()
        message = str(_invalid_message(fs))
        self.assertIn(self.reg.student.user.last_name, message)
        self.assertIn('Enter the last date of attendance for grade F.', message)

    def test_draft_may_leave_it_blank(self):
        fs = self.formset(self.final, [('F', None)], draft=True)
        self.assertTrue(fs.is_valid(), fs.errors)

    def test_future_and_pre_term_dates_are_refused(self):
        fs = self.formset(self.final, [('F', date.today() + timedelta(days=1))])
        self.assertFalse(fs.is_valid())
        ay = self.term.academic_year
        ay.hs_start_date = date.today() - timedelta(days=10)
        ay.save()
        self.section.refresh_from_db()
        fs = self.formset(self.final, [('F', date.today() - timedelta(days=11))])
        self.assertFalse(fs.is_valid())
        self.assertIn('before the school year starts', str(fs.forms[0].errors))

    def test_saving_keeps_the_date_and_a_new_grade_clears_it(self):
        fs = self.formset(self.final, [('F', YESTERDAY)])
        self.assertTrue(fs.is_valid(), fs.errors)
        fs.save()
        self.assertEqual(last_attendance.stored_for(self.reg), YESTERDAY)
        # The form shows the stored date next time.
        self.assertEqual(self.formset(self.final).forms[0].initial['last_attendance'], YESTERDAY)

        fs = self.formset(self.final, [('A', YESTERDAY)])   # the browser would clear it too
        self.assertTrue(fs.is_valid(), fs.errors)
        fs.save()
        self.assertIsNone(last_attendance.stored_for(self.reg))


class GridDisplayTests(_GridBase):
    def test_editable_cell_renders_the_widget(self):
        from django.template.loader import render_to_string
        grid = build_grid(self.section, post_url='/x', next_url='/x')
        html = render_to_string('grades/partials/_grade_grid.html', {'grid': grid})
        self.assertIn('data-last-attendance-letters="F"', html)
        self.assertIn('name="form-0-last_attendance"', html)

    def test_read_only_cell_and_csv_show_the_date(self):
        from django.template.loader import render_to_string
        self.reg.grade = 'F'
        self.reg.save()
        last_attendance.set_last_attendance(self.reg, YESTERDAY)
        grid = build_grid(self.section, post_url='/x', next_url='/x', allow_edit=False)
        html = render_to_string('grades/partials/_grade_grid.html', {'grid': grid})
        self.assertIn(f'Last attended {YESTERDAY:%m/%d/%Y}', html)
        csv_text = grades_csv_response(self.section).content.decode()
        self.assertIn('Last Date of Attendance', csv_text.splitlines()[0])
        self.assertIn(f'{YESTERDAY:%m/%d/%Y}', csv_text)


class MirroringTests(SISFixtureMixin, GradesTestCase):
    def test_date_change_after_send_flags_and_revert_unflags(self):
        reg = self.make_registration(self.make_section(), grade='F')
        last_attendance.set_last_attendance(reg, YESTERDAY)
        sync = GradeSISSync.objects.create(registration=reg, status='sent', sent_grade='F',
                                           sent_last_attendance=YESTERDAY)

        last_attendance.set_last_attendance(reg, YESTERDAY - timedelta(days=1))
        sync.refresh_from_db()
        self.assertEqual(sync.status, GradeSISSync.NEEDS_MIRRORING)

        last_attendance.set_last_attendance(reg, YESTERDAY)
        sync.refresh_from_db()
        self.assertEqual(sync.status, GradeSISSync.SENT)

        last_attendance.set_last_attendance(reg, None)
        sync.refresh_from_db()
        self.assertEqual(sync.status, GradeSISSync.NEEDS_MIRRORING)

    def test_grade_sent_before_dates_existed_stays_sent(self):
        reg = self.make_registration(self.make_section(), grade='A')
        sync = GradeSISSync.objects.create(registration=reg, status='sent', sent_grade='A')
        reg.save(update_fields=['grade'])
        sync.refresh_from_db()
        self.assertEqual(sync.status, GradeSISSync.SENT)


class PushTests(SISFixtureMixin, GradesTestCase):
    def setUp(self):
        make_scale('Std', ['A', 'B', 'C', 'F'], campus=current_campus(), is_default=True,
                   last_attendance=['F'])
        self.section = self.make_section()

    def _run(self, pusher, reg):
        from unittest.mock import patch
        with patch.object(sis_push, 'get_pusher', return_value=pusher):
            counts = sis_push.run_push([str(reg.id)])
        return counts, GradeSISSync.objects.get(registration=reg)

    def test_date_is_sent_and_recorded(self):
        reg = self.make_registration(self.section, grade='F')
        last_attendance.set_last_attendance(reg, YESTERDAY)
        pusher = MagicMock(return_value=GradePushResult(True, record_id=RECORD))
        pusher.__signature__ = __import__('inspect').signature(
            lambda registration, grade, existing_record_id=None, last_attendance=None: None)

        counts, sync = self._run(pusher, reg)

        self.assertEqual(counts['sent'], 1)
        self.assertEqual(pusher.call_args.kwargs['last_attendance'], YESTERDAY)
        self.assertEqual(sync.sent_last_attendance, YESTERDAY)
        self.assertEqual(sync.status, GradeSISSync.SENT)

    def test_missing_date_fails_without_calling_the_sis(self):
        reg = self.make_registration(self.section, grade='F')
        pusher = MagicMock()

        counts, sync = self._run(pusher, reg)

        self.assertEqual(counts['failed'], 1)
        pusher.assert_not_called()
        self.assertIn('needs a last date of attendance', sync.last_error)

    def test_old_pusher_refuses_a_flagged_grade_but_sends_others(self):
        def old_pusher(registration, grade, existing_record_id=None):
            return GradePushResult(True, record_id=RECORD)

        flagged = self.make_registration(self.section, grade='F')
        last_attendance.set_last_attendance(flagged, YESTERDAY)
        counts, sync = self._run(old_pusher, flagged)
        self.assertEqual(counts['failed'], 1)
        self.assertIn('Update the ethos package', sync.last_error)

        plain = self.make_registration(self.section, grade='A')
        counts, sync = self._run(old_pusher, plain)
        self.assertEqual(counts['sent'], 1)
        self.assertIsNone(sync.sent_last_attendance)

    def test_unflagged_grade_calls_the_pusher_as_before(self):
        reg = self.make_registration(self.section, grade='A')
        pusher = MagicMock(return_value=GradePushResult(True, record_id=RECORD))
        self._run(pusher, reg)
        self.assertNotIn('last_attendance', pusher.call_args.kwargs)

    def test_registrations_feed_shows_the_date(self):
        from ..serializers import SISRegistrationSerializer
        from ..views.sis_sync import registration_queryset
        reg = self.make_registration(self.section, grade='F')
        FinalGradeAttendance.objects.create(registration=reg, last_attendance_on=YESTERDAY)
        row = SISRegistrationSerializer(registration_queryset().get(pk=reg.pk)).data
        self.assertEqual(row['last_attendance'], f'{YESTERDAY:%m/%d/%Y}')
