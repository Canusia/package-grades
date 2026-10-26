"""v1: period reports (spec §5)."""
import csv
import io
import json
import re
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from .base import GradesTestCase
from . import factories as f
from ..compat import has_campus_gate
from ..reports import grade_by_course as m_course
from ..reports import grade_by_demographics as m_demo
from ..reports import grade_by_highschool as m_hs
from ..reports import period_grades as m_pg
from ..reports import period_submission_status as m_pss
from ..reports.grade_by_course import grade_by_course
from ..reports.grade_by_demographics import grade_by_demographics
from ..reports.grade_by_highschool import grade_by_highschool
from ..reports.period_grades import HS_ACCESS_OFF, period_grades
from ..reports.period_submission_status import period_submission_status
from ..services.csv_safe import safe_cell
from ..services.periods import save_mark, set_status
from ..services.report_marks import period_mark_annotation


def run_report(module, report, task, data):
    """Run a report with storage captured; return parsed CSV rows."""
    saved = {}

    class Storage:
        def save(self, path, content):
            saved['body'] = content.read().decode('utf-8')
            return path

        def url(self, path):
            return f'/media/{path}'

    with patch.object(module, 'PrivateMediaStorage', Storage):
        report.run(task, data)
    return list(csv.reader(io.StringIO(saved['body'])))


class PeriodReportTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        cls.term = f.term()
        cls.mid = f.period(cls.term, 'Mid', date(2026, 10, 1), date(2026, 10, 9), 1)
        cls.final = f.period(cls.term, 'Final', date(2026, 12, 1), date(2026, 12, 9), 2, is_final=True)
        cls.section = f.section(cls.term, f.teacher())
        cls.reg = f.registration(cls.section, last_name='Amador')
        save_mark(cls.mid, cls.reg, 'B')
        save_mark(cls.final, cls.reg, 'A')
        set_status(cls.section, cls.mid, 'submitted')

    def test_mark_annotation(self):
        from cis.models.section import StudentRegistration
        qs = StudentRegistration.objects.filter(pk=self.reg.pk)
        self.assertEqual(qs.annotate(m=period_mark_annotation(self.mid)).get().m, 'B')
        self.assertEqual(qs.annotate(m=period_mark_annotation(self.final)).get().m, 'A')
        self.assertEqual(qs.annotate(m=period_mark_annotation(None)).get().m, 'A')

    def test_period_grades_one_column_per_period(self):
        report = period_grades()
        data = {'term': [self.term.id], 'periods': [self.mid.id, self.final.id], 'campus': []}
        header, rows = report.table(data)
        self.assertEqual(header[-2:], ['Mid', 'Final'])
        self.assertEqual(rows[0][-2:], ['B', 'A'])

    def test_period_grades_blank_marks_and_period_status_filter(self):
        other = f.section(self.term, f.teacher())
        f.registration(other)  # grade '-' and no mid mark
        report = period_grades()
        data = {'term': [self.term.id], 'periods': [self.mid.id, self.final.id], 'campus': []}
        _, rows = report.table(data)
        self.assertEqual(len(rows), 2)
        self.assertIn(['', ''], [r[-2:] for r in rows])
        _, rows = report.table({**data, 'periods': [self.mid.id], 'period_status': ['submitted']})
        self.assertEqual([r[-1] for r in rows], ['B'])
        _, rows = report.table({**data, 'periods': [self.mid.id], 'period_status': ['not_started']})
        self.assertEqual([r[-1] for r in rows], [''])

    def test_submission_status_rows(self):
        report = period_submission_status()
        rows = list(report.rows(report.get_result({'term': [self.term.id], 'campus': []})))
        statuses = {r[2]: r[-3] for r in rows}  # period name -> status label
        self.assertEqual(statuses, {'Mid': 'Submitted', 'Final': 'Not Started'})

    def test_submission_status_run_neutralises_formulas(self):
        self.section.course.title = '=cmd'
        self.section.course.save()
        teacher = self.section.teacher.user
        teacher.last_name = '=HYPERLINK("x")'
        teacher.save()
        task = SimpleNamespace(id=3, created_by=None)
        rows = run_report(m_pss, period_submission_status(), task,
                          {'term': [self.term.id], 'campus': []})
        self.assertEqual(rows[1][6].split(',')[0], "'=HYPERLINK(\"x\")")
        self.assertEqual(safe_cell('@x'), "'@x")
        self.assertEqual(safe_cell(None), '')

    def test_period_grades_run_neutralises_formulas(self):
        u = self.reg.student.user
        u.first_name = '+evil'
        u.save()
        task = SimpleNamespace(id=4, created_by=None)
        rows = run_report(m_pg, period_grades(), task, {
            'term': [self.term.id], 'periods': [self.mid.id], 'campus': []})
        self.assertEqual(rows[1][8], "'+evil")


class DistributionPeriodFilterTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        cls.term = f.term()
        cls.mid = f.period(cls.term, 'Mid', date(2026, 10, 1), date(2026, 10, 9), 1)
        cls.final = f.period(cls.term, 'Final', date(2026, 12, 1), date(2026, 12, 9), 2, is_final=True)
        cls.hs = f.highschool()
        cls.section = f.section(cls.term, f.teacher(), highschool_obj=cls.hs)
        cls.reg = f.registration(cls.section, highschool_obj=cls.hs)
        save_mark(cls.mid, cls.reg, 'B')
        save_mark(cls.final, cls.reg, 'A')
        cls.task = SimpleNamespace(id=9, created_by=None)

    def _counts(self, module, report, period=None, **extra):
        data = {'term': [self.term.id], 'registration_status': ['registered'],
                'campus': [], **extra}
        if period is not None:
            data['grading_period'] = period.pk
        rows = run_report(module, report, self.task, data)
        row = dict(zip(rows[0], rows[1]))
        return row['A'], row['B']

    def _check(self, module, report_cls, **extra):
        self.assertEqual(self._counts(module, report_cls(), **extra), ('1', '0'))
        self.assertEqual(self._counts(module, report_cls(), self.final, **extra), ('1', '0'))
        self.assertEqual(self._counts(module, report_cls(), self.mid, **extra), ('0', '1'))

    def test_grade_by_course(self):
        self._check(m_course, grade_by_course)

    def test_grade_by_highschool(self):
        self._check(m_hs, grade_by_highschool)

    def test_grade_by_demographics(self):
        self._check(m_demo, grade_by_demographics, demographic_dimension='gender')

    def test_field_blank_means_final(self):
        self.assertFalse(grade_by_course().fields['grading_period'].required)


@unittest.skipUnless(has_campus_gate(), 'this cis has no campus gate')
class NewReportsCampusScopeTests(GradesTestCase):
    def setUp(self):
        from cis.models.course import Campus
        f.grades_setting()
        self.term = f.term()
        self.mid = f.period(self.term, 'Mid', date(2026, 10, 1), date(2026, 10, 9), 1)
        pfx = settings.CAMPUS_CODE_PREFIX
        self.campus_a = Campus.objects.create(name='A', code=f'{pfx}-A1')
        self.campus_b = Campus.objects.create(name='B', code=f'{pfx}-B1')
        self.regs = {}
        for key, campus in (('a', self.campus_a), ('b', self.campus_b)):
            course = f.course(catalog_number=key)
            course.campus = campus
            course.save()
            sec = f.section(self.term, f.teacher(), course_obj=course)
            self.regs[key] = (sec, f.registration(sec, last_name=key.upper()))
        User = get_user_model()
        self.ce = User.objects.create_user(
            username='scope_ce', email='scope_ce@x.com', password='x')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.ce.set_process_campuses([str(self.campus_a.id)])

    # No campus filter on these two: a ce user gets the campuses they process.
    def test_period_grades_scoped(self):
        _, rows = period_grades().table({
            'term': [self.term.id], 'periods': [self.mid.id]}, user=self.ce)
        self.assertEqual([r[7] for r in rows], ['A'])

    def test_submission_status_scoped(self):
        report = period_submission_status()
        result = report.get_result({'term': [self.term.id]}, user=self.ce)
        self.assertEqual({s.id for s, _, _ in result}, {self.regs['a'][0].id})


class PeriodTermCheckTests(GradesTestCase):
    """Report forms reject grading periods outside the selected terms (I4)."""

    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        cls.t1, cls.t2 = f.term(), f.term()
        cls.p1 = f.period(cls.t1, 'Mid T1', date(2026, 10, 1), date(2026, 10, 9), 1)
        cls.p2 = f.period(cls.t2, 'Mid T2', date(2026, 10, 1), date(2026, 10, 9), 1)

    def _errors(self, report_cls, field, period, terms):
        value = [str(period.id)] if field == 'periods' else str(period.id)
        form = report_cls(data={'term': [str(t.id) for t in terms], field: value})
        form.is_valid()
        return form.errors.get(field)

    def test_period_reports_reject_other_term_periods(self):
        for report_cls in (period_grades, period_submission_status):
            with self.subTest(report=report_cls.__name__):
                self.assertIn('selected term', self._errors(report_cls, 'periods', self.p2, [self.t1])[0])
                self.assertIsNone(self._errors(report_cls, 'periods', self.p1, [self.t1]))

    def test_distribution_reports_reject_other_term_period(self):
        for report_cls in (grade_by_course, grade_by_highschool, grade_by_demographics):
            with self.subTest(report=report_cls.__name__):
                self.assertIn('selected term', self._errors(report_cls, 'grading_period', self.p2, [self.t1])[0])
                self.assertIsNone(self._errors(report_cls, 'grading_period', self.p1, [self.t1, self.t2]))

    def test_status_filter_only_requires_own_term_periods(self):
        s1 = f.section(self.t1, f.teacher())
        s2 = f.section(self.t2, f.teacher())
        f.registration(s1, last_name='One')
        f.registration(s2, last_name='Two')
        set_status(s1, self.p1, 'submitted')
        set_status(s2, self.p2, 'submitted')
        _, rows = period_grades().table({
            'term': [self.t1.id, self.t2.id], 'periods': [self.p1.id, self.p2.id],
            'campus': [], 'period_status': ['submitted']})
        self.assertEqual(sorted(r[7] for r in rows), ['One', 'Two'])

    def test_period_grades_header_is_csv_safe(self):
        self.p1.name = '=cmd()'
        self.p1.save()
        task = SimpleNamespace(id=5, created_by=None)
        rows = run_report(m_pg, period_grades(), task, {
            'term': [self.t1.id], 'periods': [self.p1.id], 'campus': []})
        self.assertEqual(rows[0][-1], "'=cmd()")


class PeriodGradesTermsAndHSAdminTests(GradesTestCase):
    """Grades by Grading Period: parent terms include sub-terms, the period list
    follows the terms, no campus filter, and HS admins get only their Active
    schools."""

    @classmethod
    def setUpTestData(cls):
        from cis.models.highschool_administrator import (
            HSAdministrator, HSAdministratorPosition, HSPosition,
        )
        f.grades_setting()
        cls.parent = f.term()
        cls.child = f.term(ay=cls.parent.academic_year, parent=cls.parent)
        cls.other = f.term()
        cls.p_child = f.period(cls.child, 'Mid Child', date(2026, 10, 1), date(2026, 10, 9), 1)
        cls.p_other = f.period(cls.other, 'Mid Other', date(2026, 10, 1), date(2026, 10, 9), 1)
        cls.own, cls.closed, cls.foreign = f.highschool('Own HS'), f.highschool('Closed HS'), \
            f.highschool('Foreign HS')
        # Inactive here: per-campus status on a multi-campus host (its link to
        # this campus), the school's own status otherwise.
        from cis.models.highschool import HighSchoolCampus
        if HighSchoolCampus.objects.filter(highschool=cls.closed).exists():
            HighSchoolCampus.objects.filter(highschool=cls.closed).update(status='Inactive')
        else:
            cls.closed.status = 'Inactive'
            cls.closed.save()
        for hs, name in ((cls.own, 'Own'), (cls.closed, 'Closed'), (cls.foreign, 'Foreign')):
            sec = f.section(cls.child, f.teacher(), highschool_obj=hs)
            save_mark(cls.p_child, f.registration(sec, last_name=name), 'B')
        User = get_user_model()
        cls.hs_user = User.objects.create_user(
            username='pg_hs', email='pg_hs@x.com', password='x')
        cls.hs_user.groups.add(Group.objects.get_or_create(name='highschool_admin')[0])
        hsadmin = HSAdministrator.objects.create(user=cls.hs_user)
        position = HSPosition.objects.create(name='Counselor')
        for hs in (cls.own, cls.closed):
            HSAdministratorPosition.objects.create(
                hsadmin=hsadmin, highschool=hs, position=position, status='Active')
        HSAdministratorPosition.objects.create(
            hsadmin=hsadmin, highschool=cls.foreign, position=position, status='Inactive')

    def _form(self, user=None, data=None):
        request = SimpleNamespace(user=user, GET={}) if user else None
        return period_grades(request, data=data)

    def _names(self, data, user=None):
        _, rows = period_grades().table(data, user=user)
        return sorted(r[7] for r in rows)

    def test_no_campus_field(self):
        self.assertNotIn('campus', self._form().fields)

    def test_parent_term_includes_sub_term_registrations_and_periods(self):
        data = {'term': [str(self.parent.id)], 'periods': [str(self.p_child.id)]}
        form = self._form(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(self._names({'term': [self.parent.id], 'periods': [self.p_child.id]}),
                         ['Closed', 'Foreign', 'Own'])
        self.assertIn('selected term', self._form(data={
            'term': [str(self.parent.id)], 'periods': [str(self.p_other.id)]}).errors['periods'][0])

    def test_period_options_carry_their_term_and_follow_the_term_field(self):
        html = self._form().fields['periods'].widget.render(
            'periods', [], {'id': 'id_periods'})
        self.assertIn(f'data-term="{self.child.id}"', html)
        from crispy_forms.utils import render_crispy_form
        page = render_crispy_form(self._form())
        form_body = page[page.index('<form'):page.index('</form>')]
        # The data rides in a json_script block inside the form; the script
        # finds both selects from that form, listens through jQuery (the
        # multiple-select plugin's change is jQuery-only) and refreshes the plugin.
        data = re.search(r'<script id="(grades-period-picker-\w+)" type="application/json">'
                         r'(.*?)</script>', form_body)
        self.assertIsNotNone(data)
        cfg = json.loads(data.group(2))
        self.assertEqual((cfg['term'], cfg['periods']), ('term', 'periods'))
        self.assertIn(str(self.child.id), cfg['groups'][str(self.parent.id)])
        self.assertIn(f'getElementById("{data.group(1)}")', form_body)
        for needle in (".closest('form')", "$(terms).on('change', sync)", 'o.disabled = !ok',
                       "multipleSelect('refresh')", 'setTimeout(sync, 0)'):
            self.assertIn(needle, form_body)

    def test_hs_admin_picker_lists_only_active_schools_with_an_active_role(self):
        names = [hs.name for hs in self._form(self.hs_user).fields['highschools'].queryset]
        self.assertEqual(names, ['Own HS'])

    def test_hs_admin_cannot_run_it_when_grade_access_is_off(self):
        data = {'term': [str(self.parent.id)], 'periods': [str(self.p_child.id)]}
        form = self._form(self.hs_user, data=data)  # setting has no access: none
        self.assertFalse(form.is_valid())
        self.assertIn(HS_ACCESS_OFF, form.non_field_errors())
        unbound = self._form(self.hs_user)
        self.assertEqual(unbound.helper.inputs, [])
        self.assertIn(HS_ACCESS_OFF, unbound.helper.layout.fields[0].html)
        # CE users are not affected.
        self.assertTrue(self._form(data=data).is_valid())

    def test_hs_admin_can_run_it_with_view_or_edit_access(self):
        data = {'term': [str(self.parent.id)], 'periods': [str(self.p_child.id)]}
        for access in ('view', 'edit'):
            f.grades_setting(hs_admin_grade_entry=access)
            form = self._form(self.hs_user, data=data)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertTrue(form.helper.inputs)

    def test_hs_admin_rows_are_their_active_schools_whatever_is_selected(self):
        data = {'term': [self.parent.id], 'periods': [self.p_child.id],
                'highschools': [self.own.id, self.closed.id, self.foreign.id]}
        self.assertEqual(self._names(data, user=self.hs_user), ['Own'])
        self.assertEqual(self._names({**data, 'highschools': []}, user=self.hs_user), ['Own'])


class SubmissionStatusFilterTests(GradesTestCase):
    """Grade Submission Status by Period: no campus field, parent terms include
    sub-terms, and the period list follows the terms."""

    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        cls.parent = f.term()
        cls.child = f.term(ay=cls.parent.academic_year, parent=cls.parent)
        cls.p_child = f.period(cls.child, 'Mid Child', date(2026, 10, 1), date(2026, 10, 9), 1)
        cls.sec = f.section(cls.child, f.teacher())

    def test_no_campus_field_and_periods_follow_terms(self):
        form = period_submission_status()
        self.assertNotIn('campus', form.fields)
        html = form.fields['periods'].widget.render('periods', [], {'id': 'id_periods'})
        self.assertIn(f'data-term="{self.child.id}"', html)
        self.assertIn('"term": "term"', form.helper.layout.fields[-1].html)

    def test_parent_term_includes_sub_term_sections_and_periods(self):
        result = period_submission_status().get_result({'term': [self.parent.id]})
        self.assertEqual([(s.id, p.id) for s, p, _ in result], [(self.sec.id, self.p_child.id)])
        form = period_submission_status(data={
            'term': [str(self.parent.id)], 'periods': [str(self.p_child.id)]})
        self.assertTrue(form.is_valid(), form.errors)


@unittest.skipUnless(getattr(settings, 'MULTI_CAMPUS', False), 'single-campus host')
class ReportTermsFollowTheCampusTests(GradesTestCase):
    """On a multi-campus host every grades report lists, and accepts, only the
    current campus's terms and grading periods."""

    @classmethod
    def setUpTestData(cls):
        from cis.models.course import Campus
        from cis.models.term import AcademicYear
        f.grades_setting()
        pfx = settings.CAMPUS_CODE_PREFIX
        cls.campus_b = Campus.objects.create(name='Other', code=f'{pfx}-OTHER')
        cls.here = f.term()
        cls.there = f.term(ay=AcademicYear.objects.create(name='AY other', campus=cls.campus_b))
        cls.p_here = f.period(cls.here, 'Mid', date(2026, 10, 1), date(2026, 10, 9), 1)
        cls.p_there = f.period(cls.there, 'Mid', date(2026, 10, 1), date(2026, 10, 9), 1)

    def _reports(self):
        from ..reports.class_grade_status import class_grade_status
        return (class_grade_status, grade_by_course, grade_by_demographics,
                grade_by_highschool, period_grades, period_submission_status)

    def test_term_and_period_lists_are_this_campus_only(self):
        for report_cls in self._reports():
            with self.subTest(report=report_cls.__name__):
                form = report_cls()
                terms = set(form.fields['term'].queryset)
                self.assertIn(self.here, terms)
                self.assertNotIn(self.there, terms)
                field = form.fields.get('periods') or form.fields.get('grading_period')
                if field is not None:
                    self.assertNotIn(self.p_there, set(field.queryset))

    def test_another_campus_term_is_rejected(self):
        for report_cls in self._reports():
            with self.subTest(report=report_cls.__name__):
                form = report_cls(data={'term': [str(self.there.id)]})
                form.is_valid()
                self.assertIn('term', form.errors)
