"""Last date of attendance kept with a final grade.

A final grade whose scale entry has `asks_last_attendance` needs the date; it
is stored on FinalGradeAttendance and sent to the SIS with the grade. Shared by
the grade grid (instructor, HS admin, CE) and the host's CE registration edit
form, so the rules live once here.
"""
import datetime

from django import forms

from .scales import final_scale_for_registration


class LastAttendanceInput(forms.DateInput):
    """A date input that shows itself only while the row's grade asks for it.

    `letters` are the grades that ask. The inline script looks for the
    `grade` select in the same row (grade grid) or the same form (CE
    registration edit) and shows, hides and clears the input as it changes.
    Inline because crispy does not render `form.media`.
    """
    template_name = 'grades/widgets/last_attendance_input.html'
    input_type = 'date'

    def __init__(self, letters=(), help_text='', attrs=None):
        attrs = {'class': 'form-control form-control-sm last-attendance-input', **(attrs or {})}
        super().__init__(attrs=attrs, format='%Y-%m-%d')
        self.letters = list(letters)
        self.help_text = help_text

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['widget']['letters'] = ','.join(self.letters)
        context['widget']['help_text'] = self.help_text
        return context


def last_attendance_field(letters, required=False, help_text='', earliest=None):
    """The date field. Its label and help text live inside the widget, so
    they hide with it; the field's own label is blank so a crispy form does
    not draw a second one outside. The picker is limited to `earliest` (the
    term's start, when known) through today."""
    from django.utils import timezone
    attrs = {'max': timezone.localdate().isoformat()}
    if earliest:
        attrs['min'] = earliest.isoformat()
    return forms.DateField(
        required=required, label='',
        widget=LastAttendanceInput(letters=letters, help_text=help_text, attrs=attrs),
        input_formats=['%Y-%m-%d', '%m/%d/%Y'])


def start_for_term(term):
    """The earliest allowed last date of attendance for `term`.

    cis's Term has no start date; its academic year's high school start date
    is the closest one, so that is the bound (None when unset).
    """
    ay = getattr(term, 'academic_year', None)
    return getattr(ay, 'hs_start_date', None)


def term_start(registration):
    return start_for_term(getattr(getattr(registration, 'class_section', None), 'term', None))


def date_problem(when, start=None, today=None):
    """Why `when` can't be a last date of attendance, or None. `start` is the
    term's start date (see term_start), when known."""
    if when is None:
        return None
    if today is None:
        from django.utils import timezone
        today = timezone.localdate()   # the site's day, not the server's UTC one
    if when > today:
        return 'The last date of attendance cannot be in the future.'
    if start and when < start:
        return ('The last date of attendance cannot be before the school year starts '
                f'({start:%m/%d/%Y}).')
    return None


def needs_date(scale, grade):
    return bool(scale) and scale.asks_last_attendance(grade)


def effective_date(registration_id, grade, scale):
    """The date that goes with `grade`: the stored one while the grade asks
    for it, else None. A row left over from an earlier grade, or from a scale
    that no longer asks, is ignored, so it can neither be sent nor flag a
    re-send."""
    if not needs_date(scale, grade):
        return None
    return stored([registration_id]).get(registration_id)


def stored(registration_ids):
    """{registration id: date} for the given registrations."""
    from ..models import FinalGradeAttendance
    return dict(FinalGradeAttendance.objects.filter(registration_id__in=registration_ids)
                .values_list('registration_id', 'last_attendance_on'))


def stored_for(registration):
    from ..models import FinalGradeAttendance
    row = FinalGradeAttendance.objects.filter(registration=registration).first()
    return row.last_attendance_on if row else None


def set_last_attendance(registration, when, user=None):
    """Store `when` for `registration`, or delete it when `when` is None.

    Returns (old, new) so callers can note a change. Unchanged writes nothing,
    so no history row and no mirroring flag.
    """
    from ..models import FinalGradeAttendance
    row = FinalGradeAttendance.objects.filter(registration=registration).first()
    old = row.last_attendance_on if row else None
    if when is None:
        if row is not None:
            row.delete()
        return old, None
    if row is None:
        FinalGradeAttendance.objects.create(
            registration=registration, last_attendance_on=when, entered_by=user)
    elif row.last_attendance_on != when:
        row.last_attendance_on = when
        row.entered_by = user
        row.save()
    return old, when


def save_for_grade(registration, grade, when, user=None, scale=None):
    """Keep the date only while `grade` asks for it; otherwise clear it."""
    scale = scale or final_scale_for_registration(registration)
    return set_last_attendance(registration, when if needs_date(scale, grade) else None, user)
