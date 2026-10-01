"""Registration detail: Send Grade to SIS action and Grade SIS history tab."""
from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth.signals import user_logged_in
from django.test import RequestFactory, TestCase
from django.utils import timezone

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from myce.component_registry.registration import registration_actions, registration_tabs

from ..models import GradeSISSync, GradeSISSyncAttempt
from ..services import sis_push
from ..services.sis_push import GradePushResult
from .sis_fixtures import SISFixtureMixin


def _pusher(registration, grade, existing_record_id=None):
    return GradePushResult(True)


class RegistrationDetailSISTests(SISFixtureMixin, TestCase):
    def setUp(self):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
            self.addCleanup(user_logged_in.connect, _login_history_post_login)
        patcher = patch.object(sis_push, 'get_pusher', return_value=_pusher)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.factory = RequestFactory()

    def _post(self, registration, user=None):
        request = self.factory.post('/', {'action': 'send_grade_to_sis',
                                          'ids[]': [str(registration.id)]})
        request.user = user or self.ce_user
        return registration_actions.dispatch(request, 'send_grade_to_sis')

    def test_action_listed_for_ce_when_pusher_configured(self):
        slugs = [s for g in registration_actions.for_scope('detail', self.ce_user).values()
                 for s in g['actions']]
        self.assertIn('send_grade_to_sis', slugs)

    def test_action_hidden_without_pusher(self):
        with patch.object(sis_push, 'get_pusher', return_value=None):
            slugs = [s for g in registration_actions.for_scope('detail', self.ce_user).values()
                     for s in g['actions']]
        self.assertNotIn('send_grade_to_sis', slugs)

    def test_enqueues_even_when_section_not_submitted(self):
        reg = self.make_registration(self.make_section(grade_status=''))

        with patch.object(sis_push, '_enqueue_task') as task:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self._post(reg)

        self.assertEqual(resp.status_code, 200)
        task.assert_called_once_with([str(reg.id)], self.ce_user.pk)

    def test_lost_race_reports_already_in_progress(self):
        """check_single() can pass and then another request queues (or the
        hand-off to the task queue fails for) the same row before this one's
        own enqueue() runs: enqueue() returns 0, and the action must say so
        rather than claiming "Queued" for a row it didn't actually queue."""
        reg = self.make_registration(self.make_section())

        with patch.object(sis_push, 'enqueue', return_value=0):
            resp = self._post(reg)

        self.assertIn(b'Already in progress', resp.content)
        self.assertNotIn(b'Queued.', resp.content)

    def test_blank_grade_refused_with_alert(self):
        reg = self.make_registration(self.make_section(), grade='-')

        with patch.object(sis_push, '_enqueue_task') as task:
            resp = self._post(reg)

        self.assertIn(b'no grade', resp.content)
        task.assert_not_called()

    def test_non_ce_refused_at_dispatch(self):
        reg = self.make_registration(self.make_section())
        self.assertEqual(self._post(reg, user=self.teacher.user).status_code, 403)

    def test_refused_without_pusher_at_dispatch(self):
        reg = self.make_registration(self.make_section())
        with patch.object(sis_push, 'get_pusher', return_value=None), \
                patch.object(sis_push, '_enqueue_task') as task:
            resp = self._post(reg)
        self.assertEqual(resp.status_code, 403)
        task.assert_not_called()

    def test_history_tab_lists_attempts(self):
        reg = self.make_registration(self.make_section())
        sync = GradeSISSync.objects.create(registration=reg, status='sent', sent_grade='A')
        GradeSISSyncAttempt.objects.create(
            sync=sync, attempted_at=timezone.now(),
            attempted_by=self.ce_user, grade='A', success=True)
        request = self.factory.get('/')
        request.user = self.ce_user

        context = registration_tabs._tabs['grade_sis']['handler'](request, reg)

        self.assertEqual(context['sync'], sync)
        self.assertEqual(len(context['attempts']), 1)

    def test_history_tab_renders_local_time(self):
        reg = self.make_registration(self.make_section())
        # 20:30 UTC on 30 Sep 2026 is 1:30 PM in America/Los_Angeles (PDT, UTC-7).
        attempted_at = datetime(2026, 9, 30, 20, 30, tzinfo=dt_timezone.utc)
        sync = GradeSISSync.objects.create(
            registration=reg, status='sent', sent_grade='A',
            last_sent_at=attempted_at, last_sent_by=self.ce_user)
        GradeSISSyncAttempt.objects.create(
            sync=sync, attempted_at=attempted_at,
            attempted_by=self.ce_user, grade='A', success=True)
        request = self.factory.get('/')
        request.user = self.ce_user

        resp = registration_tabs.render_tab(request, reg, 'grade_sis')
        html = resp.content.decode()

        self.assertEqual(resp.status_code, 200)
        self.assertIn('09/30/2026 1:30 PM', html)
        self.assertNotIn('8:30 PM', html)
