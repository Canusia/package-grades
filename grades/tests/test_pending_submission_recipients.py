"""#14: report "Grades: Pending Submission Recipients" -- one row per person
who still owes grades for the chosen grading periods, usable as a Bulk
Messages data source."""
import csv
import io
import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model

from .base import GradesTestCase
from . import factories as f
from ..reports.pending_submission_recipients import pending_submission_recipients
from ..services.periods import set_status

User = get_user_model()


class PendingSubmissionRecipientsTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        today = date.today()
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', today - timedelta(days=3), today + timedelta(days=3))
        cls.hs = f.highschool()
        cls.tess = f.teacher(first_name='Tess', last_name='Teacher')
        cls.sam = f.teacher(first_name='Sam', last_name='Smith')
        cls.a = f.section(cls.term, cls.tess, highschool_obj=cls.hs)
        cls.b = f.section(cls.term, cls.tess, highschool_obj=cls.hs)
        cls.done = f.section(cls.term, cls.sam, highschool_obj=cls.hs)
        cls.orphan = f.section(cls.term, None, highschool_obj=cls.hs)
        f.registration(cls.a, highschool_obj=cls.hs, grade='B')
        f.registration(cls.a, highschool_obj=cls.hs)
        set_status(cls.b, cls.mid1, 'saved')
        set_status(cls.done, cls.mid1, 'submitted')
        cls.pat = User.objects.create_user(
            username='pat', email='pat@example.com', password='x',
            first_name='Pat', last_name='Admin')
        f.grant_submit_grades(cls.pat, cls.hs)
        cls.lee = User.objects.create_user(
            username='lee', email='lee@example.com', password='x',
            first_name='Lee', last_name='Admin')  # no permission
        cls.secondary = f.teacher(first_name='Sec', last_name='Ondary')
        if hasattr(cls.a, 'add_secondary_teacher'):
            cls.a.add_secondary_teacher(cls.secondary)

    def _data(self, **extra):
        return {'term': [str(self.term.id)], 'periods': [str(self.mid1.id)], **extra}

    def _people(self, **extra):
        return pending_submission_recipients().people(self._data(**extra))

    def test_instructors_by_default(self):
        rows = self._people()
        self.assertEqual([(r.role, r.email) for r in rows],
                         [('Instructor', self.tess.user.email)])
        tess = rows[0]
        self.assertEqual(tess.class_count, 2)
        self.assertEqual(tess.periods, 'Mid 1')
        self.assertIn('Not Started', tess.statuses)
        self.assertIn('Draft', tess.statuses)

    def test_submitted_class_and_secondary_teacher_are_left_out(self):
        emails = {r.email for r in self._people(recipients='both')}
        self.assertNotIn(self.sam.user.email, emails)
        self.assertNotIn(self.secondary.user.email, emails)

    def test_hs_admins_with_the_permission_only(self):
        rows = self._people(recipients='hs_admins')
        self.assertEqual([(r.role, r.email) for r in rows], [('HS Admin', 'pat@example.com')])
        self.assertEqual(rows[0].class_count, 3)  # a, b and the class with no instructor

    def test_both(self):
        self.assertEqual({r.email for r in self._people(recipients='both')},
                         {self.tess.user.email, 'pat@example.com'})

    def test_status_filter(self):
        rows = self._people(status=['saved'])
        self.assertEqual(rows[0].class_count, 1)
        self.assertIn(self.b.class_number, rows[0].classes)

    def test_graded_counts_for_the_final_registration_grade(self):
        final = f.period(self.term, 'Final', date.today(), date.today() + timedelta(days=9),
                         2, is_final=True)
        rows = self._people(periods=[str(final.id)], status=['not_started'])
        tess = next(r for r in rows if r.email == self.tess.user.email)
        self.assertEqual((tess.graded, tess.not_graded), (1, 1))
        # Sam's class was submitted for Mid 1 only, so it is pending for Final.
        self.assertIn(self.sam.user.email, {r.email for r in rows})

    def test_data_source(self):
        report = pending_submission_recipients()
        for token in ('FirstName', 'LastName', 'email', 'Role', 'Classes', 'ClassCount',
                      'GradingPeriods', 'Statuses', 'Graded', 'NotGraded'):
            self.assertIn(token, report.recipient_columns())
        rows = report.get_recipients(self._data(recipients='both'))
        self.assertEqual(sorted(r['email'][0] for r in rows),
                         sorted([self.tess.user.email, 'pat@example.com']))

    def test_csv(self):
        saved = {}

        def _save(path, content):
            saved['csv'] = content.read().decode('utf-8')
            return path
        storage = mock.Mock()
        storage.save.side_effect = _save
        storage.url.side_effect = lambda p: p
        from ..reports import pending_submission_recipients as module
        with mock.patch.object(module, 'PrivateMediaStorage', return_value=storage):
            pending_submission_recipients().run(
                SimpleNamespace(id=uuid.uuid4(), created_by=None), self._data())
        rows = list(csv.reader(io.StringIO(saved['csv'])))
        self.assertEqual(rows[0][:4], ['Role', 'Last Name', 'First Name', 'Email'])
        self.assertEqual(rows[1][3], self.tess.user.email)

    def test_registered_as_a_ce_report(self):
        from ..apps import _REPORTS_BASE
        entry = next(r for r in _REPORTS_BASE if r['name'] == 'pending_submission_recipients')
        self.assertEqual(entry['available_for'], ['ce'])


class HSAdminDashboardMessageTests(GradesTestCase):
    """#16: only admins who can submit grades get the open-period messages."""

    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        today = date.today()
        term = f.term()
        f.period(term, 'Mid 1', today - timedelta(days=1), today + timedelta(days=5))
        cls.hs = f.highschool()
        f.section(term, f.teacher(), highschool_obj=cls.hs)
        cls.user = User.objects.create_user(
            username='dash', email='dash@example.com', password='x')

    def _messages(self):
        from django.test import RequestFactory
        from cis.models.highschool import HighSchool
        from .. import page_messages as pm
        from ..views import hs_admin as hs_admin_views
        request = RequestFactory().get('/')
        request.user = self.user
        with mock.patch.object(hs_admin_views, '_hs_admin_context',
                               return_value=([], HighSchool.objects.filter(pk=self.hs.pk))):
            return pm.hs_admin_dashboard(request)

    def test_without_the_permission_no_messages(self):
        self.assertEqual(self._messages(), [])

    def test_with_the_permission_gets_the_open_period(self):
        f.grant_submit_grades(self.user, self.hs)
        messages = self._messages()
        self.assertEqual(len(messages), 1)
        self.assertIn('Mid 1', str(messages[0].text))
