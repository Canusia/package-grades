"""Grading period models.

A term may collect grades more than once -- a midterm, a final, or any number
of checkpoints. `GradingPeriod` defines when each collection happens;
`SectionPeriodStatus` tracks whether a section has submitted for a period.

Where the marks themselves live depends on whether the period is the final one:

* The **final** period writes to `cis.StudentRegistration.grade`, the existing
  column, which stays authoritative for "the final grade" and is what the SIS
  export reads. Nothing is duplicated into `PeriodGrade`.
* **Interim** periods write `PeriodGrade` rows here.

That split is deliberate. Storing final grades in both places would create two
sources of truth to keep in sync and would need a backfill over every
historical registration; more importantly, an interim mark reaching
`StudentRegistration.grade` would be pushed to the SIS as a final grade. See
docs/superpowers/specs/2026-08-02-grades-grading-periods-design.md
"""
import uuid

from django.conf import settings
from django.db import models


class GradingPeriod(models.Model):
    """One grade collection within a term.

    Scoped to a term and nothing else. A section that needs a different
    schedule -- an 8-week class inside a 16-week term -- belongs to a subterm
    (`cis.Term.parent` / `sub_terms`), which carries its own periods. Sections
    get the periods of their own term only, never a parent term's.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    term = models.ForeignKey(
        'cis.Term',
        on_delete=models.CASCADE,
        related_name='grading_periods',
    )

    name = models.CharField(max_length=100)
    sequence = models.PositiveIntegerField(
        default=0,
        help_text='Order within the term.',
    )

    opens_on = models.DateField(
        help_text='Grades may be entered on and after this date.')
    due_on = models.DateField(
        help_text='Grades may be entered until this date.')

    is_final = models.BooleanField(
        default=False,
        help_text=(
            'The final grade collection. Writes to the registration grade '
            'that is exported to the SIS. At most one per term.'
        ),
    )

    reminder_frequency_days = models.PositiveIntegerField(
        default=0,
        help_text=(
            'How often to re-notify instructors who have not submitted. '
            '0 disables reminders for this period.'
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['term', 'sequence']
        constraints = [
            models.UniqueConstraint(
                fields=['term', 'name'],
                name='grades_gradingperiod_unique_name_per_term',
            ),
            # Enforced in the database rather than in a save() override: a
            # second final period would silently split the SIS-bound grade
            # between two collections.
            models.UniqueConstraint(
                fields=['term'],
                condition=models.Q(is_final=True),
                name='grades_gradingperiod_one_final_per_term',
            ),
        ]

    def __str__(self):
        return f'{self.term} - {self.name}'


class PeriodGrade(models.Model):
    """An interim mark.

    Final grades are NOT stored here -- they live on
    `cis.StudentRegistration.grade`. See the module docstring.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    period = models.ForeignKey(
        GradingPeriod,
        on_delete=models.CASCADE,
        related_name='marks',
    )
    registration = models.ForeignKey(
        'cis.StudentRegistration',
        on_delete=models.CASCADE,
        related_name='period_grades',
    )

    grade = models.CharField(max_length=30, blank=True)

    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='+',
    )
    entered_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['period', 'registration'],
                name='grades_periodgrade_unique_per_registration',
            ),
        ]

    def __str__(self):
        return f'{self.registration} - {self.period.name}: {self.grade}'


class SectionPeriodStatus(models.Model):
    """Whether a section has submitted grades for a period.

    `ClassSection.grade_status` is a single column and cannot hold per-period
    state. For the **final** period this model's status is mirrored onto that
    column, so everything already reading it -- the CE sections-list grade
    stats, the grade-submitted instructor email, and
    `StudentRegistration.submitted_grade` -- keeps working untouched.
    """

    STATUS_OPTIONS = (
        ('', 'N/A'),
        ('saved', 'Grades Saved Only'),
        ('submitted', 'Grades Successfully Submitted'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    period = models.ForeignKey(
        GradingPeriod,
        on_delete=models.CASCADE,
        related_name='section_statuses',
    )
    class_section = models.ForeignKey(
        'cis.ClassSection',
        on_delete=models.CASCADE,
        related_name='period_statuses',
    )

    status = models.CharField(
        max_length=30, choices=STATUS_OPTIONS, default='', blank=True)
    status_changed_on = models.JSONField(default=dict, blank=True)

    last_notified_on = models.DateField(
        blank=True,
        null=True,
        help_text='Drives reminder cadence; see reminder_frequency_days.',
    )

    class Meta:
        verbose_name_plural = 'Section period statuses'
        constraints = [
            models.UniqueConstraint(
                fields=['period', 'class_section'],
                name='grades_sectionperiodstatus_unique_per_section',
            ),
        ]

    def __str__(self):
        return f'{self.class_section} - {self.period.name}: {self.status or "N/A"}'

    @property
    def submitted(self):
        return self.status == 'submitted'
