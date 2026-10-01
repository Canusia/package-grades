"""GradeSISSync / GradeSISSyncAttempt schema and migration hygiene."""
import importlib

from django.conf import settings
from django.db import migrations
from django.test import TestCase

from ..models import GradeSISSync, GradeSISSyncAttempt


class SyncModelTests(TestCase):
    def test_status_values(self):
        self.assertEqual(
            {c[0] for c in GradeSISSync.STATUS_CHOICES},
            {'queued', 'sent', 'failed', 'needs_mirroring'})

    def test_attempts_ordered_newest_first(self):
        self.assertEqual(GradeSISSyncAttempt._meta.ordering, ['-attempted_at'])

    def test_migration_depends_only_on_cis_first(self):
        module = importlib.import_module(
            GradeSISSync.__module__.rsplit('.', 1)[0] + '.migrations.0002_gradesissync')
        deps = set(module.Migration.dependencies)
        self.assertEqual(
            deps,
            {
                ('cis', '__first__'),
                migrations.swappable_dependency(settings.AUTH_USER_MODEL),
                ('grades', '0001_initial'),
            },
        )
