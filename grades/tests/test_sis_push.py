"""sis_push: eligibility, enqueue, run_push write-back."""
from datetime import timedelta
from unittest.mock import patch

from django.db.models.query import QuerySet
from django.test import TestCase
from django.utils import timezone

from cis.models.section import StudentRegistration

from ..models import GradeSISSync, GradeSISSyncAttempt
from ..services import sis_push
from ..services.sis_push import GradePushResult
from .sis_fixtures import SISFixtureMixin

RECORD = '3b300cc1-bcf1-496a-a0a1-d451bd52be42'


def ok_pusher(registration, grade, existing_record_id=None):
    return GradePushResult(True, record_id=RECORD, log_url='/ce/ethos/logs/1/')


def fail_pusher(registration, grade, existing_record_id=None):
    return GradePushResult(False, error='Section is not gradable', log_url='/ce/ethos/logs/2/')


class NormalizeTests(TestCase):
    def test_dash_grade_is_blank(self):
        for value in (None, '', '  ', '-', ' - '):
            self.assertEqual(sis_push.normalize_grade(value), '')
        self.assertEqual(sis_push.normalize_grade(' A- '), 'A-')


class GradedQTests(SISFixtureMixin, TestCase):
    def test_graded_q_excludes_blank_variants(self):
        section = self.make_section()
        graded = self.make_registration(section, grade='A')
        for value in ('', '   ', '-', ' - '):
            self.make_registration(section, grade=value)

        ids = set(
            StudentRegistration.objects.filter(sis_push.graded_q())
            .values_list('id', flat=True))

        self.assertEqual(ids, {graded.id})


class SelectionTests(SISFixtureMixin, TestCase):
    def test_unsubmitted_section_is_skipped_and_reported(self):
        section = self.make_section(grade_status='saved')
        self.make_registration(section)

        ids, skipped = sis_push.select_for_sections([section.id])

        self.assertEqual(ids, [])
        self.assertEqual(skipped, [section])

    def test_submitted_section_selects_graded_unsent_rows(self):
        section = self.make_section()
        graded = self.make_registration(section, grade='A')
        self.make_registration(section, grade='-')

        ids, skipped = sis_push.select_for_sections([section.id])

        self.assertEqual(ids, [str(graded.id)])
        self.assertEqual(skipped, [])

    def test_sent_rows_not_reselected_but_failed_and_flagged_are(self):
        section = self.make_section()
        sent = self.make_registration(section)
        failed = self.make_registration(section)
        flagged = self.make_registration(section)
        GradeSISSync.objects.create(registration=sent, status='sent', sent_grade='A')
        GradeSISSync.objects.create(registration=failed, status='failed')
        GradeSISSync.objects.create(registration=flagged, status='needs_mirroring', sent_grade='B')

        ids, _ = sis_push.select_for_sections([section.id])

        self.assertCountEqual(ids, [str(failed.id), str(flagged.id)])

    def test_queued_rows_not_reselected(self):
        section = self.make_section()
        reg = self.make_registration(section)
        GradeSISSync.objects.create(
            registration=reg, status='queued', last_attempt_at=timezone.now())

        ids, _ = sis_push.select_for_sections([section.id])

        self.assertEqual(ids, [])

    def test_stale_queued_rows_are_reselected(self):
        section = self.make_section()
        reg = self.make_registration(section)
        GradeSISSync.objects.create(
            registration=reg, status='queued',
            last_attempt_at=timezone.now() - timedelta(minutes=31))

        ids, _ = sis_push.select_for_sections([section.id])

        self.assertEqual(ids, [str(reg.id)])

    def test_sections_outside_grade_terms_and_bad_ids_ignored(self):
        other = self.make_section(term=self.other_term)
        self.make_registration(other)

        ids, skipped = sis_push.select_for_sections([other.id, 'not-a-uuid'])

        self.assertEqual((ids, skipped), ([], []))

    def test_single_ignores_section_status(self):
        section = self.make_section(grade_status='')
        reg = self.make_registration(section)

        self.assertIsNone(sis_push.check_single(reg))

    def test_single_refuses_blank_grade_and_in_flight(self):
        section = self.make_section()
        blank = self.make_registration(section, grade='-')
        busy = self.make_registration(section)
        GradeSISSync.objects.create(
            registration=busy, status='queued', last_attempt_at=timezone.now())

        self.assertIn('no grade', sis_push.check_single(blank))
        self.assertIn('in progress', sis_push.check_single(busy))

    def test_single_allows_resend_of_sent(self):
        section = self.make_section()
        reg = self.make_registration(section)
        GradeSISSync.objects.create(registration=reg, status='sent', sent_grade='A')

        self.assertIsNone(sis_push.check_single(reg))


class EnqueueTests(SISFixtureMixin, TestCase):
    def test_marks_queued_and_enqueues_task_on_commit(self):
        section = self.make_section()
        reg = self.make_registration(section)

        with patch.object(sis_push, '_enqueue_task') as enqueue_task:
            with self.captureOnCommitCallbacks(execute=True):
                count = sis_push.enqueue([reg.id, reg.id], self.ce_user)

        self.assertEqual(count, 1)
        sync = GradeSISSync.objects.get(registration=reg)
        self.assertEqual(sync.status, 'queued')
        self.assertEqual(sync.last_attempt_by, self.ce_user)
        enqueue_task.assert_called_once_with([str(reg.id)], self.ce_user.pk)

    def test_empty_is_noop(self):
        with patch.object(sis_push, '_enqueue_task') as enqueue_task:
            self.assertEqual(sis_push.enqueue([], self.ce_user), 0)
        enqueue_task.assert_not_called()

    def test_already_freshly_queued_row_is_not_reenqueued(self):
        """Double-click / two-staff race (spec S:153): a registration whose
        sync row is already in-flight queued must not be re-queued, re-counted
        or re-enqueued by a second concurrent request."""
        section = self.make_section()
        reg = self.make_registration(section)
        GradeSISSync.objects.create(
            registration=reg, status='queued', last_attempt_at=timezone.now())

        with patch.object(sis_push, '_enqueue_task') as enqueue_task:
            with self.captureOnCommitCallbacks(execute=True):
                count = sis_push.enqueue([reg.id], self.ce_user)

        self.assertEqual(count, 0)
        enqueue_task.assert_not_called()

    def test_handoff_failure_fails_rows_instead_of_leaving_them_stuck_queued(self):
        """If `_enqueue_task` raises inside the `on_commit` callback (e.g. the
        task queue backend is unreachable), the rows are already committed
        `queued` -- there is nothing left to roll back, so the request must
        not 500. They must also not be left looking queued (they'd otherwise
        sit looking "in flight" for 30 minutes with nothing working on
        them): the on_commit hand-off must fail them with a clear error
        instead.

        Note on timing: `captureOnCommitCallbacks` defers running the
        callback until *this* `with` block exits, not until `enqueue()`'s own
        inner `transaction.atomic()` block exits (unlike real request
        handling, where on_commit fires synchronously at that point) -- so
        the DB state is only asserted after the outer `with` block here, not
        the `count` enqueue() itself returned.
        """
        section = self.make_section()
        reg = self.make_registration(section)

        with patch.object(sis_push, '_enqueue_task', side_effect=RuntimeError('queue down')):
            with self.captureOnCommitCallbacks(execute=True):
                sis_push.enqueue([reg.id], self.ce_user)

        sync = GradeSISSync.objects.get(registration=reg)
        self.assertEqual(sync.status, 'failed')
        self.assertEqual(sync.last_error, sis_push.HANDOFF_ERROR)

    def _force_one_gradesissync_get_miss(self):
        """Patch QuerySet.get at the class level so the FIRST .get() issued
        against a GradeSISSync queryset raises DoesNotExist, and every other
        call (on any model) behaves normally.

        Patching `GradeSISSync.objects.get` is not enough: `Manager.get`
        delegates to `self.get_queryset().get(...)`, a *new* QuerySet
        instance each time, so a patch on the manager's bound method is
        never actually invoked by `get_or_create`'s internal
        `self.get(**kwargs)` call (verified: a probe showed the call counter
        staying at 0). Patching `QuerySet.get` itself intercepts every such
        call regardless of which queryset instance it runs on.

        Returns the `calls` dict; `calls['n']` is incremented exactly once,
        the first time the forced miss fires, so the caller can assert the
        IntegrityError path actually ran.
        """
        orig_get = QuerySet.get
        calls = {'n': 0}

        def fake_get(qs, *args, **kwargs):
            if qs.model is GradeSISSync and calls['n'] == 0:
                calls['n'] += 1
                raise GradeSISSync.DoesNotExist()
            return orig_get(qs, *args, **kwargs)

        return calls, patch.object(QuerySet, 'get', autospec=True, side_effect=fake_get)

    def test_concurrent_first_time_enqueue_integrity_error_is_absorbed(self):
        """Two concurrent first-time enqueue() calls for the same
        registration: this call's existing-rows lookup misses (simulating the
        other call's insert landing in between), so it falls through to
        get_or_create(), whose own create() genuinely collides with the row
        the other call already committed, raising IntegrityError. That error
        must not escape enqueue() -- it must fall back to the real row,
        re-lock it, and queue it exactly once."""
        section = self.make_section()
        reg = self.make_registration(section)

        # Simulate: the other request's enqueue() already committed a sync
        # row for this registration, by inserting one directly (bypassing
        # the manager, so it doesn't go through this test's own patches).
        competing = GradeSISSync(registration_id=reg.id, status=GradeSISSync.FAILED)
        competing.save(force_insert=True)

        calls, get_patch = self._force_one_gradesissync_get_miss()

        with patch.object(sis_push, '_locked_syncs', return_value={}):
            with get_patch:
                with patch.object(sis_push, '_enqueue_task') as enqueue_task:
                    with self.captureOnCommitCallbacks(execute=True):
                        count = sis_push.enqueue([reg.id], self.ce_user)

        # Proves the forced miss actually fired -- i.e. get_or_create's
        # create() genuinely collided and raised IntegrityError, rather than
        # this test silently passing because the row was found some other
        # way.
        self.assertEqual(calls['n'], 1)
        self.assertEqual(count, 1)
        enqueue_task.assert_called_once_with([str(reg.id)], self.ce_user.pk)
        self.assertEqual(GradeSISSync.objects.filter(registration=reg).count(), 1)
        self.assertEqual(GradeSISSync.objects.get(registration=reg).status, 'queued')

    def test_concurrent_first_time_enqueue_skips_a_row_the_other_call_queued(self):
        """Same forced IntegrityError collision as above, but the row the
        other call already committed is freshly queued (in-flight): this
        call must skip it -- not re-queue it, not count it, not enqueue it
        again."""
        section = self.make_section()
        reg = self.make_registration(section)
        attempted_at = timezone.now()
        competing = GradeSISSync(
            registration_id=reg.id, status=GradeSISSync.QUEUED,
            last_attempt_at=attempted_at)
        competing.save(force_insert=True)

        calls, get_patch = self._force_one_gradesissync_get_miss()

        with patch.object(sis_push, '_locked_syncs', return_value={}):
            with get_patch:
                with patch.object(sis_push, '_enqueue_task') as enqueue_task:
                    with self.captureOnCommitCallbacks(execute=True):
                        count = sis_push.enqueue([reg.id], self.ce_user)

        self.assertEqual(calls['n'], 1)
        self.assertEqual(count, 0)
        enqueue_task.assert_not_called()
        competing.refresh_from_db()
        self.assertEqual(competing.status, 'queued')
        self.assertEqual(competing.last_attempt_at, attempted_at)


class RunPushTests(SISFixtureMixin, TestCase):
    def _run(self, pusher, reg):
        with patch.object(sis_push, 'get_pusher', return_value=pusher):
            return sis_push.run_push([str(reg.id)], self.ce_user.pk)

    def test_success_records_sent_state_and_attempt(self):
        reg = self.make_registration(self.make_section(), grade='A')

        counts = self._run(ok_pusher, reg)

        self.assertEqual(counts, {'sent': 1, 'failed': 0})
        sync = GradeSISSync.objects.get(registration=reg)
        self.assertEqual(sync.status, 'sent')
        self.assertEqual(sync.sent_grade, 'A')
        self.assertEqual(str(sync.sis_record_id), RECORD)
        self.assertEqual(sync.last_sent_by, self.ce_user)
        self.assertEqual(sync.last_error, '')
        attempt = sync.attempts.get()
        self.assertTrue(attempt.success)
        self.assertEqual(attempt.grade, 'A')
        self.assertEqual(attempt.log_url, '/ce/ethos/logs/1/')

    def test_failure_records_error_and_keeps_previous_sent_grade(self):
        reg = self.make_registration(self.make_section(), grade='B')
        GradeSISSync.objects.create(registration=reg, status='needs_mirroring', sent_grade='A')

        counts = self._run(fail_pusher, reg)

        self.assertEqual(counts, {'sent': 0, 'failed': 1})
        sync = GradeSISSync.objects.get(registration=reg)
        self.assertEqual(sync.status, 'failed')
        self.assertEqual(sync.sent_grade, 'A')
        self.assertEqual(sync.last_error, 'Section is not gradable')
        self.assertFalse(sync.attempts.get().success)

    def test_resend_passes_known_record_id(self):
        reg = self.make_registration(self.make_section())
        GradeSISSync.objects.create(registration=reg, status='failed', sis_record_id=RECORD)
        seen = {}

        def spy(registration, grade, existing_record_id=None):
            seen['record'] = existing_record_id
            return GradePushResult(True, record_id=RECORD)

        self._run(spy, reg)

        self.assertEqual(seen['record'], RECORD)

    def test_exception_in_one_registration_does_not_stop_batch(self):
        section = self.make_section()
        first = self.make_registration(section)
        second = self.make_registration(section)

        def flaky(registration, grade, existing_record_id=None):
            if registration.pk == first.pk:
                raise RuntimeError('boom')
            return GradePushResult(True, record_id=RECORD)

        with patch.object(sis_push, 'get_pusher', return_value=flaky):
            counts = sis_push.run_push([str(first.id), str(second.id)], None)

        self.assertEqual(counts, {'sent': 1, 'failed': 1})
        self.assertIn('boom', GradeSISSync.objects.get(registration=first).last_error)

    def test_recording_exception_isolated_to_one_row(self):
        """Ruling 1: _record runs inside its own savepoint, so a bad recording
        step (e.g. Banner returning a non-UUID record id) fails only that row,
        and per spec S:175 an attempt row is still appended either way,
        carrying the pusher's log_url even though recording itself failed."""
        section = self.make_section()
        bad = self.make_registration(section)
        good = self.make_registration(section)

        def returns_bad_record_id(registration, grade, existing_record_id=None):
            if registration.pk == bad.pk:
                return GradePushResult(True, record_id='not-a-uuid', log_url='/ce/ethos/logs/9/')
            return GradePushResult(True, record_id=RECORD)

        with patch.object(sis_push, 'get_pusher', return_value=returns_bad_record_id):
            counts = sis_push.run_push([str(bad.id), str(good.id)], None)

        self.assertEqual(counts, {'sent': 1, 'failed': 1})
        self.assertEqual(GradeSISSync.objects.get(registration=good).status, 'sent')
        bad_sync = GradeSISSync.objects.get(registration=bad)
        self.assertEqual(bad_sync.status, 'failed')
        self.assertTrue(bad_sync.last_error)
        self.assertEqual(bad_sync.attempts.count(), 1)
        attempt = bad_sync.attempts.get()
        self.assertFalse(attempt.success)
        self.assertEqual(attempt.log_url, '/ce/ethos/logs/9/')

    def test_blank_grade_at_run_time_fails(self):
        reg = self.make_registration(self.make_section(), grade='-')

        self._run(ok_pusher, reg)

        sync = GradeSISSync.objects.get(registration=reg)
        self.assertEqual(sync.status, 'failed')
        self.assertIn('blank', sync.last_error)

    def test_no_pusher_configured_fails(self):
        reg = self.make_registration(self.make_section())

        self._run(None, reg)

        self.assertIn('No SIS grade pusher', GradeSISSync.objects.get(registration=reg).last_error)

    def test_grade_changed_during_push_ends_needs_mirroring(self):
        reg = self.make_registration(self.make_section(), grade='A')

        def edits_midflight(registration, grade, existing_record_id=None):
            StudentRegistration.objects.filter(pk=registration.pk).update(grade='B')
            return GradePushResult(True, record_id=RECORD)

        self._run(edits_midflight, reg)

        sync = GradeSISSync.objects.get(registration=reg)
        self.assertEqual(sync.sent_grade, 'A')
        self.assertEqual(sync.status, 'needs_mirroring')
        self.assertIsNotNone(sync.grade_changed_at)

    def test_heartbeat_stamps_last_attempt_at_before_calling_pusher(self):
        """is_in_flight's 30-minute window must measure a dead worker, not
        queue depth: the row's last_attempt_at has to move the moment the
        worker reaches it, before the (possibly slow) pusher call, not only
        afterwards when _record() writes the final outcome."""
        reg = self.make_registration(self.make_section(), grade='A')
        stale = timezone.now() - timedelta(minutes=45)
        GradeSISSync.objects.create(
            registration=reg, status='queued', last_attempt_at=stale)
        seen = {}

        def spy(registration, grade, existing_record_id=None):
            seen['last_attempt_at'] = GradeSISSync.objects.get(
                registration=registration).last_attempt_at
            return GradePushResult(True, record_id=RECORD)

        self._run(spy, reg)

        self.assertIsNotNone(seen['last_attempt_at'])
        self.assertGreater(seen['last_attempt_at'], stale)
