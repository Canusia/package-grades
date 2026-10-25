"""compat.portal_text: page text from the portal package when installed, else cis.

package-cis#81/#82 move the instructor and faculty portal text out of cis.
Patching ``compat.has_module`` stands in for a tenant that has not installed
the portal package (in-tree instructor/faculty), or whose cis no longer ships
its copy.
"""
from unittest import mock

from .base import GradesTestCase as TestCase

from cis.models.settings import Setting

from .. import compat

INSTRUCTOR_KEY = 'cis.settings.instructor_portal'
FACULTY_KEY = 'faculty.settings.faculty_portal'
FACULTY_LEGACY_KEY = 'cis.settings.faculty_portal'


def _only(*present):
    """has_module that reports only ``present`` among the portal-text sources."""
    sources = {m for role in compat.PORTAL_TEXT_SOURCES.values() for m, _ in role}
    real = compat.has_module
    return mock.patch.object(
        compat, 'has_module',
        side_effect=lambda name: name in present if name in sources else real(name))


class InstructorPortalTextTests(TestCase):
    def setUp(self):
        Setting.objects.update_or_create(
            key=INSTRUCTOR_KEY, defaults={'value': {'grades_blurb': 'Enter grades'}})

    def test_reads_the_stored_text(self):
        self.assertEqual(compat.portal_text('instructor')['grades_blurb'], 'Enter grades')

    def test_cis_copy_when_the_package_is_not_installed(self):
        with _only('cis.settings.instructor_portal'):
            self.assertEqual(compat.portal_text('instructor')['grades_blurb'], 'Enter grades')

    def test_package_copy_when_cis_no_longer_ships_one(self):
        module = next(m for m, _ in compat.PORTAL_TEXT_SOURCES['instructor']
                      if m != 'cis.settings.instructor_portal' and compat.has_module(m))
        with _only(module):
            self.assertEqual(compat.portal_text('instructor')['grades_blurb'], 'Enter grades')

    def test_empty_when_nothing_owns_it(self):
        with _only():
            self.assertEqual(compat.portal_text('instructor'), {})

    def test_empty_when_the_row_is_missing(self):
        Setting.objects.filter(key=INSTRUCTOR_KEY).delete()
        self.assertEqual(compat.portal_text('instructor'), {})


class FacultyPortalTextTests(TestCase):
    def setUp(self):
        Setting.objects.update_or_create(
            key=FACULTY_LEGACY_KEY, defaults={'value': {'a_blurb': 'old', 'b_blurb': 'old b'}})

    def test_cis_copy_when_the_package_is_not_installed(self):
        Setting.objects.update_or_create(key=FACULTY_KEY, defaults={'value': {'a_blurb': 'new'}})
        with _only('cis.settings.faculty_portal'):
            self.assertEqual(compat.portal_text('faculty')['a_blurb'], 'old')

    def test_package_copy_wins_and_falls_back_per_key(self):
        if not any(compat.has_module(m) for m, _ in compat.PORTAL_TEXT_SOURCES['faculty'][:2]):
            self.skipTest('faculty package not installed')
        Setting.objects.update_or_create(key=FACULTY_KEY, defaults={'value': {'a_blurb': 'new'}})
        text = compat.portal_text('faculty')
        self.assertEqual((text['a_blurb'], text['b_blurb']), ('new', 'old b'))
