"""v1: CE grade submission summary (spec §5)."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.urls import reverse
from mailer.models import Message

from .base import GradesTestCase
from . import factories as f
from ..services.periods import set_status
from ..services.summary import remind, summarize

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None


class SummaryTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        get_user_model().objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        f.grades_setting(is_active='Yes', grades_due_subject='Due', grades_due_email='{{grading_period}}')
        today = date.today()
        cls.term = f.term()
        cls.mid = f.period(cls.term, 'Mid', today - timedelta(days=1), today + timedelta(days=5))
        cls.t1, cls.t2, cls.t3 = f.teacher(), f.teacher(), f.teacher()
        cls.a1 = f.section(cls.term, cls.t1); cls.a2 = f.section(cls.term, cls.t1)
        cls.b1 = f.section(cls.term, cls.t2)
        cls.c1 = f.section(cls.term, cls.t3)

    def test_counts_by_class_and_instructor(self):
        set_status(self.a1, self.mid, 'submitted')
        set_status(self.a2, self.mid, 'submitted')
        set_status(self.b1, self.mid, 'saved')
        s = summarize(self.mid)
        self.assertEqual(s['classes'], {'submitted': 2, 'saved': 1, 'not_started': 1, 'total': 4})
        self.assertEqual(s['instructors'], {'submitted': 1, 'saved': 1, 'not_started': 1, 'total': 3})

    def test_instructor_with_one_draft_is_draft(self):
        set_status(self.a1, self.mid, 'submitted')
        set_status(self.a2, self.mid, 'saved')
        row = next(r for r in summarize(self.mid)['rows'] if r['teacher_user'] == self.t1.user)
        self.assertEqual(row['status'], 'saved')

    def test_remind_skips_submitted_and_same_day(self):
        set_status(self.a1, self.mid, 'submitted')
        set_status(self.a2, self.mid, 'submitted')
        sent = remind(self.mid, [self.t1.user.id, self.t2.user.id])
        self.assertEqual(sent, 1)
        self.assertEqual(remind(self.mid, [self.t2.user.id]), 0)
        self.assertEqual(Message.objects.count(), 1)


class SummaryViewTests(GradesTestCase):
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
        get_user_model().objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        f.grades_setting(is_active='Yes', grades_due_subject='Due', grades_due_email='{{grading_period}}')
        today = date.today()
        cls.term = f.term()
        cls.mid = f.period(cls.term, 'Mid', today - timedelta(days=1), today + timedelta(days=5))
        cls.t1 = f.teacher()
        cls.a1 = f.section(cls.term, cls.t1)
        cls.ce = get_user_model().objects.create_user(
            username='cesum@example.com', email='cesum@example.com', password='x', is_staff=True)
        cls.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        if getattr(cls, 'campus', None) is not None:
            from cis.signals.staff_campus import add_process_campuses
            add_process_campuses(cls.ce, [cls.campus])

    def setUp(self):
        self.client.force_login(self.ce)

    def test_page_renders(self):
        resp = self.client.get(reverse('grades_ce:summary'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Mid')
        self.assertContains(resp, self.t1.user.email)

    def test_term_switcher_defaults_to_all_current_terms(self):
        resp = self.client.get(reverse('grades_ce:summary'))
        self.assertContains(resp, '<option value="" selected>All current terms</option>')
        self.assertContains(resp, self.t1.user.email)
        resp = self.client.get(reverse('grades_ce:summary'), {'term': str(self.term.id)})
        self.assertContains(resp, f'<option value="{self.term.id}" selected>')
        self.assertNotContains(resp, '<option value="" selected>')

    def test_csv_export(self):
        resp = self.client.get(reverse('grades_ce:summary') + f'?period={self.mid.id}&format=csv')
        self.assertEqual(resp['Content-Type'], 'text/csv')
        self.assertIn(self.t1.user.email, resp.content.decode())

    def test_remind_all_posts_and_sends(self):
        resp = self.client.post(reverse('grades_ce:summary_remind'),
                                {'period': str(self.mid.id), 'all': '1'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Message.objects.count(), 1)

    def test_bad_highschool_param_is_ignored(self):
        base = reverse('grades_ce:summary')
        self.assertEqual(self.client.get(base + '?highschool=abc').status_code, 200)
        self.assertEqual(self.client.get(base + '?highschool=abc&format=csv').status_code, 200)

    def test_csv_neutralizes_formulas(self):
        u = self.t1.user
        u.last_name = '=HYPERLINK("x")'
        u.save()
        resp = self.client.get(reverse('grades_ce:summary') + f'?period={self.mid.id}&format=csv')
        self.assertIn('"\'=HYPERLINK(""x"")', resp.content.decode())

    def test_remind_all_respects_highschool_filter(self):
        hs1, hs2 = f.highschool(), f.highschool()
        t2 = f.teacher()
        f.section(self.term, t2, highschool_obj=hs2)
        self.a1.highschool = hs1
        self.a1.save()
        resp = self.client.post(reverse('grades_ce:summary_remind'),
                                {'period': str(self.mid.id), 'all': '1', 'highschool': [str(hs1.id)]})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Message.objects.count(), 1)

    def test_remind_unknown_period_404s(self):
        import uuid
        resp = self.client.post(reverse('grades_ce:summary_remind'), {'period': str(uuid.uuid4())})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(Message.objects.count(), 0)


class SummaryCampusScopeTests(GradesTestCase):
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
        get_user_model().objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        f.grades_setting(is_active='Yes', grades_due_subject='Due', grades_due_email='x')
        if not getattr(settings, 'MULTI_CAMPUS', False):
            return
        site_b, _ = Site.objects.get_or_create(
            domain='campus-b.example.com', defaults={'name': 'campus-b'})
        prefix = getattr(settings, 'CAMPUS_CODE_PREFIX', 'TEST')
        cls.campus_b, _ = Campus.objects.update_or_create(
            code=f'{prefix}_B', defaults={'name': 'Campus B', 'site': site_b})
        from cis.models.term import AcademicYear
        today = date.today()
        cls.term = f.term(ay=AcademicYear.objects.create(name='AY B', campus=cls.campus_b))
        cls.mid = f.period(cls.term, 'Mid', today - timedelta(days=1), today + timedelta(days=5))
        cls.section = f.section(cls.term, f.teacher())
        cls.section.campus = cls.campus_b
        cls.section.save()
        cls.ce = get_user_model().objects.create_user(
            username='cesa@example.com', email='cesa@example.com', password='x', is_staff=True)
        cls.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        from cis.signals.staff_campus import add_process_campuses
        add_process_campuses(cls.ce, [cls.campus])

    def setUp(self):
        from django.conf import settings
        if not getattr(settings, 'MULTI_CAMPUS', False):
            self.skipTest('multi-campus host only')
        self.client.force_login(self.ce)

    def test_remind_other_campus_period_404s_and_sends_nothing(self):
        resp = self.client.post(reverse('grades_ce:summary_remind'),
                                {'period': str(self.mid.id), 'all': '1'})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(Message.objects.count(), 0)


class SummaryUserCampusScopeTests(GradesTestCase):
    """A CE user limited to campus A sees and reminds only campus-A classes
    (course campus, as the grade reports scope); superusers see everything."""

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
        get_user_model().objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        f.grades_setting(is_active='Yes', grades_due_subject='Due', grades_due_email='x')
        if not getattr(settings, 'MULTI_CAMPUS', False):
            return
        site_b, _ = Site.objects.get_or_create(
            domain='campus-b.example.com', defaults={'name': 'campus-b'})
        prefix = getattr(settings, 'CAMPUS_CODE_PREFIX', 'TEST')
        cls.campus_b, _ = Campus.objects.update_or_create(
            code=f'{prefix}_B', defaults={'name': 'Campus B', 'site': site_b})
        today = date.today()
        cls.term = f.term()
        cls.mid = f.period(cls.term, 'Mid', today - timedelta(days=1), today + timedelta(days=5))
        cls.t_a = f.teacher(last_name='Alpha')
        cls.t_b = f.teacher(last_name='Bravo')
        course_a = f.course(catalog_number='9001')
        course_a.campus = cls.campus
        course_a.save()
        course_b = f.course(catalog_number='9002')
        course_b.campus = cls.campus_b
        course_b.save()
        cls.sec_a = f.section(cls.term, cls.t_a, course_obj=course_a)
        cls.sec_b = f.section(cls.term, cls.t_b, course_obj=course_b)
        cls.ce = get_user_model().objects.create_user(
            username='cescope@example.com', email='cescope@example.com', password='x', is_staff=True)
        cls.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        from cis.signals.staff_campus import add_process_campuses
        add_process_campuses(cls.ce, [cls.campus])
        cls.root = get_user_model().objects.create_user(
            username='root@example.com', email='root@example.com', password='x',
            is_staff=True, is_superuser=True)

    def setUp(self):
        from django.conf import settings
        if not getattr(settings, 'MULTI_CAMPUS', False):
            self.skipTest('multi-campus host only')

    def test_summary_hides_other_campus(self):
        teachers = [r['teacher_user'] for r in summarize(self.mid, user=self.ce)['rows']]
        self.assertEqual(teachers, [self.t_a.user])
        self.client.force_login(self.ce)
        resp = self.client.get(reverse('grades_ce:summary') + f'?period={self.mid.id}')
        self.assertContains(resp, self.t_a.user.email)
        self.assertNotContains(resp, self.t_b.user.email)
        csv_resp = self.client.get(reverse('grades_ce:summary') + f'?period={self.mid.id}&format=csv')
        self.assertNotIn(self.t_b.user.email, csv_resp.content.decode())

    def test_cannot_remind_other_campus(self):
        self.client.force_login(self.ce)
        self.client.post(reverse('grades_ce:summary_remind'),
                         {'period': str(self.mid.id), 'teacher': [str(self.t_b.user.id)]})
        self.assertEqual(Message.objects.count(), 0)
        self.client.post(reverse('grades_ce:summary_remind'), {'period': str(self.mid.id), 'all': '1'})
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(remind(self.mid, [self.t_b.user.id], user=self.ce), 0)

    def test_superuser_sees_all(self):
        teachers = {r['teacher_user'] for r in summarize(self.mid, user=self.root)['rows']}
        self.assertEqual(teachers, {self.t_a.user, self.t_b.user})
