"""v1: HS admin grade entry on the shared grid (spec 3)."""
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.urls import reverse

from two_step.models import TwoStep

from .base import GradesTestCase
from . import factories as f
from ..models import PeriodGrade

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None


class HSAdminV1Tests(GradesTestCase):
    @classmethod
    def setUpClass(cls):
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
        f.grades_setting(hs_admin_grade_entry='Yes')
        today = date.today()
        cls.hs = f.highschool()
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', today - timedelta(days=1), today + timedelta(days=5))
        cls.mid2 = f.period(cls.term, 'Mid 2', today + timedelta(days=20), today + timedelta(days=25), 2)
        cls.section = f.section(cls.term, f.teacher(), highschool_obj=cls.hs)
        cls.reg = f.registration(cls.section, highschool_obj=cls.hs)
        cls.admin = get_user_model().objects.create_user(
            username='hsa@example.com', email='hsa@example.com', password='x')
        cls.admin.groups.add(Group.objects.get_or_create(name='highschool_admin')[0])

    def setUp(self):
        self.client.force_login(self.admin)
        TwoStep.objects.update_or_create(
            session_id=self.client.session.session_key, user=self.admin,
            defaults={'verification_code': '123456', 'verified': True})

    def _patch_schools(self, schools):
        from cis.models.highschool import HighSchool
        from ..views import hs_admin as hs_admin_views
        return mock.patch.object(
            hs_admin_views, '_hs_admin_context',
            return_value=([], HighSchool.objects.filter(pk__in=[s.pk for s in schools])))

    def _url(self):
        return reverse('grades_highschool_admin:class_section_grade', args=[self.section.id])

    def _post(self, period):
        return self.client.post(self._url(), {
            'period': str(period.id), 'save_grade': "Save Grades as 'Draft'", 'next': '/',
            'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1', 'form-MIN_NUM_FORMS': '1',
            'form-MAX_NUM_FORMS': '1', 'form-0-student': 'x',
            'form-0-student_id': str(self.reg.id), 'form-0-grade': 'B'})

    def test_open_period_saved(self):
        with self._patch_schools([self.hs]):
            self._post(self.mid1)
        self.assertEqual(PeriodGrade.objects.get(period=self.mid1).grade, 'B')

    def test_closed_period_refused(self):
        with self._patch_schools([self.hs]):
            self._post(self.mid2)
        self.assertFalse(PeriodGrade.objects.filter(period=self.mid2).exists())

    def test_other_school_404(self):
        with self._patch_schools([f.highschool()]):
            resp = self._post(self.mid1)
        self.assertEqual(resp.status_code, 404)

    def test_get_renders_shared_grid(self):
        with self._patch_schools([self.hs]):
            resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'grades/js/grade_roster.js')
        self.assertContains(resp, 'action=download_roster_pdf')

    def test_download_roster_get(self):
        with self._patch_schools([self.hs]), mock.patch(
                'cis.models.section.ClassSection.download_roster_pdf',
                return_value=__import__('django.http', fromlist=['x']).HttpResponse('pdf')):
            resp = self.client.get(self._url() + '?action=download_roster_pdf')
        self.assertEqual(resp.content, b'pdf')

    def test_download_roster_other_school_404(self):
        with self._patch_schools([f.highschool()]):
            resp = self.client.get(self._url() + '?action=download_roster_pdf')
        self.assertEqual(resp.status_code, 404)
