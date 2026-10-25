"""v1: student columns on the grade grid (spec §3)."""
from unittest import mock

from .base import GradesTestCase
from . import factories as f
from ..services import columns


class ColumnTests(GradesTestCase):
    def test_defaults(self):
        with mock.patch.object(columns, 'get_tenant_override', return_value=None):
            self.assertEqual([c.key for c in columns.get_columns()], columns.DEFAULT_KEYS)

    def test_tenant_adds_highschool(self):
        def tenant(builtin, default_keys):
            return [builtin[k] for k in default_keys + ['highschool']]
        with mock.patch.object(columns, 'get_tenant_override', return_value=tenant):
            self.assertEqual([c.key for c in columns.get_columns()][-1], 'highschool')

    def test_values(self):
        hs = f.highschool('Bob Hope HS')
        reg = f.registration(f.section(f.term()), highschool_obj=hs,
                             last_name='Amador', first_name='Helena', psid='P1')
        values = {k: c.value(reg) for k, c in columns.BUILTIN.items()}
        self.assertEqual(values, {'last_name': 'Amador', 'first_name': 'Helena',
                                  'psid': 'P1', 'highschool': 'Bob Hope HS'})

    def test_tenant_returning_junk_falls_back(self):
        with mock.patch.object(columns, 'get_tenant_override', return_value=lambda b, d: None):
            self.assertEqual([c.key for c in columns.get_columns()], columns.DEFAULT_KEYS)
