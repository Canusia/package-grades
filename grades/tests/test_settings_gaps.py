"""Settings gaps from the Grades Configuration Workbook (#2).

New keys: is_active / debug_email_list (master switch), notify_instructor_on_submit,
grades_submitted_cc, send_grade_reminders, student_grades_visible,
student_transcript_enabled. A legacy row with none of them must behave exactly as before.
"""
import importlib.util
import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from django.http import Http404, HttpRequest
from django.test import RequestFactory, TestCase, override_settings

from mailer.models import Message
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.course import Cohort, Course
from cis.models.crontab import CronTab
from cis.models.section import ClassSection
from cis.models.settings import Setting
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from ..services.email import resolve_recipients
from ..settings.class_section_grades import class_section_grades

User = get_user_model()
GRADES_APP = 'grades.grades' if importlib.util.find_spec('grades.grades') else 'grades'
KEY = class_section_grades.key


def _sfx():
    return uuid.uuid4().hex[:8]


def legacy_value(term_id):
    """A v0.0.8-era row: every key the old form required, none of the new ones."""
    return {
        'grade_scale': class_section_grades.get_default_grade_scale(),
        'registration_status': ['registered'],
        'terms': [str(term_id)],
        'start_date': '01/01/2026', 'end_date': '12/31/2026',
        'cron': '0 8 * * *',
        'grades_due_subject': 'Grades due', 'grades_due_email': 'Hi {{teacher_first_name}}',
        'grades_closed': 'closed', 'grades_open': 'open',
        'grades_open_class_section': 'how to', 'grades_submitted_class_section': 'done',
        'grades_submitted_email_subject': 'Submitted',
        'grades_submitted_email': 'Thanks {{instructor_first_name}}',
    }


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        cls.term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        cls.course = Course.objects.create(catalog_number='101', title='A', cohort=cohort)
        cls.instructor = User.objects.create_user(
            username=f'i_{_sfx()}', email=f'ins_{_sfx()}@x.com', password='x',
            first_name='Ida')
        cls.teacher = Teacher.objects.create(user=cls.instructor)

    def _store(self, **overrides):
        Setting.objects.update_or_create(
            key=KEY, defaults={'value': {**legacy_value(self.term.id), **overrides}})

    def _submit_section(self):
        section = ClassSection.objects.create(
            course=self.course, term=self.term, teacher=self.teacher,
            class_number=f'C-{_sfx()}', section_number='001')
        Message.objects.all().delete()
        section.grade_status = 'submitted'
        section.save()
        return [m.email.to for m in Message.objects.all()]


class EmailSwitchTest(_Fixture):
    def test_legacy_row_still_emails_instructor(self):
        self._store()
        self.assertEqual(self._submit_section(), [[self.instructor.email]])

    def test_master_switch_off_sends_nothing(self):
        self._store(is_active='No')
        self.assertEqual(self._submit_section(), [])

    def test_debug_mode_goes_to_debug_list_only(self):
        self._store(is_active='Debug', debug_email_list='qa@x.com, dev@x.com')
        self.assertEqual(self._submit_section(), [['qa@x.com', 'dev@x.com']])

    @override_settings(DEBUG=True)
    def test_django_debug_never_mails_real_recipients(self):
        self._store()  # is_active absent -> Yes, but DEBUG forces Debug
        self.assertEqual(self._submit_section(), [])
        self.assertEqual(resolve_recipients({'is_active': 'Yes'}, ['real@x.com']), [])

    def test_instructor_copy_can_be_turned_off(self):
        self._store(notify_instructor_on_submit='No')
        self.assertEqual(self._submit_section(), [])

    def test_office_cc_gets_a_copy(self):
        self._store(grades_submitted_cc='ce@x.com')
        self.assertEqual(self._submit_section(), [[self.instructor.email, 'ce@x.com']])

    def test_office_cc_without_instructor(self):
        self._store(notify_instructor_on_submit='No', grades_submitted_cc='ce@x.com')
        self.assertEqual(self._submit_section(), [['ce@x.com']])

    def test_no_hardcoded_personal_address_left(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        for path in root.rglob('*.py'):
            if 'tests' in path.parts:
                continue
            self.assertNotIn('kadaji@', path.read_text(), str(path))


class SettingsFormTest(_Fixture):
    def _form(self, **overrides):
        data = {**legacy_value(self.term.id), 'grade_scale': '',
                'is_active': 'Yes', 'debug_email_list': '',
                'notify_instructor_on_submit': 'Yes', 'grades_submitted_cc': '',
                'send_grade_reminders': 'Yes', 'student_grades_visible': 'Yes',
                'student_transcript_enabled': 'Yes', **overrides}
        return class_section_grades(HttpRequest(), data)

    def test_cron_optional_when_reminders_off(self):
        form = self._form(send_grade_reminders='No', cron='')
        self.assertTrue(form.is_valid(), form.errors)

    def test_cron_required_when_reminders_on(self):
        form = self._form(cron='')
        self.assertFalse(form.is_valid())
        self.assertIn('cron', form.errors)

    def test_bad_cc_address_rejected(self):
        form = self._form(grades_submitted_cc='ce@x.com, not-an-email')
        self.assertFalse(form.is_valid())
        self.assertIn('not-an-email', str(form.errors['grades_submitted_cc']))

    def test_debug_mode_needs_a_list(self):
        form = self._form(is_active='Debug', debug_email_list='')
        self.assertFalse(form.is_valid())
        self.assertIn('debug_email_list', form.errors)

    def test_reminders_off_leaves_crontab_alone(self):
        CronTab.objects.update_or_create(
            command='notify_grades_pending', defaults={'cron': '5 5 * * *'})
        form = self._form(send_grade_reminders='No', cron='')
        self.assertTrue(form.is_valid(), form.errors)
        form.run_record()
        self.assertEqual(CronTab.objects.get(command='notify_grades_pending').cron, '5 5 * * *')
        self.assertEqual(Setting.objects.get(key=KEY).value['send_grade_reminders'], 'No')

    def test_terms_choices_are_term_ids(self):
        choices = dict(class_section_grades(HttpRequest()).fields['terms'].choices)
        self.assertEqual(choices[str(self.term.id)], str(self.term))

    def test_from_db_fills_new_keys_only_when_absent(self):
        self._store(student_grades_visible='No')
        values = class_section_grades.from_db()
        self.assertEqual(values['student_grades_visible'], 'No')
        self.assertEqual(values['send_grade_reminders'], 'Yes')
        self.assertEqual(values['is_active'], 'Yes')

    def test_install_seeds_new_keys(self):
        Setting.objects.filter(key=KEY).delete()
        class_section_grades(HttpRequest()).install()
        value = Setting.objects.get(key=KEY).value
        for k in ('is_active', 'notify_instructor_on_submit', 'send_grade_reminders',
                  'student_grades_visible', 'student_transcript_enabled'):
            self.assertEqual(value[k], 'Yes', k)


class SettingsAPITest(_Fixture):
    """The settings API validates a legacy row unchanged, and a dry run has no side effects."""

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
        try:
            from setting.setting.models.setting import SettingRecord
        except ImportError:  # pragma: no cover - installed package layout
            from setting.models.setting import SettingRecord
        SettingRecord.objects.create(
            app=GRADES_APP, name='class_section_grades', title='Grades',
            description='d', categories='1')
        admin = User.objects.create_user(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x',
            is_superuser=True)
        token, _ = Token.objects.get_or_create(user=admin)
        self.api = APIClient(REMOTE_ADDR='127.0.0.1')
        self.api.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        self._store()
        CronTab.objects.update_or_create(
            command='notify_grades_pending', defaults={'cron': '0 8 * * *'})

    def _patch(self, value, query=''):
        return self.api.patch(f'/api/v1/settings/{KEY}/{query}',
                              {'value': value}, format='json')

    def test_legacy_row_validates(self):
        resp = self._patch({'grades_due_subject': 'New'})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(Setting.objects.get(key=KEY).value['send_grade_reminders'], 'Yes')

    def test_dry_run_does_not_touch_crontab(self):
        resp = self._patch({'cron': '0 9 * * 1'}, '?dry_run=1')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()['dry_run'])
        self.assertEqual(CronTab.objects.get(command='notify_grades_pending').cron, '0 8 * * *')
        self.assertEqual(Setting.objects.get(key=KEY).value['cron'], '0 8 * * *')


class ReminderSwitchTest(_Fixture):
    def _run(self, command):
        from django.core.management import call_command
        module = f'{__package__.rsplit(".", 1)[0]}.management.commands.{command}'
        with patch(f'{module}.cron_task_started'), \
                patch(f'{module}.cron_task_done') as done:
            call_command(command, time='now')
        return done.send.call_args.kwargs['summary']

    def test_both_commands_noop_when_off(self):
        self._store(send_grade_reminders='No', reminder_dates='01/01/2026')
        for command in ('notify_grades_pending', 'notify_period_grades_pending'):
            with self.subTest(command):
                self.assertEqual(self._run(command), 'Grade reminders are turned off')


class StudentSwitchTest(_Fixture):
    def _request(self):
        request = RequestFactory().get('/student/grades/')
        request.user = self.instructor
        return request

    def _views(self):
        from ..views import student as views
        return views

    def test_grades_page_shows_notice_when_hidden(self):
        self._store(student_grades_visible='No')
        views = self._views()
        with patch.object(views, 'get_current_student', return_value=MagicMock()), \
                patch.object(views, 'portal_lang') as lang, \
                patch.object(views, 'draw_menu', return_value=''), \
                patch.object(views, 'render') as render:
            lang.return_value.from_db.return_value = {'grades_blurb': 'x'}
            views.grades(self._request())
        ctx = render.call_args.args[2]
        self.assertFalse(ctx['grades_visible'])

    def test_transcript_download_404_when_disabled(self):
        self._store(student_transcript_enabled='No')
        views = self._views()
        student = MagicMock()
        with patch.object(views, 'get_current_student', return_value=student):
            with self.assertRaises(Http404):
                views.download_transcript.__wrapped__(self._request())
        student.generate_unofficial_transcript.assert_not_called()

    def test_transcript_flag_reaches_template(self):
        self._store(student_transcript_enabled='No')
        views = self._views()
        with patch.object(views, 'get_current_student', return_value=MagicMock()), \
                patch.object(views, 'portal_lang') as lang, \
                patch.object(views, 'draw_menu', return_value=''), \
                patch.object(views, 'render') as render:
            lang.return_value.from_db.return_value = {'grades_blurb': 'x'}
            views.grades(self._request())
        self.assertFalse(render.call_args.args[2]['transcript_enabled'])

    def test_template_hides_table_and_button(self):
        from django.template.loader import render_to_string
        html = render_to_string('grades/student/_grades_body.html', {
            'grades_visible': False, 'transcript_enabled': False})
        self.assertNotIn('student_class_registrations', html)
        self.assertNotIn('Download Unofficial Transcript', html)
        self.assertIn('not available', html)
