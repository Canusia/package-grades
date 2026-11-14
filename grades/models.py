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
from simple_history.models import HistoricalRecords


class GradeScale(models.Model):
    """A named set of grades a grading period offers.

    Each campus has at most one default scale; a scale with no campus serves
    the whole deployment (single-campus sites, or a shared fallback). A period
    with no scale of its own uses the default -- see services/scales.py, the
    one place that resolves which scale applies.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')
    campus = models.ForeignKey(
        'cis.Campus', on_delete=models.PROTECT, null=True, blank=True,
        related_name='grade_scales')
    is_default = models.BooleanField(
        default=False,
        help_text='Periods with no scale of their own use the default scale.')
    is_active = models.BooleanField(
        default=True,
        help_text='Inactive scales cannot be picked for a grading period.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['campus', 'name'], condition=models.Q(campus__isnull=False),
                name='grades_gradescale_unique_name_per_campus'),
            models.UniqueConstraint(
                fields=['name'], condition=models.Q(campus__isnull=True),
                name='grades_gradescale_unique_name_global'),
            models.UniqueConstraint(
                fields=['campus'],
                condition=models.Q(is_default=True, campus__isnull=False),
                name='grades_gradescale_one_default_per_campus'),
            models.UniqueConstraint(
                fields=['is_default'],
                condition=models.Q(is_default=True, campus__isnull=True),
                name='grades_gradescale_one_global_default'),
        ]

    def __str__(self):
        return self.name


class GradeScaleEntry(models.Model):
    """One grade on a scale."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scale = models.ForeignKey(GradeScale, on_delete=models.CASCADE, related_name='entries')
    grade = models.CharField(max_length=30)
    points = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True,
        help_text='GPA points. Blank means the grade does not count toward GPA.')
    sequence = models.PositiveIntegerField(default=0)
    asks_last_attendance = models.BooleanField(
        default=False,
        help_text=('As a final grade, this grade needs a last date of attendance, '
                   'which is sent to the SIS with it.'))
    history = HistoricalRecords()

    class Meta:
        ordering = ['scale', 'sequence', 'grade']
        constraints = [
            models.UniqueConstraint(
                fields=['scale', 'grade'], name='grades_gradescaleentry_unique_grade'),
        ]

    def __str__(self):
        return self.grade


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

    remind_days_before_due = models.PositiveIntegerField(
        default=0,
        help_text=(
            'Send one extra reminder this many days before the due date. '
            '0 turns it off.'
        ),
    )

    grade_scale = models.ForeignKey(
        GradeScale, on_delete=models.PROTECT, null=True, blank=True,
        related_name='periods',
        help_text='Blank uses the default grade scale.')

    visible_to_students = models.BooleanField(
        default=False,
        help_text=(
            "Students see this period's grades once their class has "
            'submitted them.'
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

    def scale(self):
        """The scale this period offers: its own, or the default (services/scales.py)."""
        from .services.scales import scale_for_period
        return scale_for_period(self)

    @classmethod
    def overlapping(cls, term, opens_on, due_on, exclude_pk=None):
        """Periods on ``term`` whose [opens_on, due_on] range touches this one.

        Inclusive at both ends: a period due 10/30 and one opening 10/30
        overlap (both would be open that day).
        """
        qs = cls.objects.filter(term=term, opens_on__lte=due_on, due_on__gte=opens_on)
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        return qs


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
    # Every change to an interim mark, who made it and when (final grades
    # get theirs from StudentRegistration's own history).
    history = HistoricalRecords()

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


class GradeSISSync(models.Model):
    """SIS push state for one registration's final grade.

    No row means the grade has never been sent. `sent_grade` is the value the
    SIS last accepted; the post_save receiver compares the live grade against
    it to flag needs_mirroring.
    """
    QUEUED = 'queued'
    SENT = 'sent'
    FAILED = 'failed'
    NEEDS_MIRRORING = 'needs_mirroring'
    STATUS_CHOICES = [
        (QUEUED, 'Queued'),
        (SENT, 'Sent'),
        (FAILED, 'Failed'),
        (NEEDS_MIRRORING, 'Needs Mirroring'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    registration = models.OneToOneField(
        'cis.StudentRegistration', on_delete=models.CASCADE,
        related_name='grade_sis_sync')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, db_index=True)
    sent_grade = models.CharField(max_length=30, blank=True, default='')
    sis_record_id = models.UUIDField(blank=True, null=True)
    last_sent_at = models.DateTimeField(blank=True, null=True)
    last_sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        blank=True, null=True, related_name='+')
    last_attempt_at = models.DateTimeField(blank=True, null=True, db_index=True)
    last_attempt_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        blank=True, null=True, related_name='+')
    last_error = models.TextField(blank=True, default='')
    grade_changed_at = models.DateTimeField(blank=True, null=True)
    # The last date of attendance the SIS last accepted with the grade, if any.
    sent_last_attendance = models.DateField(blank=True, null=True)

    def __str__(self):
        return f'{self.registration_id}: {self.status}'


class GradeSISSyncAttempt(models.Model):
    """Append-only history of pushes: who sent which grade, when, and the outcome."""
    sync = models.ForeignKey(
        GradeSISSync, on_delete=models.CASCADE, related_name='attempts')
    attempted_at = models.DateTimeField()
    attempted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        blank=True, null=True, related_name='+')
    grade = models.CharField(max_length=30, blank=True, default='')
    success = models.BooleanField()
    error = models.TextField(blank=True, default='')
    log_url = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        ordering = ['-attempted_at']


class FinalGradeAttendance(models.Model):
    """A registration's last date of attendance, kept with its final grade.

    Asked for when the final grade's scale entry has `asks_last_attendance`,
    and sent to the SIS with the grade. Lives here, not on cis's
    StudentRegistration, so cis needs no change.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    registration = models.OneToOneField(
        'cis.StudentRegistration', on_delete=models.CASCADE,
        related_name='final_grade_attendance')
    last_attendance_on = models.DateField()
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        blank=True, null=True, related_name='+')
    entered_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    def __str__(self):
        return f'{self.registration_id}: {self.last_attendance_on}'
