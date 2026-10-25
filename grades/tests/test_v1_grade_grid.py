"""v1: column-per-period grid and the shared POST handler (spec §3)."""
from datetime import date
from unittest import mock

from django.test import RequestFactory

from .base import GradesTestCase
from . import factories as f
from ..models import PeriodGrade, SectionPeriodStatus
from ..services import grade_grid
from ..views import grade_entry

TODAY = date(2026, 10, 25)


class GradeGridTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting(grades_open_class_section='How to', grades_submitted_class_section='Thanks')
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', date(2026, 10, 19), date(2026, 10, 30), 1)
        cls.mid2 = f.period(cls.term, 'Mid 2', date(2026, 11, 16), date(2026, 11, 27), 2)
        cls.final = f.period(cls.term, 'Final', date(2026, 12, 1), date(2026, 12, 9), 3, is_final=True)
        cls.section = f.section(cls.term, f.teacher())
        cls.reg = f.registration(cls.section, last_name='Amador')

    def _grid(self, **kw):
        return grade_grid.build_grid(self.section, post_url='/post', next_url='/back',
                                     on_date=TODAY, **kw)

    def test_one_column_per_period_only_open_editable(self):
        grid = self._grid()
        self.assertEqual([p['period'] for p in grid['periods']], [self.mid1, self.mid2, self.final])
        self.assertEqual([p['editable'] for p in grid['periods']], [True, False, False])
        self.assertEqual(grid['editable_period'], self.mid1)
        self.assertIsNotNone(grid['rows'][0]['form'])
        self.assertEqual(grid['periods'][1]['header'], 'Opens 11/16/2026')
        self.assertEqual(grid['periods'][0]['header'], 'Open · due 10/30/2026')

    def test_no_periods(self):
        section = f.section(f.term(), f.teacher())
        grid = grade_grid.build_grid(section, post_url='/p', next_url='/n', on_date=TODAY)
        self.assertFalse(grid['has_periods'])
        self.assertEqual(grid['rows'], [])

    def test_submitted_period_read_only_with_message(self):
        from ..services.periods import set_status
        set_status(self.section, self.mid1, 'submitted')
        grid = self._grid()
        self.assertIsNone(grid['editable_period'])
        self.assertTrue(grid['periods'][0]['header'].startswith('Submitted'))
        self.assertEqual(grid['message'], 'Thanks')

    def test_partial_renders_sort_attrs_and_one_column_per_period(self):
        from django.template.loader import render_to_string
        html = render_to_string('grades/partials/_grade_grid.html', {'grid': self._grid()})
        self.assertIn('data-sort-lastname="Amador"', html)
        self.assertIn('name="period"', html)
        self.assertIn('Submit Mid 1 Grades', html)
        for name in ('Mid 1', 'Mid 2', 'Final'):
            self.assertIn(name, html)


class GradePostTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', date(2026, 10, 19), date(2026, 10, 30), 1)
        cls.mid2 = f.period(cls.term, 'Mid 2', date(2026, 11, 16), date(2026, 11, 27), 2)
        cls.teacher = f.teacher()
        cls.section = f.section(cls.term, cls.teacher)
        cls.reg = f.registration(cls.section)

    def _post(self, period, grade='B', action="Save Grades as 'Draft'", next_url='/back',
              force=None, xhr=False):
        data = {'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1', 'form-MIN_NUM_FORMS': '1',
                'form-MAX_NUM_FORMS': '1', 'form-0-student': 'x', 'form-0-student_id': str(self.reg.id),
                'form-0-grade': grade, 'save_grade': action, 'period': str(period.id),
                'next': next_url}
        headers = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'} if xhr else {}
        request = RequestFactory().post('/post', data, **headers)
        request.user = self.teacher.user
        request._messages = mock.MagicMock()
        return grade_entry.handle_grade_post(request, self.section, redirect_url='/default',
                                             force_period=force, on_date=TODAY)

    def test_draft_saves_open_period(self):
        resp = self._post(self.mid1)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/back')
        self.assertEqual(PeriodGrade.objects.get(period=self.mid1).grade, 'B')

    def test_closed_period_refused(self):
        self._post(self.mid2)
        self.assertFalse(PeriodGrade.objects.exists())

    def test_submitted_period_refused(self):
        from ..services.periods import set_status
        set_status(self.section, self.mid1, 'submitted')
        self._post(self.mid1, grade='C')
        self.assertFalse(PeriodGrade.objects.filter(grade='C').exists())

    def test_force_period_lets_ce_edit_closed(self):
        self._post(self.mid2, force=self.mid2)
        self.assertEqual(PeriodGrade.objects.get(period=self.mid2).grade, 'B')

    def test_offsite_next_rejected(self):
        for bad in ('//evil.example/x', 'https://evil.example/x'):
            resp = self._post(self.mid1, next_url=bad)
            self.assertEqual(resp['Location'], '/default')

    def test_submit_sets_status(self):
        self._post(self.mid1, action='Submit Grades')
        self.assertEqual(SectionPeriodStatus.objects.get(period=self.mid1).status, 'submitted')

    def test_autosave_returns_json(self):
        resp = self._post(self.mid1, xhr=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(SectionPeriodStatus.objects.get(period=self.mid1).status, 'saved')
        resp = self._post(self.mid2, xhr=True)
        self.assertEqual(resp.status_code, 403)
