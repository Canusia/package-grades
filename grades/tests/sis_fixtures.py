"""Shared fixtures for the SIS grade-push tests."""
import json

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.settings import Setting
from cis.models.student import Student
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

User = get_user_model()
GRADES_KEY = getattr(django_settings, 'CAMPUS_CODE_PREFIX') + '_class_grades'
REG_SIS = 'b1132b12-cda9-4e2a-bc48-a06870e41802'


class SISFixtureMixin:
    """setUpTestData + helpers: one grade term, CE user, section/registration makers."""

    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='instructor')
        Group.objects.get_or_create(name='student')
        ce_group, _ = Group.objects.get_or_create(name='ce')
        User.objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        Setting.objects.get_or_create(
            key='cis.settings.menu',
            defaults={'value': {'instructor_menu': json.dumps([])}})

        ay = AcademicYear.objects.create(name='AY sis push')
        cls.term = Term.objects.create(academic_year=ay, code='FA40', label='Fall 2040')
        cls.other_term = Term.objects.create(academic_year=ay, code='SP41', label='Spring 2041')
        Setting.objects.update_or_create(key=GRADES_KEY, defaults={'value': {
            'grades': 'A,B,C',
            'registration_status': ['applied'],
            'terms': [str(cls.term.id)],
            'start_date': '01/01/2020',
            'end_date': '01/01/2040',
        }})

        teacher_user = User.objects.create_user(
            username='sis_teacher', email='sis_teacher@example.com', password='x')
        cls.teacher = Teacher.objects.create(user=teacher_user)
        cls.ce_user = User.objects.create_user(
            username='sis_ce', email='sis_ce@example.com', password='x')
        cls.ce_user.groups.add(ce_group)
        cohort = Cohort.objects.create(name='Cohort SIS', designator='CS')
        cls.course = Course.objects.create(
            catalog_number='101', title='SIS Course', cohort=cohort, credit_hours=5)
        cls.highschool = HighSchool.objects.create(name='HS SIS')
        cls._n = 7000

    def make_section(self, term=None, grade_status='submitted'):
        type(self)._n += 1
        return ClassSection.objects.create(
            class_number=str(self._n), section_number='01', term=term or self.term,
            course=self.course, teacher=self.teacher, grade_status=grade_status)

    def make_registration(self, section, grade='A', sis_id=REG_SIS, status='applied'):
        type(self)._n += 1
        user = User.objects.create_user(
            username=f'sis_stu_{self._n}', email=f'sis_stu_{self._n}@example.com', password='x')
        student = Student.objects.create(user=user, account_verified=True)
        return StudentRegistration.objects.create(
            student=student, class_section=section, highschool=self.highschool,
            status=status, verification_status='pending', grade=grade, sis_id=sis_id,
            status_changed_on={'applied_on': '01/01/2024'})
