$(document).ready(function () {
    var config = $('#grades-config');
    var apiURL = config.data('classes-api');

    $('#records_classes').DataTable({
        ajax: apiURL,
        serverSide: true,
        processing: true,
        stateSave: true,
        language: {
            'loadingRecords': '&nbsp;',
        },
        'lengthMenu': [30, 50, 100],
        'columns': [
            {
                'render': function (data, type, row, meta) {
                    return row.term.label;
                }
            },
            {
                'render': function (data, type, row, meta) {
                    return row.course.cohort.designator + ' ' + row.course.catalog_number + '<br>' + row.course.title;
                }
            },
            {
                'render': function (data, type, row, meta) {
                    return row.class_number;
                }
            },
            {
                'render': function (data, type, row, meta) {
                    var status = row.grade_status ? row.grade_status.toUpperCase() : '-';

                    // Roster confirmation gate: flag the section rather than
                    // hiding it, so an instructor can see why it is not
                    // gradeable yet. The server enforces the gate; this is
                    // signposting only.
                    if (config.data('require-roster-confirmation') &&
                        row.roster_status === 'pending verification') {
                        status += ' <span class="badge badge-warning">Roster not confirmed</span>';
                    }

                    return status;
                }
            },
            {
                'searchable': false,
                'orderable': false,
                'render': function (data, type, row, meta) {
                    return "<a class='btn btn-sm btn-primary' href='/instructor/grades/class_section/" + row.id + "'>Manage/Edit</a>";
                }
            }
        ]
    });
});
