"""v1: students see a period's grades only when visible and submitted (spec §2)."""
from datetime import date

from .base import GradesTestCase
from . import factories as f
from ..services import student_table
from ..services.periods import save_mark, set_status


class StudentVisibilityTests(GradesTestCase):
    def test_visible_submitted_periods_only(self):
        f.grades_setting()
        term = f.term()
        mid1 = f.period(term, 'Mid 1', date(2026, 10, 1), date(2026, 10, 9), 1, visible_to_students=True)
        mid2 = f.period(term, 'Mid 2', date(2026, 11, 1), date(2026, 11, 9), 2, visible_to_students=False)
        final = f.period(term, 'Final', date(2026, 12, 1), date(2026, 12, 9), 3, is_final=True)
        section = f.section(term, f.teacher())
        reg = f.registration(section)
        for p, g in ((mid1, 'B'), (mid2, 'C'), (final, 'A')):
            save_mark(p, reg, g)
        cell = student_table.COLUMNS['grade'][1]
        self.assertEqual(cell(reg), '-')
        set_status(section, mid1, 'submitted')
        set_status(section, mid2, 'submitted')
        self.assertEqual(str(cell(reg)), 'Mid 1: B')
        set_status(section, final, 'submitted')
        reg.refresh_from_db()
        self.assertEqual(str(cell(reg)), 'Mid 1: B<br>Final: A')
