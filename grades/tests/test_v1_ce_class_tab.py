"""v1: CE Class Details Grades tab (spec 5)."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import RequestFactory
from django.urls import reverse

from cis.models.note import ClassSectionNote

from .base import GradesTestCase
from . import factories as f
from ..models import PeriodGrade, SectionPeriodStatus
from ..services.periods import set_status

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None


class CEClassTabTests(GradesTestCase):
    @classmethod
    def setUpClass(cls):
        # force_login has no REMOTE_ADDR; the login-history receiver needs one.
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
        f.grades_setting()
        today = date.today()
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', today - timedelta(days=30), today - timedelta(days=20))
        cls.section = f.section(cls.term, f.teacher())
        cls.reg = f.registration(cls.section)
        cls.ce = get_user_model().objects.create_user(
            username='ce@example.com', email='ce@example.com', password='x', is_staff=True)
        cls.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        if getattr(cls, 'campus', None) is not None:
            from cis.signals.staff_campus import add_process_campuses
            add_process_campuses(cls.ce, [cls.campus])

    def setUp(self):
        self.client.force_login(self.ce)

    def test_tab_read_only_by_default(self):
        from ..tabs import ce_class_section_grades_tab
        request = RequestFactory().get('/')
        request.user = self.ce
        ctx = ce_class_section_grades_tab(request, self.section)
        self.assertIsNone(ctx['grid']['editable_period'])

    def test_ce_can_edit_closed_period_and_note_is_logged(self):
        url = reverse('grades_ce:class_section_grade', args=[self.section.id])
        self.client.post(url + f'?period={self.mid1.id}', {
            'period': str(self.mid1.id), 'save_grade': 'Submit', 'next': '/',
            'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1', 'form-MIN_NUM_FORMS': '1',
            'form-MAX_NUM_FORMS': '1', 'form-0-student': 'x',
            'form-0-student_id': str(self.reg.id), 'form-0-grade': 'B'})
        self.assertEqual(PeriodGrade.objects.get(period=self.mid1).grade, 'B')
        self.assertTrue(ClassSectionNote.objects.filter(
            class_section=self.section, note__icontains='ce@example.com').exists())

    def test_edit_page_renders(self):
        url = reverse('grades_ce:class_section_grade', args=[self.section.id])
        resp = self.client.get(url + f'?period={self.mid1.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Mid 1')

    def test_reopen(self):
        set_status(self.section, self.mid1, 'submitted')
        self.client.post(reverse('grades_ce:reopen_period', args=[self.section.id, self.mid1.id]))
        self.assertEqual(SectionPeriodStatus.objects.get(period=self.mid1).status, 'saved')

    def test_non_ce_forbidden(self):
        self.client.force_login(self.section.teacher.user)
        resp = self.client.post(reverse('grades_ce:reopen_period', args=[self.section.id, self.mid1.id]))
        self.assertNotEqual(resp.status_code, 200)
        self.assertEqual(SectionPeriodStatus.objects.filter(period=self.mid1).count(), 0)
