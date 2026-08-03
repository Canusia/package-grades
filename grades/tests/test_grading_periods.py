"""Phase A: grading period models, constraints, and the CE form.

The database constraints are tested directly rather than only through the form.
`one final per term` protects the SIS-bound grade column -- if a second final
period could exist, the final grade for a term would be split across two
collections -- so it must hold even when a write bypasses the form.

See docs/superpowers/specs/2026-08-02-grades-grading-periods-design.md
"""
from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase

from cis.models.term import AcademicYear, Term

from ..models import GradingPeriod


class GradingPeriodConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ay = AcademicYear.objects.create(name='AY periods')
        cls.term = Term.objects.create(
            academic_year=cls.ay, code='FA28', label='Fall 2028')
        cls.other_term = Term.objects.create(
            academic_year=cls.ay, code='SP29', label='Spring 2029')

    def _period(self, term=None, name='Midterm', is_final=False, sequence=0):
        return GradingPeriod.objects.create(
            term=term or self.term,
            name=name,
            sequence=sequence,
            opens_on=date(2028, 9, 1),
            due_on=date(2028, 10, 1),
            is_final=is_final,
        )

    def test_one_final_period_per_term_enforced_by_database(self):
        self._period(name='Final', is_final=True)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._period(name='Another Final', is_final=True)

    def test_final_period_allowed_in_each_term_independently(self):
        self._period(name='Final', is_final=True)
        self._period(term=self.other_term, name='Final', is_final=True)

        self.assertEqual(
            GradingPeriod.objects.filter(is_final=True).count(), 2)

    def test_multiple_interim_periods_allowed(self):
        self._period(name='Midterm 1', sequence=1)
        self._period(name='Midterm 2', sequence=2)
        self._period(name='Final', is_final=True, sequence=3)

        self.assertEqual(
            GradingPeriod.objects.filter(term=self.term).count(), 3)

    def test_name_unique_within_term(self):
        self._period(name='Midterm')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._period(name='Midterm')

    def test_same_name_allowed_in_different_terms(self):
        self._period(name='Midterm')
        self._period(term=self.other_term, name='Midterm')

        self.assertEqual(GradingPeriod.objects.filter(name='Midterm').count(), 2)

    def test_ordering_is_by_sequence(self):
        self._period(name='Third', sequence=3)
        self._period(name='First', sequence=1)
        self._period(name='Second', sequence=2)

        names = list(
            GradingPeriod.objects.filter(term=self.term).values_list(
                'name', flat=True))
        self.assertEqual(names, ['First', 'Second', 'Third'])


class GradingPeriodSubtermTests(TestCase):
    """Sections follow their own term's periods, never a parent term's.

    This is what lets an 8-week class inside a 16-week term have a different
    schedule without a per-section opt-in.
    """

    @classmethod
    def setUpTestData(cls):
        ay = AcademicYear.objects.create(name='AY subterm')
        cls.parent = Term.objects.create(
            academic_year=ay, code='FA30', label='Fall 2030')
        cls.subterm = Term.objects.create(
            academic_year=ay, code='FA30A', label='Fall 2030 First 8 Weeks',
            parent=cls.parent)

    def test_subterm_periods_are_independent_of_parent(self):
        GradingPeriod.objects.create(
            term=self.parent, name='Midterm', sequence=1,
            opens_on=date(2030, 10, 1), due_on=date(2030, 10, 15))
        GradingPeriod.objects.create(
            term=self.subterm, name='Final', sequence=1, is_final=True,
            opens_on=date(2030, 9, 15), due_on=date(2030, 9, 30))

        self.assertEqual(
            list(self.subterm.grading_periods.values_list('name', flat=True)),
            ['Final'])
        self.assertEqual(
            list(self.parent.grading_periods.values_list('name', flat=True)),
            ['Midterm'])

    def test_parent_link_is_available_but_periods_do_not_inherit(self):
        GradingPeriod.objects.create(
            term=self.parent, name='Final', sequence=1, is_final=True,
            opens_on=date(2030, 12, 1), due_on=date(2030, 12, 15))

        self.assertEqual(self.subterm.parent, self.parent)
        self.assertFalse(self.subterm.grading_periods.exists())


class GradingPeriodFormTests(TestCase):
    """The CE form must turn constraint violations into field errors, not 500s."""

    @classmethod
    def setUpTestData(cls):
        ay = AcademicYear.objects.create(name='AY form')
        cls.term = Term.objects.create(
            academic_year=ay, code='FA31', label='Fall 2031')

    def _form(self, **overrides):
        from ..forms.grading_period import GradingPeriodForm

        data = {
            'name': 'Midterm',
            'sequence': 1,
            'opens_on': '09/01/2031',
            'due_on': '10/01/2031',
            'reminder_frequency_days': 0,
        }
        data.update(overrides.pop('data', {}))
        return GradingPeriodForm(self.term, data=data, **overrides)

    def test_due_before_opens_is_rejected(self):
        form = self._form(data={'opens_on': '10/01/2031', 'due_on': '09/01/2031'})

        self.assertFalse(form.is_valid())
        self.assertIn('due_on', form.errors)

    def test_second_final_period_is_a_field_error_not_an_exception(self):
        GradingPeriod.objects.create(
            term=self.term, name='Final', sequence=9, is_final=True,
            opens_on=date(2031, 12, 1), due_on=date(2031, 12, 15))

        form = self._form(data={'name': 'Another Final', 'is_final': True})

        self.assertFalse(form.is_valid())
        self.assertIn('is_final', form.errors)

    def test_duplicate_name_in_term_is_a_field_error(self):
        GradingPeriod.objects.create(
            term=self.term, name='Midterm', sequence=1,
            opens_on=date(2031, 9, 1), due_on=date(2031, 10, 1))

        form = self._form()

        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)

    def test_valid_period_saves(self):
        form = self._form()

        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.assertTrue(
            GradingPeriod.objects.filter(term=self.term, name='Midterm').exists())
