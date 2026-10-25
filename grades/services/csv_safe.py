"""CSV formula-injection guard shared by every grades CSV export."""


def safe_cell(value):
    """Prefix ' when a text cell would be read as a formula by a spreadsheet."""
    value = '' if value is None else str(value)
    return "'" + value if value[:1] in ('=', '+', '-', '@', '\t', '\r') else value
