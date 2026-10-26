"""The grade grid drops its top border only under a tab strip, and the
standalone instructor grade page works with an older instructor tab registry."""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.template.loader import render_to_string
from django.test import RequestFactory

from .base import GradesTestCase
from . import factories as f
from .. import instructor_tabs, tabs
from ..services.grade_grid import build_grid


class GridInTabTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        today = date.today()
        cls.term = f.term()
        f.period(cls.term, 'Mid 1', today - timedelta(days=5), today + timedelta(days=5))
        cls.section = f.section(cls.term, f.teacher())
        f.registration(cls.section)
        cls.ce = get_user_model().objects.create_user(
            username='ce_tab@example.com', email='ce_tab@example.com', is_staff=True)
        cls.ce.groups.add(Group.objects.get_or_create(name='ce')[0])

    def _request(self):
        request = RequestFactory().get('/')
        request.user = self.ce
        return request

    def _grid(self):
        return build_grid(self.section, post_url='/g/', next_url='/n/')

    def test_border_only_in_a_tab(self):
        standalone = render_to_string('grades/partials/_grade_grid.html', {'grid': self._grid()})
        tabbed = render_to_string('grades/partials/_grade_grid.html',
                                  {'grid': self._grid(), 'in_tab': True})
        self.assertIn('<div class="card mb-3">', standalone)
        self.assertIn('<div class="card mb-3 border-top-0">', tabbed)

    def test_every_tab_context_sets_in_tab(self):
        self.assertIs(tabs.ce_class_section_grades_tab(self._request(), self.section)['in_tab'], True)
        self.assertIs(tabs.hs_admin_grades_tab(self._request(), self.section)['in_tab'], True)
        if instructor_tabs.instructor_class_section_tabs is not None:
            ctx = instructor_tabs.instructor_grades_tab(self._request(), self.section)
            self.assertIs(ctx['in_tab'], True)

    def test_grade_page_tabs_without_render_tab_is_grades_only(self):
        with patch.object(instructor_tabs, 'instructor_class_section_tabs', SimpleNamespace()):
            result = instructor_tabs.grade_page_tabs(self._request(), self.section, '<p>g</p>')
        self.assertEqual(list(result), ['grades'])
        self.assertEqual(result['grades']['html'], '<p>g</p>')
