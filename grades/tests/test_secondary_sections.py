"""cis#154: secondary teachers and secondary high schools on a class section.

Grade entry stays with the primary teacher: a secondary teacher gets no
"My Grades" row, no grade page, no Grades tab. An HS admin at a secondary
school reaches the grade page but sees -- and may grade -- only their own
school's students; a primary-school admin keeps the whole class.
"""
import json
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from cis.models.settings import Setting
from two_step.models import TwoStep

from .base import GradesTestCase
from . import factories as f
from .. import page_messages as pm
from ..compat import has_module
from ..models import PeriodGrade, SectionPeriodStatus
from ..services.periods import set_status
from ..services.summary import summarize


class _NoLoginHistory:
    """django_login_history's handler fails on the test client's missing IP."""

    @classmethod
    def setUpClass(cls):
        cls._saved_receivers = list(user_logged_in.receivers)
        user_logged_in.receivers = []
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        user_logged_in.receivers = cls._saved_receivers


class SecondaryTeacherGradesTests(_NoLoginHistory, GradesTestCase):
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
        cls.primary = f.teacher()
        cls.secondary = f.teacher()
        cls.section = f.section(cls.term, cls.primary)
        cls.section.add_secondary_teacher(cls.secondary)
        cls.reg = f.registration(cls.section, last_name='Amador')

    def setUp(self):
        self.client.force_login(self.secondary.user)

    def _url(self):
        return reverse('instructor:class_section_grade', args=[self.section.id])

    def test_secondary_teacher_has_no_my_grades_row(self):
        resp = self.client.get(reverse('instructor:grades'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, self._url())

    def test_primary_teacher_still_has_the_row(self):
        self.client.force_login(self.primary.user)
        resp = self.client.get(reverse('instructor:grades'))
        self.assertContains(resp, self._url())

    def test_secondary_teacher_grade_page_404(self):
        self.assertEqual(self.client.get(self._url()).status_code, 404)
        self.assertEqual(
            self.client.get(self._url() + '?action=download_grades').status_code, 404)
        self.assertEqual(
            self.client.get(self._url() + '?action=download_roster_pdf').status_code, 404)

    def test_secondary_teacher_post_404_and_nothing_saved(self):
        resp = self.client.post(self._url(), {
            'period': str(self.mid1.id), 'save_grade': "Save Grades as 'Draft'", 'next': '/',
            'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1', 'form-MIN_NUM_FORMS': '1',
            'form-MAX_NUM_FORMS': '1', 'form-0-student': 'x',
            'form-0-student_id': str(self.reg.id), 'form-0-grade': 'B'})
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(PeriodGrade.objects.exists())

    def test_secondary_teacher_gets_no_grades_tab(self):
        if not (has_module('instructor.instructor.registry') or has_module('instructor.registry')):
            self.skipTest('instructor portal not installed')
        from ..instructor_tabs import _has_periods
        self.assertTrue(_has_periods(self.primary.user, self.section))
        self.assertFalse(_has_periods(self.secondary.user, self.section))

    def test_secondary_teacher_gets_no_page_message(self):
        request = RequestFactory().get('/')
        request.user = self.secondary.user
        self.assertEqual(pm.instructor_grades(request), [])


class SecondaryHighSchoolAdminGradesTests(_NoLoginHistory, GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting(hs_admin_grade_entry='Yes')
        today = date.today()
        cls.primary_hs = f.highschool()
        cls.secondary_hs = f.highschool()
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', today - timedelta(days=1), today + timedelta(days=5))
        cls.section = f.section(cls.term, f.teacher(), highschool_obj=cls.primary_hs)
        cls.section.add_secondary_highschool(cls.secondary_hs)
        cls.mine = f.registration(cls.section, highschool_obj=cls.secondary_hs,
                                  last_name='Secondaryson')
        cls.theirs = f.registration(cls.section, highschool_obj=cls.primary_hs,
                                    last_name='Primarydottir')
        cls.admin = get_user_model().objects.create_user(
            username='hsa2@example.com', email='hsa2@example.com', password='x')
        cls.admin.groups.add(Group.objects.get_or_create(name='highschool_admin')[0])

    def setUp(self):
        self.client.force_login(self.admin)
        TwoStep.objects.update_or_create(
            session_id=self.client.session.session_key, user=self.admin,
            defaults={'verification_code': '123456', 'verified': True})

    def _schools(self, schools):
        from cis.models.highschool import HighSchool
        from ..views import hs_admin as hs_admin_views
        return mock.patch.object(
            hs_admin_views, '_hs_admin_context',
            return_value=([], HighSchool.objects.filter(pk__in=[s.pk for s in schools])))

    def _url(self, query=''):
        return reverse('grades_highschool_admin:class_section_grade',
                       args=[self.section.id]) + query

    def _post(self, regs, save='Save Grades as \'Draft\''):
        data = {'period': str(self.mid1.id), 'save_grade': save, 'next': '/',
                'form-TOTAL_FORMS': str(len(regs)), 'form-INITIAL_FORMS': str(len(regs)),
                'form-MIN_NUM_FORMS': '1', 'form-MAX_NUM_FORMS': str(len(regs))}
        for i, reg in enumerate(regs):
            data.update({f'form-{i}-student': 'x', f'form-{i}-student_id': str(reg.id),
                         f'form-{i}-grade': 'B'})
        return self.client.post(self._url(), data)

    # -- the grid --------------------------------------------------------

    def test_secondary_admin_sees_only_own_students(self):
        with self._schools([self.secondary_hs]):
            resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Secondaryson')
        self.assertNotContains(resp, 'Primarydottir')

    def test_secondary_admin_cannot_submit_the_whole_class(self):
        with self._schools([self.secondary_hs]):
            resp = self.client.get(self._url())
        self.assertNotContains(resp, 'Submit Mid 1 Grades')
        self.assertContains(resp, "Save Grades as 'Draft'")

    def test_primary_admin_sees_whole_class(self):
        with self._schools([self.primary_hs]):
            resp = self.client.get(self._url())
        self.assertContains(resp, 'Secondaryson')
        self.assertContains(resp, 'Primarydottir')
        self.assertContains(resp, 'Submit Mid 1 Grades')

    def test_admin_of_both_schools_sees_whole_class(self):
        with self._schools([self.primary_hs, self.secondary_hs]):
            resp = self.client.get(self._url())
        self.assertContains(resp, 'Secondaryson')
        self.assertContains(resp, 'Primarydottir')

    def test_unrelated_school_404(self):
        with self._schools([f.highschool()]):
            self.assertEqual(self.client.get(self._url()).status_code, 404)
            self.assertEqual(self._post([self.mine]).status_code, 404)
        self.assertFalse(PeriodGrade.objects.exists())

    def test_section_without_primary_school_admits_secondary_admin(self):
        self.section.highschool = None
        self.section.save()
        with self._schools([self.secondary_hs]):
            resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Secondaryson')
        self.assertNotContains(resp, 'Primarydottir')

    def test_csv_is_scoped(self):
        with self._schools([self.secondary_hs]):
            resp = self.client.get(self._url('?action=download_grades'))
        body = resp.content.decode()
        self.assertIn('Secondaryson', body)
        self.assertNotIn('Primarydottir', body)

    def test_roster_pdf_is_scoped(self):
        captured = {}

        def fake_pdf(html, *args, **kwargs):
            captured['html'] = html
            return b'%PDF'
        with self._schools([self.secondary_hs]), mock.patch('pdfkit.from_string', fake_pdf):
            resp = self.client.get(self._url('?action=download_roster_pdf'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertIn('Secondaryson', captured['html'])
        self.assertNotIn('Primarydottir', captured['html'])

    def test_primary_admin_roster_pdf_is_the_cis_one(self):
        with self._schools([self.primary_hs]), mock.patch(
                'cis.models.section.ClassSection.download_roster_pdf',
                return_value=HttpResponse('whole')):
            resp = self.client.get(self._url('?action=download_roster_pdf'))
        self.assertEqual(resp.content, b'whole')

    # -- POST ------------------------------------------------------------

    def test_secondary_admin_saves_own_student(self):
        with self._schools([self.secondary_hs]):
            self._post([self.mine])
        self.assertEqual(PeriodGrade.objects.get(registration=self.mine).grade, 'B')

    def test_secondary_admin_post_for_other_school_student_rejected(self):
        with self._schools([self.secondary_hs]):
            resp = self._post([self.mine, self.theirs])
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(PeriodGrade.objects.exists())

    def test_secondary_admin_autosave_for_other_school_student_403(self):
        with self._schools([self.secondary_hs]):
            resp = self.client.post(self._url(), {
                'period': str(self.mid1.id), 'save_grade': "Save Grades as 'Draft'",
                'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1', 'form-MIN_NUM_FORMS': '1',
                'form-MAX_NUM_FORMS': '1', 'form-0-student': 'x',
                'form-0-student_id': str(self.theirs.id), 'form-0-grade': 'B'},
                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(PeriodGrade.objects.exists())

    def test_secondary_admin_submit_saves_but_does_not_submit_the_class(self):
        with self._schools([self.secondary_hs]):
            self._post([self.mine], save='Submit Mid 1 Grades')
        self.assertEqual(PeriodGrade.objects.get(registration=self.mine).grade, 'B')
        row = SectionPeriodStatus.objects.get(period=self.mid1, class_section=self.section)
        self.assertEqual(row.status, 'saved')

    def test_primary_admin_still_submits_the_class(self):
        with self._schools([self.primary_hs]):
            self._post([self.mine, self.theirs], save='Submit Mid 1 Grades')
        row = SectionPeriodStatus.objects.get(period=self.mid1, class_section=self.section)
        self.assertEqual(row.status, 'submitted')
        self.assertEqual(PeriodGrade.objects.count(), 2)

    # -- the inline tab on the HS admin class page -----------------------

    def test_tab_is_scoped(self):
        from ..tabs import hs_admin_grades_tab
        request = RequestFactory().get('/')
        request.user = self.admin
        with self._schools([self.secondary_hs]):
            ctx = hs_admin_grades_tab(request, self.section)
        regs = [row['registration'] for row in ctx['grid']['rows']]
        self.assertEqual(regs, [self.mine])
        self.assertFalse(ctx['grid']['can_submit'])

    def test_tab_for_admin_off_the_section_keeps_whole_class(self):
        # highschool_admin may show the class page through another rule
        # (hosted_or_own_students); the tab then lists the class as before #154.
        from ..tabs import hs_admin_grades_tab
        request = RequestFactory().get('/')
        request.user = self.admin
        with self._schools([f.highschool()]):
            ctx = hs_admin_grades_tab(request, self.section)
        regs = {row['registration'] for row in ctx['grid']['rows']}
        self.assertEqual(regs, {self.mine, self.theirs})
        self.assertTrue(ctx['grid']['can_submit'])

    def test_narrowed_to_schools_on_the_section(self):
        # The admin also runs a school that is not on the section; a student
        # of that school CE-enrolled into the section stays hidden.
        stray_hs = f.highschool()
        f.registration(self.section, highschool_obj=stray_hs, last_name='Strayberg')
        with self._schools([self.secondary_hs, stray_hs]):
            resp = self.client.get(self._url())
            csv = self.client.get(self._url('?action=download_grades')).content.decode()
        self.assertContains(resp, 'Secondaryson')
        self.assertNotContains(resp, 'Strayberg')
        self.assertNotContains(resp, 'Primarydottir')
        self.assertNotIn('Strayberg', csv)

    def test_admin_scope_values(self):
        from ..views.hs_admin import admin_scope
        request = RequestFactory().get('/')
        request.user = self.admin
        stray_hs = f.highschool()
        cases = [
            ([self.primary_hs], (True, None)),
            ([self.primary_hs, self.secondary_hs], (True, None)),
            ([self.secondary_hs, stray_hs], (True, [self.secondary_hs.id])),
            ([stray_hs], (False, None)),
        ]
        for schools, expected in cases:
            with self._schools(schools):
                self.assertEqual(admin_scope(request, self.section), expected, schools)

    # -- dashboard message -----------------------------------------------

    def test_dashboard_message_counts_secondary_sections(self):
        request = RequestFactory().get('/')
        request.user = self.admin
        with self._schools([self.secondary_hs]):
            [msg] = pm.hs_admin_dashboard(request)
        self.assertIn('1 of 1 class(es) not submitted', msg.text)


class SecondaryHighSchoolSummaryTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        today = date.today()
        cls.term = f.term()
        cls.mid = f.period(cls.term, 'Mid', today - timedelta(days=1), today + timedelta(days=5))
        cls.primary_hs, cls.secondary_hs = f.highschool(), f.highschool()
        cls.teacher, cls.secondary_teacher = f.teacher(), f.teacher()
        cls.section = f.section(cls.term, cls.teacher, highschool_obj=cls.primary_hs)
        cls.section.add_secondary_highschool(cls.secondary_hs)
        cls.section.add_secondary_teacher(cls.secondary_teacher)
        f.section(cls.term, f.teacher(), highschool_obj=f.highschool())

    def test_highschool_filter_includes_secondary_sections(self):
        s = summarize(self.mid, highschool_ids=[self.secondary_hs.id])
        self.assertEqual(s['classes']['total'], 1)
        [row] = s['rows']
        self.assertEqual(row['teacher_user'], self.teacher.user)

    def test_teacher_grouping_stays_primary(self):
        set_status(self.section, self.mid, 'submitted')
        teachers = [r['teacher_user'] for r in summarize(self.mid)['rows']]
        self.assertIn(self.teacher.user, teachers)
        self.assertNotIn(self.secondary_teacher.user, teachers)
