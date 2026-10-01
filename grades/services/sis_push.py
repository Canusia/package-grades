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
        registrations = list(students_for_grades(section).filter(graded_q()))
        ids.extend(bulk_eligible_ids(registrations, now))
    return ids, skipped


def bulk_eligible_ids(registrations, now=None):
    """Ids (str) of `registrations` a class / bulk push may send, by sync state.

    The bulk rule: no sync row yet, failed, needs_mirroring, or a stale queued
    row. `sent` rows and fresh `queued` rows are left alone. The caller is
    responsible for the section-status (submitted) and graded checks.
    """
    now = now or timezone.now()
    registrations = list(registrations)
    syncs = {
        s.registration_id: s
        for s in GradeSISSync.objects.filter(registration__in=registrations)
    }
    ids = []
    for registration in registrations:
        sync = syncs.get(registration.pk)
        if sync is None or sync.status in (GradeSISSync.FAILED, GradeSISSync.NEEDS_MIRRORING):
            ids.append(str(registration.pk))
        elif sync.status == GradeSISSync.QUEUED and not is_in_flight(sync, now):
            ids.append(str(registration.pk))
    return ids


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


def _locked_syncs(ids):
    """Existing GradeSISSync rows for `ids`, locked for update.

    `.order_by('pk')` gives multi-id batches a consistent lock order so two
    overlapping `enqueue()` calls over intersecting id sets can't deadlock
    against each other.
    """
    return {
        str(s.registration_id): s
        for s in GradeSISSync.objects.select_for_update()
            .filter(registration_id__in=ids).order_by('pk')
    }


def enqueue(registration_ids, user):
    """Mark registrations queued and enqueue the background push after commit.

    Guards against the double-click / two-staff race (spec S:153): a
    registration whose sync row is already freshly `queued` (`is_in_flight`)
    is left alone -- not re-queued, not re-counted, not re-enqueued -- so two
    concurrent requests for the same registration cannot both reach the SIS.
    `select_for_update` on the existing rows makes that check atomic against
    a concurrent `enqueue` call racing to the same rows.

    A registration with no sync row yet can't be locked by that query (there
    is nothing to lock), so two concurrent first-time `enqueue()` calls can
    both see no row and both attempt to create one. `get_or_create` absorbs
    that race: it wraps its insert in its own savepoint and, on the unique
    constraint's `IntegrityError`, falls back to fetching the row the other
    call just created instead of letting the error escape. When this call
    loses that race (`created` is False), the row it gets back is re-fetched
    with `select_for_update` and put through the same in-flight check -- a
    row the other request just queued must be skipped here too, not
    re-queued or re-enqueued.
    """
    ids = list(dict.fromkeys(str(i) for i in registration_ids))
    if not ids:
        return 0
    now = timezone.now()
    with transaction.atomic():
        existing = _locked_syncs(ids)
        transitioned = []
        for reg_id in ids:
            sync = existing.get(reg_id)
            if sync is None:
                sync, created = GradeSISSync.objects.get_or_create(
                    registration_id=reg_id,
                    defaults={'status': GradeSISSync.QUEUED,
                              'last_attempt_at': now, 'last_attempt_by': user})
                if created:
                    transitioned.append(reg_id)
                    continue
                # Lost the race: another request's enqueue() (or run_push())
                # got there first. Lock the real row and decide fresh.
                sync = GradeSISSync.objects.select_for_update().get(pk=sync.pk)

            if is_in_flight(sync, now):
                continue  # already queued and fresh elsewhere; don't re-enqueue

            sync.status = GradeSISSync.QUEUED
            sync.last_attempt_at = now
            sync.last_attempt_by = user
            sync.save()
            transitioned.append(reg_id)

        if not transitioned:
            return 0
        user_id = user.pk if user else None
        transaction.on_commit(lambda: _enqueue_task(transitioned, user_id))
    return len(transitioned)


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

        # The pusher call (an HTTP round-trip to Banner) runs OUTSIDE any
        # savepoint: it must never be rolled back by a later bookkeeping
        # failure, since rolling it back would erase DB rows it wrote (e.g.
        # the ethos pusher's EthosLog) while the SIS side effect it caused
        # stands. Only the per-row bookkeeping (_record) gets its own
        # savepoint (Ruling 1), so a bad result (e.g. a non-UUID record id)
        # fails only this row's recording without reaching back into the
        # pusher call or forward into the next registration.
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

        try:
            with transaction.atomic():
                _record(sync, grade, result, user)
            counts['sent' if result.success else 'failed'] += 1
        except Exception as exc:
            logger.exception('Recording SIS push outcome failed for registration %s', reg_id)
            # The failed savepoint rolled back `sync`'s in-flight write (e.g.
            # an unparsable record id), so reload the clean persisted row
            # before writing the failure state. Per spec S:175, an attempt
            # row is appended either way -- carry the pusher's own log_url
            # when a result was produced, so the Banner-side log link isn't
            # lost even though the sync row records a bookkeeping failure.
            now = timezone.now()
            sync.refresh_from_db()
            sync.status = GradeSISSync.FAILED
            sync.last_attempt_at = now
            sync.last_attempt_by = user
            sync.last_error = f'Unexpected error recording result: {exc}'
            sync.save()
            GradeSISSyncAttempt.objects.create(
                sync=sync, attempted_at=now, attempted_by=user, grade=grade,
                success=False, error=sync.last_error,
                log_url=(result.log_url or '') if result is not None else '')
            counts['failed'] += 1

    return counts
