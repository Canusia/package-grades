"""
Grade-related forms for class sections.
"""
from django import forms
from django.forms.formsets import BaseFormSet

from cis.models.section import StudentRegistration
from ..services import last_attendance
from ..services.periods import save_mark
from ..services.scales import scale_for_period


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

    # Submitting needs the date for a grade that asks for it; a draft or an
    # autosave does not (handle_grade_post clears this for those).
    require_last_attendance = True

    def __init__(self, *args, scale=None, final=False, term_start=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.final = final
        self.term_start = term_start
        # The period's grade scale (services/scales.py); the formset resolves
        # it once and hands it to every row.
        scale = scale if scale is not None else scale_for_period(None)
        letters = scale.letters()
        # A saved mark no longer on the scale stays selectable, so re-saving
        # the page never blanks it.
        current = (self.initial.get('grade') or '').strip()
        if current and current not in letters:
            letters = letters + [current]
        self.fields['grade'].choices = [('', '')] + [(g, g) for g in letters]
        self.scale = scale
        # Only a final grade goes to the SIS, so only it carries the date.
        if final and scale.last_attendance_letters():
            self.fields['last_attendance'] = last_attendance.last_attendance_field(
                scale.last_attendance_letters())

    def clean(self):
        cleaned = super().clean()
        if 'last_attendance' not in self.fields:
            return cleaned
        grade = cleaned.get('grade')
        when = cleaned.get('last_attendance')
        if not last_attendance.needs_date(self.scale, grade):
            cleaned['last_attendance'] = None
            return cleaned
        if when is None:
            if self.require_last_attendance:
                self.add_error('last_attendance',
                               f'Enter the last date of attendance for grade {grade}.')
            return cleaned
        problem = last_attendance.date_problem(when, self.term_start)
        if problem:
            self.add_error('last_attendance', problem)
        return cleaned


class ClassSectionGradeFormSet(BaseFormSet):
    """Grade entry for one class section.

    The formset is bound to a single ClassSection and will only ever write
    grades to registrations belonging to that section. The view already scopes
    the section to the requesting instructor (PT-32); this closes the matching
    hole one layer down, where `student_id` arrives from POST and was
    previously used as a bare primary key.
    """

    def __init__(self, *args, class_section=None, period=None, user=None,
                 **kwargs):
        self.class_section = class_section
        self.period = period
        self.user = user
        self.scale = scale_for_period(period)
        # period None (no grading periods) writes the registration grade,
        # i.e. the final grade.
        self.final = period is None or period.is_final
        self.term_start = last_attendance.start_for_term(getattr(class_section, 'term', None))
        super().__init__(*args, **kwargs)
        if self.final and self.scale.last_attendance_letters() and self.initial:
            dates = last_attendance.stored(
                [row.get('student_id') for row in self.initial if row.get('student_id')])
            for row in self.initial:
                row.setdefault('last_attendance', dates.get(row.get('student_id')))

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs.update(scale=self.scale, final=self.final, term_start=self.term_start)
        return kwargs

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

            registration = qs.first()
            if registration is None:
                continue

            # Where the mark lands depends on whether this period is the final
            # one; services.periods owns that rule so it cannot be duplicated
            # and drift. period=None means no grading periods are configured,
            # which routes to the registration grade -- today's behaviour.
            save_mark(self.period, registration, grade, user=self.user)
            if self.final:
                # Kept only while the grade asks for it; any other grade clears it.
                last_attendance.save_for_grade(
                    registration, grade, data.get('last_attendance'), user=self.user,
                    scale=self.scale)
