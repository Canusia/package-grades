import io
import csv
import datetime

from django import forms
from django.db.models import Count, Case, When, IntegerField
from django.urls import reverse_lazy
from django.core.files.base import ContentFile

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.models.term import Term
from cis.models.highschool import HighSchool
from cis.models.course import Course, Campus
from cis.models.student import Student
from cis.models.section import StudentRegistration
from cis.campus_gate import get_accessible_campuses, scope_report_by_campus
from ..settings.class_section_grades import class_section_grades


class grade_by_demographics(forms.Form):
    """Grade Distribution by Demographics Report for Institutional Research."""

    campus = forms.ModelMultipleChoiceField(
        queryset=Campus.objects.none(), required=True, label='Campus',
    )

    DIMENSION_CHOICES = [
        ('gender', 'Gender'),
        ('ethnicity', 'Race/Ethnicity'),
        ('hispanic', 'Hispanic/Latino'),
        ('first_gen_student', 'First-Generation Student'),
        ('grade_level', 'Grade Level (FR, SO, JR, SR)'),
        ('parent1_education_level', 'Parent 1 Education Level'),
    ]

    term = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Term(s)',
        help_text='Select one or more terms to include'
    )

    demographic_dimension = forms.ChoiceField(
        choices=DIMENSION_CHOICES,
        label='Group By',
        help_text='Select which demographic dimension to analyze'
    )

    highschools = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        label='High School(s)',
        help_text='Leave blank to include all high schools'
    )

    courses = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        label='Course(s)',
        help_text='Leave blank to include all courses'
    )

    registration_status = forms.MultipleChoiceField(
        choices=StudentRegistration.STATUS_OPTIONS,
        label='Registration Status(es)',
        help_text='Which registration statuses to include in analysis'
    )

    roles = []
    request = None

    # Mapping of dimension field to display labels
    DIMENSION_LABELS = {
        'gender': {
            'm': 'Male',
            'f': 'Female',
            'u': 'Undisclosed',
            '': 'Not Specified'
        },
        'ethnicity': {
            '1': 'American Indian/Alaska Native',
            '2': 'Asian',
            '3': 'Black/African American',
            '4': 'Native Hawaiian/Other Pacific Islander',
            '5': 'White',
            '': 'Not Specified'
        },
        'hispanic': {
            'True': 'Hispanic/Latino',
            'False': 'Not Hispanic/Latino',
            '': 'Not Specified'
        },
        'first_gen_student': {
            'Y': 'First-Generation',
            'N': 'Not First-Generation',
            '': 'Not Specified'
        },
        'grade_level': {
            'FR': 'Freshman',
            'SO': 'Sophomore',
            'JR': 'Junior',
            'SR': 'Senior',
            '': 'Not Specified'
        },
        'parent1_education_level': {
            '1': 'Unknown',
            '2': 'High school/GED',
            '3': 'Some college, no degree',
            '4': 'Associate degree',
            '5': "Bachelor's degree",
            '6': 'Some graduate school',
            '7': 'Graduate Degree or higher',
            '8': 'Unknown / Prefer not to answer',
            '': 'Not Specified'
        }
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Report'))

        self.fields['term'].queryset = Term.objects.all().order_by('-code')
        self.fields['highschools'].queryset = HighSchool.objects.filter(
            status__iexact='active'
        ).order_by('name')
        self.fields['courses'].queryset = Course.objects.all().order_by('name')

        if self.request:
            # Populate the campus selector with only the campuses the
            # requesting user may process (superusers see all).
            self.fields['campus'].queryset = get_accessible_campuses(
                self.request.user)
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

    def _get_dimension_field(self, dimension):
        """Return the appropriate ORM field path for the dimension."""
        dimension_fields = {
            'gender': 'student__gender',
            'ethnicity': 'student__ethnicity',
            'hispanic': 'student__hispanic',
            'first_gen_student': 'student__first_gen_student',
            'grade_level': 'student__grade_level',
            'parent1_education_level': 'student__parent1_education_level',
        }
        return dimension_fields.get(dimension, 'student__gender')

    def _get_dimension_label(self, dimension, value):
        """Convert a dimension value to a human-readable label."""
        labels = self.DIMENSION_LABELS.get(dimension, {})

        # Handle multiselect ethnicity field (comma-separated values)
        if dimension == 'ethnicity' and value:
            ethnicities = []
            for v in str(value).split(','):
                v = v.strip()
                if v in labels:
                    ethnicities.append(labels[v])
            return ', '.join(ethnicities) if ethnicities else labels.get(str(value), str(value))

        return labels.get(str(value), str(value) if value else 'Not Specified')

    def get_result(self, data, user=None):
        """Return the scoped, pre-aggregation StudentRegistration queryset."""
        term_ids = data.get('term')
        highschool_ids = data.get('highschools')
        course_ids = data.get('courses')
        statuses = data.get('registration_status')

        # Build base queryset
        registrations = StudentRegistration.objects.select_related(
            'student'
        ).filter(
            class_section__term__id__in=term_ids,
            status__in=statuses
        )

        if highschool_ids:
            registrations = registrations.filter(
                class_section__highschool__id__in=highschool_ids
            )

        if course_ids:
            registrations = registrations.filter(
                class_section__course__id__in=course_ids
            )

        # Campus gate: filter to the selected campus(es), constrained to the
        # ce requester's processable campuses (superusers/non-ce as-is).
        registrations = scope_report_by_campus(
            registrations, user, data.get('campus'),
            campus_path='class_section__course__campus')

        return registrations

    def run(self, task, data):
        dimension = data.get('demographic_dimension')[0] if isinstance(data.get('demographic_dimension'), list) else data.get('demographic_dimension')

        # Get grade settings
        grade_settings = class_section_grades.from_db()
        grade_list = [g.strip() for g in grade_settings.get('grades', '').split(',') if g.strip()]
        gpa_points = grade_settings.get('gpa_points', {})

        # Get the ORM field for the selected dimension
        dimension_field = self._get_dimension_field(dimension)

        # `task` is the ReportScheduler; task.created_by is the requesting user
        # (there is no request in the background task, so gate by the scheduler).
        registrations = self.get_result(data, user=getattr(task, 'created_by', None))

        # Aggregate by dimension with grade counts
        aggregations = {
            'total': Count('id'),
        }

        # Add count for each configured grade
        for grade in grade_list:
            field_name = f'count_{grade.replace("+", "plus").replace("-", "minus").lower()}'
            aggregations[field_name] = Count(
                Case(When(grade=grade, then=1), output_field=IntegerField())
            )

        # Also count W for withdrawals if not in grade list
        if 'W' not in grade_list:
            aggregations['count_w'] = Count(
                Case(When(grade='W', then=1), output_field=IntegerField())
            )

        grade_dist = registrations.values(
            dimension_field
        ).annotate(**aggregations).order_by(dimension_field)

        # Build CSV
        dimension_display = dict(self.DIMENSION_CHOICES).get(dimension, dimension)
        file_name = f"grade_distribution_by_{dimension}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        # Header row
        header = [dimension_display, 'Total Enrolled']
        for grade in grade_list:
            header.append(grade)
        if 'W' not in grade_list:
            header.append('W')
        for grade in grade_list:
            header.append(f'{grade}%')
        if 'W' not in grade_list:
            header.append('W%')
        header.extend(['Success Rate', 'DFW Rate', 'Avg GPA'])

        writer.writerow(header)

        # Data rows
        for row_data in grade_dist:
            total = row_data['total'] or 0
            dimension_value = row_data.get(dimension_field, '')

            row = [
                self._get_dimension_label(dimension, dimension_value),
                total,
            ]

            # Grade counts
            grade_counts = {}
            for grade in grade_list:
                field_name = f'count_{grade.replace("+", "plus").replace("-", "minus").lower()}'
                count = row_data.get(field_name, 0) or 0
                grade_counts[grade] = count
                row.append(count)

            # W count
            if 'W' not in grade_list:
                w_count = row_data.get('count_w', 0) or 0
                grade_counts['W'] = w_count
                row.append(w_count)

            # Grade percentages
            for grade in grade_list:
                pct = (grade_counts[grade] / total * 100) if total > 0 else 0
                row.append(f'{pct:.1f}')
            if 'W' not in grade_list:
                pct = (grade_counts.get('W', 0) / total * 100) if total > 0 else 0
                row.append(f'{pct:.1f}')

            # Success rate (A, B, C grades or variants)
            success_grades = [g for g in grade_counts.keys() if g.startswith(('A', 'B', 'C')) and g != 'W']
            success_count = sum(grade_counts.get(g, 0) for g in success_grades)
            success_rate = (success_count / total * 100) if total > 0 else 0
            row.append(f'{success_rate:.1f}')

            # DFW rate (D, F, W grades)
            dfw_grades = [g for g in grade_counts.keys() if g.startswith(('D', 'F')) or g == 'W']
            dfw_count = sum(grade_counts.get(g, 0) for g in dfw_grades)
            dfw_rate = (dfw_count / total * 100) if total > 0 else 0
            row.append(f'{dfw_rate:.1f}')

            # Average GPA
            total_points = 0
            graded_count = 0
            for grade, count in grade_counts.items():
                if grade in gpa_points and count > 0:
                    total_points += gpa_points[grade] * count
                    graded_count += count
            avg_gpa = (total_points / graded_count) if graded_count > 0 else 0
            row.append(f'{avg_gpa:.2f}')

            writer.writerow(row)

        # Save to storage
        now = datetime.datetime.now().strftime("%Y/%m")
        path = f"reports/{now}/{task.id}/{file_name}"
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)

        return path

    def run_report(self):
        ...
