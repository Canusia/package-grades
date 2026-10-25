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
                         start_date='not a date', end_date='12/09/2026')
        lines = _run()
        self.assertFalse(GradingPeriod.objects.exists())
        self.assertTrue(any('skipped' in line for line in lines))

    def test_no_setting_row(self):
        _run()  # must not raise
