"""v1: instructor Grades list (spec §3)."""
from datetime import date, timedelta

from django.contrib.auth.signals import user_logged_in
from django.urls import reverse

from .base import GradesTestCase
from . import factories as f
from ..services.class_list import class_rows
from ..services.periods import set_status

try:
    from django_login_history.models import post_login as _login_history_post_login
except ImportError:
    _login_history_post_login = None


class InstructorListTests(GradesTestCase):
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
        f.grades_setting(grades_intro='<p>Intro text</p>')
        today = date.today()
        cls.teacher = f.teacher()
        cls.now = f.term(label='Fall Now')
        cls.mid1 = f.period(cls.now, 'Mid 1', today - timedelta(days=2), today + timedelta(days=2))
        cls.past = f.term(label='Spring Past')
        f.period(cls.past, 'Final', today - timedelta(days=200), today - timedelta(days=190), is_final=True)
        cls.s_now = f.section(cls.now, cls.teacher)
        cls.s_past = f.section(cls.past, cls.teacher)
        f.registration(cls.s_now)
        f.registration(cls.s_now, status='dropped')

    def test_rows_have_counts_and_period_status(self):
        set_status(self.s_now, self.mid1, 'submitted')
        [row] = class_rows([self.s_now])
        self.assertEqual(dict(row['registrations']), {'Registered': 1, 'Dropped': 1})
        self.assertEqual([(p['name'], p['label']) for p in row['periods']], [('Mid 1', 'Submitted')])

    def test_page_defaults_to_current_term_and_switches(self):
        self.client.force_login(self.teacher.user)
        resp = self.client.get(reverse('instructor:grades'))
        self.assertContains(resp, 'Intro text')
        self.assertContains(resp, self.s_now.class_number)
        self.assertNotContains(resp, self.s_past.class_number)
        resp = self.client.get(reverse('instructor:grades'), {'term': str(self.past.id)})
        self.assertContains(resp, self.s_past.class_number)
