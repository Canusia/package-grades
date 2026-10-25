"""Grades page-message providers (auto-discovered by cis.apps.ready)."""
from django.utils.html import format_html

from cis.page_messages import PageMessage, page_message

from .services.open_periods import open_period_summary


def _messages(sections, tile_id=''):
    out = []
    for period, submitted, total in open_period_summary(sections):
        pending = total - submitted
        if pending:
            out.append(PageMessage(text=format_html(
                '<strong>{}</strong> is open through {} &mdash; {} of {} class(es) not submitted.',
                period.name, period.due_on.strftime('%m/%d/%Y'), pending, total),
                level='warning', tile_id=tile_id))
        else:
            out.append(PageMessage(text=format_html(
                '<strong>{}</strong>: grades submitted for all {} class(es).', period.name, total),
                level='success'))
    return out


def _teacher_sections(request):
    from cis.models.section import ClassSection
    return list(ClassSection.objects.filter(teacher__user=request.user, status='A'))


def _hs_admin_sections(request):
    from cis.models.section import ClassSection
    from .views.hs_admin import _hs_admin_context
    _, highschools = _hs_admin_context(request)
    return list(ClassSection.objects.filter(highschool__in=highschools, status='A'))


@page_message('instructor', 'grades')
def instructor_grades(request):
    return _messages(_teacher_sections(request))


@page_message('instructor', 'dashboard')
def instructor_dashboard(request):
    return _messages(_teacher_sections(request), tile_id='id_tile_grades')


@page_message('highschool_admin', 'dashboard')
def hs_admin_dashboard(request):
    from .services.gating import hs_admin_grade_entry_enabled
    if not hs_admin_grade_entry_enabled():
        return []
    return _messages(_hs_admin_sections(request))
