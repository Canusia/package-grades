# Grades — Internal Guide (v1.0.0)

How the grades package works for CE staff, instructors, high school admins and
students: grading periods, what each portal shows, the reports and their
columns, and the settings. For upgrade steps and the change list see
[CHANGELOG.md](../CHANGELOG.md).

**Where grades live**

| Grade | Stored on | Exported to the SIS |
|---|---|---|
| Interim (mid-semester) marks | `PeriodGrade`, one per student per period, with change history: each actual change and who made it (re-saving an unchanged grade records nothing) | No |
| Final grade | `StudentRegistration.grade` (cis), with change history (written only when the grade actually changes) | Yes |

Submission state is per class and per grading period (`SectionPeriodStatus`:
Not Started, Draft, Submitted). The final period's state is mirrored onto the
class's `grade_status`, which the SIS push and older pages read.

---

## 1. Grading periods

Grading periods belong to a **term**. They decide when grades can be entered,
when reminders go out and when students see grades. There are no grade dates
in the settings.

**Where:** CE → Terms → *term* → **Grading Periods** tab (add, edit, delete).

| Field | Meaning |
|---|---|
| Name | Shown everywhere (e.g. "Mid-Semester Grades 1", "Final Grades"). Unique within the term. |
| Sequence | Order within the term (grid columns, reports). |
| Opens On / Due On | Grades can be entered from *Opens On* through *Due On*. Due cannot be before opens. |
| Final Grade Collection | The final grade collection: writes the registration grade sent to the SIS. At most one per term. |
| Reminder Frequency (days) | Re-email instructors who have not submitted every N days while the period is open. 0 = off. |
| Remind Days Before Due | One extra reminder this many days before *Due On*. 0 = off. |
| Visible to Students | Students see this period's grades once their class has submitted them. |

**Rules**

- Periods on one term cannot overlap.
- A class follows **its own term's** periods. A class on a sub-term (e.g.
  "Fall 2026 - First Half Term") does not inherit the parent term's periods:
  give the sub-term its own periods if its classes need grades.
- A term with no grading periods has no grade entry. Pages show "No grading
  periods are set up for this class's term."
- A period is **editable** by the instructor or HS admin only while it is open,
  not yet submitted, and (if the setting is on) the roster is confirmed. CE can
  edit any period at any time.
- **Submit** locks the period for the instructor. Only CE **Reopen** un-submits it.
- On a multi-campus host each campus has its own terms, so each campus sets up
  its own periods.

**Reminders** — the `notify_period_grades_pending` job (scheduled by the
setting's cron, below) emails each instructor with unsubmitted, active classes
in an open period. The job only runs when *Send Grades-Due Reminders* is Yes,
and a period only sends reminders when it has a frequency or a days-before-due
value. An instructor gets at most one reminder email a day per grading
period, and none once the period is submitted. The old `notify_grades_pending` job does nothing since v1.0.0;
delete its cron.

---

## 2. CE staff

| Where | What |
|---|---|
| **Terms → term → Grading Periods** | Set up periods (section 1). |
| **Class Sections → Grades tab** | Per-period progress for the selected term (submitted / draft / not started / % complete), and the final-grade distribution. Has a term switcher. |
| **Class Section → Grades tab** | The class's grid: one column per period, read-only. Each period's status, dates and **Edit** / **Reopen** sit in the card header, beside **Download Roster** and **Download Grades** (CSV). |
| **Edit** (from the Grades tab) | Edit one period for the instructor, any period at any time, with no auto-save. Saving a submitted period keeps it submitted. Every save adds a **class note** naming the staff member and listing each change (`Last, First: B → A`). |
| **Reopen** | Sets a submitted period back to Draft so the instructor can edit it again (while it is open). Adds a class note. |
| **Grades → Summary** (`/ce/grades/summary/`) | For one grading period: each instructor's classes, Submitted / Draft / Not Started, status and last reminder. Filter by high school. Download as CSV. **Remind** one instructor, or all who have not submitted. Shows only the CE user's campuses. |
| **Grades → SIS** (`/ce/grades/sis/`) | Final grades pushed to the SIS: per class (graded, sent, failed, not sent) and per registration (sync status, sent grade, last sent, sent by), with push actions. Registration pages also get a **Grade SIS** tab. |
| **Reports** | Section 6. |
| **Settings → Class Grades Settings** | Section 7. |

CE grade pages only open for classes on campuses the CE user may edit.

---

## 3. Instructors

| Where | What |
|---|---|
| **Dashboard** | A page message while a grading period is open for their classes. |
| **Grades** (`/instructor/grades/`) | Their classes for the current grade terms, with a term switcher ("All current terms" by default). Columns: Term, Course, CRN, High School, Students (count by registration status), Grades Status (each period's status, open periods marked), and Manage/Edit. Page messages and the *Grades Intro* text show above it. |
| **Grade page** (Manage/Edit) | The Class Details layout with two tabs, **Grades** (open) and **Notes**. The grid has one column per period; only the open, unsubmitted period is editable. Student columns default to Last Name, First Name and Student ID; a tenant can change them (Lamar adds High School). **Save as Draft** (auto-saves as you go) or **Submit** the period. **Download Roster** (PDF) and **Download Grades** (CSV). |
| **Class Details → Grades tab** | The same grid, inside the class page (only when the term has grading periods). |

Instructors can only open their own classes.

---

## 4. High school admins

What they get depends on the **High School Admin Grade Access** setting:

| Setting | Class page Grades tab | Enter / submit | Download Grades | Grades by Grading Period report |
|---|---|---|---|---|
| No access (default) | hidden | no | no | no (the form says access is turned off) |
| View grades only | read-only grid | no | yes | yes |
| View and enter grades | editable grid (same rules as instructors) | yes | yes | yes |

- Only classes at schools they administer (Active role). Other classes 404.
- With *View and enter*, their dashboard shows a page message while a period is open.
- **Reports:** *Grades by Grading Period* (section 6) follows the same setting:
  with No access they cannot run it. Otherwise it is limited to their schools
  that are Active at the class's campus.

---

## 5. Students

| Where | What |
|---|---|
| **Grades** (`/student/grades/`) | Their registrations. Columns are chosen in the settings: Term, Course / Section No., Tuition, Status, Grades. The Grades column shows the final grade once the class has submitted it, plus each period marked *Visible to students* once submitted. |
| **Unofficial transcript** | PDF download from the Grades page, built from the transcript templates in the settings. |

Both can be turned off in the settings (*Students Can See Their Grades*,
*Students Can Download the Unofficial Transcript*).

---

## 6. Reports

All run in the background and produce a CSV. On a multi-campus host every
report lists, and accepts, only the current campus's terms and grading periods.
Fields marked * are required.

### Grades by Grading Period
*For CE and HS admins* (HS admins only while High School Admin Grade Access is
View or View and enter; section 4). One row per student registration, one
column per selected period.

- **Filters:** Term(s)* (parent/sub-term tree; a parent includes its
  sub-terms), Grading Period(s)* (only periods of the selected terms can be
  picked; the server also rejects a period of another term),
  High School(s), Registration Status(es), Period Submission Status. No campus
  field: CE get the campuses they process; HS admins get their own Active schools.
- **Columns:** Term, Course, Class No., Section No., Instructor, Instructor
  Email, High School, Student Last Name, Student First Name, Student ID,
  Registration Status, then one column per selected period (the mark; blank if none).

### Grade Submission Status by Period
*For CE.* One row per class per grading period.

- **Filters:** Term(s)* (tree; parent includes sub-terms), Grading Period(s)
  (follows the terms, and the server rejects a period of another term; blank =
  every period), High School(s). No campus field.
- **Columns:** Term, Course, Grading Period, Final (Yes/No), Class No., Section
  No., Instructor, Instructor Email, High School, Status (Not Started / Draft /
  Submitted), Status Changed On, Last Reminder.

### Class Grade Status
*For CE.* One row per class: final-grade status and how many students are graded.

- **Filters:** Campus*, Term(s)*, Grade Status, High School(s).
- **Columns:** Term Code, Term, Course, Course Title, Class No., Section No.,
  Instructor Last Name, Instructor First Name, Instructor Email, High School,
  Grade Status, Grade Status Changed On, Students, Graded, Not Graded.

### Grade Distribution by Course / by High School / by Demographics
*For CE.* Counts of each grade, from the final grade or from one chosen grading period.

| Report | Filters | Row columns |
|---|---|---|
| by Course | Campus*, Term(s)*, Course(s), High School(s), Registration Status(es)*, Grading Period | Course, Stream, Credit Hours, Total Enrolled |
| by High School | Term(s)*, High School(s), Registration Status(es)*, Grading Period | High School, District, Total Enrolled |
| by Demographics | Campus*, Term(s)*, Group By* (Gender, Race/Ethnicity, Hispanic/Latino, First-Generation Student, Grade Level, Parent 1 Education Level), High School(s), Course(s), Registration Status(es)*, Grading Period | the group value, Total Enrolled |

Every distribution report then adds:

- one count column per grade in the **Grade Scale** setting, plus W;
- the same grades as percentages (`A%`, `B%`, … `W%`);
- **Success Rate** (A/B/C grades), **DFW Rate** (D, F and W), **Avg GPA**
  (from the scale's points).

Grading Period blank = final grade. Total Enrolled counts every registration
selected, including students without a mark for the chosen period.

---

## 7. Settings — Class Grades Settings

CE → Settings → **Class Grades Settings**. One per campus on a multi-campus
host. It holds no term- or date-specific values: those live on the grading
periods.

**Grades and roster**

| Setting | What it does |
|---|---|
| Grade Scale | The grades instructors can choose and their GPA points. It also sets the grade columns in the distribution reports. |
| Registration Status(es) | Which registrations appear on the grade grid. |
| Require roster confirmation before grades are entered | Blocks grade entry while the roster is Pending Verification. |
| Roster not confirmed message | Shown on the grid while blocked. |
| High School Admin Grade Access | No access / View grades only / View and enter grades (section 4). Old Yes = enter, No = no access. |

**Reminders and emails**

| Setting | What it does |
|---|---|
| Send Grades Emails | Master switch for grades emails. |
| Debug Email List | Where grades emails go in Debug mode. |
| Send Grades-Due Reminders | Turns the reminder job on or off. |
| When should the notification be sent? | Cron for `notify_period_grades_pending` (Min Hr Day Month WeekDay). |
| Grades Due Email Subject / Message | The reminder email. Merge fields: `{{teacher_first_name}}`, `{{teacher_last_name}}`, `{{term}}`, `{{number_of_sections_pending_grades}}`, `{{grading_period}}`, `{{due_date}}`. |
| Email the Instructor When Grades Are Submitted | Confirmation email to the instructor on submit. |
| Grades Submitted - Copy To | Extra addresses copied on every grades-submitted email (sent even when the instructor copy is off). |
| Grades Submitted - Email Subject / Email | The confirmation email. Merge fields: `{{instructor_first_name}}`, `{{instructor_last_name}}`, `{{course}}`, `{{class_number}}`. |

**Page text**

| Setting | Where it shows |
|---|---|
| Grades Intro | Above the instructor Grades class list. |
| Grades How To | On the grade grid while grades are not yet submitted. |
| Grades Submitted Message | On the grade grid once submitted. |

**Student portal**

| Setting | What it does |
|---|---|
| Students Can See Their Grades | Off shows a notice instead of the grades table. |
| Students Can Download the Unofficial Transcript | Off hides the download. |
| Student Grades Table Columns | Which columns the student Grades page shows (unchecked ones are not sent to the browser). |
| Transcript Header / Table Header / Row Template / Footer | HTML templates for the unofficial transcript PDF. Merge fields include `{{student_name}}`, `{{student_id}}`, `{{highschool}}`, `{{generated_date}}`, and per row `{{term}}`, `{{course_name}}`, `{{course_title}}`, `{{teacher}}`, `{{credit_hours}}`, `{{grade}}`. |
| Transcript Registration Status(es) | Which registrations appear on the transcript. |

**Tenant (code) hooks**, not settings: the grade grid's student columns
(`services/grades_columns.py` → `columns(builtin, default_keys)`).

---

## 8. Quick troubleshooting

| Symptom | Check |
|---|---|
| "No grading periods are set up" | The class's **own** term has no periods. |
| Instructor can't edit | Is the period open today, not submitted, and is the roster confirmed (if required)? CE can Reopen or Edit. |
| Report: "Choose grading periods of the selected term(s) only" | The period belongs to another term (the server checks this on every grades report). On the period reports, pick the term first: periods of other terms are greyed out and unselected. |
| HS admin: "High school admin access to grades is turned off." on Grades by Grading Period | High School Admin Grade Access is No access; set it to View or View and enter. |
| HS admin sees no Grades tab | High School Admin Grade Access is No access, or the class's school isn't one of theirs. |
| No reminders | Send Grades-Due Reminders = Yes, the cron is set, and the period has a reminder frequency or days-before-due. |
| Student sees no interim grade | The period must be *Visible to students* **and** submitted for that class. |
