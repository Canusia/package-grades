"""Class Grade Status: one row per class with its grade status and how far grading got.

Grade status is ``ClassSection.grade_status`` — '' is Not Started, 'saved'
is Draft, 'submitted' is Submitted (the same three the CE Grades tab counts).
With grading periods it mirrors the final period (``services.periods.set_status``).
Student counts use the grade-entry roster statuses, so they match what the
instructor sees on the grade-entry page.
"""
import io
import csv
import datetime

from django import forms
from django.db.models import Count, Q
from django.urls import reverse_lazy
from django.core.files.base import ContentFile

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.models.term import Term
from cis.models.course import Campus
from cis.models.section import ClassSection, StudentRegistration
from ..compat import apply_campus_field, picker_queryset, scope_report_by_campus
from ..services.roster import roster_statuses


NOT_STARTED = 'not_started'
GRADE_STATUS_CHOICES = (
    (NOT_STARTED, 'Not Started'),
    ('saved', 'Draft'),
    ('submitted', 'Submitted'),
)
STATUS_LABELS = dict(GRADE_STATUS_CHOICES)
BLANK_GRADES = ('', '-')

COLUMNS = [
    'Term Code', 'Term', 'Course', 'Course Title', 'Class No.', 'Section No.',
    'Instructor Last Name', 'Instructor First Name', 'Instructor Email',
    'High School', 'Grade Status', 'Grade Status Changed On',
    'Students', 'Graded', 'Not Graded',
]


def status_key(grade_status):
    """The report's key for a section's grade_status ('' and None are Not Started)."""
    return grade_status if grade_status in ('saved', 'submitted') else NOT_STARTED


def last_changed(history):
    """The latest timestamp in grade_status_changed_on ('%m/%d/%Y %I:%M:%S %p' keys)."""
    stamps = []
    for key in (history or {}):
        try:
            stamps.append(datetime.datetime.strptime(key, '%m/%d/%Y %I:%M:%S %p'))
        except (TypeError, ValueError):
            continue
    return max(stamps).strftime('%m/%d/%Y %I:%M %p') if stamps else ''


class class_grade_status(forms.Form):
    """Classes by grade status (Not Started / Draft / Submitted)."""

    campus = forms.ModelMultipleChoiceField(
        queryset=Campus.objects.none(), required=True, label='Campus',
    )

    term = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Term(s)',
        help_text='Select one or more terms to include'
    )

    grade_status = forms.MultipleChoiceField(
        choices=GRADE_STATUS_CHOICES,
        required=False,
        label='Grade Status',
        help_text='Leave blank to include every class'
    )

    highschools = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        label='High School(s)',
        help_text='Leave blank to include all high schools'
    )

    roles = []
    request = None

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Report'))

        self.fields['term'].queryset = Term.objects.all().order_by('-code')
        self.fields['highschools'].queryset = picker_queryset()
        apply_campus_field(self, getattr(self.request, 'user', None))

        if self.request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

    def get_result(self, data, user=None):
        statuses = [s for s in (data.get('grade_status') or []) if s in STATUS_LABELS]
        highschool_ids = [h for h in (data.get('highschools') or []) if h]

        sections = ClassSection.objects.select_related(
            'term', 'course', 'highschool', 'teacher__user'
        ).filter(
            term__id__in=data.get('term') or []
        )

        if statuses:
            q = Q(grade_status__in=[s for s in statuses if s != NOT_STARTED])
            if NOT_STARTED in statuses:
                q |= Q(grade_status='') | Q(grade_status__isnull=True)
            sections = sections.filter(q)

        if highschool_ids:
            sections = sections.filter(highschool__id__in=highschool_ids)

        sections = scope_report_by_campus(
            sections, user, data.get('campus'), campus_path='course__campus')

        return sections.order_by('term__code', 'course__name', 'class_number')

    def counts(self, section_ids):
        """{section_id: (students, graded)} over the grade-entry roster statuses."""
        registrations = StudentRegistration.objects.filter(class_section__id__in=section_ids)
        statuses = roster_statuses()
        if statuses:
            registrations = registrations.filter(status__in=statuses)
        rows = registrations.values('class_section').annotate(
            students=Count('id'),
            graded=Count('id', filter=~Q(grade__in=BLANK_GRADES) & Q(grade__isnull=False)),
        )
        return {row['class_section']: (row['students'], row['graded']) for row in rows}

    def rows(self, sections):
        sections = list(sections)
        counts = self.counts([s.id for s in sections])
        for section in sections:
            students, graded = counts.get(section.id, (0, 0))
            teacher_user = section.teacher.user if section.teacher_id else None
            yield [
                section.term.code,
                section.term.label,
                section.course.name,
                section.course.title,
                section.class_number,
                section.section_number,
                teacher_user.last_name if teacher_user else '',
                teacher_user.first_name if teacher_user else '',
                teacher_user.email if teacher_user else '',
                section.highschool.name if section.highschool_id else '',
                STATUS_LABELS[status_key(section.grade_status)],
                last_changed(section.grade_status_changed_on),
                students,
                graded,
                students - graded,
            ]

    def run(self, task, data):
        # `task` is the ReportScheduler; task.created_by is the requesting user.
        sections = self.get_result(data, user=getattr(task, 'created_by', None))

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')
        writer.writerow(COLUMNS)
        for row in self.rows(sections):
            writer.writerow(row)

        file_name = f"class_grade_status_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        now = datetime.datetime.now().strftime("%Y/%m")
        path = f"reports/{now}/{task.id}/{file_name}"
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        return media_storage.url(path)
