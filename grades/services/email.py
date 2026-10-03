"""The one place grades emails are sent from (#2).

Applies the `is_active` master switch (Yes / Debug / No) and the
`debug_email_list`, replacing the hard-coded DEBUG recipient that used to sit in
each sender. With `settings.DEBUG` on, `Yes` is treated as `Debug`, so a dev or
misconfigured tenant cannot mail real instructors: mail goes to the debug list,
or nowhere when the list is empty.
"""
from django.conf import settings
from django.core.validators import validate_email

from mailer import send_html_mail

YES, DEBUG, NO = 'Yes', 'Debug', 'No'


def parse_addresses(value):
    """Comma/newline-separated text -> list of stripped, non-empty addresses."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = str(value).replace('\n', ',').replace(';', ',').split(',')
    return [a.strip() for a in items if a and a.strip()]


def invalid_addresses(value):
    bad = []
    for address in parse_addresses(value):
        try:
            validate_email(address)
        except Exception:
            bad.append(address)
    return bad


def email_mode(configs):
    mode = configs.get('is_active') or YES
    if mode == YES and getattr(settings, 'DEBUG', False):
        return DEBUG
    return mode


def resolve_recipients(configs, to):
    """The addresses a grades email should actually go to; [] means don't send."""
    mode = email_mode(configs)
    if mode == NO:
        return []
    if mode == DEBUG:
        return parse_addresses(configs.get('debug_email_list'))
    return [a for a in parse_addresses(to) if not invalid_addresses([a])]


def send_grades_mail(configs, subject, text_body, html_body, to):
    """Send through the switch. Returns the recipients used ([] = nothing sent)."""
    recipients = resolve_recipients(configs, to)
    if recipients:
        send_html_mail(
            subject, text_body, html_body, settings.DEFAULT_FROM_EMAIL, recipients)
    return recipients
