"""post_save flags needs_mirroring when a sent grade changes."""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from ..models import GradeSISSync, GradeSISSyncAttempt
from .sis_fixtures import SISFixtureMixin


class FlagGradeChangeTests(SISFixtureMixin, TestCase):
    def setUp(self):
        self.reg = self.make_registration(self.make_section(), grade='A')

    def _sync(self, status='sent', sent_grade='A'):
        return GradeSISSync.objects.create(
            registration=self.reg, status=status, sent_grade=sent_grade)

    def test_sent_grade_change_flags_needs_mirroring(self):
        self._sync()
        self.reg.grade = 'B'
        self.reg.save()

        sync = GradeSISSync.objects.get(registration=self.reg)
        self.assertEqual(sync.status, 'needs_mirroring')
        self.assertIsNotNone(sync.grade_changed_at)

    def test_reverting_to_sent_grade_unflags(self):
        self._sync(status='needs_mirroring')
        self.reg.grade = 'A'
        self.reg.save(update_fields=['grade'])

        self.assertEqual(GradeSISSync.objects.get(registration=self.reg).status, 'sent')

    def test_same_grade_resave_is_noop(self):
        self._sync()
        self.reg.save()

        self.assertEqual(GradeSISSync.objects.get(registration=self.reg).status, 'sent')

    def test_update_fields_without_grade_is_noop(self):
        sync = self._sync()
        self.reg.grade = 'C'  # in memory only; not saved
        sync_table = GradeSISSync._meta.db_table
        attempt_table = GradeSISSyncAttempt._meta.db_table
        with CaptureQueriesContext(connection) as ctx:
            self.reg.save(update_fields=['sis_id'])

        for query in ctx.captured_queries:
            sql = query['sql']
            self.assertNotIn(sync_table, sql)
            self.assertNotIn(attempt_table, sql)

        sync.refresh_from_db()
        self.assertEqual(sync.status, 'sent')
        self.assertEqual(sync.sent_grade, 'A')

    def test_failed_and_queued_left_alone(self):
        for status in ('failed', 'queued'):
            GradeSISSync.objects.filter(registration=self.reg).delete()
            self._sync(status=status)
            self.reg.grade = 'C'
            self.reg.save()
            self.assertEqual(GradeSISSync.objects.get(registration=self.reg).status, status)

    def test_never_sent_registration_creates_no_row(self):
        self.reg.grade = 'C'
        self.reg.save()

        self.assertFalse(GradeSISSync.objects.filter(registration=self.reg).exists())
