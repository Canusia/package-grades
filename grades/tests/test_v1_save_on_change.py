"""Saving a grade page writes only the marks that changed: no history row and no
new entered_by for a student whose grade is the same as before."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model

from .base import GradesTestCase
from . import factories as f
from ..models import PeriodGrade
from ..services.grade_grid import build_formset
from ..services.periods import grades_for


class SaveOnlyChangedMarksTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        today = date.today()
        cls.term = f.term()
        cls.mid = f.period(cls.term, 'Mid 1', today - timedelta(days=5), today + timedelta(days=5))
        cls.final = f.period(cls.term, 'Final Grades', today - timedelta(days=5),
                             today + timedelta(days=5), sequence=9, is_final=True)
        cls.section = f.section(cls.term, f.teacher())
        cls.a = f.registration(cls.section, last_name='Alpha')
        cls.b = f.registration(cls.section, last_name='Bravo')
        User = get_user_model()
        cls.u1 = User.objects.create_user(username='one@example.com', email='one@example.com')
        cls.u2 = User.objects.create_user(username='two@example.com', email='two@example.com')

    def _save(self, period, grades, user):
        regs = [self.a, self.b]
        data = {'form-TOTAL_FORMS': str(len(regs)), 'form-INITIAL_FORMS': str(len(regs)),
                'form-MIN_NUM_FORMS': '1', 'form-MAX_NUM_FORMS': str(len(regs))}
        for i, (reg, grade) in enumerate(zip(regs, grades)):
            data.update({f'form-{i}-student_id': str(reg.id), f'form-{i}-student': 'x',
                         f'form-{i}-grade': grade})
        for reg in regs:
            reg.refresh_from_db()
        formset = build_formset(self.section, period, regs, grades_for(self.section, period, regs),
                                user=user, data=data)
        self.assertTrue(formset.is_valid(), formset.errors)
        formset.save()

    def _history(self, reg):
        return PeriodGrade.history.filter(period=self.mid, registration=reg).count()

    def test_same_interim_grades_twice_add_no_history(self):
        self._save(self.mid, ['A', 'B'], self.u1)
        self.assertEqual((self._history(self.a), self._history(self.b)), (1, 1))
        self._save(self.mid, ['A', 'B'], self.u1)
        self.assertEqual((self._history(self.a), self._history(self.b)), (1, 1))

    def test_one_change_adds_one_row_and_keeps_others_entered_by(self):
        self._save(self.mid, ['A', 'B'], self.u1)
        self._save(self.mid, ['A', 'C'], self.u2)
        self.assertEqual((self._history(self.a), self._history(self.b)), (1, 2))
        marks = {m.registration_id: m for m in PeriodGrade.objects.filter(period=self.mid)}
        self.assertEqual(marks[self.a.id].entered_by, self.u1)
        self.assertEqual(marks[self.b.id].entered_by, self.u2)
        self.assertEqual(marks[self.b.id].grade, 'C')

    def test_final_grades_written_only_when_changed(self):
        from cis.models.section import StudentRegistration
        self._save(self.final, ['A', 'B'], self.u1)
        count = StudentRegistration.history.filter(id__in=[self.a.id, self.b.id]).count
        before = count()
        self._save(self.final, ['A', 'B'], self.u1)
        self.assertEqual(count(), before)
        self._save(self.final, ['A', 'C'], self.u1)
        self.assertEqual(count(), before + 1)
        self.b.refresh_from_db()
        self.assertEqual(self.b.grade, 'C')
