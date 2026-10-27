"""grades.compat: fallbacks for tenants whose cis predates the modules grades uses.

Each test patches ``compat.has_module`` to report the module missing, which is the
only thing that differs on an in-repo-cis tenant (nnu, lsco, ...).
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from .base import GradesTestCase as TestCase

from cis.models.highschool import HighSchool

from .. import compat


def _missing(*names):
    real = compat.has_module
    return mock.patch.object(
        compat, 'has_module', side_effect=lambda name: name not in names and real(name))


class CisHasTests(TestCase):
    def test_present_and_absent_modules(self):
        self.assertTrue(compat.has_module('cis.models'))
        self.assertFalse(compat.has_module('cis.no_such_module'))
        self.assertFalse(compat.has_module('no_such_pkg.child'))


class SpecLessModuleTests(TestCase):
    """#11: package-cis registry stand-ins sit in sys.modules with no
    __spec__, which makes find_spec() raise ValueError."""

    def test_spec_less_module_in_sys_modules_is_importable(self):
        import sys
        import types
        name = 'grades_test_standin_registry'
        stand_in = types.ModuleType(name)
        stand_in.__spec__ = None
        stand_in.registration = object()
        self.addCleanup(sys.modules.pop, name, None)
        sys.modules[name] = stand_in
        self.assertTrue(compat.has_module(name))
        self.assertIs(compat.registry(name, 'registration'), stand_in.registration)

    def test_none_in_sys_modules_is_not_importable(self):
        import sys
        name = 'grades_test_blocked_module'
        self.addCleanup(sys.modules.pop, name, None)
        sys.modules[name] = None
        self.assertFalse(compat.has_module(name))


class PickerQuerysetFallbackTests(TestCase):
    def test_without_highschool_scope_lists_active_schools_by_name(self):
        b = HighSchool.objects.create(name='Zeta Compat', code='zc1', status='Active')
        a = HighSchool.objects.create(name='Alpha Compat', code='ac1', status='active')
        HighSchool.objects.create(name='Gone Compat', code='gc1', status='Inactive')
        with _missing('cis.highschool_scope'):
            names = [h.name for h in compat.picker_queryset()
                     if h.name.endswith('Compat')]
        self.assertEqual(names, [a.name, b.name])


class TenantOverrideFallbackTests(TestCase):
    def test_without_tenant_services_override_is_none(self):
        with _missing('cis.services.tenant_services'):
            self.assertIsNone(compat.get_tenant_override('grade_sis_pusher', 'x'))

    def test_sis_push_reports_unconfigured(self):
        from ..services import sis_push
        with _missing('cis.services.tenant_services'):
            self.assertIsNone(sis_push.get_pusher())
            self.assertEqual(sis_push.get_config_errors(), [])

    def test_can_push_is_false_not_an_error(self):
        from ..actions import can_push
        user = get_user_model().objects.create_user(
            username='compat-ce', email='compat-ce@example.com', password='x')
        user.groups.add(Group.objects.get_or_create(name='ce')[0])
        with _missing('cis.services.tenant_services'):
            self.assertFalse(can_push(user))


class CampusGateFallbackTests(TestCase):
    def test_reports_drop_the_campus_field_and_leave_records_unscoped(self):
        from ..reports.class_grade_status import class_grade_status
        from ..reports.grade_by_course import grade_by_course
        from ..reports.grade_by_demographics import grade_by_demographics
        with _missing('cis.campus_gate'):
            for form in (grade_by_course, grade_by_demographics, class_grade_status):
                self.assertNotIn('campus', form().fields, form.__name__)
            records = HighSchool.objects.all()
            self.assertIs(
                compat.scope_report_by_campus(records, None, None, 'campus'),
                records)

    def test_reports_keep_the_campus_field_when_gate_present(self):
        from ..reports.grade_by_course import grade_by_course
        self.assertIn('campus', grade_by_course().fields)


class RegistryFallbackTests(TestCase):
    def test_missing_registry_is_none_and_register_is_a_no_op(self):
        self.assertIsNone(compat.registry('myce.no_such_registry', 'tabs'))

        def fn():
            return 'unchanged'
        self.assertIs(compat.register(None, 'tab', slug='x')(fn), fn)

    def test_present_registry_is_returned(self):
        from myce.component_registry.term import term_tabs
        self.assertIs(
            compat.registry('myce.component_registry.term', 'term_tabs'), term_tabs)
