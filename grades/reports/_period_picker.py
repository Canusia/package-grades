"""A Grading Period(s) picker that follows a report form's Term(s) field.

Each period option carries ``data-term``; the script enables only periods of
the selected terms or their sub-terms (every period while no term is
selected) and unselects the others. The server still validates the pairing
(services.report_marks.periods_outside_terms_error).

On the report page (report/templates/reports/index.html) the form arrives by
jQuery ``.html()``, which runs this script before the page wraps every
``select[multiple]`` with the multiple-select 1.5.2 plugin. That plugin
reports a pick with a jQuery-only ``trigger('change')`` and builds its
checkbox list from the options once, so the script listens through jQuery,
marks options ``disabled`` (which the plugin honours; ``hidden`` it ignores),
calls ``multipleSelect('refresh')`` once the plugin is attached, and syncs
again after the plugin has initialised.
"""
import json
import uuid

from crispy_forms.layout import LayoutObject
from django import forms
from django.utils.html import json_script
from django.utils.safestring import mark_safe

from ..compat import term_groups


class PeriodSelectMultiple(forms.SelectMultiple):
    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        period = getattr(value, 'instance', None)
        if period is not None:
            option['attrs']['data-term'] = str(period.term_id)
        return option


_SCRIPT = """<script>(function () {
  var cfg = JSON.parse(document.getElementById(%(data_id)s).textContent);
  var form = document.getElementById(%(data_id)s).closest('form');
  if (!form) { return; }
  var terms = form.querySelector('select[name="' + cfg.term + '"]');
  var periods = form.querySelector('select[name="' + cfg.periods + '"]');
  if (!terms || !periods) { return; }
  var $ = window.jQuery, last = null;
  function plugin() {
    return $ && $.fn && $.fn.multipleSelect && $(periods).data('multipleSelect');
  }
  function sync() {
    var allowed = {}, any = false, key = [];
    Array.prototype.forEach.call(terms.options, function (o) {
      if (!o.selected || !o.value) { return; }
      any = true;
      (cfg.groups[o.value] || [o.value]).forEach(function (id) { allowed[id] = true; });
    });
    Array.prototype.forEach.call(periods.options, function (o) {
      var ok = !any || !!allowed[o.getAttribute('data-term')];
      o.disabled = !ok;
      o.hidden = !ok;
      if (!ok) { o.selected = false; }
      key.push(ok ? 1 : 0, o.selected ? 1 : 0);
    });
    var ms = plugin();
    key = key.join('');
    if (ms && (ms !== last || key !== ms._gradesKey)) {
      ms._gradesKey = key;
      last = ms;
      $(periods).multipleSelect('refresh');
    }
  }
  if ($) { $(terms).on('change', sync); } else { terms.addEventListener('change', sync); }
  sync();
  setTimeout(sync, 0);
  setTimeout(sync, 300);
})();</script>"""


class FollowTerms(LayoutObject):
    """Crispy layout object emitting the period/term data (via json_script)
    and the script that wires the two fields. Rendered as-is, not as a
    Django template."""

    def __init__(self, groups, periods_field='periods', term_field='term'):
        self.groups = groups
        self.periods_field = periods_field
        self.term_field = term_field
        self.fields = []

    @property
    def html(self):
        data_id = f'grades-period-picker-{uuid.uuid4().hex}'
        data = json_script({'groups': self.groups, 'periods': self.periods_field,
                            'term': self.term_field}, data_id)
        return mark_safe(data + _SCRIPT % {'data_id': json.dumps(data_id)})

    def render(self, form, context=None, template_pack=None, **kwargs):
        return self.html


def follow_terms(term_queryset, periods_field='periods', term_field='term'):
    """A crispy layout object wiring ``periods_field`` to ``term_field``."""
    groups = {str(term_id): sorted(str(i) for i in ids)
              for term_id, ids in term_groups(list(term_queryset.values_list('pk', flat=True))).items()}
    return FollowTerms(groups, periods_field, term_field)
