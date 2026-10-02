"""Campus-scoped school pickers on the grade reports (cis HighSchoolCampus)."""
import uuid

from django.conf import settings
from django.test import TestCase, override_settings

from cis.campus_context import campus_context
from cis.models.course import Campus
from cis.models.highschool import HighSchool, HighSchoolCampus


def _sfx():
    return uuid.uuid4().hex[:8]


def _campus():
    return Campus.objects.create(
        name=f"C-{_sfx()}", code=f"{settings.CAMPUS_CODE_PREFIX}_{_sfx()[:6]}")


def _hs(name, campus=None, status="Active"):
    hs = HighSchool.objects.create(name=name, code=_sfx())
    HighSchoolCampus.objects.filter(highschool=hs).delete()
    if campus is not None:
        HighSchoolCampus.objects.create(
            highschool=hs, campus=campus, status=status)
    return hs


class _Base(TestCase):
    def setUp(self):
        self.a, self.b = _campus(), _campus()
        self.mine = _hs("Mine", self.a)
        self.foreign = _hs("Foreign", self.b)
        self.dormant = _hs("Dormant", self.a, "Inactive")


from ..reports.grade_by_course import grade_by_course
from ..reports.grade_by_demographics import grade_by_demographics
from ..reports.grade_by_highschool import grade_by_highschool

FORMS = (grade_by_course, grade_by_demographics, grade_by_highschool)


@override_settings(MULTI_CAMPUS=True)
class MultiCampusTests(_Base):
    def test_excludes_other_campus_and_inactive_schools(self):
        for form in FORMS:
            with campus_context(self.a):
                qs = form().fields['highschools'].queryset
                self.assertEqual(list(qs), [self.mine], form.__name__)

    def test_follows_the_request_campus(self):
        for form in FORMS:
            with campus_context(self.b):
                qs = form().fields['highschools'].queryset
                self.assertEqual(list(qs), [self.foreign], form.__name__)

    def test_foreign_school_is_not_a_valid_choice(self):
        for form in FORMS:
            with campus_context(self.a):
                field = form().fields['highschools']
                from django.core.exceptions import ValidationError
                with self.assertRaises(ValidationError, msg=form.__name__):
                    field.clean([str(self.foreign.pk)])


@override_settings(MULTI_CAMPUS=False)
class SingleCampusTests(_Base):
    def test_options_are_campus_linked_active_schools(self):
        for form in FORMS:
            with campus_context(self.a):
                qs = form().fields['highschools'].queryset
                self.assertEqual(list(qs), [self.mine], form.__name__)
