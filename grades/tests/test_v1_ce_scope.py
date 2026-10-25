"""v1: CE grade pages scope by grading periods (spec §2)."""
from datetime import date, timedelta

from django.test import RequestFactory

from .base import GradesTestCase
from . import factories as f
from ..services import sis_push
from ..services.periods import set_status
from ..tabs import sections_grades_tab


class CEScopeTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        today = date.today()
        cls.term = f.term()
        cls.mid = f.period(cls.term, 'Mid', today - timedelta(days=1), today + timedelta(days=1), 1)
        cls.final = f.period(cls.term, 'Final', today + timedelta(days=10), today + timedelta(days=12), 2, is_final=True)
        cls.a = f.section(cls.term, f.teacher())
        cls.b = f.section(cls.term, f.teacher())

    def test_sections_tab_counts_per_period(self):
        set_status(self.a, self.mid, 'submitted')
        set_status(self.b, self.mid, 'saved')
        ctx = sections_grades_tab(RequestFactory().get('/'), None)
        mid = next(s for s in ctx['period_stats'] if s['period'] == self.mid)
        self.assertEqual((mid['submitted'], mid['saved'], mid['not_started'], mid['total']), (1, 1, 0, 2))

    def test_sections_tab_context_has_term_switcher(self):
        ctx = sections_grades_tab(RequestFactory().get('/'), None)
        self.assertIn(self.term, list(ctx['terms']))
        self.assertEqual(ctx['selected_term_ids'], [str(self.term.id)])

    def test_push_scope_is_grade_terms(self):
        set_status(self.a, self.final, 'submitted')
        ids, skipped = sis_push.select_for_sections([str(self.a.id), str(self.b.id)])
        self.assertIn(self.b, skipped)
