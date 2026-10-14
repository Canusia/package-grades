/*
 * Grade roster (instructor and HS admin): sortable columns and auto-save.
 *
 * Sorting only reorders <tr> elements. Each row keeps its own formset inputs
 * (form-N-student_id / form-N-grade), so the order on screen never changes
 * which grade is saved against which registration.
 *
 * Auto-save posts the whole form as "Save Grades as 'Draft'" with
 * X-Requested-With, which the view answers with JSON. One request is in flight
 * at a time; a change made meanwhile is sent once it returns, so the last
 * choice always wins.
 */
(function () {
    'use strict';

    var SORT_STORAGE_KEY = 'grades.roster.sort';
    var DRAFT_VALUE = "Save Grades as 'Draft'";

    // --- sorting -----------------------------------------------------------

    function loadSort() {
        try {
            var saved = JSON.parse(window.localStorage.getItem(SORT_STORAGE_KEY));
            if (saved && saved.key) { return saved; }
        } catch (e) { /* storage unavailable: use the default */ }
        return { key: 'last_name', dir: 'asc' };
    }

    function storeSort(sort) {
        try {
            window.localStorage.setItem(SORT_STORAGE_KEY, JSON.stringify(sort));
        } catch (e) { /* not essential */ }
    }

    function dataKey(key) {
        // last_name -> lastName, matching element.dataset.
        return key.replace(/_([a-z])/g, function (m, c) { return c.toUpperCase(); });
    }

    function compareRows(a, b, key) {
        var prop = dataKey(key);
        var primary = (a.dataset[prop] || '').localeCompare(
            b.dataset[prop] || '', undefined, { numeric: true, sensitivity: 'base' });
        if (primary !== 0) { return primary; }
        // Ties fall back to last name, then first name.
        return (a.dataset.lastName || '').localeCompare(b.dataset.lastName || '', undefined, { sensitivity: 'base' })
            || (a.dataset.firstName || '').localeCompare(b.dataset.firstName || '', undefined, { sensitivity: 'base' });
    }

    function applySort(table, sort) {
        var tbody = table.tBodies[0];
        if (!tbody) { return; }
        var rows = Array.prototype.slice.call(tbody.rows);
        rows.sort(function (a, b) {
            var result = compareRows(a, b, sort.key);
            return sort.dir === 'desc' ? -result : result;
        });
        rows.forEach(function (row) { tbody.appendChild(row); });

        table.querySelectorAll('[data-sort-key]').forEach(function (button) {
            var active = button.dataset.sortKey === sort.key;
            var th = button.closest('th');
            var icon = button.querySelector('i');
            if (th) {
                th.setAttribute('aria-sort', active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none');
            }
            if (icon) {
                icon.className = 'fas ' + (active ? (sort.dir === 'asc' ? 'fa-sort-up' : 'fa-sort-down') : 'fa-sort');
            }
        });
    }

    function initSorting() {
        var tables = document.querySelectorAll('table.js-sortable-roster');
        if (!tables.length) { return; }
        var sort = loadSort();

        tables.forEach(function (table) {
            applySort(table, sort);
            table.querySelectorAll('[data-sort-key]').forEach(function (button) {
                button.addEventListener('click', function () {
                    var key = button.dataset.sortKey;
                    sort = {
                        key: key,
                        dir: (sort.key === key && sort.dir === 'asc') ? 'desc' : 'asc'
                    };
                    storeSort(sort);
                    applySort(table, sort);
                });
            });
        });
    }

    // --- auto-save ---------------------------------------------------------

    function setRowStatus(row, text, cssClass) {
        var el = row && row.querySelector('.autosave-status');
        if (!el) { return; }
        el.textContent = text;
        el.className = 'autosave-status d-block ' + cssClass;
    }

    function initAutosave() {
        var form = document.querySelector('form[data-autosave="1"]');
        if (!form) { return; }

        var summary = form.querySelector('.autosave-summary');
        var inFlight = false;
        var pending = false;
        var stopped = false;
        var dirtyRows = new Set();   // changed since the last request was sent
        var sendingRows = new Set(); // included in the request in flight
        var failed = false;

        function setSummary(text, cssClass) {
            if (!summary) { return; }
            summary.textContent = text;
            summary.className = 'autosave-summary mr-2 ' + cssClass;
        }

        function finish(ok, message) {
            var time = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
            sendingRows.forEach(function (row) {
                if (dirtyRows.has(row)) { return; } // changed again; a newer save follows
                setRowStatus(row, ok ? 'Saved' : 'Not saved', ok ? 'text-success' : 'text-danger');
            });
            sendingRows = new Set();
            failed = !ok;
            setSummary(ok ? 'Draft saved at ' + time + '.' : message, ok ? 'text-muted' : 'text-danger');
        }

        function send() {
            if (stopped) { return; }
            if (inFlight) { pending = true; return; }
            inFlight = true;
            pending = false;
            sendingRows = new Set(dirtyRows);
            dirtyRows.clear();
            setSummary('Saving…', 'text-muted');

            var data = new FormData(form);
            data.set('save_grade', DRAFT_VALUE);
            data.delete('submit_grade');

            fetch(window.location.href, {
                method: 'POST',
                body: data,
                credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            }).then(function (response) {
                return response.json().catch(function () { return {}; }).then(function (body) {
                    if (response.ok && body.ok) {
                        finish(true);
                        return;
                    }
                    var message = body.error || 'Grades could not be saved. Use "Save Grades as \'Draft\'".';
                    if (response.status === 403 || response.status === 409) {
                        // Closed window, roster gate, or already submitted:
                        // retrying cannot succeed, so stop auto-saving.
                        stopped = true;
                    }
                    finish(false, message);
                });
            }).catch(function () {
                finish(false, 'Connection problem: grades not saved. They will be retried on your next change.');
            }).then(function () {
                inFlight = false;
                if (pending || dirtyRows.size) { send(); }
            });
        }

        form.addEventListener('change', function (event) {
            var target = event.target;
            if (!target.matches('select[name$="-grade"]')) { return; }
            var row = target.closest('tr');
            dirtyRows.add(row);
            setRowStatus(row, 'Saving…', 'text-muted');
            send();
        });

        window.addEventListener('beforeunload', function (event) {
            if (inFlight || dirtyRows.size || failed) {
                event.preventDefault();
                event.returnValue = '';
            }
        });

        // A normal submit (Draft / Submit Final) sends everything itself.
        form.addEventListener('submit', function () {
            stopped = true;
            dirtyRows.clear();
            failed = false;
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        initSorting();
        initAutosave();
    });
})();
