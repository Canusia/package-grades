"""Which grade scale applies, and what it offers.

The one place that resolves a scale. A grading period uses its own
`grade_scale`, else the default scale for its term's campus, else the
deployment-wide default (a scale with no campus). Until a site has any scale
record -- a fresh install, or one whose grades setting was never saved -- the
grades setting's own list is used, exactly as before scales were records.

Callers get a `Scale`: the letters in order, their GPA points and which ones
ask for a last date of attendance, whatever the source.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional

from ..compat import has_module


@dataclass(frozen=True)
class ScaleEntry:
    grade: str
    points: Optional[Decimal] = None
    asks_last_attendance: bool = False


@dataclass(frozen=True)
class Scale:
    """A resolved scale. `record` is the GradeScale row, or None for the
    grades-setting fallback."""
    name: str
    entries: tuple = ()
    record: object = field(default=None, compare=False)

    @property
    def id(self):
        return self.record.pk if self.record is not None else None

    def letters(self):
        return [e.grade for e in self.entries]

    def points_map(self):
        """{grade: float points} for grades that count toward GPA."""
        return {e.grade: float(e.points) for e in self.entries if e.points is not None}

    def last_attendance_letters(self):
        return [e.grade for e in self.entries if e.asks_last_attendance]

    def asks_last_attendance(self, grade):
        return (grade or '').strip() in self.last_attendance_letters()


def _campus_of_term(term):
    ay = getattr(term, 'academic_year', None)
    return getattr(ay, 'campus', None) if ay is not None else None


def current_campus():
    """The request's campus on a multi-campus host, else None."""
    if not has_module('cis.campus_context'):
        return None
    from cis.campus_context import current_campus_or_none, is_multi_campus
    return current_campus_or_none() if is_multi_campus() else None


def _from_record(record):
    entries = tuple(
        ScaleEntry(e.grade, e.points, e.asks_last_attendance)
        for e in record.entries.all().order_by('sequence', 'grade'))
    return Scale(name=record.name, entries=entries, record=record)


def _points(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def setting_scale():
    """The grades setting's list as a Scale (the pre-records behaviour)."""
    from ..settings.class_section_grades import class_section_grades
    values = class_section_grades.from_db() or {}
    points = values.get('gpa_points') if isinstance(values.get('gpa_points'), dict) else {}
    entries = []
    for grade in str(values.get('grades') or '').split(','):
        grade = grade.strip()
        if grade and grade not in [e.grade for e in entries]:
            entries.append(ScaleEntry(grade, _points(points.get(grade))))
    return Scale(name='Standard', entries=tuple(entries))


def default_record(campus=None):
    """The default GradeScale for `campus`, else the deployment-wide one, else None."""
    from ..models import GradeScale
    qs = GradeScale.objects.filter(is_default=True)
    if campus is not None:
        own = qs.filter(campus=campus).first()
        if own is not None:
            return own
    return qs.filter(campus__isnull=True).first()


def default_scale(campus=None):
    """The default scale for `campus` (the current campus when omitted)."""
    record = default_record(campus if campus is not None else current_campus())
    return _from_record(record) if record is not None else setting_scale()


def scale_for_period(period):
    if period is None:
        return default_scale()
    if period.grade_scale_id:
        return _from_record(period.grade_scale)
    return default_scale(_campus_of_term(period.term))


def final_scale_for_term(term):
    """The scale of `term`'s final period, else the term campus's default."""
    from ..models import GradingPeriod
    if term is None:
        return default_scale()
    final = (GradingPeriod.objects.filter(term=term, is_final=True)
             .select_related('grade_scale', 'term__academic_year').first())
    if final is not None:
        return scale_for_period(final)
    return default_scale(_campus_of_term(term))


def final_scale_for_registration(registration):
    section = getattr(registration, 'class_section', None)
    return final_scale_for_term(getattr(section, 'term', None))


def all_final_letters(term_ids=None):
    """Letters any final grade can hold: the scales of final periods in
    `term_ids` (the grade terms when omitted) plus the default scale."""
    from ..models import GradingPeriod
    from .window import grade_terms
    term_ids = grade_terms() if term_ids is None else term_ids
    letters = list(default_scale().letters())
    finals = (GradingPeriod.objects.filter(term_id__in=term_ids, is_final=True)
              .select_related('grade_scale', 'term__academic_year'))
    for period in finals:
        for letter in scale_for_period(period).letters():
            if letter not in letters:
                letters.append(letter)
    return letters


def scales_for_campus(campus=None):
    """GradeScale rows a page for `campus` may list or pick: its own and the
    deployment-wide ones."""
    from django.db.models import Q
    from ..models import GradeScale
    campus = campus if campus is not None else current_campus()
    qs = GradeScale.objects.all()
    if campus is not None:
        qs = qs.filter(Q(campus=campus) | Q(campus__isnull=True))
    return qs.order_by('name')


def ensure_default_record(campus=None):
    """The default GradeScale for `campus`, creating "Standard" from the
    grades setting when there is none yet. Used by the Grade Scales page."""
    from django.db import transaction
    from ..models import GradeScale, GradeScaleEntry
    campus = campus if campus is not None else current_campus()
    record = default_record(campus)
    if record is not None:
        return record
    legacy = setting_scale()
    with transaction.atomic():
        name = 'Standard'
        if GradeScale.objects.filter(campus=campus, name=name).exists():
            name = 'Standard (default)'
        record = GradeScale.objects.create(
            name=name, campus=campus, is_default=True,
            description='Copied from the grades settings.')
        GradeScaleEntry.objects.bulk_create([
            GradeScaleEntry(scale=record, grade=e.grade, points=e.points, sequence=i)
            for i, e in enumerate(legacy.entries)])
    return record


# --- Guards: a scale edit must not strand marks already entered -------------

def periods_using(record):
    """GradingPeriods whose grades come from GradeScale `record`: those that
    name it, plus -- when it is a default -- those with no scale whose term's
    campus resolves to it."""
    from django.db.models import Q
    from ..models import GradingPeriod
    q = Q(grade_scale=record)
    if record.is_default:
        unset = Q(grade_scale__isnull=True)
        if record.campus_id is not None:
            unset &= Q(term__academic_year__campus_id=record.campus_id)
        else:
            # The deployment-wide default serves terms whose campus has no
            # default of its own (and campus-less terms).
            from ..models import GradeScale
            covered = GradeScale.objects.filter(
                is_default=True, campus__isnull=False).values('campus_id')
            unset &= (Q(term__academic_year__campus__isnull=True)
                      | ~Q(term__academic_year__campus_id__in=covered))
        q |= unset
    return GradingPeriod.objects.filter(q).select_related('term')


def _period_marks(period):
    """{letter: count} of the marks entered in `period`."""
    from django.db.models import Count
    from cis.models.section import StudentRegistration
    from ..models import PeriodGrade
    if period.is_final:
        rows = (StudentRegistration.objects.filter(class_section__term=period.term)
                .exclude(grade__isnull=True).values('grade').annotate(n=Count('id')))
    else:
        rows = PeriodGrade.objects.filter(period=period).values('grade').annotate(n=Count('id'))
    out = {}
    for row in rows:
        letter = (row['grade'] or '').strip()
        if letter and letter != '-':
            out[letter] = out.get(letter, 0) + row['n']
    return out


def letters_in_use(record):
    """{letter: count} of marks in periods that use GradeScale `record`."""
    out = {}
    for period in periods_using(record):
        for letter, n in _period_marks(period).items():
            out[letter] = out.get(letter, 0) + n
    return out


def stranded_marks(period, new_letters):
    """{letter: count} of `period`'s marks that `new_letters` would not offer."""
    allowed = set(new_letters)
    return {k: v for k, v in _period_marks(period).items() if k not in allowed}
