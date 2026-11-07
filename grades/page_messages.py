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


def _hs_admin_sections(request, highschools=None):
    from cis.models.section import ClassSection
    from .compat import has_secondary_sections, sections_at_highschools_q
    if highschools is None:
        from .views.hs_admin import _hs_admin_context
        _, highschools = _hs_admin_context(request)
    # Primary or secondary school (cis#154).
    sections = ClassSection.objects.filter(
        sections_at_highschools_q(highschools), status='A').select_related('course')
    if has_secondary_sections():
        sections = sections.prefetch_related('secondary_highschool_links')
    return list(sections)


@page_message('instructor', 'grades')
def instructor_grades(request):
    return _messages(_teacher_sections(request))


@page_message('instructor', 'dashboard')
def instructor_dashboard(request):
    return _messages(_teacher_sections(request), tile_id='id_tile_grades')


def _hs_admin_submit_sections(request):
    """The admin's sections they may enter grades for (#16): Can submit
    grades held, for the course's campus, at the school they act for -- the
    primary school when it is one of theirs, else their own secondary
    schools (as views.hs_admin.admin_scope decides)."""
    from .services.gating import submit_grade_grants
    from .compat import section_highschool_ids
    from .views.hs_admin import _hs_admin_context
    # (school, campus) pairs this admin holds the grant for; campus None is
    # an all-campus grant. One query, then a check per section in memory.
    grants = submit_grade_grants(request.user)
    if not grants:
        return []
    _, highschools = _hs_admin_context(request)
    admin_ids = set(highschools.values_list('id', flat=True))
    out = []
    for section in _hs_admin_sections(request, highschools):
        if section.highschool_id in admin_ids:
            acting = [section.highschool_id]
        else:
            acting = [h for h in section_highschool_ids(section) if h in admin_ids]
        campus_id = getattr(section.course, 'campus_id', None)
        if any((hs, None) in grants or (hs, campus_id) in grants for hs in acting):
            out.append(section)
    return out


@page_message('highschool_admin', 'dashboard')
def hs_admin_dashboard(request):
    return _messages(_hs_admin_submit_sections(request))
