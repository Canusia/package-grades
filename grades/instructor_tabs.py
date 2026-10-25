"""The Grades tab on the instructor Class Details page (instructor portal's
tab registry). Imported from GradesConfig.ready(); a host without the
instructor portal simply gets no tab."""
from django.urls import reverse

from .compat import register, registry

instructor_class_section_tabs = (
    registry('instructor.instructor.registry', 'instructor_class_section_tabs')
    or registry('instructor.registry', 'instructor_class_section_tabs'))


def _has_periods(user, section):
    from .services.periods import periods_for_section
    return bool(periods_for_section(section))


@register(instructor_class_section_tabs, 'tab', slug='grades', title='Grades',
          order=50, lazy=True, permission=_has_periods,
          template='grades/instructor/_class_section_grades_tab.html')
def instructor_grades_tab(request, class_section):
    from .services.grade_grid import build_grid
    post_url = reverse('instructor:class_section_grade', args=[class_section.id])
    next_url = reverse('instructor:class_section', args=[class_section.id]) + '#grades'
    return {'grid': build_grid(class_section, post_url=post_url, next_url=next_url)}
