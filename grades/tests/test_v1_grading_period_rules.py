"""v1: period fields and the no-overlap rule (spec §1)."""
from datetime import date

from .base import GradesTestCase
from . import factories as f
from ..forms.grading_period import GradingPeriodForm
from ..models import GradingPeriod


def _data(**kw):
    data = {'name': 'Mid 1', 'sequence': 1, 'opens_on': '2026-10-19',
            'due_on': '2026-10-30', 'reminder_frequency_days': 0,
            'remind_days_before_due': 0}
    data.update(kw)
    return data


class GradingPeriodV1Tests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.term = f.term()
        f.period(cls.term, 'Mid 1', date(2026, 10, 19), date(2026, 10, 30))

    def test_new_fields_default_off(self):
        p = GradingPeriod.objects.get(name='Mid 1')
        self.assertEqual(p.remind_days_before_due, 0)
        self.assertFalse(p.visible_to_students)

    def test_overlap_rejected(self):
        form = GradingPeriodForm(self.term, data=_data(
            name='Mid 2', opens_on='2026-10-25', due_on='2026-11-05'))
        self.assertFalse(form.is_valid())
        self.assertIn('overlap', str(form.errors))

    def test_touching_dates_overlap(self):
        form = GradingPeriodForm(self.term, data=_data(
            name='Mid 2', opens_on='2026-10-30', due_on='2026-11-05'))
        self.assertFalse(form.is_valid())

    def test_adjacent_dates_allowed(self):
        form = GradingPeriodForm(self.term, data=_data(
            name='Mid 2', opens_on='2026-10-31', due_on='2026-11-05',
            visible_to_students='on', remind_days_before_due=2))
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertTrue(saved.visible_to_students)
        self.assertEqual(saved.remind_days_before_due, 2)

    def test_editing_itself_is_not_an_overlap(self):
        p = GradingPeriod.objects.get(name='Mid 1')
        form = GradingPeriodForm(self.term, instance=p, data=_data(due_on='2026-10-31'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_other_term_does_not_overlap(self):
        other = f.term()
        form = GradingPeriodForm(other, data=_data())
        self.assertTrue(form.is_valid(), form.errors)
