"""#15: grading-period reminders also go to HS admins who can submit grades.

An admin is a recipient when HS admin grade entry is Edit and their position
at the section's high school holds Can submit grades for the course's campus.
"""
from datetime import date, timedelta
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model

from mailer.models import Message

from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdminPerm, HSAdministrator, HSAdministratorPosition, HSPosition)
from cis.models.section import ClassSection
from cis.models.settings import Setting
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from .base import GradesTestCase as TestCase
from ..models import GradingPeriod, SectionPeriodStatus
from ..services.period_reminders import notify_sections_pending_period_grade

User = get_user_model()

GRADES_KEY = getattr(django_settings, 'CAMPUS_CODE_PREFIX') + '_class_grades'
TODAY = date(2034, 3, 15)


class HSAdminPeriodReminderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})

        teacher_user = User.objects.create_user(
            username='hsr_inst', email='hsr_inst@example.com', password='x',
            first_name='Tea', last_name='Cher')
        cls.teacher = Teacher.objects.create(user=teacher_user)
        cls.teacher_user = teacher_user

        ay = AcademicYear.objects.create(name='AY hs admin reminders')
        cls.term = Term.objects.create(
            academic_year=ay, code='SP34', label='Spring 2034')
        cohort = Cohort.objects.create(name='Cohort HSR', designator='HR')
        cls.course = Course.objects.create(
            catalog_number='601', title='HS Reminder Course', cohort=cohort,
            credit_hours=3)
        cls.school = HighSchool.objects.create(name='HSR School')
        cls.other_school = HighSchool.objects.create(name='HSR Other School')
        cls.position = HSPosition.objects.create(name='Registrar')

    def setUp(self):
        self._settings(entry='edit')
        self.counter = getattr(self.__class__, '_counter', 8000) + 1
        self.__class__._counter = self.counter

    # -- fixtures ---------------------------------------------------------

    def _settings(self, entry='edit', admin_subject='HS grades are due'):
        Setting.objects.update_or_create(
            key=GRADES_KEY,
            defaults={'value': {
                'grades': 'A,B,C',
                'registration_status': ['applied'],
                'hs_admin_grade_entry': entry,
                'grades_due_subject': 'Grades are due',
                'grades_due_email': (
                    'Teacher {{teacher_first_name}}: '
                    '{{number_of_sections_pending_grades}} pending.'),
                'hsadmin_grades_due_subject': admin_subject,
                'hsadmin_grades_due_email': (
                    'Admin {{admin_first_name}} {{admin_last_name}}: '
                    '{{number_of_sections_pending_grades}} pending for '
                    '{{grading_period}} ({{term}}), due {{due_date}}.'),
            }},
        )

    def _admin(self, name, school=None, perm=True, status='Active', campus=None):
        user = User.objects.create_user(
            username=name, email=f'{name}@example.com', password='x',
            first_name=name.title(), last_name='Admin')
        hsadmin = HSAdministrator.objects.create(user=user)
        role = HSAdministratorPosition.objects.create(
            hsadmin=hsadmin, highschool=school or self.school,
            position=self.position, status=status)
        if perm:
            role.grant(HSAdminPerm.SUBMIT_GRADES, campus=campus)
        return user, role

    def _section(self, teacher=True, school=True):
        self.counter += 1
        return ClassSection.objects.create(
            class_number=str(self.counter), section_number='01',
            term=self.term, course=self.course,
            teacher=self.teacher if teacher else None,
            highschool=self.school if school else None)

    def _period(self):
        return GradingPeriod.objects.create(
            term=self.term, name='Quarter 3', sequence=1,
            opens_on=TODAY - timedelta(days=5),
            due_on=TODAY + timedelta(days=5),
            reminder_frequency_days=3)

    def _recipients(self):
        return sorted(
            address for message in Message.objects.all()
            for address in message.email.to)

    def _body_for(self, address):
        for message in Message.objects.all():
            if address in message.email.to:
                return message.email.body
        return None

    # -- who gets it ------------------------------------------------------

    def test_admin_with_submit_grades_gets_the_admin_email(self):
        self._admin('perm_admin')
        self._section()
        self._period()

        notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(
            self._recipients(),
            ['hsr_inst@example.com', 'perm_admin@example.com'])
        body = self._body_for('perm_admin@example.com')
        self.assertIn('Admin Perm_Admin Admin: 1 pending for Quarter 3', body)
        self.assertIn((TODAY + timedelta(days=5)).strftime('%m/%d/%Y'), body)
        self.assertIn('Teacher Tea', self._body_for('hsr_inst@example.com'))

    def test_admin_without_the_permission_is_not_emailed(self):
        self._admin('no_perm_admin', perm=False)
        self._section()
        self._period()

        notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(self._recipients(), ['hsr_inst@example.com'])

    def test_inactive_position_is_not_emailed(self):
        self._admin('inactive_admin', status='Inactive')
        self._section()
        self._period()

        notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(self._recipients(), ['hsr_inst@example.com'])

    def test_admin_at_another_school_is_not_emailed(self):
        self._admin('elsewhere_admin', school=self.other_school)
        self._section()
        self._period()

        notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(self._recipients(), ['hsr_inst@example.com'])

    def test_admins_reminded_whatever_the_retired_access_value(self):
        # v1.3.0 (#17): the permission alone decides; a stored none/view from
        # the retired High School Admin Grade Access setting changes nothing.
        self._admin('perm_admin')
        self._section()
        self._period()

        for entry in ('view', 'none'):
            Message.objects.all().delete()
            SectionPeriodStatus.objects.all().delete()
            self._settings(entry=entry)
            notify_sections_pending_period_grade(today=TODAY)
            self.assertEqual(
                self._recipients(), ['hsr_inst@example.com', 'perm_admin@example.com'], entry)

    def test_empty_admin_subject_uses_the_default(self):
        # #17: a blank admin subject no longer turns admin reminders off.
        self._settings(admin_subject='')
        self._admin('perm_admin')
        self._section()
        self._period()

        notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(
            self._recipients(), ['hsr_inst@example.com', 'perm_admin@example.com'])
        subjects = {m.email.subject for m in Message.objects.all()
                    if 'perm_admin@example.com' in m.email.to}
        self.assertEqual(subjects, {'Grades are due'})

    # -- sections without a teacher --------------------------------------

    def test_section_without_teacher_reminds_admins_and_is_stamped(self):
        self._admin('perm_admin')
        section = self._section(teacher=False)
        period = self._period()

        result = notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(self._recipients(), ['perm_admin@example.com'])
        row = SectionPeriodStatus.objects.get(period=period, class_section=section)
        self.assertEqual(row.last_notified_on, TODAY)
        summary, log = result
        self.assertIn('1 HS admin(s)', summary)
        self.assertEqual(
            [a['email'] for a in log['hs_admins_notified']],
            ['perm_admin@example.com'])

    def test_section_without_teacher_or_admins_is_skipped(self):
        self._section(teacher=False)
        period = self._period()

        notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(Message.objects.count(), 0)
        self.assertFalse(SectionPeriodStatus.objects.filter(
            period=period, last_notified_on=TODAY).exists())

    def test_submitted_section_does_not_remind_admins(self):
        self._admin('perm_admin')
        section = self._section()
        period = self._period()
        SectionPeriodStatus.objects.create(
            period=period, class_section=section, status='submitted')

        notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(Message.objects.count(), 0)

    # -- grouping ---------------------------------------------------------

    def test_one_admin_email_per_period_covering_all_sections(self):
        self._admin('perm_admin')
        self._section()
        self._section(teacher=False)
        self._period()

        notify_sections_pending_period_grade(today=TODAY)

        admin_messages = [m for m in Message.objects.all()
                          if 'perm_admin@example.com' in m.email.to]
        self.assertEqual(len(admin_messages), 1)
        self.assertIn('2 pending', admin_messages[0].email.body)

    def test_teacher_who_is_also_an_admin_gets_one_email(self):
        role = HSAdministratorPosition.objects.create(
            hsadmin=HSAdministrator.objects.create(user=self.teacher_user),
            highschool=self.school, position=self.position, status='Active')
        role.grant(HSAdminPerm.SUBMIT_GRADES)
        self._section()
        self._period()

        notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(self._recipients(), ['hsr_inst@example.com'])

    def test_debug_mode_routes_admin_email_to_debug_list(self):
        setting = Setting.objects.get(key=GRADES_KEY)
        value = dict(setting.value)
        value.update({'is_active': 'Debug', 'debug_email_list': 'qa@example.com'})
        setting.value = value
        setting.save()
        self._admin('perm_admin')
        self._section(teacher=False)
        self._period()

        notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(self._recipients(), ['qa@example.com'])


class HSAdminReminderSettingDefaultsTests(TestCase):
    def test_saved_row_without_admin_keys_gets_default_copy(self):
        from ..settings.class_section_grades import class_section_grades
        Setting.objects.update_or_create(
            key=GRADES_KEY, defaults={'value': {'grades': 'A,B'}})
        values = class_section_grades.from_db()
        self.assertEqual(values['hsadmin_grades_due_subject'], 'Grades are due')
        self.assertIn('{{admin_first_name}}', values['hsadmin_grades_due_email'])

    def test_blank_admin_wording_falls_back_to_the_default(self):
        # #17: blank never means "off".
        from ..settings.class_section_grades import class_section_grades
        Setting.objects.update_or_create(
            key=GRADES_KEY,
            defaults={'value': {'grades': 'A,B', 'hsadmin_grades_due_subject': '',
                                'hsadmin_grades_due_email': ''}})
        values = class_section_grades.from_db()
        self.assertEqual(values['hsadmin_grades_due_subject'], 'Grades are due')
        self.assertIn('{{admin_first_name}}', values['hsadmin_grades_due_email'])


class HSAdminReminderScopeTests(HSAdminPeriodReminderTests):
    """Review follow-ups: campus scoping, cis compatibility, query count."""

    # The parent's tests are not re-run here.
    test_admin_with_submit_grades_gets_the_admin_email = None
    test_admin_without_the_permission_is_not_emailed = None
    test_inactive_position_is_not_emailed = None
    test_admin_at_another_school_is_not_emailed = None
    test_admins_reminded_whatever_the_retired_access_value = None
    test_empty_admin_subject_uses_the_default = None
    test_section_without_teacher_reminds_admins_and_is_stamped = None
    test_section_without_teacher_or_admins_is_skipped = None
    test_submitted_section_does_not_remind_admins = None
    test_one_admin_email_per_period_covering_all_sections = None
    test_teacher_who_is_also_an_admin_gets_one_email = None
    test_debug_mode_routes_admin_email_to_debug_list = None

    def _campus(self, code):
        from cis.models.course import Campus
        return Campus.objects.create(name=f'Campus {code}', code=code)

    def _on_campus(self, campus):
        self.course.campus = campus
        self.course.save()

    def test_campus_grant_counts_only_on_its_campus(self):
        here, there = self._campus('HR1'), self._campus('HR2')
        self._on_campus(here)
        self._admin('here_admin', campus=here)
        self._admin('there_admin', campus=there)
        self._admin('anywhere_admin')
        self._section(teacher=False)
        self._period()

        notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(self._recipients(),
                         ['anywhere_admin@example.com', 'here_admin@example.com'])

    def test_deactivated_admin_account_is_not_emailed(self):
        user, _role = self._admin('gone_admin')
        user.is_active = False
        user.save()
        self._section(teacher=False)
        self._period()

        notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(Message.objects.count(), 0)

    def test_teacher_who_is_also_an_admin_gets_the_teacher_template(self):
        role = HSAdministratorPosition.objects.create(
            hsadmin=HSAdministrator.objects.create(user=self.teacher_user),
            highschool=self.school, position=self.position, status='Active')
        role.grant(HSAdminPerm.SUBMIT_GRADES)
        self._section()
        self._section(teacher=False)
        self._period()

        notify_sections_pending_period_grade(today=TODAY)

        body = self._body_for('hsr_inst@example.com')
        self.assertIn('Teacher Tea: 2 pending.', body)

    def test_teacher_with_bad_email_still_lets_admins_be_reminded(self):
        bad = User.objects.create_user(
            username='hsr_bad', email='not-an-address', password='x')
        section = ClassSection.objects.create(
            class_number='HSR-BAD', section_number='01', term=self.term,
            course=self.course, teacher=Teacher.objects.create(user=bad),
            highschool=self.school)
        self._admin('perm_admin')
        period = self._period()

        notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(self._recipients(), ['perm_admin@example.com'])
        self.assertEqual(SectionPeriodStatus.objects.get(
            period=period, class_section=section).last_notified_on, TODAY)

    def test_blank_teacher_subject_still_reminds_admins(self):
        setting = Setting.objects.get(key=GRADES_KEY)
        value = dict(setting.value)
        value['grades_due_subject'] = ''
        setting.value = value
        setting.save()
        self._admin('perm_admin')
        self._section()
        self._period()

        notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(self._recipients(), ['perm_admin@example.com'])

    def test_cis_without_hs_admin_permissions_reminds_teachers_only(self):
        import builtins
        real_import = builtins.__import__

        def no_perms(name, *args, **kwargs):
            if name == 'cis.models.highschool_administrator':
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        self._admin('perm_admin')
        self._section()
        self._period()
        with mock.patch('builtins.__import__', side_effect=no_perms):
            notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(self._recipients(), ['hsr_inst@example.com'])

    def test_cis_without_submit_grades_reminds_teachers_only(self):
        self._admin('perm_admin')
        self._section()
        self._period()
        with mock.patch.object(HSAdminPerm, 'SUBMIT_GRADES', None):
            notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(self._recipients(), ['hsr_inst@example.com'])

    def test_with_perm_without_campus_reminds_teachers_only(self):
        from cis.models.highschool_administrator import (
            HSAdministratorPositionQuerySet)

        def old_with_perm(self, codename):
            return self

        self._admin('perm_admin')
        self._section()
        self._period()
        with mock.patch.object(HSAdministratorPositionQuerySet, 'with_perm', old_with_perm):
            notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(self._recipients(), ['hsr_inst@example.com'])

    def test_admin_lookup_is_not_per_section(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self._on_campus(self._campus('HR3'))
        self._admin('perm_admin')
        period = self._period()

        def admin_queries(count):
            for _ in range(count):
                self._section(teacher=False)
            SectionPeriodStatus.objects.all().delete()
            with CaptureQueriesContext(connection) as ctx:
                notify_sections_pending_period_grade(today=TODAY)
            return sum(1 for q in ctx.captured_queries
                       if 'cis_hsadministratorposition' in q['sql']
                       or 'cis_campus' in q['sql'])

        self.assertEqual(admin_queries(1), admin_queries(5))


class HSAdminReminderSecondaryTests(HSAdminPeriodReminderTests):
    """cis#154: admins at a section's secondary high schools are reminded
    too; secondary teachers are not."""

    def _secondary_section(self, teacher=True, primary=True):
        section = self._section(teacher=teacher, school=primary)
        section.add_secondary_highschool(self.other_school)
        return section

    def test_secondary_school_admin_is_reminded(self):
        self._admin('second_admin', school=self.other_school)
        self._secondary_section()
        self._period()

        notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(self._recipients(),
                         ['hsr_inst@example.com', 'second_admin@example.com'])
        self.assertIn('1 pending', self._body_for('second_admin@example.com'))

    def test_section_with_only_a_secondary_school_reminds_its_admin(self):
        self._admin('second_admin', school=self.other_school)
        section = self._secondary_section(teacher=False, primary=False)
        period = self._period()

        notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(self._recipients(), ['second_admin@example.com'])
        self.assertEqual(SectionPeriodStatus.objects.get(
            period=period, class_section=section).last_notified_on, TODAY)

    def test_admin_at_both_schools_counts_the_section_once(self):
        user, _role = self._admin('both_admin')
        HSAdministratorPosition.objects.create(
            hsadmin=HSAdministrator.objects.get(user=user), highschool=self.other_school,
            position=self.position, status='Active').grant(HSAdminPerm.SUBMIT_GRADES)
        self._secondary_section()
        self._period()

        notify_sections_pending_period_grade(today=TODAY)

        admin_messages = [m for m in Message.objects.all()
                          if 'both_admin@example.com' in m.email.to]
        self.assertEqual(len(admin_messages), 1)
        self.assertIn('1 pending', admin_messages[0].email.body)

    def test_secondary_teacher_is_not_reminded(self):
        other = User.objects.create_user(
            username='hsr_second', email='hsr_second@example.com', password='x')
        section = self._section()
        section.add_secondary_teacher(Teacher.objects.create(user=other))
        self._period()

        notify_sections_pending_period_grade(today=TODAY)

        self.assertEqual(self._recipients(), ['hsr_inst@example.com'])

    def test_secondary_schools_add_no_query_per_section(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self._admin('second_admin', school=self.other_school)
        self._period()

        def queries(count):
            for _ in range(count):
                self._secondary_section(teacher=False)
            SectionPeriodStatus.objects.all().delete()
            Message.objects.all().delete()
            with CaptureQueriesContext(connection) as ctx:
                notify_sections_pending_period_grade(today=TODAY)
            return sum(1 for q in ctx.captured_queries
                       if 'cis_classsectionsecondaryhighschool' in q['sql']
                       or 'cis_hsadministratorposition' in q['sql']
                       or 'cis_campus' in q['sql'])

        self.assertEqual(queries(1), queries(5))


for _name in [n for n in dir(HSAdminPeriodReminderTests) if n.startswith('test_')]:
    setattr(HSAdminReminderSecondaryTests, _name, None)
