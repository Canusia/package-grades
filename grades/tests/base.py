"""Test base for hosts with and without MULTI_CAMPUS.

On a multi-campus host every AcademicYear needs a campus, and CampusMiddleware
needs a Site/Campus for the test client's host. GradesTestCase enters one test
campus for the whole class (setUpTestData and every test); on a single-campus
host it does nothing.
"""
from django.conf import settings
from django.test import TestCase

from ..compat import has_module


def _multi_campus():
    return bool(getattr(settings, 'MULTI_CAMPUS', False))


def test_campus():
    """The campus reachable at 'testserver' (created on first use)."""
    from django.contrib.sites.models import Site
    from cis.models import Campus
    site, _ = Site.objects.update_or_create(
        pk=getattr(settings, 'SITE_ID', 1),
        defaults={'domain': 'testserver', 'name': 'testserver'})
    prefix = getattr(settings, 'CAMPUS_CODE_PREFIX', 'TEST')
    campus, _ = Campus.objects.update_or_create(
        code=f'{prefix}_A', defaults={'name': 'Test Campus', 'site': site})
    return campus


class GradesTestCase(TestCase):
    """TestCase that runs inside a campus context on multi-campus hosts."""

    @classmethod
    def _enter_test_campus(cls):
        if not _multi_campus() or not has_module('cis.campus_context'):
            return
        from cis.campus_context import campus_context, current_campus_or_none
        if current_campus_or_none() is not None:
            return
        cls.campus = test_campus()
        cls.enterClassContext(campus_context(cls.campus))

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        own = cls.__dict__.get('setUpTestData')
        if own is None:
            return
        func = own.__func__

        def wrapped(klass):
            klass._enter_test_campus()
            func(klass)
        cls.setUpTestData = classmethod(wrapped)

    @classmethod
    def setUpTestData(cls):
        cls._enter_test_campus()
