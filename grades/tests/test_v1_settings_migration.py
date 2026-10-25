"""v1: data migration from the old window to Final Grades periods (spec §1)."""
import importlib
from datetime import date

from .base import GradesTestCase
from . import factories as f
from ..models import GradingPeriod

mig = importlib.import_module(
    GradingPeriod.__module__.rsplit('.', 1)[0] + '.migrations.0005_settings_to_periods')


def _run():
    from cis.models.settings import Setting
    from cis.models.term import Term
    lines = []
    mig.migrate_settings(Setting, Term, GradingPeriod, f.grades_key(), log=lines.append)
    return lines


class SettingsMigrationTests(GradesTestCase):
    def test_creates_final_period_for_period_less_term(self):
        t = f.term()
        f.grades_setting(terms=[str(t.id)], start_date='12/01/2026',
                         end_date='12/09/2026', grades_open='<p>Open</p>')
        _run()
        p = GradingPeriod.objects.get(term=t)
        self.assertEqual((p.name, p.is_final, p.opens_on, p.due_on),
                         ('Final Grades', True, date(2026, 12, 1), date(2026, 12, 9)))
        self.assertEqual((p.reminder_frequency_days, p.remind_days_before_due,
                          p.visible_to_students), (0, 0, False))

    def test_term_with_periods_untouched(self):
        t = f.term()
        f.period(t, 'Mid 1', date(2026, 10, 1), date(2026, 10, 9))
        f.grades_setting(terms=[str(t.id)], start_date='12/01/2026', end_date='12/09/2026')
        _run()
        self.assertEqual(list(GradingPeriod.objects.filter(term=t).values_list('name', flat=True)), ['Mid 1'])

    def test_retired_keys_removed_and_intro_copied(self):
        from cis.models.settings import Setting
        t = f.term()
        f.grades_setting(terms=[str(t.id)], start_date='12/01/2026', end_date='12/09/2026',
                         grades_open='<p>Open</p>', grades_closed='<p>Closed</p>',
                         reminder_dates='12/05/2026')
        _run()
        value = Setting.objects.get(key=f.grades_key()).value
        self.assertEqual(value['grades_intro'], '<p>Open</p>')
        for key in ('terms', 'start_date', 'end_date', 'reminder_dates', 'grades_open', 'grades_closed'):
            self.assertNotIn(key, value)

    def test_messy_values_do_not_abort(self):
        f.grades_setting(terms='', start_date='', end_date='')
        _run()
        f.grades_setting(terms=['00000000-0000-0000-0000-000000000000'],
                         start_date='12/01/2026', end_date='12/09/2026')
        lines = _run()
        self.assertTrue(any('no such term' in line for line in lines))
        t = f.term()
        f.grades_setting(terms=[str(t.id)], start_date='not a date', end_date='12/09/2026')
        lines = _run()
        self.assertFalse(GradingPeriod.objects.exists())
        self.assertTrue(any('no usable start/end dates' in line for line in lines), lines)

    def test_non_dict_value_and_non_list_terms(self):
        from cis.models.settings import Setting
        Setting.objects.update_or_create(key=f.grades_key(), defaults={'value': ['junk']})
        lines = _run()
        self.assertEqual(Setting.objects.get(key=f.grades_key()).value, ['junk'])
        self.assertTrue(any('not a dict' in line for line in lines))
        f.grades_setting(terms=42, start_date='12/01/2026', end_date='12/09/2026')
        _run()
        self.assertNotIn('terms', Setting.objects.get(key=f.grades_key()).value)

    def test_iso_dates_accepted(self):
        t = f.term()
        f.grades_setting(terms=[str(t.id)], start_date='2026-12-01', end_date='2026-12-09')
        _run()
        p = GradingPeriod.objects.get(term=t)
        self.assertEqual((p.opens_on, p.due_on), (date(2026, 12, 1), date(2026, 12, 9)))

    def test_blank_intro_is_filled(self):
        from cis.models.settings import Setting
        f.grades_setting(grades_intro='', grades_open='<p>Open</p>')
        _run()
        self.assertEqual(Setting.objects.get(key=f.grades_key()).value['grades_intro'], '<p>Open</p>')

    def test_existing_intro_kept(self):
        from cis.models.settings import Setting
        f.grades_setting(grades_intro='<p>Mine</p>', grades_open='<p>Open</p>')
        _run()
        self.assertEqual(Setting.objects.get(key=f.grades_key()).value['grades_intro'], '<p>Mine</p>')

    def test_failing_row_is_logged_and_skipped(self):
        from unittest.mock import patch
        t = f.term()
        f.grades_setting(terms=[str(t.id)], start_date='12/01/2026', end_date='12/09/2026')
        with patch.object(GradingPeriod.objects, 'create', side_effect=RuntimeError('boom')):
            lines = _run()  # must not raise
        self.assertTrue(any('boom' in line for line in lines))
        self.assertFalse(GradingPeriod.objects.exists())

    def test_no_setting_row(self):
        _run()  # must not raise
