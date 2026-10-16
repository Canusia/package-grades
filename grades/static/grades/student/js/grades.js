/**
 * Student Grades DataTable
 *
 * Columns come from the #grade-columns JSON the template renders from
 * services.student_table (the student_grade_columns setting), so the <th> row
 * and this config cannot drift. Rows come from student:grades_rows, already
 * HTML-escaped and limited to those columns.
 */
(function($) {
    'use strict';

    $(document).ready(function() {
        var columns = JSON.parse(document.getElementById('grade-columns').textContent);

        $('#student_class_registrations').DataTable({
            ajax: $('#student_class_registrations').data('rows-url'),
            lengthMenu: [50, 100],
            searching: false,
            order: [],
            columns: columns.map(function(column) {
                return {data: column.key};
            })
        });
    });

})(jQuery);
