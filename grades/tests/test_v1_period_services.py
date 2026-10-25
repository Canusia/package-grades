"""v1: period-based services (spec §2)."""
from datetime import date
from unittest import mock

from django.test import RequestFactory

from .base import GradesTestCase
from . import factories as f
from ..services import periods as P
from ..services import window as W

TODAY = date(2026, 10, 25)


class PeriodServiceTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', date(2026, 10, 19), date(2026, 10, 30), 1)
        cls.mid2 = f.period(cls.term, 'Mid 2', date(2026, 11, 16), date(2026, 11, 27), 2)
        cls.final = f.period(cls.term, 'Final', date(2026, 12, 1), date(2026, 12, 9), 3, is_final=True)
        cls.section = f.section(cls.term, f.teacher())
        cls.empty_term = f.term()
        cls.empty_section = f.section(cls.empty_term, f.teacher())

    def test_open_period(self):
        self.assertEqual(P.open_period(self.section, TODAY), self.mid1)
        self.assertIsNone(P.open_period(self.section, date(2026, 11, 5)))

    def test_resolve_period_falls_back_to_latest_started(self):
        self.assertEqual(P.resolve_period(self.section, on_date=date(2026, 11, 5)), self.mid1)
        self.assertEqual(P.resolve_period(self.section, on_date=date(2026, 1, 1)), self.mid1)
        self.assertEqual(P.resolve_period(self.section, str(self.final.id)), self.final)
        self.assertIsNone(P.resolve_period(self.section, str(f.period(f.term(), 'X', TODAY, TODAY).id)))
        self.assertIsNone(P.resolve_period(self.empty_section))

    def test_editable(self):
        self.assertTrue(P.is_period_editable(self.section, self.mid1, TODAY))
        self.assertFalse(P.is_period_editable(self.section, self.mid2, TODAY))
        P.set_status(self.section, self.mid1, 'submitted')
        self.assertFalse(P.is_period_editable(self.section, self.mid1, TODAY))

    def test_editable_respects_roster_gate(self):
        f.grades_setting(require_roster_confirmation=True)
        self.section.roster_status = 'pending verification'
        self.assertFalse(P.is_period_editable(self.section, self.mid1, TODAY))

    def test_period_is_required(self):
        with self.assertRaises(ValueError):
            P.get_status(self.section, None)

    def test_marks_by_period(self):
        reg = f.registration(self.section)
        P.save_mark(self.mid1, reg, 'B')
        P.save_mark(self.final, reg, 'A')
        marks = P.marks_by_period(self.section, [self.mid1, self.mid2, self.final], [reg])
        self.assertEqual(marks[self.mid1.id][reg.id], 'B')
        self.assertEqual(marks[self.mid2.id].get(reg.id, ''), '')
        self.assertEqual(marks[self.final.id][reg.id], 'A')


class WindowServiceTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        cls.past = f.term()
        f.period(cls.past, 'Final', date(2026, 5, 1), date(2026, 5, 9), is_final=True)
        cls.now = f.term()
        f.period(cls.now, 'Mid 1', date(2026, 10, 19), date(2026, 10, 30))
        cls.none = f.term()

    def test_grade_terms_are_terms_with_periods(self):
        self.assertEqual(set(W.grade_terms()), {str(self.past.id), str(self.now.id)})

    def test_current_grade_terms(self):
        self.assertEqual(W.current_grade_terms(TODAY), [str(self.now.id)])

    def test_is_submit_grades_open(self):
        self.assertTrue(W.is_submit_grades_open(TODAY))
        self.assertFalse(W.is_submit_grades_open(date(2026, 11, 5)))

    def test_selected_term_ids(self):
        avail = W.grade_terms()
        rf = RequestFactory()
        self.assertEqual(W.selected_term_ids(rf.get('/'), avail, TODAY), [str(self.now.id)])
        self.assertEqual(W.selected_term_ids(rf.get('/', {'term': str(self.past.id)}), avail, TODAY),
                         [str(self.past.id)])
        # a term outside the available list is ignored, falling back to the default
        self.assertEqual(W.selected_term_ids(rf.get('/', {'term': str(self.none.id)}), avail, TODAY),
                         [str(self.now.id)])

    def test_submitted_grade_needs_submitted_final_period(self):
        section = f.section(self.past, f.teacher())
        reg = f.registration(section, grade='A')
        self.assertEqual(W.submitted_grade(reg), '-')
        P.set_status(section, P.periods_for_section(section)[0], 'submitted')
        reg.refresh_from_db()
        self.assertEqual(W.submitted_grade(reg), 'A')


class SectionsGradesTabTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        cls.term = f.term()
        f.period(cls.term, 'Final', date(2020, 1, 1), date(2040, 1, 1), is_final=True)

    def test_tab_renders_context_for_grade_terms(self):
        from ..tabs import sections_grades_tab
        ctx = sections_grades_tab(RequestFactory().get('/'), None)
        self.assertIn(self.term, list(ctx['terms']))


class CampusScopedWindowTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        from django.conf import settings
        from django.contrib.sites.models import Site
        from cis.models import Campus
        from cis.models.term import AcademicYear, Term
        f.grades_setting()
        site_b, _ = Site.objects.get_or_create(
            domain='campus-b.example.com', defaults={'name': 'campus-b'})
        prefix = getattr(settings, 'CAMPUS_CODE_PREFIX', 'TEST')
        cls.campus_a = getattr(cls, 'campus', None)
        if cls.campus_a is None:
            cls.campus_a = Campus.objects.first()
        cls.campus_b, _ = Campus.objects.update_or_create(
            code=f'{prefix}_B', defaults={'name': 'Campus B', 'site': site_b})
        ay_a = AcademicYear.objects.create(name='AY scoped A', campus=cls.campus_a)
        ay_b = AcademicYear.objects.create(name='AY scoped B', campus=cls.campus_b)
        cls.term_a = Term.objects.create(academic_year=ay_a, code='SA1', label='A')
        cls.term_b = Term.objects.create(academic_year=ay_b, code='SB1', label='B')
        f.period(cls.term_a, 'Final', date(2026, 5, 1), date(2026, 5, 9), is_final=True)
        f.period(cls.term_b, 'Mid', date(2026, 10, 19), date(2026, 10, 30))

    def setUp(self):
        from django.conf import settings
        if not getattr(settings, 'MULTI_CAMPUS', False):
            self.skipTest('multi-campus host only')

    def test_grade_terms_follow_current_campus(self):
        from cis.campus_context import campus_context
        with campus_context(self.campus_a):
            self.assertEqual(W.grade_terms(), [str(self.term_a.id)])
        with campus_context(self.campus_b):
            self.assertEqual(W.grade_terms(), [str(self.term_b.id)])

    def test_open_check_ignores_other_campus(self):
        from cis.campus_context import campus_context
        with campus_context(self.campus_a):
            self.assertFalse(W.is_submit_grades_open(TODAY))
            self.assertEqual(W.current_grade_terms(TODAY), [])
        with campus_context(self.campus_b):
            self.assertTrue(W.is_submit_grades_open(TODAY))
