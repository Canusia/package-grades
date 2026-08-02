"""
Grade-related forms for class sections.
"""
from django import forms
from django.forms.formsets import BaseFormSet

from cis.models.section import StudentRegistration
from ..settings.class_section_grades import class_section_grades


class ClassSectionGradeForm(forms.Form):
    student = forms.CharField(
        label='',
        widget=forms.HiddenInput
    )

    student_id = forms.CharField(
       widget=forms.HiddenInput
    )
    grade = forms.ChoiceField(
        required=True,
        label='',
        choices=()
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        grade_settings = class_section_grades.from_db()

        grades = grade_settings.get('grades', '').split(',')
        grade_choices = [('', '')] + [
            (grade, grade) for grade in grades
        ]
        self.fields['grade'].choices = grade_choices


class ClassSectionGradeFormSet(BaseFormSet):
    """Grade entry for one class section.

    The formset is bound to a single ClassSection and will only ever write
    grades to registrations belonging to that section. The view already scopes
    the section to the requesting instructor (PT-32); this closes the matching
    hole one layer down, where `student_id` arrives from POST and was
    previously used as a bare primary key.
    """

    def __init__(self, *args, class_section=None, **kwargs):
        self.class_section = class_section
        super().__init__(*args, **kwargs)

    def _allowed_registration_ids(self):
        """Registration ids the view offered for grading, as strings.

        Derived from `initial`, which the view builds from the section's own
        roster -- never from submitted data.
        """
        return {
            str(row.get('student_id'))
            for row in (self.initial or [])
            if row.get('student_id') is not None
        }

    def save(self):
        allowed_ids = self._allowed_registration_ids()

        for form in self.forms:
            data = getattr(form, 'cleaned_data', None)
            if not data:
                continue

            grade = data.get('grade')
            student_id = data.get('student_id')

            # Reject anything the view did not put on this page. A forged or
            # malformed id (including a non-UUID, which would otherwise reach
            # the database as an invalid pk and 500) simply fails to match.
            if str(student_id) not in allowed_ids:
                continue

            qs = StudentRegistration.objects.filter(pk=student_id)
            if self.class_section is not None:
                qs = qs.filter(class_section=self.class_section)

            qs.update(grade=grade)
