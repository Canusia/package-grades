"""Grade Submission Status by Period: one row per class per grading period."""
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
from cis.models.section import ClassSection
from ..compat import apply_campus_field, picker_queryset, scope_report_by_campus
from ..models import GradingPeriod, SectionPeriodStatus
from ..services.csv_safe import safe_cell
from .class_grade_status import STATUS_LABELS, last_changed, status_key

COLUMNS = ['Term', 'Course', 'Grading Period', 'Final', 'Class No.', 'Section No.',
           'Instructor', 'Instructor Email', 'High School', 'Status',
           'Status Changed On', 'Last Reminder']


class period_submission_status(forms.Form):
    """Per class and grading period: submitted, draft or not started."""

    campus = forms.ModelMultipleChoiceField(
        queryset=Campus.objects.none(), required=True, label='Campus',
    )
    term = forms.ModelMultipleChoiceField(
        queryset=None, label='Term(s)', help_text='Select one or more terms to include')
    periods = forms.ModelMultipleChoiceField(
        queryset=GradingPeriod.objects.none(), required=False, label='Grading Period(s)',
        help_text='Leave blank to include every period of the selected terms')
    highschools = forms.ModelMultipleChoiceField(
        queryset=None, required=False, label='High School(s)',
        help_text='Leave blank to include all high schools')

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

    def get_result(self, data, user=None):
        """[(section, period, SectionPeriodStatus or None)] for active sections x periods."""
        term_ids = data.get('term') or []
        sections = ClassSection.objects.select_related(
            'term', 'course', 'highschool', 'teacher__user'
        ).filter(term_id__in=term_ids, status='A')
        if data.get('highschools'):
            sections = sections.filter(highschool_id__in=data['highschools'])
        sections = scope_report_by_campus(
            sections, user, data.get('campus'), campus_path='course__campus')
        sections = list(sections.order_by('term__code', 'course__name', 'class_number'))

        periods = GradingPeriod.objects.filter(term_id__in=term_ids)
        if data.get('periods'):
            periods = periods.filter(pk__in=data['periods'])
        by_term = {}
        for p in periods.order_by('sequence'):
            by_term.setdefault(p.term_id, []).append(p)

        statuses = {(s.class_section_id, s.period_id): s
                    for s in SectionPeriodStatus.objects.filter(
                        period__in=periods, class_section__in=sections)}
        return [(section, p, statuses.get((section.id, p.pk)))
                for section in sections for p in by_term.get(section.term_id, [])]

    def rows(self, result):
        for section, period, row in result:
            t = section.teacher.user if section.teacher_id else None
            yield [
                section.term.label,
                section.course.name,
                period.name,
                'Yes' if period.is_final else 'No',
                section.class_number,
                section.section_number,
                f'{t.last_name}, {t.first_name}' if t else '',
                t.email if t else '',
                section.highschool.name if section.highschool_id else '',
                STATUS_LABELS[status_key(row.status if row else '')],
                last_changed(row.status_changed_on) if row else '',
                row.last_notified_on.strftime('%m/%d/%Y') if row and row.last_notified_on else '',
            ]

    def run(self, task, data):
        result = self.get_result(data, user=getattr(task, 'created_by', None))

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')
        writer.writerow(COLUMNS)
        for row in self.rows(result):
            writer.writerow([safe_cell(c) for c in row])

        file_name = f"period_submission_status_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        now = datetime.datetime.now().strftime("%Y/%m")
        path = f"reports/{now}/{task.id}/{file_name}"
        media_storage = PrivateMediaStorage()
        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        return media_storage.url(path)

    def run_report(self):
        ...
