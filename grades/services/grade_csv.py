"""One class section's grades as CSV: the grid's student columns plus a
column per grading period (interim marks and the final grade)."""
import csv

from django.http import HttpResponse
from django.utils.text import slugify

from .csv_safe import safe_cell
from .grade_grid import build_grid


def grades_csv_response(section):
    grid = build_grid(section, post_url='', next_url='', allow_edit=False)
    response = HttpResponse(content_type='text/csv')
    filename = slugify(f'{section} grades') or 'grades'
    response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
    writer = csv.writer(response)
    writer.writerow([safe_cell(c.header) for c in grid['columns']]
                    + [safe_cell(p['period'].name) for p in grid['periods']])
    for row in grid['rows']:
        writer.writerow([safe_cell(v) for v in row['cells'] + row['marks']])
    return response
