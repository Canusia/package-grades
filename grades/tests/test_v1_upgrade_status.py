"""v1 upgrade: sections submitted under 0.0.x keep their final grades (C1)."""
import importlib
from datetime import date

from .base import GradesTestCase
from . import factories as f
from ..models import GradingPeriod, SectionPeriodStatus
from ..services import student_table
from ..services.grade_grid import build_grid
from ..services.window import submitted_grade

mig = importlib.import_module(
    GradingPeriod.__module__.rsplit('.', 1)[0] + '.migrations.0007_backfill_final_period_status')


def _run():
    from cis.models.section import ClassSection
    return mig.backfill(GradingPeriod, ClassSection, SectionPeriodStatus)


def _legacy_section(term, status='submitted', grade='A'):
    """A section as 0.0.x left it: grade_status set, no SectionPeriodStatus."""
    section = f.section(term, f.teacher())
    reg = f.registration(section, grade=grade)
    section.grade_status = status
    section.grade_status_changed_on = {'05/01/2026 10:00:00 AM': status}
    section.save()
    return section, reg


class UpgradeStatusTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()

    def test_backfill_restores_submitted_final(self):
        term = f.term()
        final = f.period(term, 'Final Grades', date(2026, 5, 1), date(2026, 5, 9), is_final=True)
        section, reg = _legacy_section(term)
        self.assertEqual(_run(), 1)
        row = SectionPeriodStatus.objects.get(period=final, class_section=section)
        self.assertEqual(row.status, 'submitted')
        section.refresh_from_db()
        self.assertEqual(row.status_changed_on, section.grade_status_changed_on)
        self.assertIn('05/01/2026 10:00:00 AM', row.status_changed_on)
        grid = build_grid(section, post_url='/x', next_url='/', on_date=date(2026, 5, 5))
        self.assertEqual(grid['periods'][0]['status'], 'submitted')
        self.assertIsNone(grid['editable_period'])
        reg.refresh_from_db()
        self.assertEqual(submitted_grade(reg), 'A')

    def test_backfill_is_idempotent_and_skips_unstarted(self):
        term = f.term()
        final = f.period(term, 'Final Grades', date(2026, 5, 1), date(2026, 5, 9), is_final=True)
        _legacy_section(term, status='saved')
        _legacy_section(term, status='')
        self.assertEqual(_run(), 1)
        self.assertEqual(_run(), 0)
        self.assertEqual(SectionPeriodStatus.objects.get(period=final).status, 'saved')

    def test_backfill_ignores_interim_periods(self):
        term = f.term()
        mid = f.period(term, 'Mid', date(2026, 3, 1), date(2026, 3, 9))
        _legacy_section(term)
        self.assertEqual(_run(), 0)
        self.assertFalse(SectionPeriodStatus.objects.filter(period=mid).exists())

    def test_submitted_grade_before_backfill(self):
        term = f.term()
        f.period(term, 'Final Grades', date(2026, 5, 1), date(2026, 5, 9), is_final=True)
        _section, reg = _legacy_section(term)
        self.assertEqual(submitted_grade(reg), 'A')

    def test_submitted_grade_without_any_period(self):
        term = f.term()
        _section, reg = _legacy_section(term, grade='B')
        self.assertEqual(submitted_grade(reg), 'B')
        self.assertEqual(str(student_table.COLUMNS['grade'][1](reg)), 'B')

    def test_unsubmitted_section_without_period_hides_grade(self):
        term = f.term()
        _section, reg = _legacy_section(term, status='saved', grade='B')
        self.assertEqual(submitted_grade(reg), '-')

    def test_reopened_final_hides_grade(self):
        from ..services.periods import set_status
        term = f.term()
        final = f.period(term, 'Final Grades', date(2026, 5, 1), date(2026, 5, 9), is_final=True)
        section, reg = _legacy_section(term)
        _run()
        set_status(section, final, 'saved')
        reg.refresh_from_db()
        self.assertEqual(submitted_grade(reg), '-')
