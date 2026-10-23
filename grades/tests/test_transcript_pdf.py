"""Unofficial transcript (#6): grades ships its own page template, without the
full-height styling that pushed every transcript onto a blank second page."""
import re
import shutil
from types import SimpleNamespace
from unittest import mock, skipUnless

from django.test import RequestFactory, TestCase

from ..services.transcript import render_transcript

STUDENT = SimpleNamespace(
    user=SimpleNamespace(first_name='Ann', last_name='Lee', psid='P1'),
    suid='S1', highschool=SimpleNamespace(name='Central HS'))


def _no_registrations():
    chain = mock.MagicMock()
    chain.filter.return_value.select_related.return_value.order_by.return_value = []
    return mock.patch('cis.models.section.StudentRegistration.objects', chain)


class TranscriptTemplateTests(TestCase):
    def _page(self):
        request = RequestFactory().get('/x', {'mode': 'page'})
        with _no_registrations():
            return render_transcript(STUDENT, request).content.decode()

    def test_page_has_no_full_height_styling(self):
        html = self._page()
        self.assertNotIn('h-100', html)
        self.assertNotIn('height: 100%', html)
        self.assertIn('No courses found', html)

    @skipUnless(shutil.which('wkhtmltopdf'), 'wkhtmltopdf not installed')
    def test_short_transcript_is_one_page(self):
        with _no_registrations():
            pdf = render_transcript(STUDENT)
        pages = re.findall(rb'/Type\s*/Page\b', pdf)
        self.assertEqual(len(pages), 1)
