"""v1: grades page messages (spec §3)."""
from datetime import date, timedelta

from django.test import RequestFactory

from .base import GradesTestCase
from . import factories as f
from .. import page_messages as pm
from ..services.open_periods import open_period_summary
from ..services.periods import set_status


class PageMessageTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        today = date.today()
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', today - timedelta(days=1), today + timedelta(days=5))
        cls.teacher = f.teacher()
        cls.a = f.section(cls.term, cls.teacher)
        cls.b = f.section(cls.term, cls.teacher)

    def _request(self):
        request = RequestFactory().get('/')
        request.user = self.teacher.user
        return request

    def test_summary(self):
        set_status(self.a, self.mid1, 'submitted')
        self.assertEqual(open_period_summary([self.a, self.b]), [(self.mid1, 1, 2)])

    def test_pending_warning_then_success(self):
        [msg] = pm.instructor_grades(self._request())
        self.assertEqual(msg.level, 'warning')
        self.assertIn('2 of 2 class(es) not submitted', msg.text)
        set_status(self.a, self.mid1, 'submitted')
        set_status(self.b, self.mid1, 'submitted')
        [msg] = pm.instructor_grades(self._request())
        self.assertEqual(msg.level, 'success')

    def test_dashboard_highlights_tile(self):
        [msg] = pm.instructor_dashboard(self._request())
        self.assertEqual(msg.tile_id, 'id_tile_grades')

    def test_no_teacher_no_message(self):
        request = RequestFactory().get('/')
        request.user = f.registration(self.a).student.user
        self.assertEqual(pm.instructor_grades(request), [])
