/**
 * Student Grades/Registrations DataTable
 *
 * Initializes a DataTable for displaying student class registrations
 * with status=registered filter.
 */
(function($) {
    'use strict';

    var tbl_student_class_registrations;

    $(document).ready(function() {
        tbl_student_class_registrations = $('#student_class_registrations').DataTable({
            ajax: '/student/api/registrations/?status=registered&format=datatables',
            lengthMenu: [50, 100],
            searching: false,
            columns: [
                {
                    searchable: false,
                    orderable: false,
                    render: function(data, type, row, meta) {
                        return row.class_section.term.label;
                    }
                },
                {
                    width: '20%',
                    render: function(data, type, row, meta) {
                        return row.class_section.course.name +
                            ' (' + row.class_section.course.credit_hours + ' credits)<br>' +
                            '<span class="text-muted">' + row.class_section.course.title + '</span><br>' +
                            row.class_section.class_number + ' - ' + row.class_section.section_number + '<br>' +
                            row.class_section.highschool_course_name;
                    }
                },
                {
                    render: function(data, type, row, meta) {
                        return '$' + parseFloat(row.class_section.tuition).toFixed(2);
                    }
                },
                {
                    sortable: false,
                    searchable: false,
                    render: function(data, type, row, meta) {
                        return row.status_pretty;
                    }
                },
                {
                    sortable: false,
                    searchable: false,
                    render: function(data, type, row, meta) {
                        return row.submitted_grade;
                    }
                }
            ]
        });
    });

})(jQuery);
