"""Pushing final grades to the SIS.

`grades` decides *what* to send and records the outcome; *how* to send is a
tenant-provided pusher, resolved through
``get_tenant_override('grade_sis_pusher', 'push_final_grade')``. A tenant that
ships no such module gets ``None`` here and the feature stays hidden.

A pusher is ``push_final_grade(registration, grade, existing_record_id=None)``
returning an object with ``success``, ``record_id``, ``error`` and ``log_url``
(see GradePushResult). It returns failures rather than raising; anything it does
raise is recorded as a failure for that registration only.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.utils import timezone

from ..models import GradeSISSync, GradeSISSyncAttempt
from .roster import students_for_grades
from .window import grade_terms

logger = logging.getLogger(__name__)

STALE_QUEUED = timedelta(minutes=30)


@dataclass
class GradePushResult:
    success: bool
    record_id: str | None = None
    error: str = ''
    log_url: str = ''


def get_pusher():
    """The tenant's push_final_grade callable, or None when not configured."""
    from cis.services.tenant_services import get_tenant_override
    return get_tenant_override('grade_sis_pusher', 'push_final_grade')


def get_config_errors():
    """Pusher-reported configuration problems ([] when none or not supported)."""
    from cis.services.tenant_services import get_tenant_override
    fn = get_tenant_override('grade_sis_pusher', 'config_errors')
    return fn() if fn else []


def normalize_grade(value):
    """'' for a missing grade. StudentRegistration.grade defaults to '-'."""
    value = (value or '').strip()
    return '' if value == '-' else value


def graded_q():
    """Q object for "has a real final grade" on StudentRegistration.grade.

    The single definition of "graded" shared by eligibility here and by page
    counts (Task 6): excludes NULL, '', '-', and whitespace-only grades,
    consistent with `normalize_grade`'s notion of blank.
    """
    return models.Q(grade__isnull=False) & ~models.Q(grade__regex=r'^\s*-?\s*$')


def is_in_flight(sync, now=None):
    if sync is None or sync.status != GradeSISSync.QUEUED:
        return False
    if sync.last_attempt_at is None:
        return False
    return sync.last_attempt_at > (now or timezone.now()) - STALE_QUEUED


def _parse_ids(ids):
    parsed = []
    for value in ids:
        try:
            parsed.append(uuid.UUID(str(value)))
        except (ValueError, TypeError):
            continue
    return parsed


def select_for_sections(section_ids):
    """Eligible registration ids for a class / bulk push.

    Only sections in the configured grade terms are considered. Sections not in
    grade_status 'submitted' are returned in `skipped` so the caller can say so.
    Within a section: roster registrations with a grade whose sync row is
    missing, failed, needs_mirroring, or a stale queued row.
    """
    from cis.models.section import ClassSection

    sections = list(
        ClassSection.objects.filter(
            pk__in=_parse_ids(section_ids), term_id__in=grade_terms()
        ).select_related('course'))

    now = timezone.now()
    ids, skipped = [], []
    for section in sections:
        if section.grade_status != 'submitted':
            skipped.append(section)
            continue
        registrations = [r for r in students_for_grades(section) if normalize_grade(r.grade)]
        syncs = {
            s.registration_id: s
            for s in GradeSISSync.objects.filter(registration__in=registrations)
        }
        for registration in registrations:
            sync = syncs.get(registration.pk)
            if sync is None or sync.status in (GradeSISSync.FAILED, GradeSISSync.NEEDS_MIRRORING):
                ids.append(str(registration.pk))
            elif sync.status == GradeSISSync.QUEUED and not is_in_flight(sync, now):
                ids.append(str(registration.pk))
    return ids, skipped


def check_single(registration):
    """Why a single-student push is refused, or None when it may go."""
    if not normalize_grade(registration.grade):
        return 'This registration has no grade.'
    sync = GradeSISSync.objects.filter(registration=registration).first()
    if is_in_flight(sync):
        return 'A send for this registration is already in progress.'
    return None


def _enqueue_task(ids, user_id):
    from ..tasks import send_grades_to_sis
    send_grades_to_sis.enqueue(ids, user_id)


def enqueue(registration_ids, user):
    """Mark registrations queued and enqueue the background push after commit."""
    ids = list(dict.fromkeys(str(i) for i in registration_ids))
    if not ids:
        return 0
    now = timezone.now()
    with transaction.atomic():
        for reg_id in ids:
            GradeSISSync.objects.update_or_create(
                registration_id=reg_id,
                defaults={'status': GradeSISSync.QUEUED,
                          'last_attempt_at': now, 'last_attempt_by': user})
        user_id = user.pk if user else None
        transaction.on_commit(lambda: _enqueue_task(ids, user_id))
    return len(ids)


def _current_grade(registration_id):
    from cis.models.section import StudentRegistration
    value = StudentRegistration.objects.filter(
        pk=registration_id).values_list('grade', flat=True).first()
    return normalize_grade(value)


def _record(sync, grade, result, user):
    """Persist the outcome of one push attempt onto `sync` and its attempt log.

    Called inside the per-row try in `run_push` (Ruling 1): if anything here
    raises -- e.g. `result.record_id` is not a valid UUID -- it must only mark
    this one registration failed, not abort the batch.
    """
    now = timezone.now()
    sync.last_attempt_at = now
    sync.last_attempt_by = user
    if result.success:
        sync.status = GradeSISSync.SENT
        sync.sent_grade = grade
        sync.last_sent_at = now
        sync.last_sent_by = user
        sync.last_error = ''
        sync.grade_changed_at = None
        if result.record_id:
            sync.sis_record_id = result.record_id
        # The grade may have been edited while the SIS call was in flight;
        # post_save saw the old sync state, so re-check here.
        if _current_grade(sync.registration_id) != grade:
            sync.status = GradeSISSync.NEEDS_MIRRORING
            sync.grade_changed_at = now
    else:
        sync.status = GradeSISSync.FAILED
        sync.last_error = result.error or 'Unknown error'
    sync.save()
    GradeSISSyncAttempt.objects.create(
        sync=sync, attempted_at=now, attempted_by=user, grade=grade,
        success=result.success, error=result.error or '', log_url=result.log_url or '')


def run_push(registration_ids, user_id=None):
    """Push each registration's current final grade; return {'sent', 'failed'} counts."""
    from cis.models.section import StudentRegistration

    pusher = get_pusher()
    user = get_user_model().objects.filter(pk=user_id).first() if user_id else None
    counts = {'sent': 0, 'failed': 0}

    for reg_id in registration_ids:
        registration = (
            StudentRegistration.objects.select_related('student', 'class_section')
            .filter(pk=reg_id).first())
        if registration is None:
            continue
        sync, _ = GradeSISSync.objects.get_or_create(
            registration=registration, defaults={'status': GradeSISSync.QUEUED})
        grade = normalize_grade(registration.grade)

        result = None
        try:
            # Ruling 1: the per-row bookkeeping (_record) runs inside this
            # same per-row try/atomic block, so a bad result (e.g. a non-UUID
            # record id) only fails this row and the batch continues. The
            # nested atomic() gives this row its own savepoint: a DB-level
            # error in _record (e.g. an invalid UUID write) only rolls back
            # this row's work, leaving the outer transaction healthy for the
            # next registration.
            with transaction.atomic():
                if pusher is None:
                    result = GradePushResult(False, error='No SIS grade pusher is configured.')
                elif not grade:
                    result = GradePushResult(False, error='Grade is blank.')
                else:
                    try:
                        result = pusher(
                            registration, grade,
                            existing_record_id=(
                                str(sync.sis_record_id) if sync.sis_record_id else None))
                    except Exception as exc:  # one bad registration must not stop the batch
                        logger.exception('Grade SIS push failed for registration %s', reg_id)
                        result = GradePushResult(False, error=f'Unexpected error: {exc}')

                _record(sync, grade, result, user)
            counts['sent' if result.success else 'failed'] += 1
        except Exception as exc:
            logger.exception('Recording SIS push outcome failed for registration %s', reg_id)
            # The failed atomic block rolled back `sync`'s in-flight write
            # (e.g. an unparsable record id), so reload the clean persisted
            # row before writing the failure state.
            sync.refresh_from_db()
            sync.status = GradeSISSync.FAILED
            sync.last_attempt_at = timezone.now()
            sync.last_attempt_by = user
            sync.last_error = f'Unexpected error recording result: {exc}'
            sync.save()
            counts['failed'] += 1

    return counts
