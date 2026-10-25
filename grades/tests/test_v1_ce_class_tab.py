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

    def _notes(self):
        return ClassSectionNote.objects.filter(
            class_section=self.section, note__icontains='on the instructor').count()

    def _base(self, grade='B'):
        return {
            'period': str(self.mid1.id), 'next': '/',
            'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1', 'form-MIN_NUM_FORMS': '1',
            'form-MAX_NUM_FORMS': '1', 'form-0-student': 'x',
            'form-0-student_id': str(self.reg.id), 'form-0-grade': grade}

    def test_invalid_post_adds_no_note(self):
        url = reverse('grades_ce:class_section_grade', args=[self.section.id])
        self.client.post(url + f'?period={self.mid1.id}', dict(self._base(''), save_grade='Submit'))
        self.assertEqual(self._notes(), 0)

    def test_xhr_draft_save_is_audited(self):
        """Every CE write leaves a note, even an XHR draft save."""
        url = reverse('grades_ce:class_section_grade', args=[self.section.id])
        resp = self.client.post(url + f'?period={self.mid1.id}',
                                dict(self._base(), save_grade="Save Grades as 'Draft'"),
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._notes(), 1)

    def test_edit_page_has_no_autosave(self):
        url = reverse('grades_ce:class_section_grade', args=[self.section.id])
        resp = self.client.get(url + f'?period={self.mid1.id}')
        self.assertNotContains(resp, 'data-autosave')
        self.assertNotContains(resp, 'save automatically')

    def test_editing_submitted_period_keeps_it_submitted(self):
        set_status(self.section, self.mid1, 'submitted')
        url = reverse('grades_ce:class_section_grade', args=[self.section.id])
        resp = self.client.get(url + f'?period={self.mid1.id}')
        self.assertContains(resp, 'Save Mid 1 Grades')
        self.assertNotContains(resp, "Save Grades as &#x27;Draft&#x27;")
        for label in ('Save Mid 1 Grades', "Save Grades as 'Draft'"):
            self.client.post(url + f'?period={self.mid1.id}', dict(self._base('C'), save_grade=label))
            self.assertEqual(SectionPeriodStatus.objects.get(period=self.mid1).status, 'submitted')
        self.client.post(url + f'?period={self.mid1.id}', dict(self._base('D'), save_grade="Save Grades as 'Draft'"),
                         HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(SectionPeriodStatus.objects.get(period=self.mid1).status, 'submitted')
        self.assertEqual(PeriodGrade.objects.get(period=self.mid1).grade, 'D')
        self.assertEqual(ClassSectionNote.objects.filter(
            class_section=self.section, note__icontains='edited submitted Mid 1').count(), 3)

    def test_editing_submitted_final_keeps_section_submitted(self):
        today = date.today()
        final = f.period(self.term, 'Final', today - timedelta(days=10), today - timedelta(days=5),
                         sequence=2, is_final=True)
        set_status(self.section, final, 'submitted')
        url = reverse('grades_ce:class_section_grade', args=[self.section.id])
        self.client.post(url + f'?period={final.id}', dict(self._base('A'), period=str(final.id),
                                                          save_grade="Save Grades as 'Draft'"))
        self.section.refresh_from_db()
        self.reg.refresh_from_db()
        self.assertEqual(self.section.grade_status, 'submitted')
        self.assertEqual(self.reg.grade, 'A')

    def test_draft_of_unsubmitted_period_stays_saved(self):
        url = reverse('grades_ce:class_section_grade', args=[self.section.id])
        self.client.post(url + f'?period={self.mid1.id}', dict(self._base(), save_grade="Save Grades as 'Draft'"))
        self.assertEqual(SectionPeriodStatus.objects.get(period=self.mid1).status, 'saved')

    def test_draft_and_submit_each_add_one_note(self):
        url = reverse('grades_ce:class_section_grade', args=[self.section.id])
        base = {
            'period': str(self.mid1.id), 'next': '/',
            'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1', 'form-MIN_NUM_FORMS': '1',
            'form-MAX_NUM_FORMS': '1', 'form-0-student': 'x',
            'form-0-student_id': str(self.reg.id), 'form-0-grade': 'B'}
        self.client.post(url + f'?period={self.mid1.id}', dict(base, save_grade="Save Grades as 'Draft'"))
        self.assertEqual(self._notes(), 1)
        self.client.post(url + f'?period={self.mid1.id}', dict(base, save_grade='Submit'))
        self.assertEqual(self._notes(), 2)

    def test_reopen_only_when_submitted(self):
        self.client.post(reverse('grades_ce:reopen_period', args=[self.section.id, self.mid1.id]))
        self.assertEqual(SectionPeriodStatus.objects.filter(period=self.mid1).count(), 0)
        self.assertEqual(ClassSectionNote.objects.filter(class_section=self.section).count(), 0)

    def test_reopen(self):
        set_status(self.section, self.mid1, 'submitted')
        self.client.post(reverse('grades_ce:reopen_period', args=[self.section.id, self.mid1.id]))
        self.assertEqual(SectionPeriodStatus.objects.get(period=self.mid1).status, 'saved')

    def test_non_ce_forbidden(self):
        self.client.force_login(self.section.teacher.user)
        resp = self.client.post(reverse('grades_ce:reopen_period', args=[self.section.id, self.mid1.id]))
        self.assertNotEqual(resp.status_code, 200)
        self.assertEqual(SectionPeriodStatus.objects.filter(period=self.mid1).count(), 0)


class CECampusScopeTests(GradesTestCase):
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
        from django.conf import settings
        from django.contrib.sites.models import Site
        from cis.models import Campus
        f.grades_setting()
        if not getattr(settings, 'MULTI_CAMPUS', False):
            return
        site_b, _ = Site.objects.get_or_create(
            domain='campus-b.example.com', defaults={'name': 'campus-b'})
        prefix = getattr(settings, 'CAMPUS_CODE_PREFIX', 'TEST')
        cls.campus_b, _ = Campus.objects.update_or_create(
            code=f'{prefix}_B', defaults={'name': 'Campus B', 'site': site_b})
        today = date.today()
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', today - timedelta(days=30), today - timedelta(days=20))
        cls.section = f.section(cls.term, f.teacher())
        cls.section.campus = cls.campus_b
        cls.section.save()
        cls.reg = f.registration(cls.section)
        set_status(cls.section, cls.mid1, 'submitted')
        cls.ce = get_user_model().objects.create_user(
            username='cea@example.com', email='cea@example.com', password='x', is_staff=True)
        cls.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        from cis.signals.staff_campus import add_process_campuses
        add_process_campuses(cls.ce, [cls.campus])

    def setUp(self):
        from django.conf import settings
        if not getattr(settings, 'MULTI_CAMPUS', False):
            self.skipTest('multi-campus host only')
        self.client.force_login(self.ce)

    def test_other_campus_section_is_404_everywhere(self):
        url = reverse('grades_ce:class_section_grade', args=[self.section.id])
        reopen = reverse('grades_ce:reopen_period', args=[self.section.id, self.mid1.id])
        self.assertEqual(self.client.get(url + f'?period={self.mid1.id}').status_code, 404)
        self.assertEqual(self.client.get(url + '?action=download_roster_pdf').status_code, 404)
        resp = self.client.post(url + f'?period={self.mid1.id}', {
            'period': str(self.mid1.id), 'save_grade': 'Submit', 'next': '/',
            'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1', 'form-MIN_NUM_FORMS': '1',
            'form-MAX_NUM_FORMS': '1', 'form-0-student': 'x',
            'form-0-student_id': str(self.reg.id), 'form-0-grade': 'B'})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.client.post(reopen).status_code, 404)
        self.assertFalse(PeriodGrade.objects.filter(period=self.mid1).exists())
        self.assertEqual(SectionPeriodStatus.objects.get(period=self.mid1).status, 'submitted')
        self.assertFalse(ClassSectionNote.objects.filter(class_section=self.section).exists())
