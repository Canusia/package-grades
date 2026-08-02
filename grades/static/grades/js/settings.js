/**
 * Grade Settings Configurator JavaScript
 *
 * Provides dynamic UI components for the class_section_grades configurator:
 * - initReminderDatesPicker: Multi-date picker for grade reminder dates
 * - initGradeScaleTable: Dynamic table for grade scale configuration
 */

// Initialize flatpickr for multi-date reminder picker
function initReminderDatesPicker() {
    var $picker = $('.reminder-dates-picker');
    if ($picker.length && !$picker.data('flatpickr-initialized')) {
        var $startDate = $('input[name="start_date"]');
        var $endDate = $('input[name="end_date"]');

        var minDate = $startDate.val() || null;
        var maxDate = $endDate.val() || null;

        $picker.flatpickr({
            mode: 'multiple',
            dateFormat: 'm/d/Y',
            minDate: minDate,
            maxDate: maxDate,
            conjunction: ', ',
            allowInput: false,
            clickOpens: true,
            onChange: function(selectedDates, dateStr, instance) {
                // Sort dates chronologically
                selectedDates.sort(function(a, b) { return a - b; });
                var formatted = selectedDates.map(function(d) {
                    return instance.formatDate(d, 'm/d/Y');
                }).join(', ');
                $picker.val(formatted);
            }
        });
        $picker.data('flatpickr-initialized', true);

        // Update date constraints when start/end dates change
        $startDate.on('change', function() {
            var fp = $picker[0]._flatpickr;
            if (fp) fp.set('minDate', $(this).val());
        });
        $endDate.on('change', function() {
            var fp = $picker[0]._flatpickr;
            if (fp) fp.set('maxDate', $(this).val());
        });
    }
}

// Initialize Grade Scale dynamic table
function initGradeScaleTable() {
    var $hiddenField = $('#id_grade_scale');
    if (!$hiddenField.length || $hiddenField.data('table-initialized')) return;

    // Default grade scale
    var defaultScale = [
        {grade: 'A', points: 4.0}, {grade: 'A-', points: 3.7},
        {grade: 'B+', points: 3.3}, {grade: 'B', points: 3.0}, {grade: 'B-', points: 2.7},
        {grade: 'C+', points: 2.3}, {grade: 'C', points: 2.0}, {grade: 'C-', points: 1.7},
        {grade: 'D+', points: 1.3}, {grade: 'D', points: 1.0}, {grade: 'D-', points: 0.7},
        {grade: 'F', points: 0.0}
    ];

    // Parse existing value or use default
    var gradeScale = defaultScale;
    try {
        var val = $hiddenField.val();
        if (val) {
            gradeScale = JSON.parse(val);
        }
    } catch (e) {}

    // Create table container
    var $container = $('<div class="grade-scale-container mb-3"></div>');
    var $label = $('<label class="form-label"><strong>Grade Scale</strong></label>');
    var $helpText = $('<small class="form-text text-muted mb-2 d-block">Define grades and their GPA point values</small>');
    var $table = $('<table class="table table-sm table-bordered grade-scale-table" style="max-width: 400px;"></table>');
    var $thead = $('<thead class="thead-light"><tr><th>Grade</th><th>GPA Points</th><th style="width: 50px;"></th></tr></thead>');
    var $tbody = $('<tbody></tbody>');
    var $addBtn = $('<button type="button" class="btn btn-sm btn-outline-primary mt-2"><i class="fa fa-plus"></i> Add Grade</button>');

    function createRow(grade, points) {
        var $row = $('<tr></tr>');
        var $gradeInput = $('<input type="text" class="form-control form-control-sm grade-input" value="' + (grade || '') + '" placeholder="e.g., A+">');
        var $pointsInput = $('<input type="number" step="0.1" class="form-control form-control-sm points-input" value="' + (points !== undefined ? points : '') + '" placeholder="e.g., 4.0">');
        var $removeBtn = $('<button type="button" class="btn btn-sm btn-outline-danger"><i class="fa fa-times"></i></button>');

        $row.append($('<td></td>').append($gradeInput));
        $row.append($('<td></td>').append($pointsInput));
        $row.append($('<td class="text-center"></td>').append($removeBtn));

        $removeBtn.on('click', function() {
            $row.remove();
            updateHiddenField();
        });

        $gradeInput.on('change', updateHiddenField);
        $pointsInput.on('change', updateHiddenField);

        return $row;
    }

    function updateHiddenField() {
        var scale = [];
        $tbody.find('tr').each(function() {
            var grade = $(this).find('.grade-input').val().trim();
            var points = parseFloat($(this).find('.points-input').val());
            if (grade) {
                scale.push({grade: grade, points: isNaN(points) ? 0 : points});
            }
        });
        $hiddenField.val(JSON.stringify(scale));
    }

    // Populate table with existing data
    gradeScale.forEach(function(item) {
        $tbody.append(createRow(item.grade, item.points));
    });

    $addBtn.on('click', function() {
        $tbody.append(createRow('', ''));
    });

    $table.append($thead).append($tbody);
    $container.append($label).append($helpText).append($table).append($addBtn);

    // Insert before the registration_status field (first visible field)
    var $firstVisibleField = $('select[name="registration_status"], input[name="registration_status"]').closest('.form-group');
    if ($firstVisibleField.length) {
        $firstVisibleField.before($container);
    } else {
        // Fallback: insert after hidden field's container
        $hiddenField.closest('div').after($container);
    }
    $hiddenField.data('table-initialized', true);

    // Set initial value
    updateHiddenField();
}

// Initialize on AJAX complete (for settings forms loaded dynamically)
$(document).ajaxComplete(function() {
    initReminderDatesPicker();
    initGradeScaleTable();
});

// Also initialize on document ready
$(document).ready(function() {
    initReminderDatesPicker();
    initGradeScaleTable();
});
