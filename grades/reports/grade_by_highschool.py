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
from cis.models.section import StudentRegistration
from ..settings.class_section_grades import class_section_grades


class grade_by_highschool(forms.Form):
    """Grade Distribution by High School Report for Institutional Research."""

    term = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Term(s)',
        help_text='Select one or more terms to include'
    )

    highschools = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        label='High School(s)',
        help_text='Leave blank to include all high schools'
    )

    registration_status = forms.MultipleChoiceField(
        choices=StudentRegistration.STATUS_OPTIONS,
        label='Registration Status(es)',
        help_text='Which registration statuses to include in analysis'
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
        self.fields['highschools'].queryset = HighSchool.objects.filter(
            status__iexact='active'
        ).order_by('name')

        if self.request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

    def run(self, task, data):
        term_ids = data.get('term')
        highschool_ids = data.get('highschools')
        statuses = data.get('registration_status')

        # Get grade settings
        grade_settings = class_section_grades.from_db()
        grade_list = [g.strip() for g in grade_settings.get('grades', '').split(',') if g.strip()]
        gpa_points = grade_settings.get('gpa_points', {})

        # Build base queryset
        registrations = StudentRegistration.objects.select_related(
            'class_section__highschool__district'
        ).filter(
            class_section__term__id__in=term_ids,
            status__in=statuses
        )

        if highschool_ids:
            registrations = registrations.filter(
                class_section__highschool__id__in=highschool_ids
            )

        # Aggregate by high school with grade counts
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
            'class_section__highschool__id',
            'class_section__highschool__name',
            'class_section__highschool__district__name'
        ).annotate(**aggregations).order_by('class_section__highschool__name')

        # Build CSV
        file_name = f"grade_distribution_by_highschool_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        # Header row
        header = ['High School', 'District', 'Total Enrolled']
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
            row = [
                row_data['class_section__highschool__name'] or '',
                row_data['class_section__highschool__district__name'] or '',
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
