"""Class Grade Status report: status filter, roster counts, campus gate, CSV."""
import unittest
import csv
import io
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from .base import GradesTestCase as TestCase

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from ..compat import has_campus_gate

if not (has_campus_gate() and hasattr(get_user_model(), 'set_process_campuses')):
    raise unittest.SkipTest('this cis has no per-user campus gating')

from cis.models.term import AcademicYear, Term
from cis.models.course import Campus, Cohort, Course
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from ..reports import class_grade_status as module
from ..reports.class_grade_status import (
    COLUMNS, class_grade_status, last_changed, status_key)

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class HelperTests(TestCase):
    def test_status_key(self):
        self.assertEqual(status_key(''), 'not_started')
        self.assertEqual(status_key(None), 'not_started')
        self.assertEqual(status_key('saved'), 'saved')
        self.assertEqual(status_key('submitted'), 'submitted')

    def test_last_changed_picks_latest_and_skips_junk(self):
        history = {'01/02/2026 09:00:00 AM': 'saved',
                   '12/01/2025 11:00:00 PM': 'submitted',
                   'junk': 'saved'}
        self.assertEqual(last_changed(history), '01/02/2026 09:00 AM')
        self.assertEqual(last_changed(None), '')
        self.assertEqual(last_changed({}), '')


class ClassGradeStatusReportTests(TestCase):
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

    def setUp(self):
        Group.objects.get_or_create(name='student')
        User.objects.get_or_create(username='cron', defaults={'email': 'cron@x.com'})

        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        self.term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.campus_a = Campus.objects.create(
            name=f'A-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'B-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        course_a = Course.objects.create(
            catalog_number='101', title='A', cohort=cohort, campus=self.campus_a)
        course_b = Course.objects.create(
            catalog_number='102', title='B', cohort=cohort, campus=self.campus_b)

        self.not_started = ClassSection.objects.create(
            class_number='1001', term=self.term, course=course_a, grade_status='')
        self.draft = ClassSection.objects.create(
            class_number='1002', term=self.term, course=course_a, grade_status='saved')
        self.submitted = ClassSection.objects.create(
            class_number='1003', term=self.term, course=course_a, grade_status='submitted')
        self.other_campus = ClassSection.objects.create(
            class_number='1004', term=self.term, course=course_b, grade_status='submitted')

        self._registration(self.draft, 'active', 'A')
        self._registration(self.draft, 'active', '-')
        self._registration(self.draft, 'active', '')
        self._registration(self.draft, 'dropped', 'W')

        self.ce = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.ce.save()
        self.ce.set_process_campuses([str(self.campus_a.id)])

    def _registration(self, section, status, grade):
        u = User.objects.create_user(
            username=f'stu_{_sfx()}', email=f'stu_{_sfx()}@x.com', password='x')
        student = Student.objects.create(user=u, account_verified=True)
        return StudentRegistration.objects.create(
            student=student, class_section=section, status=status, grade=grade,
            status_changed_on={'applied_on': '01/01/2024'})

    def _data(self, **extra):
        data = {'term': [str(self.term.id)], 'campus': [str(self.campus_a.id)]}
        data.update(extra)
        return data

    def test_blank_status_filter_includes_every_class_on_the_campus(self):
        qs = class_grade_status().get_result(self._data(), user=self.ce)
        self.assertEqual(set(qs), {self.not_started, self.draft, self.submitted})

    def test_not_started_matches_blank_and_null(self):
        ClassSection.objects.filter(pk=self.not_started.pk).update(grade_status=None)
        qs = class_grade_status().get_result(
            self._data(grade_status=['not_started']), user=self.ce)
        self.assertEqual(list(qs), [self.not_started])

    def test_status_filter_combines(self):
        qs = class_grade_status().get_result(
            self._data(grade_status=['not_started', 'saved']), user=self.ce)
        self.assertEqual(set(qs), {self.not_started, self.draft})

    def test_ce_cannot_see_other_campus(self):
        qs = class_grade_status().get_result(
            self._data(campus=[str(self.campus_b.id)]), user=self.ce)
        self.assertEqual(list(qs), [])

    def test_counts_use_roster_statuses(self):
        report = class_grade_status()
        with patch.object(module, 'roster_statuses', return_value=['active']):
            self.assertEqual(report.counts([self.draft.id]), {self.draft.id: (3, 1)})
        with patch.object(module, 'roster_statuses', return_value=[]):
            self.assertEqual(report.counts([self.draft.id]), {self.draft.id: (4, 2)})

    def test_run_writes_csv(self):
        saved = {}

        class Storage:
            def save(self, path, content):
                saved['path'], saved['body'] = path, content.read().decode('utf-8')
                return path

            def url(self, path):
                return f'/media/{path}'

        task = SimpleNamespace(id=7, created_by=self.ce)
        with patch.object(module, 'PrivateMediaStorage', Storage), \
                patch.object(module, 'roster_statuses', return_value=['active']):
            url = class_grade_status().run(task, self._data(grade_status=['saved']))

        self.assertIn('/7/class_grade_status_', url)
        rows = list(csv.reader(io.StringIO(saved['body'])))
        self.assertEqual(rows[0], COLUMNS)
        self.assertEqual(len(rows), 2)
        row = dict(zip(COLUMNS, rows[1]))
        self.assertEqual(row['Class No.'], '1002')
        self.assertEqual(row['Grade Status'], 'Draft')
        self.assertEqual((row['Students'], row['Graded'], row['Not Graded']), ('3', '1', '2'))
