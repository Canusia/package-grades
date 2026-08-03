"""CE-facing form for configuring a term's grading periods.

Intra-package imports are relative: in editable mode this package is
``grades.grades``, so ``grades.models`` would resolve to the repo root.
"""
from django import forms
from django.db import IntegrityError, transaction

from ..models import GradingPeriod


class GradingPeriodForm(forms.ModelForm):
    """Add/edit one grading period on a term.

    The term is supplied by the view, never by the submitted data -- a period
    can only ever be created or moved within the term whose detail page it was
    opened from.

    Two of the three rules this enforces are also database constraints
    (``grades_gradingperiod_unique_name_per_term`` and
    ``grades_gradingperiod_one_final_per_term``). They are checked here so the
    user gets a readable message, and re-checked around ``save()`` so a race
    between two staff members surfaces as a form error rather than a 500.
    Django's own constraint validation cannot do this for us: ``term`` is not a
    form field, and ``Model.validate_constraints()`` skips every constraint
    that references an excluded field.
    """

    class Meta:
        model = GradingPeriod
        fields = [
            'name',
            'sequence',
            'opens_on',
            'due_on',
            'is_final',
            'reminder_frequency_days',
        ]
        labels = {
            'name': 'Name',
            'sequence': 'Sequence',
            'opens_on': 'Opens On',
            'due_on': 'Due On',
            'is_final': 'Final Grade Collection',
            'reminder_frequency_days': 'Reminder Frequency (days)',
        }
        widgets = {
            'opens_on': forms.DateInput(
                format='%Y-%m-%d', attrs={'type': 'date'}),
            'due_on': forms.DateInput(
                format='%Y-%m-%d', attrs={'type': 'date'}),
        }

    def __init__(self, term, *args, **kwargs):
        self.term = term
        super().__init__(*args, **kwargs)
        self.instance.term = term

    def _siblings(self):
        """Other periods in this term (excludes the record being edited)."""
        qs = GradingPeriod.objects.filter(term=self.term)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        return qs

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if name and self._siblings().filter(name__iexact=name).exists():
            raise forms.ValidationError(
                f'This term already has a grading period named "{name}". '
                'Grading period names must be unique within a term.'
            )
        return name

    def clean(self):
        cleaned_data = super().clean()

        opens_on = cleaned_data.get('opens_on')
        due_on = cleaned_data.get('due_on')
        if opens_on and due_on and due_on < opens_on:
            self.add_error(
                'due_on',
                'The due date cannot be before the date the period opens.'
            )

        if cleaned_data.get('is_final'):
            existing_final = self._siblings().filter(is_final=True).first()
            if existing_final is not None:
                self.add_error(
                    'is_final',
                    f'"{existing_final.name}" is already the final grade '
                    'collection for this term. A term can have only one '
                    'final period -- clear it there first.'
                )

        return cleaned_data

    def _report_integrity_error(self, exc):
        """Turn a constraint violation into a field error.

        Reached only when another request created a conflicting period between
        this form's validation and its save.
        """
        message = str(exc)
        if 'grades_gradingperiod_one_final_per_term' in message:
            self.add_error(
                'is_final',
                'This term already has a final grade collection. A term can '
                'have only one final period.'
            )
        elif 'grades_gradingperiod_unique_name_per_term' in message:
            self.add_error(
                'name',
                'This term already has a grading period with that name.'
            )
        else:
            self.add_error(
                None,
                'Unable to save this grading period. Please review the '
                'values and try again.'
            )

    def save(self, commit=True):
        """Save, converting a constraint violation into a form error.

        Returns ``None`` (with ``self.errors`` populated) instead of raising,
        so the view can render the same error response it uses for ordinary
        validation failures.
        """
        record = super().save(commit=False)
        record.term = self.term

        if not commit:
            return record

        try:
            with transaction.atomic():
                record.save()
        except IntegrityError as exc:
            self._report_integrity_error(exc)
            return None

        return record
