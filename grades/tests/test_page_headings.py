"""Grades pages follow renamed menu items and show ``<menu item>_blurb`` (#21)."""
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from cis.models.settings import Setting

from .base import GradesTestCase
from . import factories as f
from .. import portal_text
from ..views import hs_admin as hs_admin_views
from ..views import instructor as instructor_views
from ..views import sis_sync as sis_views
from ..views import student as student_views
from ..views import summary as summary_views

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

MENU = 'cis.menu.get_role_menu'


def _no_cis():
    """Behave like a cis without cis.portal_text.page_heading/page_blurb."""
    return mock.patch.object(portal_text, '_cis_helper', return_value=None)


def _renamed(mapping):
    """page_heading as if staff renamed (role, item) → label; others keep default."""
    return lambda role, name, default: mapping.get((role, name), default)


# --------------------------------------------------------------------------- #
# The helper module
# --------------------------------------------------------------------------- #

class FallbackHeadingTests(SimpleTestCase):

    def test_renamed_label_wins(self):
        with _no_cis(), mock.patch(MENU, return_value=[
                {'name': 'classes', 'label': 'Classes', 'sub_menu': [
                    {'name': 'grades', 'label': 'Final Marks'}]}]):
            self.assertEqual(portal_text.page_heading('instructor', 'grades', 'D'), 'Final Marks')

    def test_stock_labels_keep_default(self):
        for role, name, label in (('instructor', 'grades', 'Class Grades'),
                                  ('instructor', 'grades', 'Grades'),
                                  ('student', 'grades', 'My Courses'),
                                  ('ce', 'grades_sis_sync', 'Grades'),
                                  ('ce', 'grades_summary', 'Grade Summary')):
            with _no_cis(), mock.patch(MENU, return_value=[{'name': name, 'label': label}]):
                self.assertEqual(portal_text.page_heading(role, name, 'D'), 'D', label)

    def test_missing_blank_or_unreadable_keeps_default(self):
        for menu in ([{'name': 'home', 'label': 'Home'}], [{'name': 'grades', 'label': ' '}], None):
            with _no_cis(), mock.patch(MENU, return_value=menu):
                self.assertEqual(portal_text.page_heading('instructor', 'grades', 'D'), 'D')
        with _no_cis(), mock.patch(MENU, side_effect=RuntimeError):
            self.assertEqual(portal_text.page_heading('instructor', 'grades', 'D'), 'D')


class FallbackBlurbTests(SimpleTestCase):

    def _stored(self, value):
        return mock.patch.object(portal_text, '_stored_text', return_value=value)

    def test_item_blurb_wins_over_legacy(self):
        with _no_cis(), self._stored({'class_blurb': 'New', 'classes_blurb': 'Old'}):
            self.assertEqual(portal_text.page_blurb(
                'highschool_admin', 'class', legacy_keys=('classes_blurb',)), 'New')

    def test_legacy_key_when_item_blurb_blank_or_placeholder(self):
        for item in ('', '  ', 'Change me', 'Change this in Settings -> HS Admin Portal'):
            with _no_cis(), self._stored({'class_blurb': item, 'classes_blurb': 'Old'}):
                self.assertEqual(portal_text.page_blurb(
                    'highschool_admin', 'class', legacy_keys=('classes_blurb',)), 'Old')

    def test_default_when_nothing_usable(self):
        with _no_cis(), self._stored({'grades_blurb': 'Change me'}):
            self.assertEqual(portal_text.page_blurb('student', 'grades', default='D'), 'D')
        with _no_cis(), self._stored('not a dict'):
            self.assertEqual(portal_text.page_blurb('student', 'grades', default='D'), 'D')
        with _no_cis(), mock.patch.object(portal_text, '_stored_text', side_effect=RuntimeError):
            self.assertEqual(portal_text.page_blurb('instructor', 'grades', default='D'), 'D')
        self.assertEqual(portal_text.page_blurb('ce', 'grades_summary', default='D'), 'D')

    def test_instructor_and_faculty_text_come_from_the_owning_package(self):
        from .. import compat
        with _no_cis(), mock.patch.object(
                compat, 'portal_text', side_effect=lambda role: {'grades_blurb': role}):
            self.assertEqual(portal_text.page_blurb('instructor', 'grades'), 'instructor')
            self.assertEqual(portal_text.page_blurb('faculty', 'grades'), 'faculty')


class CisHelperTests(SimpleTestCase):
    """With cis.portal_text.page_heading/page_blurb, those are used."""

    def _helpers(self, **helpers):
        return mock.patch.object(portal_text, '_cis_helper', side_effect=helpers.get)

    def test_delegates(self):
        heading = mock.Mock(return_value='H')
        blurb = mock.Mock(return_value='B')
        with self._helpers(page_heading=heading, page_blurb=blurb):
            self.assertEqual(portal_text.page_heading('instructor', 'grades', 'D'), 'H')
            self.assertEqual(portal_text.page_blurb(
                'highschool_admin', 'class', legacy_keys=('classes_blurb',)), 'B')
        heading.assert_called_once_with('instructor', 'grades', 'D')
        blurb.assert_called_once_with('highschool_admin', 'class',
                                      legacy_keys=('classes_blurb',), default='')

    def test_converted_old_menu_label_is_not_a_rename(self):
        # The settings-driven menu (migration 0006) seeded "Grades"; the
        # registry label is "Class Grades". Neither is a staff rename.
        with self._helpers(page_heading=mock.Mock(return_value='Grades')):
            self.assertEqual(portal_text.page_heading('instructor', 'grades', 'Class Grades'),
                             'Class Grades')

    def test_helper_errors_fall_back(self):
        with self._helpers(page_heading=mock.Mock(side_effect=RuntimeError),
                           page_blurb=mock.Mock(side_effect=RuntimeError)):
            self.assertEqual(portal_text.page_heading('instructor', 'grades', 'D'), 'D')
            self.assertEqual(portal_text.page_blurb('student', 'grades', default='D'), 'D')


class RealCisBlurbTests(GradesTestCase):
    """End to end through whichever cis is installed."""

    def test_hs_admin_class_text_then_classes_text(self):
        Setting.objects.update_or_create(
            key='cis.settings.highschool_admin_portal',
            defaults={'value': {'classes_blurb': 'Saved for Classes'}})
        self.assertEqual(portal_text.page_blurb(
            'highschool_admin', 'class', legacy_keys=('classes_blurb',)), 'Saved for Classes')


# --------------------------------------------------------------------------- #
# The pages
# --------------------------------------------------------------------------- #

class _LoginHistoryOff:
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


class InstructorPagesTests(_LoginHistoryOff, GradesTestCase):

    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='instructor')
        f.grades_setting()
        today = date.today()
        cls.term = f.term()
        f.period(cls.term, 'Mid 1', today - timedelta(days=3), today + timedelta(days=3))
        cls.teacher = f.teacher()
        cls.teacher.user.groups.add(Group.objects.get(name='instructor'))
        cls.section = f.section(cls.term, cls.teacher)

    def setUp(self):
        self.client.force_login(self.teacher.user)

    def _get(self, url, renamed=None, blurb=None):
        blurbs = []

        def fake_blurb(role, name, legacy_keys=(), default=''):
            blurbs.append((role, name))
            return blurb if blurb is not None else default
        with mock.patch.object(instructor_views, 'page_heading',
                               side_effect=_renamed(renamed or {})), \
                mock.patch.object(instructor_views, 'page_blurb', side_effect=fake_blurb):
            resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        return resp, blurbs

    def test_list_heading_follows_rename(self):
        resp, _ = self._get(reverse('instructor:grades'),
                            renamed={('instructor', 'grades'): 'Final Marks'})
        self.assertContains(resp, '<title>Final Marks', html=False)
        self.assertContains(resp, 'Final Marks</li>')

    def test_list_stock_label_keeps_heading(self):
        resp, _ = self._get(reverse('instructor:grades'))
        self.assertContains(resp, 'Class Grades')
        self.assertNotContains(resp, 'Final Marks')

    def test_list_text_from_grades_item(self):
        resp, blurbs = self._get(reverse('instructor:grades'), blurb='<p>Saved text</p>')
        self.assertContains(resp, '<p>Saved text</p>')
        self.assertEqual(blurbs, [('instructor', 'grades')])

    def test_detail_breadcrumb_follows_rename(self):
        url = reverse('instructor:class_section_grade', args=[self.section.id])
        resp, blurbs = self._get(url, renamed={('instructor', 'grades'): 'Final Marks'},
                                 blurb='<p>Saved text</p>')
        self.assertContains(resp, '>Final Marks</a>')
        self.assertContains(resp, '<title>Final Marks</title>')
        self.assertContains(resp, '<p>Saved text</p>')
        self.assertEqual(blurbs, [('instructor', 'grades')])

    def test_detail_stock_breadcrumb(self):
        url = reverse('instructor:class_section_grade', args=[self.section.id])
        resp, _ = self._get(url)
        self.assertContains(resp, '>Grades</a>')
        self.assertContains(resp, '<title>Class Grades</title>')


class HSAdminPageTests(_LoginHistoryOff, GradesTestCase):

    @classmethod
    def setUpTestData(cls):
        from two_step.models import TwoStep  # noqa: F401 (app must be installed)
        f.grades_setting()
        cls.hs = f.highschool()
        cls.section = f.section(f.term(), f.teacher(), highschool_obj=cls.hs)
        cls.admin = get_user_model().objects.create_user(
            username='hsa21@example.com', email='hsa21@example.com', password='x')
        cls.admin.groups.add(Group.objects.get_or_create(name='highschool_admin')[0])

    def setUp(self):
        from two_step.models import TwoStep
        from cis.models.highschool import HighSchool
        self.client.force_login(self.admin)
        TwoStep.objects.update_or_create(
            session_id=self.client.session.session_key, user=self.admin,
            defaults={'verification_code': '123456', 'verified': True})
        patcher = mock.patch.object(hs_admin_views, '_hs_admin_context', return_value=(
            [], HighSchool.objects.filter(pk=self.hs.pk)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_text_from_class_item_with_classes_fallback(self):
        calls = []

        def fake_blurb(role, name, legacy_keys=(), default=''):
            calls.append((role, name, tuple(legacy_keys)))
            return '<p>Class text</p>'
        with mock.patch.object(hs_admin_views, 'page_blurb', side_effect=fake_blurb):
            resp = self.client.get(
                reverse('grades_highschool_admin:class_section_grade', args=[self.section.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '<p>Class text</p>')
        self.assertEqual(calls, [('highschool_admin', 'class', ('classes_blurb',))])

    def test_saved_classes_text_shows(self):
        Setting.objects.update_or_create(
            key='cis.settings.highschool_admin_portal',
            defaults={'value': {'class_blurb': '', 'classes_blurb': '<p>For Classes</p>'}})
        resp = self.client.get(
            reverse('grades_highschool_admin:class_section_grade', args=[self.section.id]))
        self.assertContains(resp, '<p>For Classes</p>')


class StudentPageTests(GradesTestCase):

    def _context(self, renamed=None, blurb=None, stored=None):
        captured = {}

        def fake_render(request, template, context):
            captured.update(context)
            return mock.Mock()
        request = RequestFactory().get('/')
        request.user = mock.Mock()
        portal = mock.Mock()
        portal.return_value.from_db.return_value = stored or {}
        with mock.patch.object(student_views, 'get_current_student', return_value=None), \
                mock.patch.object(student_views, 'draw_menu', return_value=''), \
                mock.patch.object(student_views, 'render', side_effect=fake_render), \
                mock.patch.object(student_views, 'portal_lang', portal), \
                mock.patch.object(student_views, 'page_heading',
                                  side_effect=_renamed(renamed or {})), \
                mock.patch.object(student_views, 'page_blurb',
                                  side_effect=lambda r, n, legacy_keys=(), default='':
                                  blurb if blurb is not None else default):
            student_views.grades(request)
        return captured

    def test_heading_follows_rename(self):
        ctx = self._context(renamed={('student', 'grades'): 'Grades & Transcripts'})
        self.assertEqual(ctx['heading'], 'Grades & Transcripts')

    def test_stock_heading(self):
        self.assertEqual(self._context()['heading'], 'My Courses')

    def test_text_from_grades_item_is_a_template(self):
        ctx = self._context(blurb='Hi{% if show_message %}!{% endif %}')
        self.assertEqual(ctx['intro'], 'Hi')

    def test_untouched_setting_shows_what_it_did(self):
        self.assertEqual(self._context()['intro'], 'Change me')
        pointer = 'Change this in Settings -> Student Portal'
        self.assertEqual(self._context(stored={'grades_blurb': pointer})['intro'], pointer)


class CEPagesTests(_LoginHistoryOff, GradesTestCase):

    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        cls.ce = get_user_model().objects.create_user(
            username='ce21@example.com', email='ce21@example.com', password='x', is_staff=True)
        cls.ce.groups.add(Group.objects.get_or_create(name='ce')[0])

    def setUp(self):
        self.client.force_login(self.ce)

    def _get(self, module, url, renamed=None):
        with mock.patch.object(module, 'page_heading', side_effect=_renamed(renamed or {})):
            resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_summary_follows_rename(self):
        resp = self._get(summary_views, reverse('grades_ce:summary'),
                         {('ce', 'grades_summary'): 'Grade Tracker'})
        self.assertContains(resp, '<title>Grade Tracker', html=False)
        self.assertContains(resp, 'aria-current="page">Grade Tracker</li>')

    def test_summary_stock(self):
        resp = self._get(summary_views, reverse('grades_ce:summary'))
        self.assertContains(resp, 'Grade Submission Summary')
        self.assertContains(resp, 'aria-current="page">Grade Summary</li>')

    def test_sis_follows_rename(self):
        with mock.patch.object(sis_views.sis_push, 'get_pusher', return_value=None):
            resp = self._get(sis_views, reverse('grades_ce:sis_sync'),
                             {('ce', 'grades_sis_sync'): 'Banner Grades'})
        self.assertContains(resp, '<h1 class="h3 mb-0 text-gray-800">Banner Grades</h1>')

    def test_sis_stock(self):
        with mock.patch.object(sis_views.sis_push, 'get_pusher', return_value=None):
            resp = self._get(sis_views, reverse('grades_ce:sis_sync'))
        self.assertContains(resp, '<h1 class="h3 mb-0 text-gray-800">Grades → SIS</h1>')
