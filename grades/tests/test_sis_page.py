"""CE Grades → SIS page: visibility, feeds, bulk actions."""
import json
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from ..actions import grade_sis_actions
from ..models import GradeSISSync, GradeSISSyncAttempt
from ..services.sis_push import GradePushResult
from .sis_fixtures import SISFixtureMixin

GET_PUSHER = 'grades.grades.services.sis_push.get_pusher'
ENQUEUE_TASK = 'grades.grades.services.sis_push._enqueue_task'


def _pusher(registration, grade, existing_record_id=None):
    return GradePushResult(True)


def _page_columns(html, table):
    """The DataTables `columns` config the page JS uses for `table`.

    The page JS reads its column list from a json_script block, so this is
    exactly what DataTables sends as columns[i][data|name|orderable|searchable].
    """
    match = re.search(
        r'<script id="%s-columns" type="application/json">(.*?)</script>' % table,
        html, re.S)
    assert match, f'no column config for {table}'
    return json.loads(match.group(1))


class _SISPageBase(SISFixtureMixin, TestCase):
    def setUp(self):
        # django_login_history's post_login receiver needs a usable request IP
        # and errors under force_login; disconnect it for each test.
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
            self.addCleanup(user_logged_in.connect, _login_history_post_login)
        self.client.force_login(self.ce_user)
        patcher = patch(GET_PUSHER, return_value=_pusher)
        patcher.start()
        self.addCleanup(patcher.stop)

    def sections_feed(self, query=''):
        url = reverse('grades_ce:sis-sections-list') + '?format=datatables&draw=1' + query
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, resp.content[:500])
        return resp.json()['data']

    def registrations_feed(self, query=''):
        url = (reverse('grades_ce:sis-registrations-list')
               + '?format=datatables&draw=1' + query)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, resp.content[:500])
        return resp.json()['data']

    def post_action(self, action, ids):
        return self.client.post(reverse('grades_ce:sis_action'),
                                {'action': action, 'ids[]': [str(i) for i in ids]})


class SISPageTests(_SISPageBase):
    def test_page_renders_for_ce(self):
        resp = self.client.get(reverse('grades_ce:sis_sync'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('id="sis-sections-table"', html)
        self.assertIn('id="sis-registrations-table"', html)

    def test_page_renders_filters(self):
        hs_section = self.make_section()
        hs_section.highschool = self.highschool
        hs_section.save()

        html = self.client.get(reverse('grades_ce:sis_sync')).content.decode()

        self.assertIn('id="sis-sections-term-filter"', html)
        self.assertIn('id="sis-sections-highschool-filter"', html)
        self.assertIn('id="sis-registrations-term-filter"', html)
        self.assertIn('id="sis-registrations-section-filter"', html)
        self.assertIn('id="sis-status-filter"', html)
        self.assertIn(f'value="{self.term.id}"', html)
        self.assertIn(f'value="{self.highschool.id}"', html)
        self.assertIn(f'value="{hs_section.id}"', html)

    def test_buttons_render_from_registry(self):
        action = grade_sis_actions._find_action('send_sections')
        with patch.dict(action, {'label': 'SENTINELLABEL', 'confirm': 'SENTINELCONFIRM'}):
            html = self.client.get(reverse('grades_ce:sis_sync')).content.decode()
        # escapejs would mangle punctuation, hence sentinels without any.
        self.assertIn('SENTINELLABEL', html)
        self.assertIn('SENTINELCONFIRM', html)
        # And the registration send is there too, from its own registry entry.
        reg_action = grade_sis_actions._find_action('send_registrations')
        self.assertIn(reg_action['label'], html)

    def test_page_shows_not_configured_notice_without_pusher(self):
        with patch(GET_PUSHER, return_value=None):
            resp = self.client.get(reverse('grades_ce:sis_sync'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('not configured', html)
        self.assertNotIn('id="sis-sections-table"', html)
        self.assertNotIn(grade_sis_actions._find_action('send_sections')['label'], html)

    def test_actions_refused_without_pusher(self):
        section = self.make_section()
        reg = self.make_registration(section)
        with patch(GET_PUSHER, return_value=None), patch(ENQUEUE_TASK) as task:
            with self.captureOnCommitCallbacks(execute=True):
                r1 = self.post_action('send_sections', [section.id])
                r2 = self.post_action('send_registrations', [reg.id])
        self.assertEqual(r1.status_code, 403)
        self.assertEqual(r2.status_code, 403)
        self.assertEqual(r1.json()['outcome'], 'alert')
        task.assert_not_called()
        self.assertFalse(GradeSISSync.objects.exists())

    def test_feeds_refused_without_pusher(self):
        with patch(GET_PUSHER, return_value=None):
            for name in ('sis-sections-list', 'sis-registrations-list'):
                resp = self.client.get(reverse(f'grades_ce:{name}') + '?format=datatables')
                self.assertEqual(resp.status_code, 403, name)

    def test_unknown_slug_400_before_method_check(self):
        resp = self.client.get(reverse('grades_ce:sis_action') + '?action=nope')
        self.assertEqual(resp.status_code, 400)

    def test_get_known_slug_405(self):
        resp = self.client.get(reverse('grades_ce:sis_action') + '?action=send_sections')
        self.assertEqual(resp.status_code, 405)

    def test_non_ce_user_refused_at_endpoint(self):
        self.client.force_login(self.teacher.user)
        resp = self.client.post(reverse('grades_ce:sis_action'), {
            'action': 'send_sections', 'ids[]': []})
        self.assertIn(resp.status_code, (302, 403))

    def test_non_ce_user_refused_at_feeds(self):
        self.client.force_login(self.teacher.user)
        for name in ('sis-sections-list', 'sis-registrations-list'):
            resp = self.client.get(reverse(f'grades_ce:{name}') + '?format=datatables')
            self.assertIn(resp.status_code, (302, 403), name)


class SISSectionFeedTests(_SISPageBase):
    def test_section_counts_ignore_dash(self):
        section = self.make_section()
        self.make_registration(section, grade='A')
        self.make_registration(section, grade='-')
        self.make_registration(section, grade='   ')

        row = self.sections_feed()[0]

        self.assertEqual(row['graded_count'], 1)
        self.assertEqual(row['not_sent_count'], 1)

    def test_section_counts_follow_roster_statuses(self):
        section = self.make_section()
        self.make_registration(section, grade='A')
        self.make_registration(section, grade='B', status='dropped')

        row = self.sections_feed()[0]

        self.assertEqual(row['graded_count'], 1)

    def test_section_counts_by_sync_status(self):
        section = self.make_section()
        self.make_registration(section)
        for status in ('sent', 'sent', 'needs_mirroring', 'failed', 'queued'):
            reg = self.make_registration(section)
            GradeSISSync.objects.create(registration=reg, status=status)

        row = self.sections_feed()[0]

        self.assertEqual(row['graded_count'], 6)
        self.assertEqual(row['sent_count'], 2)
        self.assertEqual(row['needs_mirroring_count'], 1)
        self.assertEqual(row['failed_count'], 1)
        self.assertEqual(row['not_sent_count'], 1)

    def test_only_submitted_sections_in_grade_terms(self):
        submitted = self.make_section()
        self.make_section(grade_status='saved')
        self.make_section(term=self.other_term)

        ids = {r['id'] for r in self.sections_feed()}

        self.assertEqual(ids, {str(submitted.id)})

    def test_filters_by_term_and_highschool(self):
        from cis.models.highschool import HighSchool
        other_hs = HighSchool.objects.create(name='HS Other')
        at_hs = self.make_section()
        at_hs.highschool = self.highschool
        at_hs.save()
        elsewhere = self.make_section()
        elsewhere.highschool = other_hs
        elsewhere.save()

        ids = {r['id'] for r in self.sections_feed(f'&highschool={self.highschool.id}')}
        self.assertEqual(ids, {str(at_hs.id)})

        ids = {r['id'] for r in self.sections_feed(f'&term={self.term.id}')}
        self.assertEqual(ids, {str(at_hs.id), str(elsewhere.id)})

        # A term outside the grade terms narrows to nothing; it never widens scope.
        ids = {r['id'] for r in self.sections_feed(f'&term={self.other_term.id}')}
        self.assertEqual(ids, set())

        # A malformed filter value is ignored, not a 500.
        ids = {r['id'] for r in self.sections_feed('&term=junk&highschool=junk')}
        self.assertEqual(ids, {str(at_hs.id), str(elsewhere.id)})


class SISRegistrationFeedTests(_SISPageBase):
    def test_registration_feed_filters_by_sync_status(self):
        section = self.make_section()
        unsent = self.make_registration(section)
        failed = self.make_registration(section)
        GradeSISSync.objects.create(registration=failed, status='failed', last_error='x')

        ids = {r['id'] for r in self.registrations_feed('&sync_status=failed')}
        self.assertEqual(ids, {str(failed.id)})
        ids = {r['id'] for r in self.registrations_feed('&sync_status=not_sent')}
        self.assertEqual(ids, {str(unsent.id)})

    def test_registration_feed_excludes_blank_and_off_roster(self):
        section = self.make_section()
        graded = self.make_registration(section)
        self.make_registration(section, grade='-')
        self.make_registration(section, grade='  ')
        self.make_registration(section, status='dropped')
        self.make_registration(self.make_section(term=self.other_term))

        ids = {r['id'] for r in self.registrations_feed()}

        self.assertEqual(ids, {str(graded.id)})

    def test_registration_feed_filters_by_term_and_section(self):
        first = self.make_section()
        second = self.make_section()
        in_first = self.make_registration(first)
        in_second = self.make_registration(second)

        ids = {r['id'] for r in self.registrations_feed(f'&section={first.id}')}
        self.assertEqual(ids, {str(in_first.id)})

        ids = {r['id'] for r in self.registrations_feed(f'&term={self.term.id}')}
        self.assertEqual(ids, {str(in_first.id), str(in_second.id)})

        ids = {r['id'] for r in self.registrations_feed(f'&term={self.other_term.id}')}
        self.assertEqual(ids, set())

        ids = {r['id'] for r in self.registrations_feed('&section=junk&term=junk')}
        self.assertEqual(ids, {str(in_first.id), str(in_second.id)})

    def test_last_sent_at_is_local_time(self):
        reg = self.make_registration(self.make_section())
        # 20:30 UTC on 15 Jan is 12:30 PM in America/Los_Angeles (PST, UTC-8).
        sent_at = datetime(2040, 1, 15, 20, 30, tzinfo=dt_timezone.utc)
        GradeSISSync.objects.create(registration=reg, status='sent', sent_grade='A',
                                    last_sent_at=sent_at, last_sent_by=self.ce_user)

        row = self.registrations_feed()[0]

        self.assertEqual(row['last_sent_at'], '01/15/2040 12:30 PM')
        self.assertEqual(row['sync_status'], 'Sent')
        self.assertEqual(row['sent_grade'], 'A')

    def test_log_url_is_latest_attempt(self):
        reg = self.make_registration(self.make_section())
        sync = GradeSISSync.objects.create(registration=reg, status='failed')
        now = timezone.now()
        GradeSISSyncAttempt.objects.create(sync=sync, attempted_at=now - timedelta(hours=1),
                                           success=False, log_url='/old/')
        GradeSISSyncAttempt.objects.create(sync=sync, attempted_at=now,
                                           success=False, log_url='/new/')

        row = self.registrations_feed()[0]

        self.assertEqual(row['log_url'], '/new/')

    def test_every_column_orders_and_searches_without_error(self):
        section = self.make_section()
        section.highschool = self.highschool
        section.save()
        reg = self.make_registration(section)
        sync = GradeSISSync.objects.create(
            registration=reg, status='sent', sent_grade='A', last_sent_at=timezone.now(),
            last_sent_by=self.ce_user, last_error='x')
        GradeSISSyncAttempt.objects.create(sync=sync, attempted_at=timezone.now(),
                                           success=True, log_url='/x/')
        self.make_registration(section)
        html = self.client.get(reverse('grades_ce:sis_sync')).content.decode()

        for table, url_name in (('sis-sections', 'sis-sections-list'),
                                ('sis-registrations', 'sis-registrations-list')):
            columns = _page_columns(html, table)
            self.assertTrue(columns)
            # Only the select-checkbox column may opt out of ordering/search.
            for col in columns:
                if col.get('orderable', True) is False or col.get('searchable', True) is False:
                    self.assertEqual(col.get('className'), 'select-checkbox',
                                     f'{table} {col["data"]} opts out of order/search')
            base = {'format': 'datatables', 'draw': '1', 'start': '0', 'length': '10'}
            for i, col in enumerate(columns):
                self.assertTrue(col.get('data'), f'{table} column {i} has no data key')
                base[f'columns[{i}][data]'] = col['data']
                base[f'columns[{i}][name]'] = col.get('name', '')
                base[f'columns[{i}][searchable]'] = 'true' if col.get('searchable', True) else 'false'
                base[f'columns[{i}][orderable]'] = 'true' if col.get('orderable', True) else 'false'
            url = reverse(f'grades_ce:{url_name}')
            for i, col in enumerate(columns):
                for direction in ('asc', 'desc'):
                    params = dict(base, **{'order[0][column]': str(i),
                                           'order[0][dir]': direction})
                    resp = self.client.get(url, params)
                    self.assertEqual(resp.status_code, 200,
                                     f'{table} order {col["data"]} {direction}')
                    self.assertEqual(resp.json()['recordsFiltered'],
                                     resp.json()['recordsTotal'])
                params = dict(base, **{'order[0][column]': str(i), 'order[0][dir]': 'asc',
                                       'search[value]': 'x',
                                       f'columns[{i}][search][value]': '1'})
                resp = self.client.get(url, params)
                self.assertEqual(resp.status_code, 200, f'{table} search {col["data"]}')


class SISActionTests(_SISPageBase):
    def test_send_sections_enqueues_and_reports_skipped(self):
        submitted = self.make_section()
        reg = self.make_registration(submitted)
        draft = self.make_section(grade_status='saved')

        with patch(ENQUEUE_TASK) as task:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.post_action('send_sections', [submitted.id, draft.id])

        body = resp.json()
        self.assertEqual(body['outcome'], 'call')
        self.assertEqual(body['fn'], 'onBulkActionComplete')
        self.assertIn('1 registration', body['args']['message'])
        self.assertIn('not submitted', body['args']['message'])
        task.assert_called_once_with([str(reg.id)], self.ce_user.pk)

    def test_send_sections_ignores_out_of_scope_ids(self):
        other = self.make_section(term=self.other_term)
        self.make_registration(other)

        with patch(ENQUEUE_TASK) as task:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                resp = self.post_action('send_sections', [other.id, 'junk'])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(callbacks, [])
        task.assert_not_called()
        self.assertFalse(GradeSISSync.objects.exists())

    def test_send_registrations_skips_blank_and_in_flight(self):
        section = self.make_section()
        good = self.make_registration(section)
        blank = self.make_registration(section, grade='-')
        in_flight = self.make_registration(section)
        queued_at = timezone.now() - timedelta(minutes=1)
        GradeSISSync.objects.create(registration=in_flight, status=GradeSISSync.QUEUED,
                                    last_attempt_at=queued_at)

        with patch(ENQUEUE_TASK) as task:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.post_action('send_registrations', [good.id, blank.id, in_flight.id])

        task.assert_called_once_with([str(good.id)], self.ce_user.pk)
        self.assertIn('1 registration', resp.json()['args']['message'])
        self.assertIn('2 skipped', resp.json()['args']['message'])
        in_flight_sync = GradeSISSync.objects.get(registration=in_flight)
        self.assertEqual(in_flight_sync.last_attempt_at, queued_at)
        self.assertFalse(GradeSISSync.objects.filter(registration=blank).exists())

    def test_send_registrations_ignores_ids_outside_page_queryset(self):
        section = self.make_section()
        off_roster = self.make_registration(section, status='dropped')
        other_term = self.make_registration(self.make_section(term=self.other_term))

        with patch(ENQUEUE_TASK) as task:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                resp = self.post_action('send_registrations',
                                        [off_roster.id, other_term.id, 'junk', ''])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(callbacks, [])
        task.assert_not_called()
        self.assertFalse(GradeSISSync.objects.exists())

    def test_send_registrations_skips_unsubmitted_section(self):
        draft = self.make_section(grade_status='saved')
        in_draft = self.make_registration(draft)
        submitted = self.make_section()
        ok = self.make_registration(submitted)

        with patch(ENQUEUE_TASK) as task:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.post_action('send_registrations', [in_draft.id, ok.id])

        task.assert_called_once_with([str(ok.id)], self.ce_user.pk)
        message = resp.json()['args']['message']
        self.assertIn('1 skipped', message)
        self.assertIn('not submitted', message)
        self.assertFalse(GradeSISSync.objects.filter(registration=in_draft).exists())

    def test_send_registrations_does_not_resend_sent_rows(self):
        section = self.make_section()
        sent = self.make_registration(section)
        sent_at = timezone.now() - timedelta(days=1)
        GradeSISSync.objects.create(registration=sent, status=GradeSISSync.SENT,
                                    sent_grade='A', last_sent_at=sent_at,
                                    last_attempt_at=sent_at)

        with patch(ENQUEUE_TASK) as task:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                resp = self.post_action('send_registrations', [sent.id])

        self.assertEqual(callbacks, [])
        task.assert_not_called()
        self.assertIn('already sent', resp.json()['args']['message'])
        sync = GradeSISSync.objects.get(registration=sent)
        self.assertEqual(sync.status, GradeSISSync.SENT)
        self.assertEqual(sync.last_attempt_at, sent_at)
