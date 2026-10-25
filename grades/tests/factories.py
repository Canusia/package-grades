"""Fixture builders for grades tests. Call inside a GradesTestCase."""
import itertools
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model

_seq = itertools.count(1000)


def _n():
    return next(_seq)


def grades_key():
    return getattr(settings, 'CAMPUS_CODE_PREFIX') + '_class_grades'


def grades_setting(**values):
    from cis.models.settings import Setting
    base = {'grades': 'A,B,C,D,F', 'registration_status': ['registered']}
    base.update(values)
    Setting.objects.update_or_create(key=grades_key(), defaults={'value': base})
    return base


def term(code=None, label=None, ay=None, parent=None):
    from cis.models.term import AcademicYear, Term
    n = _n()
    ay = ay or AcademicYear.objects.create(name=f'AY {n}')
    return Term.objects.create(
        academic_year=ay, code=code or f'T{n}', label=label or f'Term {n}',
        parent=parent)


def teacher(username=None, first_name='Ina', last_name='Instructor'):
    from django.contrib.auth.models import Group
    from cis.models.teacher import Teacher
    n = _n()
    username = username or f'inst{n}@example.com'
    user = get_user_model().objects.create_user(
        username=username, email=username, password='x',
        first_name=first_name, last_name=last_name)
    user.groups.add(Group.objects.get_or_create(name='instructor')[0])
    return Teacher.objects.create(user=user)


def course(designator='ENGL', catalog_number='1301'):
    from cis.models.course import Cohort, Course
    cohort, _ = Cohort.objects.get_or_create(
        designator=designator, defaults={'name': designator})
    return Course.objects.create(
        catalog_number=catalog_number, title=f'{designator} {catalog_number}',
        cohort=cohort, credit_hours=3)


def highschool(name=None):
    from cis.models.highschool import HighSchool
    return HighSchool.objects.create(name=name or f'HS {_n()}')


def section(term, teacher=None, course_obj=None, highschool_obj=None,
            class_number=None):
    from cis.models.section import ClassSection
    return ClassSection.objects.create(
        class_number=class_number or str(_n()), section_number='01',
        term=term, course=course_obj or course(catalog_number=str(_n())),
        teacher=teacher, highschool=highschool_obj, status='A')


def registration(section_obj, status='registered', grade='', highschool_obj=None,
                 last_name=None, first_name='Stu', psid=None):
    from django.contrib.auth.models import Group
    from cis.models.section import StudentRegistration
    from cis.models.student import Student
    Group.objects.get_or_create(name='student')
    get_user_model().objects.get_or_create(
        username='cron', defaults={'email': 'cron@example.com'})  # signals note as 'cron'
    n = _n()
    user = get_user_model().objects.create_user(
        username=f'stu{n}@example.com', email=f'stu{n}@example.com', password='x',
        first_name=first_name, last_name=last_name or f'Student{n}',
        psid=psid or f'P{n}')
    student = Student.objects.create(
        user=user, account_verified=True, highschool=highschool_obj)
    return StudentRegistration.objects.create(
        student=student, class_section=section_obj, highschool=highschool_obj,
        status=status, grade=grade or '-', status_changed_on={})


def period(term_obj, name, opens_on, due_on, sequence=1, is_final=False, **kw):
    from ..models import GradingPeriod
    return GradingPeriod.objects.create(
        term=term_obj, name=name, sequence=sequence, opens_on=opens_on,
        due_on=due_on, is_final=is_final, **kw)


D = date  # short alias for tests

