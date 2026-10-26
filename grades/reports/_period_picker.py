"""A Grading Period(s) picker that follows a report form's Term(s) field.

Each period option carries ``data-term``; the script shows only periods of
the selected terms or their sub-terms (every period while no term is
selected) and unselects hidden ones. The server still validates the pairing
(services.report_marks.periods_outside_terms_error).
"""
import json

from django import forms
from crispy_forms.layout import HTML

from ..compat import term_groups


class PeriodSelectMultiple(forms.SelectMultiple):
    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        period = getattr(value, 'instance', None)
        if period is not None:
            option['attrs']['data-term'] = str(period.term_id)
        return option


_SCRIPT = """<script>(function () {
  var groups = %s;
  var pickers = document.querySelectorAll('select[name="%s"]');
  var periods = pickers[pickers.length - 1];
  var terms = periods && periods.form && periods.form.querySelector('select[name="%s"]');
  if (!terms) { return; }
  function sync() {
    var allowed = {}, any = false;
    Array.prototype.forEach.call(terms.options, function (o) {
      if (!o.selected || !o.value) { return; }
      any = true;
      (groups[o.value] || [o.value]).forEach(function (id) { allowed[id] = true; });
    });
    Array.prototype.forEach.call(periods.options, function (o) {
      var ok = !any || allowed[o.getAttribute('data-term')];
      o.hidden = !ok;
      o.disabled = !ok;
      if (!ok) { o.selected = false; }
    });
  }
  terms.addEventListener('change', sync);
  sync();
})();</script>"""


def follow_terms(term_queryset, periods_field='periods', term_field='term'):
    """A crispy HTML layout object wiring ``periods_field`` to ``term_field``."""
    groups = {str(term_id): sorted(str(i) for i in ids)
              for term_id, ids in term_groups(list(term_queryset.values_list('pk', flat=True))).items()}
    return HTML(_SCRIPT % (json.dumps(groups), periods_field, term_field))
