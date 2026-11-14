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
    """The id of `term`'s campus, or None. An id, not the Campus: reading
    `.campus` would load the row once per term (an N+1 on multi-campus)."""
    ay = getattr(term, 'academic_year', None)
    return getattr(ay, 'campus_id', None) if ay is not None else None


def _campus_key(campus):
    """A Campus or a campus id -> the id (None stays None)."""
    return getattr(campus, 'pk', campus)


def current_campus():
    """The request's campus on a multi-campus host, else None."""
    if not has_module('cis.campus_context'):
        return None
    from cis.campus_context import current_campus_or_none, is_multi_campus
    return current_campus_or_none() if is_multi_campus() else None


def _from_record(record):
    # Sorted here, not with order_by(), so a prefetched entries cache is used.
    entries = tuple(
        ScaleEntry(e.grade, e.points, e.asks_last_attendance)
        for e in sorted(record.entries.all(), key=lambda e: (e.sequence, e.grade)))
    return Scale(name=record.name, entries=entries, record=record)


def academic_year_has_campus():
    """Whether cis's AcademicYear carries a campus. In-tree cis on some hosts
    (nnu, csn, weber, westmoreland) has none, so campus paths must be guarded."""
    from django.core.exceptions import FieldDoesNotExist
    from cis.models.term import AcademicYear
    try:
        AcademicYear._meta.get_field('campus')
    except FieldDoesNotExist:
        return False
    return True


def _points(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _saved_setting_value():
    """The grades setting row as saved, without from_db()'s filled-in
    defaults (it adds any missing key, which hides what was really saved)."""
    import json
    from cis.models.settings import Setting
    from ..settings.class_section_grades import class_section_grades
    try:
        value = Setting.objects.get(key=class_section_grades.key).value
    except Exception:
        # No row, or a multi-campus lookup with no campus in context: the
        # fallback is then the shipped default, never an error page.
        return {}
    while isinstance(value, str):     # a value saved as a JSON string
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def setting_scale():
    """The grades setting's list as a Scale (the pre-records behaviour).

    Letters come from the saved `grades` list, as the grade picker always
    read them; a row with only `grade_scale` uses that; a row with neither
    gets the shipped default. Points come from `grade_scale`, else `gpa_points`.
    """
    from ..settings.class_section_grades import class_section_grades
    values = _saved_setting_value()
    scale = values.get('grade_scale') if isinstance(values.get('grade_scale'), list) else []
    points = {str((i or {}).get('grade') or '').strip(): i.get('points')
              for i in scale if isinstance(i, dict)}
    if not points and isinstance(values.get('gpa_points'), dict):
        points = values['gpa_points']
    if str(values.get('grades') or '').strip():
        letters = str(values['grades']).split(',')
    elif scale:
        letters = list(points)
    else:
        shipped = class_section_grades.get_default_grade_scale()
        letters = [i['grade'] for i in shipped]
        points = {i['grade']: i['points'] for i in shipped}
    entries = []
    for grade in letters:
        grade = str(grade).strip()
        if grade and grade != '-' and grade not in [e.grade for e in entries]:
            entries.append(ScaleEntry(grade, _points(points.get(grade))))
    return Scale(name='Standard', entries=tuple(entries))


def default_record(campus=None):
    """The default GradeScale for `campus` (a Campus or its id), else the
    deployment-wide one, else None."""
    from ..models import GradeScale
    qs = GradeScale.objects.filter(is_default=True)
    campus = _campus_key(campus)
    if campus is not None:
        own = qs.filter(campus_id=campus).first()
        if own is not None:
            return own
    return qs.filter(campus__isnull=True).first()


def default_scale(campus=None, cache=None):
    """The default scale for `campus` (the current campus when omitted).
    `cache` (a dict) reuses lookups across one batch of calls."""
    campus = campus if campus is not None else current_campus()
    key = _campus_key(campus)
    if cache is not None and key in cache:
        return cache[key]
    record = default_record(key)
    if record is not None:
        from django.db.models import prefetch_related_objects
        prefetch_related_objects([record], 'entries')
    scale = _from_record(record) if record is not None else setting_scale()
    if cache is not None:
        cache[key] = scale
    return scale


def scale_for_period(period, cache=None, term=None):
    """`period`'s scale. With no period (a term with no grading periods), the
    default for `term`'s campus."""
    if period is None:
        return default_scale(_campus_of_term(term), cache=cache)
    if period.grade_scale_id:
        return _from_record(period.grade_scale)
    return default_scale(_campus_of_term(period.term), cache=cache)


def final_scale_for_term(term, cache=None):
    """The scale of `term`'s final period, else the term campus's default."""
    from ..models import GradingPeriod
    if term is None:
        return default_scale()
    final = (GradingPeriod.objects.filter(term=term, is_final=True)
             .select_related('grade_scale', 'term__academic_year')
             .prefetch_related('grade_scale__entries').first())
    if final is not None:
        return scale_for_period(final, cache=cache)
    return default_scale(_campus_of_term(term), cache=cache)


def final_scale_for_registration(registration):
    section = getattr(registration, 'class_section', None)
    return final_scale_for_term(getattr(section, 'term', None))


def all_final_letters(term_ids=None):
    """Letters any final grade can hold: the scales of final periods in
    `term_ids` (the grade terms when omitted) plus the default scale."""
    from ..models import GradingPeriod
    from .window import grade_terms
    term_ids = grade_terms() if term_ids is None else term_ids
    cache = {}
    letters = list(default_scale(cache=cache).letters())
    finals = (GradingPeriod.objects.filter(term_id__in=term_ids, is_final=True)
              .select_related('grade_scale', 'term__academic_year')
              .prefetch_related('grade_scale__entries'))
    for period in finals:
        for letter in scale_for_period(period, cache=cache).letters():
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
        if not academic_year_has_campus():
            pass    # no campuses on terms: a default serves every unset period
        elif record.campus_id is not None:
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


def _marks_in(periods):
    """{letter: count} over `periods` in two queries: interim marks, then the
    final grades of the final periods' terms."""
    from django.db.models import Count
    from cis.models.section import StudentRegistration
    from ..models import PeriodGrade
    periods = list(periods)
    interim = [p.pk for p in periods if not p.is_final]
    final_terms = [p.term_id for p in periods if p.is_final]
    rows = []
    if interim:
        rows += PeriodGrade.objects.filter(period_id__in=interim).values(
            'grade').annotate(n=Count('id')).order_by()
    if final_terms:
        rows += StudentRegistration.objects.filter(
            class_section__term_id__in=final_terms).exclude(grade__isnull=True).values(
            'grade').annotate(n=Count('id')).order_by()
    out = {}
    for row in rows:
        letter = (row['grade'] or '').strip()
        if letter and letter != '-':
            out[letter] = out.get(letter, 0) + row['n']
    return out


def letters_in_use(record):
    """{letter: count} of marks in periods that use GradeScale `record`."""
    return _marks_in(periods_using(record))


def stranded_by_default_swap(old_default, new_letters):
    """{letter: count} of marks in periods that follow `old_default` only
    because they have no scale of their own, which `new_letters` lacks."""
    if old_default is None:
        return {}
    allowed = set(new_letters)
    marks = _marks_in(periods_using(old_default).filter(grade_scale__isnull=True))
    return {k: v for k, v in marks.items() if k not in allowed}


def stranded_marks(period, new_letters):
    """{letter: count} of `period`'s marks that `new_letters` would not offer."""
    allowed = set(new_letters)
    return {k: v for k, v in _period_marks(period).items() if k not in allowed}
