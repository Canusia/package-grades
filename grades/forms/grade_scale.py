"""CE forms for grade scales: the scale itself and its letters."""
from django import forms
from django.core.validators import MaxLengthValidator
from django.forms import BaseInlineFormSet, inlineformset_factory

from ..models import GradeScale, GradeScaleEntry


class GradeScaleForm(forms.ModelForm):
    class Meta:
        model = GradeScale
        fields = ['name', 'description', 'is_default', 'is_active']
        labels = {'is_default': 'Default scale', 'is_active': 'Active'}
        help_texts = {
            'is_default': ('Grading periods with no scale of their own use the default. '
                           'Making this the default replaces the current one.'),
        }
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, campus=None, **kwargs):
        self.campus = campus
        super().__init__(*args, **kwargs)
        if self.instance._state.adding:
            self.instance.campus = campus

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        clash = GradeScale.objects.filter(campus=self.instance.campus, name__iexact=name)
        if not self.instance._state.adding:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(f'There is already a grade scale named "{name}".')
        return name

    def clean(self):
        cleaned = super().clean()
        if (not self.instance._state.adding and self.instance.is_default
                and not cleaned.get('is_default')):
            self.add_error('is_default', 'Make another scale the default instead; '
                                         'there must always be one.')
        if cleaned.get('is_default') and cleaned.get('is_active') is False:
            self.add_error('is_active', 'The default scale must be active.')
        return cleaned


class GradeScaleEntryForm(forms.ModelForm):
    class Meta:
        model = GradeScaleEntry
        fields = ['grade', 'points', 'asks_last_attendance', 'sequence']
        labels = {'asks_last_attendance': 'Asks for last date of attendance'}
        widgets = {
            'sequence': forms.HiddenInput(attrs={'class': 'entry-sequence'}),
            'grade': forms.TextInput(attrs={'class': 'form-control form-control-sm',
                                            'placeholder': 'e.g. A'}),
            'points': forms.NumberInput(attrs={'class': 'form-control form-control-sm',
                                               'step': '0.01', 'placeholder': 'blank = no GPA'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A blank grade removes the row (see the formset), so an added row
        # left empty is ignored rather than an error.
        self.fields['grade'].required = False
        # A final grade is stored on cis's StudentRegistration.grade (10 chars).
        self.fields['grade'].max_length = 10
        self.fields['grade'].widget.attrs['maxlength'] = 10
        self.fields['grade'].validators.append(MaxLengthValidator(10))

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('grade') and cleaned.get('points') is not None and self.instance._state.adding:
            self.add_error('grade', 'Enter a grade, or clear the points to drop this row.')
        return cleaned

    def clean_grade(self):
        grade = (self.cleaned_data.get('grade') or '').strip()
        if grade == '-':
            raise forms.ValidationError('"-" means no grade and cannot be on a scale.')
        if ',' in grade:
            raise forms.ValidationError('A grade cannot contain a comma.')
        return grade


class BaseGradeScaleEntryFormSet(BaseInlineFormSet):
    """Letters of one scale. Refuses duplicates, an empty scale, and dropping
    or renaming a letter that marks already hold (`in_use`, from the view)."""

    def __init__(self, *args, in_use=None, **kwargs):
        self.in_use = in_use or {}
        super().__init__(*args, **kwargs)

    def _should_delete_form(self, form):
        if super()._should_delete_form(form):
            return True
        if form.errors:      # e.g. points with no grade: report it, don't drop the row
            return False
        data = getattr(form, 'cleaned_data', None) or {}
        return not data.get('grade')

    def kept_letters(self):
        return [f.cleaned_data['grade'] for f in self.forms
                if getattr(f, 'cleaned_data', None) and f.cleaned_data.get('grade')
                and not f.cleaned_data.get('DELETE')]

    def clean(self):
        if any(self.errors):
            return
        kept = self.kept_letters()
        if not kept:
            raise forms.ValidationError('A grade scale needs at least one grade.')
        # Before super().clean(): its unique check says only "correct the
        # duplicate data".
        dupes = sorted({g for g in kept if kept.count(g) > 1})
        if dupes:
            raise forms.ValidationError(f'Each grade can appear once: {", ".join(dupes)}.')
        super().clean()
        missing = {g: n for g, n in self.in_use.items() if g not in kept}
        if missing:
            listed = ', '.join(f'{g} ({n})' for g, n in sorted(missing.items()))
            raise forms.ValidationError(
                f'These grades are already entered for students and cannot be removed or '
                f'renamed: {listed}. Add a new grade instead.')


GradeScaleEntryFormSet = inlineformset_factory(
    GradeScale, GradeScaleEntry, form=GradeScaleEntryForm,
    formset=BaseGradeScaleEntryFormSet, extra=0, can_delete=True)
