"""Registration detail: Send Grade to SIS action and Grade SIS history tab."""
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
from ..services.sis_push import GradePushResult
from .sis_fixtures import SISFixtureMixin


def _pusher(registration, grade, existing_record_id=None):
    return GradePushResult(True)


class RegistrationDetailSISTests(SISFixtureMixin, TestCase):
    def setUp(self):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
            self.addCleanup(user_logged_in.connect, _login_history_post_login)
        patcher = patch('grades.grades.services.sis_push.get_pusher', return_value=_pusher)
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
        with patch('grades.grades.services.sis_push.get_pusher', return_value=None):
            slugs = [s for g in registration_actions.for_scope('detail', self.ce_user).values()
                     for s in g['actions']]
        self.assertNotIn('send_grade_to_sis', slugs)

    def test_enqueues_even_when_section_not_submitted(self):
        reg = self.make_registration(self.make_section(grade_status=''))

        with patch('grades.grades.services.sis_push._enqueue_task') as task:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self._post(reg)

        self.assertEqual(resp.status_code, 200)
        task.assert_called_once_with([str(reg.id)], self.ce_user.pk)

    def test_blank_grade_refused_with_alert(self):
        reg = self.make_registration(self.make_section(), grade='-')

        with patch('grades.grades.services.sis_push._enqueue_task') as task:
            resp = self._post(reg)

        self.assertIn(b'no grade', resp.content)
        task.assert_not_called()

    def test_non_ce_refused_at_dispatch(self):
        reg = self.make_registration(self.make_section())
        self.assertEqual(self._post(reg, user=self.teacher.user).status_code, 403)

    def test_refused_without_pusher_at_dispatch(self):
        reg = self.make_registration(self.make_section())
        with patch('grades.grades.services.sis_push.get_pusher', return_value=None), \
                patch('grades.grades.services.sis_push._enqueue_task') as task:
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
