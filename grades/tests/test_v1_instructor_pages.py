"""v1: instructor grade page and Class Details tab (spec §3)."""
from datetime import date, timedelta

import json

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.urls import reverse

from cis.models.settings import Setting

from .base import GradesTestCase
from . import factories as f
from ..compat import has_module

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None


class InstructorPagesTests(GradesTestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's handler fails on the test client's missing IP.
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='instructor')
        Setting.objects.get_or_create(
            key='cis.settings.menu',
            defaults={'value': {'instructor_menu': json.dumps([])}})
        f.grades_setting()
        today = date.today()
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', today - timedelta(days=3), today + timedelta(days=3))
        cls.teacher = f.teacher()
        cls.teacher.user.groups.add(Group.objects.get(name='instructor'))
        cls.section = f.section(cls.term, cls.teacher)
        f.registration(cls.section, last_name='Amador')
        cls.other = f.section(cls.term, f.teacher())

    def setUp(self):
        self.client.force_login(self.teacher.user)

    def test_standalone_page_renders_grid(self):
        resp = self.client.get(reverse('instructor:class_section_grade', args=[self.section.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Mid 1')
        self.assertContains(resp, 'Amador')
        self.assertContains(resp, 'name="next"')

    def test_other_instructors_section_404(self):
        resp = self.client.get(reverse('instructor:class_section_grade', args=[self.other.id]))
        self.assertEqual(resp.status_code, 404)

    def test_post_redirects_back_to_tab(self):
        url = reverse('instructor:class_section_grade', args=[self.section.id])
        resp = self.client.post(url, {'period': str(self.mid1.id), 'save_grade': "Save Grades as 'Draft'",
                                      'next': f'/instructor/class_section/{self.section.id}#grades',
                                      'form-TOTAL_FORMS': '0', 'form-INITIAL_FORMS': '0',
                                      'form-MIN_NUM_FORMS': '0', 'form-MAX_NUM_FORMS': '1'})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].endswith('#grades'))

    def test_tab_registered_and_hidden_without_periods(self):
        if not (has_module('instructor.instructor.registry') or has_module('instructor.registry')):
            self.skipTest('instructor portal not installed')
        from ..instructor_tabs import instructor_class_section_tabs, _has_periods
        self.assertIn('grades', instructor_class_section_tabs._tabs)
        self.assertTrue(_has_periods(self.teacher.user, self.section))
        self.assertFalse(_has_periods(self.teacher.user, f.section(f.term(), self.teacher)))

    def test_tab_fragment_renders_grid_posting_to_grades_url(self):
        if not (has_module('instructor.instructor.registry') or has_module('instructor.registry')):
            self.skipTest('instructor portal not installed')
        from django.test import RequestFactory
        from ..instructor_tabs import instructor_class_section_tabs
        request = RequestFactory().get('/')
        request.user = self.teacher.user
        resp = instructor_class_section_tabs.render_tab(request, self.section, 'grades')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('Amador', html)
        self.assertIn(reverse('instructor:class_section_grade', args=[self.section.id]), html)
        self.assertIn(f'/instructor/class_section/{self.section.id}#grades', html)

    def test_standalone_page_has_only_grades_and_notes_tabs(self):
        if not (has_module('instructor.instructor.registry') or has_module('instructor.registry')):
            self.skipTest('instructor portal not installed')
        resp = self.client.get(reverse('instructor:class_section_grade', args=[self.section.id]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('href="#grades"', html)
        self.assertIn('href="#notes"', html)
        for slug in ('details', 'class_roster', 'docs'):
            self.assertNotIn(f'href="#{slug}"', html)
        self.assertNotIn('card-header">Details', html)
        self.assertIn('Amador', html)

    def test_standalone_page_has_only_grades_and_notes_tabs(self):
        if not (has_module('instructor.instructor.registry') or has_module('instructor.registry')):
            self.skipTest('instructor portal not installed')
        resp = self.client.get(reverse('instructor:class_section_grade', args=[self.section.id]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('href="#grades"', html)
        self.assertIn('href="#notes"', html)
        for slug in ('details', 'class_roster', 'docs'):
            self.assertNotIn(f'href="#{slug}"', html)
        self.assertIn('Amador', html)
        self.assertIn('?action=download_grades', html)

    def test_download_grades_csv_has_a_column_per_period(self):
        url = reverse('instructor:class_section_grade', args=[self.section.id])
        resp = self.client.get(url + '?action=download_grades')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        lines = resp.content.decode().splitlines()
        self.assertTrue(lines[0].endswith('Mid 1'))
        self.assertIn('Amador', lines[1])

    def test_download_grades_other_instructors_section_404(self):
        url = reverse('instructor:class_section_grade', args=[self.other.id])
        self.assertEqual(self.client.get(url + '?action=download_grades').status_code, 404)
