"""Grades: Pending Submission Recipients (#14).

Who still owes grades for the chosen grading periods: one row per person,
the primary instructors and/or the high school admins who can submit grades,
with the classes they still need to submit. Usable as a Bulk Messages data
source (one recipient per person), so CE can email them without a CSV
round-trip.

Built on the same per-period status as "Grade Submission Status by Period"
(``SectionPeriodStatus``). Only primary instructors are listed -- a secondary
instructor (cis#154) never enters grades -- and HS admins are those whose
Active position at the class's primary school holds Can submit grades for the
course's campus.
"""
import csv
import datetime
import io
from types import SimpleNamespace

from django import forms
from django.core.files.base import ContentFile
from django.urls import reverse_lazy

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit

from cis.backends.storage_backend import PrivateMediaStorage
from cis.models.section import ClassSection
from cis.models.term import Term
from cis.reports.datasource_mixin import ReportDataSourceMixin

from ..compat import (
    apply_term_tree, current_campus_only, expand_term_ids, picker_queryset,
    scope_to_user_campuses,
)
from ..models import GradingPeriod, SectionPeriodStatus
from ..services.csv_safe import safe_cell
from ..services.gating import submit_grades_admins_lookup
from ..services.report_marks import periods_outside_terms_error
from ..services.roster import roster_statuses
from ._period_picker import PeriodSelectMultiple, follow_terms

NOT_STARTED = 'not_started'
STATUS_CHOICES = ((NOT_STARTED, 'Not Started'), ('saved', 'Draft'))
STATUS_LABELS = dict(STATUS_CHOICES)

INSTRUCTORS, HS_ADMINS, BOTH = 'instructors', 'hs_admins', 'both'
RECIPIENT_CHOICES = (
    (INSTRUCTORS, 'Instructors'),
    (HS_ADMINS, 'High school admins who can submit grades'),
    (BOTH, 'Both'),
)
ROLE_LABELS = {'instructor': 'Instructor', 'hs_admin': 'HS Admin'}

COLUMNS = ['Role', 'Last Name', 'First Name', 'Email', 'Grading Period(s)',
           'Class Count', 'Classes', 'Statuses', 'Graded', 'Not Graded']
BLANK_GRADES = ('', '-')


def _list(value):
    if value in (None, ''):
        return []
    if isinstance(value, (list, tuple)):
        return [str(v.pk if hasattr(v, 'pk') else v) for v in value if v not in (None, '')]
    return [str(getattr(value, 'pk', value))]


def _class_label(section):
    course = section.course.name or str(section.course)
    return f'{course} {section.section_number} ({section.class_number})'


class pending_submission_recipients(ReportDataSourceMixin, forms.Form):
    """One row per person who still has grades to submit."""

    datasource_descriptor = (
        'Instructors and/or high school admins who still need to submit grades '
        'for the chosen grading periods (one row per person).')
    email_column = 'email'
    name_columns = ['FirstName', 'LastName']
    datasource_fields = {
        'FirstName': 'first_name',
        'LastName': 'last_name',
        'email': 'email',
        'Role': 'role',
        'GradingPeriods': 'periods',
        'ClassCount': 'class_count',
        'Classes': 'classes',
        'Statuses': 'statuses',
        'Graded': 'graded',
        'NotGraded': 'not_graded',
    }

    term = forms.ModelMultipleChoiceField(
        queryset=None, label='Term(s)', help_text='Select one or more terms to include')
    periods = forms.ModelMultipleChoiceField(
        queryset=GradingPeriod.objects.none(), required=False, label='Grading Period(s)',
        widget=PeriodSelectMultiple,
        help_text='Only periods of the selected term(s) and their sub-terms can be picked; '
                  'leave blank to include every one')
    status = forms.MultipleChoiceField(
        choices=STATUS_CHOICES, required=False, label='Status',
        initial=[NOT_STARTED, 'saved'],
        help_text='Classes whose grades for the period are not yet submitted. '
                  'Leave blank for both.')
    highschools = forms.ModelMultipleChoiceField(
        queryset=None, required=False, label='High School(s)',
        help_text='Leave blank to include all high schools')
    recipients = forms.ChoiceField(
        choices=RECIPIENT_CHOICES, initial=INSTRUCTORS, label='Recipients',
        help_text='Instructors are the primary instructor of each class. High school '
                  "admins are those whose position at the class's school holds Can "
                  'submit grades.')

    request = None

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request

        self.helper = FormHelper()
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Report'))

        terms = current_campus_only(Term.objects.order_by('-code'), 'academic_year__campus')
        apply_term_tree(self.fields['term'], terms)
        self.fields['periods'].queryset = current_campus_only(
            GradingPeriod.objects.select_related('term').order_by('-term__code', 'sequence'),
            'term__academic_year__campus')
        self.fields['highschools'].queryset = picker_queryset()
        self.helper.layout = Layout(*self.fields, follow_terms(terms))

        if self.request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')])

    def clean(self):
        cleaned = super().clean()
        periods_outside_terms_error(self, 'periods')
        return cleaned

    # -- the data ---------------------------------------------------------

    def pending(self, data, user=None):
        """``[(section, period, status_key)]`` for active sections not yet
        submitted for a chosen period, matching the chosen statuses."""
        term_ids = expand_term_ids(_list(data.get('term')))
        sections = ClassSection.objects.select_related(
            'term', 'course', 'highschool', 'teacher__user',
        ).filter(term_id__in=term_ids, status='A')
        highschools = _list(data.get('highschools'))
        if highschools:
            sections = sections.filter(highschool_id__in=highschools)
        sections = scope_to_user_campuses(sections, user, campus_path='course__campus')
        sections = list(sections.order_by('term__code', 'course__name', 'class_number'))

        periods = GradingPeriod.objects.filter(term_id__in=term_ids)
        chosen = _list(data.get('periods'))
        if chosen:
            periods = periods.filter(pk__in=chosen)
        by_term = {}
        for period in periods.order_by('sequence'):
            by_term.setdefault(period.term_id, []).append(period)

        statuses = {(row.class_section_id, row.period_id): row.status
                    for row in SectionPeriodStatus.objects.filter(
                        period__in=periods, class_section__in=sections)}
        wanted = set(_list(data.get('status'))) or {NOT_STARTED, 'saved'}
        out = []
        for section in sections:
            for period in by_term.get(section.term_id, []):
                status = statuses.get((section.id, period.pk)) or ''
                if status == 'submitted':
                    continue
                key = status if status == 'saved' else NOT_STARTED
                if key in wanted:
                    out.append((section, period, key))
        return out

    def _counts(self, pending):
        """``{(section_id, period_id): (graded, not_graded)}`` over the
        grade-entry roster statuses: the period grade for an interim period,
        the registration grade for the final one."""
        from cis.models.section import StudentRegistration
        from ..models import PeriodGrade
        if not pending:
            return {}
        section_ids = {s.id for s, _p, _k in pending}
        regs = StudentRegistration.objects.filter(class_section_id__in=section_ids)
        statuses = roster_statuses()  # [] means every status
        if statuses:
            regs = regs.filter(status__in=statuses)
        regs = list(regs.values_list('id', 'class_section_id', 'grade'))
        interim = {p.pk for _s, p, _k in pending if not p.is_final}
        period_grades = {}
        if interim:
            for reg_id, period_id, grade in PeriodGrade.objects.filter(
                    period_id__in=interim, registration_id__in=[r[0] for r in regs],
            ).values_list('registration_id', 'period_id', 'grade'):
                period_grades[(reg_id, period_id)] = grade
        counts = {}
        for section, period, _key in pending:
            graded = total = 0
            for reg_id, section_id, final_grade in regs:
                if section_id != section.id:
                    continue
                total += 1
                grade = final_grade if period.is_final else period_grades.get((reg_id, period.pk))
                if (grade or '').strip() not in BLANK_GRADES:
                    graded += 1
            counts[(section.id, period.pk)] = (graded, total - graded)
        return counts

    def people(self, data, user=None):
        """One entry per person: ``SimpleNamespace`` with the datasource
        attributes, in role then name order."""
        pending = self.pending(data, user)
        counts = self._counts(pending)
        choice = data.get('recipients') or INSTRUCTORS
        if isinstance(choice, (list, tuple)):
            choice = choice[0] if choice else INSTRUCTORS
        want_instructors = choice in (INSTRUCTORS, BOTH)
        lookup = submit_grades_admins_lookup() if choice in (HS_ADMINS, BOTH) else None

        people = {}

        def add(person, role, section, period, key):
            entry = people.setdefault((role, person.pk), {
                'user': person, 'role': role, 'items': []})
            entry['items'].append((section, period, key))

        for section, period, key in pending:
            if want_instructors and section.teacher_id and section.teacher.user.email:
                add(section.teacher.user, 'instructor', section, period, key)
            if lookup is not None and section.highschool_id:
                for admin in lookup(section.highschool_id,
                                    getattr(section.course, 'campus_id', None)):
                    add(admin, 'hs_admin', section, period, key)

        rows = []
        for entry in people.values():
            person, items = entry['user'], entry['items']
            classes, periods, statuses = [], [], []
            graded = not_graded = 0
            for section, period, key in items:
                label = _class_label(section)
                if label not in classes:
                    classes.append(label)
                if period.name not in periods:
                    periods.append(period.name)
                statuses.append(f'{label} {period.name}: {STATUS_LABELS[key]}')
                done, left = counts.get((section.id, period.pk), (0, 0))
                graded += done
                not_graded += left
            rows.append(SimpleNamespace(
                first_name=person.first_name, last_name=person.last_name,
                email=person.email, role=ROLE_LABELS[entry['role']],
                periods=', '.join(periods), class_count=len(classes),
                classes=', '.join(classes), statuses='; '.join(statuses),
                graded=graded, not_graded=not_graded,
            ))
        rows.sort(key=lambda r: (r.role != 'Instructor', r.last_name.lower(),
                                 r.first_name.lower()))
        return rows

    def recipient_queryset(self, data):
        user = self.request.user if self.request is not None else None
        return self.people(data, user)

    def run(self, task, data):
        rows = self.people(data, user=getattr(task, 'created_by', None))
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')
        writer.writerow(COLUMNS)
        for r in rows:
            writer.writerow([safe_cell(c) for c in (
                r.role, r.last_name, r.first_name, r.email, r.periods,
                r.class_count, r.classes, r.statuses, r.graded, r.not_graded)])

        name = f"pending_submission_recipients_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = f"reports/{datetime.datetime.now().strftime('%Y/%m')}/{task.id}/{name}"
        storage = PrivateMediaStorage()
        path = storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        return storage.url(path)

    def run_report(self):
        ...
