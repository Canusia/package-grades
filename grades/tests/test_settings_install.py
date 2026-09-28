"""install() is seed-only (package-cis #51)."""
from unittest import mock

from django.http import HttpRequest
from django.test import TestCase

from cis.models.settings import Setting
from ..settings.class_section_grades import class_section_grades


class InstallIsSeedOnlyTests(TestCase):
    """install() must never overwrite a customised setting (package-cis #51).

    The old tail assigned `setting.value = defaults` on the existing row as
    well as a new one, so any re-run of install() replaced a tenant's
    configuration with shipped placeholders.
    """
    settings_classes = [class_section_grades]

    def _install(self, cls):
        cls(HttpRequest()).install()

    def test_creates_the_setting_when_absent(self):
        for cls in self.settings_classes:
            with self.subTest(cls.__name__):
                Setting.objects.filter(key=cls.key).delete()
                self._install(cls)
                self.assertTrue(Setting.objects.filter(key=cls.key).exists())

    def test_customised_values_survive_install(self):
        for cls in self.settings_classes:
            with self.subTest(cls.__name__):
                Setting.objects.filter(key=cls.key).delete()
                self._install(cls)
                defaults = Setting.objects.get(key=cls.key).value
                custom = {k: f'custom-{k}' for k in defaults} or {'custom': 'value'}
                Setting.objects.filter(key=cls.key).update(value=custom)

                self._install(cls)

                self.assertEqual(Setting.objects.get(key=cls.key).value, custom)
