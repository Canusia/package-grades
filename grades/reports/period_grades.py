"""Grades by Grading Period: one row per registration, one column per selected period."""
import io
import csv
import datetime

from django import forms
from django.urls import reverse_lazy
from django.core.files.base import ContentFile

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.models.term import Term
from cis.models.course import Campus
from cis.models.section import StudentRegistration
from ..compat import apply_campus_field, picker_queryset, scope_report_by_campus
from ..models import GradingPeriod, SectionPeriodStatus
from ..services.csv_safe import safe_cell
from ..services.report_marks import period_mark_annotation, periods_outside_terms_error
from .class_grade_status import GRADE_STATUS_CHOICES, NOT_STARTED, status_key


class period_grades(forms.Form):
    """Student grades for each selected grading period (mid-semester and final)."""

    campus = forms.ModelMultipleChoiceField(
        queryset=Campus.objects.none(), required=True, label='Campus',
    )
    term = forms.ModelMultipleChoiceField(
        queryset=None, label='Term(s)', help_text='Select one or more terms to include')
    periods = forms.ModelMultipleChoiceField(
        queryset=GradingPeriod.objects.none(), required=True, label='Grading Period(s)')
    highschools = forms.ModelMultipleChoiceField(
        queryset=None, required=False, label='High School(s)',
        help_text='Leave blank to include all high schools')
    registration_status = forms.MultipleChoiceField(
        choices=StudentRegistration.STATUS_OPTIONS, required=False,
        label='Registration Status(es)')
    period_status = forms.MultipleChoiceField(
        choices=GRADE_STATUS_CHOICES, required=False, label='Period Submission Status',
        help_text='Leave blank to include every class')

    COLUMNS = ['Term', 'Course', 'Class No.', 'Section No.', 'Instructor', 'Instructor Email',
               'High School', 'Student Last Name', 'Student First Name', 'Student ID',
               'Registration Status']

    roles = []
    request = None

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request

        self.helper = FormHelper()
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Report'))

        self.fields['term'].queryset = Term.objects.all().order_by('-code')
        self.fields['periods'].queryset = GradingPeriod.objects.select_related(
            'term').order_by('-term__code', 'sequence')
        self.fields['highschools'].queryset = picker_queryset()
        apply_campus_field(self, getattr(self.request, 'user', None))

        if self.request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

    @staticmethod
    def _mark(value):
        return '' if value in (None, '-') else value

    def _keep_by_period_status(self, regs, periods, wanted):
        """Registrations whose section has a wanted status for every selected
        period of the section's own term (other terms' periods do not apply)."""
        section_terms = dict(regs.values_list('class_section_id', 'class_section__term_id'))
        found = {}
        for s in SectionPeriodStatus.objects.filter(
                period__in=periods, class_section_id__in=section_terms):
            found[(s.class_section_id, s.period_id)] = status_key(s.status)
        # A section whose term has none of the selected periods has no status
        # to match, so it is left out rather than passing vacuously.
        ok = []
        for sid, term_id in section_terms.items():
            own = [p for p in periods if p.term_id == term_id]
            if own and all(found.get((sid, p.pk), NOT_STARTED) in wanted for p in own):
                ok.append(sid)
        return regs.filter(class_section_id__in=ok)

    def clean(self):
        cleaned = super().clean()
        periods_outside_terms_error(self, 'periods')
        return cleaned

    def table(self, data, user=None):
        periods = list(GradingPeriod.objects.filter(pk__in=data.get('periods') or [])
                       .order_by('sequence'))
        regs = StudentRegistration.objects.filter(
            class_section__term_id__in=data.get('term') or []
        ).select_related('class_section__term', 'class_section__course',
                         'class_section__teacher__user', 'class_section__highschool',
                         'student__user')
        if data.get('highschools'):
            regs = regs.filter(class_section__highschool_id__in=data['highschools'])
        if data.get('registration_status'):
            regs = regs.filter(status__in=data['registration_status'])
        regs = scope_report_by_campus(regs, user, data.get('campus'),
                                      campus_path='class_section__course__campus')
        if data.get('period_status'):
            regs = self._keep_by_period_status(regs, periods, set(data['period_status']))
        for i, p in enumerate(periods):
            regs = regs.annotate(**{f'p{i}': period_mark_annotation(p)})
        header = self.COLUMNS + [p.name for p in periods]
        rows = []
        for r in regs.order_by('class_section__term__code', 'class_section__class_number',
                               'student__user__last_name'):
            s, u = r.class_section, r.student.user
            t = s.teacher.user if s.teacher_id else None
            rows.append([s.term.label, s.course.name, s.class_number, s.section_number,
                         f'{t.last_name}, {t.first_name}' if t else '', t.email if t else '',
                         s.highschool.name if s.highschool_id else '', u.last_name, u.first_name,
                         u.psid or '', r.status] +
                        [self._mark(getattr(r, f'p{i}')) for i in range(len(periods))])
        return header, rows

    def run(self, task, data):
        header, rows = self.table(data, user=getattr(task, 'created_by', None))

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')
        writer.writerow([safe_cell(c) for c in header])
        for row in rows:
            writer.writerow([safe_cell(c) for c in row])

        file_name = f"period_grades_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        now = datetime.datetime.now().strftime("%Y/%m")
        path = f"reports/{now}/{task.id}/{file_name}"
        media_storage = PrivateMediaStorage()
        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        return media_storage.url(path)

    def run_report(self):
        ...
