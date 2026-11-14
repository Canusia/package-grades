"""Grade scale records and the services/scales.py lookup."""
from datetime import date
from decimal import Decimal
from importlib import import_module

from django.db import IntegrityError, transaction

from ..models import GradeScale, GradeScaleEntry
from ..services import scales
from . import factories
from .base import GradesTestCase


def make_scale(name, letters, campus=None, is_default=False, last_attendance=()):
    scale = GradeScale.objects.create(name=name, campus=campus, is_default=is_default)
    for i, letter in enumerate(letters):
        GradeScaleEntry.objects.create(
            scale=scale, grade=letter, sequence=i,
            points=Decimal(str(4 - i)) if i < 5 else None,
            asks_last_attendance=letter in last_attendance)
    return scale


class LookupTests(GradesTestCase):
    def setUp(self):
        factories.grades_setting(grades='A,B,C', gpa_points={'A': 4, 'B': 3})
        self.term = factories.term()
        self.campus = scales.current_campus()

    def test_falls_back_to_the_setting_without_records(self):
        scale = scales.default_scale()
        self.assertIsNone(scale.record)
        self.assertEqual(scale.letters(), ['A', 'B', 'C'])
        self.assertEqual(scale.points_map(), {'A': 4.0, 'B': 3.0})
        self.assertEqual(scale.last_attendance_letters(), [])

    def test_default_record_wins_over_the_setting(self):
        make_scale('Std', ['A', 'F'], campus=self.campus, is_default=True,
                   last_attendance=['F'])
        scale = scales.default_scale()
        self.assertEqual(scale.letters(), ['A', 'F'])
        self.assertTrue(scale.asks_last_attendance('F'))
        self.assertTrue(scale.asks_last_attendance(' F '))
        self.assertFalse(scale.asks_last_attendance('A'))

    def test_campus_default_wins_over_the_global_default(self):
        if self.campus is None:
            self.skipTest('single-campus host')
        make_scale('Global', ['P', 'NP'], is_default=True)
        make_scale('Campus', ['A', 'F'], campus=self.campus, is_default=True)
        self.assertEqual(scales.default_scale().letters(), ['A', 'F'])

    def test_global_default_serves_a_campus_without_its_own(self):
        make_scale('Global', ['P', 'NP'], is_default=True)
        self.assertEqual(scales.default_scale().letters(), ['P', 'NP'])

    def test_period_uses_its_own_scale_else_the_default(self):
        make_scale('Std', ['A', 'F'], campus=self.campus, is_default=True)
        mid = make_scale('Mid', ['S', 'U'], campus=self.campus)
        midterm = factories.period(self.term, 'Midterm', date(2020, 1, 1), date(2020, 2, 1),
                                   grade_scale=mid)
        final = factories.period(self.term, 'Final', date(2020, 3, 1), date(2020, 4, 1),
                                 is_final=True)
        self.assertEqual(midterm.scale().letters(), ['S', 'U'])
        self.assertEqual(final.scale().letters(), ['A', 'F'])
        self.assertEqual(scales.final_scale_for_term(self.term).letters(), ['A', 'F'])

    def test_final_scale_for_term_without_a_final_period(self):
        self.assertEqual(scales.final_scale_for_term(self.term).letters(), ['A', 'B', 'C'])

    def test_all_final_letters_unions_final_scales(self):
        make_scale('Std', ['A', 'F'], campus=self.campus, is_default=True)
        other = make_scale('Other', ['A', 'P', 'NP'], campus=self.campus)
        factories.period(self.term, 'Final', date(2020, 3, 1), date(2020, 4, 1),
                         is_final=True, grade_scale=other)
        self.assertEqual(scales.all_final_letters([self.term.id]), ['A', 'F', 'P', 'NP'])

    def test_ensure_default_record_copies_the_setting_once(self):
        record = scales.ensure_default_record()
        self.assertTrue(record.is_default)
        self.assertEqual([e.grade for e in record.entries.order_by('sequence')], ['A', 'B', 'C'])
        self.assertEqual(scales.ensure_default_record(), record)
        self.assertEqual(GradeScale.objects.count(), 1)


class ConstraintTests(GradesTestCase):
    def test_one_default_per_campus(self):
        campus = scales.current_campus()
        make_scale('One', ['A'], campus=campus, is_default=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_scale('Two', ['A'], campus=campus, is_default=True)

    def test_letter_unique_within_a_scale(self):
        scale = make_scale('One', ['A'])
        with self.assertRaises(IntegrityError), transaction.atomic():
            GradeScaleEntry.objects.create(scale=scale, grade='A')

    def test_scale_in_use_cannot_be_deleted(self):
        from django.db.models import ProtectedError
        scale = make_scale('Used', ['A'])
        factories.period(factories.term(), 'Final', date(2020, 1, 1), date(2020, 2, 1),
                         grade_scale=scale)
        with self.assertRaises(ProtectedError):
            scale.delete()


class SettingMigrationParseTests(GradesTestCase):
    """The data migration's parser for every saved setting shape."""

    def setUp(self):
        self.parse = import_module(
            f'{GradeScale.__module__.rsplit(".", 1)[0]}.migrations.0010_settings_to_grade_scales'
        ).entries_from_setting

    def test_grade_scale_list(self):
        self.assertEqual(
            self.parse({'grade_scale': [{'grade': 'A', 'points': 4.0},
                                        {'grade': 'P', 'points': None},
                                        {'grade': '-', 'points': 0}]}),
            [('A', Decimal('4.00')), ('P', None)])

    def test_legacy_grades_and_gpa_points(self):
        self.assertEqual(self.parse({'grades': 'A, B,-', 'gpa_points': {'A': '4.0'}}),
                         [('A', Decimal('4.00')), ('B', None)])

    def test_empty_gives_the_shipped_default(self):
        parsed = self.parse({})
        self.assertEqual(parsed[0], ('A', Decimal('4.0')))
        self.assertEqual(parsed[-1][0], 'F')


class ReportScaleTests(GradesTestCase):
    def test_gpa_uses_each_terms_final_scale(self):
        from cis.models.section import StudentRegistration
        from ..services.report_marks import gpa_by_group, period_mark_annotation, report_letters
        factories.grades_setting(grades='A,B,C')
        campus = scales.current_campus()
        make_scale('Std', ['A', 'B'], campus=campus, is_default=True)   # A=4, B=3
        honors = GradeScale.objects.create(name='Honors', campus=campus)
        GradeScaleEntry.objects.create(scale=honors, grade='A', points=Decimal('5'), sequence=0)
        GradeScaleEntry.objects.create(scale=honors, grade='P', points=None, sequence=1)
        t1, t2 = factories.term(), factories.term()
        factories.period(t1, 'Final', date(2020, 1, 1), date(2020, 2, 1), is_final=True)
        factories.period(t2, 'Final', date(2020, 1, 1), date(2020, 2, 1), is_final=True,
                         grade_scale=honors)
        course = factories.course(catalog_number='999')
        s1 = factories.section(t1, course_obj=course)
        s2 = factories.section(t2, course_obj=course)
        factories.registration(s1, grade='A')
        factories.registration(s1, grade='B')
        factories.registration(s2, grade='A')
        factories.registration(s2, grade='P')   # no points: left out

        regs = StudentRegistration.objects.filter(class_section__in=[s1, s2]).annotate(
            period_mark=period_mark_annotation(None))

        gpa = gpa_by_group(regs, ['class_section__course__id'])
        self.assertAlmostEqual(gpa[(course.id,)], (4 + 3 + 5) / 3)
        self.assertEqual(report_letters(regs), ['A', 'B', 'P'])
