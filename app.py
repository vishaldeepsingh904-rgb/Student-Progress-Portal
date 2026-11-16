import pandas as pd
import streamlit as st

from portal_db import (
    SUBJECTS, authenticate, connect, get_subject_records, init_db,
    list_students, save_subject_record, update_student,
)
from ml_support import build_model, risk_label, suggested_focus, support_probability
from gmail_reports import start_email_scheduler

st.set_page_config(page_title="Student Progress Portal", page_icon="🎓", layout="wide")


@st.cache_resource
def initialize_database():
    init_db()


initialize_database()


@st.cache_resource
def get_risk_model():
    return build_model()


RISK_MODEL = get_risk_model()


@st.cache_resource
def configure_email_scheduler():
    """Read Streamlit secrets and start the background email scheduler."""
    try:
        enabled_value = st.secrets.get("AUTO_EMAIL_ENABLED", False)
        sender = str(st.secrets.get("GMAIL_SENDER", "")).strip()
        password = str(st.secrets.get("GMAIL_APP_PASSWORD", "")).replace(" ", "")
        interval = max(1, int(st.secrets.get("EMAIL_INTERVAL_MINUTES", 1)))

        enabled = (
            enabled_value is True
            or str(enabled_value).strip().lower() == "true"
        )

        if not enabled:
            return False, interval, None, "AUTO_EMAIL_ENABLED is missing or not true."
        if not sender:
            return False, interval, None, "GMAIL_SENDER is missing."
        if not password:
            return False, interval, None, "GMAIL_APP_PASSWORD is missing."

        scheduler = start_email_scheduler(sender, password, interval)
        return True, interval, scheduler, "Gmail scheduler started."

    except Exception as error:
        # Do not display or log the Gmail App Password.
        return False, 1, None, f"Gmail setup error: {type(error).__name__}: {error}"


EMAIL_ACTIVE, EMAIL_INTERVAL, EMAIL_SCHEDULER, EMAIL_MESSAGE = configure_email_scheduler()


def attendance_total(records):
    held = sum(int(r["periods_held"] or 0) for r in records)
    attended = sum(int(r["periods_attended"] or 0) for r in records)
    return attended, held, (attended * 100 / held if held else None)


def record_table(records):
    rows = []
    for r in records:
        held = int(r["periods_held"] or 0)
        attended = int(r["periods_attended"] or 0)
        attendance_pct = attended * 100 / held if held else 75.0
        mst_pct = float(r["mst1"]) / 40 * 100 if r["mst1"] is not None else 60.0
        assignment_pct = float(r["assignment1"]) / 20 * 100 if r["assignment1"] is not None else 60.0
        has_data = held > 0 or r["mst1"] is not None or r["assignment1"] is not None
        risk = (
            support_probability(RISK_MODEL, attendance_pct, mst_pct, assignment_pct)
            if has_data else None
        )
        rows.append({
            "Subject": r["subject"],
            "Total Periods Held": held,
            "Total Periods Attended": attended,
            "Attendance %": round(attended * 100 / held, 2) if held else None,
            "MST1 (/40)": r["mst1"],
            "Assignment1 (/20)": r["assignment1"],
            "ML Support Risk": f"{risk_label(risk)} ({risk:.0%})" if risk is not None else "—",
            "Suggested Focus": (
                suggested_focus(attendance_pct, mst_pct, assignment_pct)
                if has_data else "—"
            ),
        })
    return pd.DataFrame(rows)


def login_screen():
    st.title("🎓 Student Progress Portal")
    if EMAIL_ACTIVE:
        st.success(f"Automatic Gmail check is active (every {EMAIL_INTERVAL} minute(s)).")
    else:
        st.warning("Automatic Gmail is off.")
        st.caption(EMAIL_MESSAGE)

    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", type="primary")

    if submitted:
        account = authenticate(username.strip(), password)
        if account:
            st.session_state.user = account
            st.rerun()
        st.error("Username or password is incorrect.")

    with st.expander("Demo login details"):
        st.write("Teacher: `teacher` / `teach123`")
        st.write("Students: `student01`–`student20` / `student123`")


if "user" not in st.session_state:
    login_screen()
    st.stop()


user = st.session_state.user
with st.sidebar:
    st.write(f"Signed in: **{user['username']}** · {user['role'].title()}")
    if st.button("Log out"):
        del st.session_state.user
        st.rerun()

st.title("🎓 Student Progress Portal")

if user["role"] == "student":
    with connect() as conn:
        student = conn.execute(
            "SELECT * FROM students WHERE student_id=?", (user["student_id"],)
        ).fetchone()

    records = get_subject_records(user["student_id"])
    st.header(f"Student: {student['name']} · {student['student_id']}")
    st.caption("View only · subject-wise attendance and marks")
    st.dataframe(record_table(records), hide_index=True, use_container_width=True)
    st.caption(
        "ML support-risk estimate and study focus are demo guidance only; "
        "the model was trained on synthetic data, not validated student outcomes."
    )

    attended, held, percent = attendance_total(records)
    if percent is None:
        st.info("Overall attendance will appear after classes are recorded.")
    else:
        st.metric("Overall attendance", f"{percent:.2f}%", f"{attended} / {held} total periods attended")

    low = [r for r in records if r["mst1"] is not None and float(r["mst1"]) < 16]
    for r in low:
        st.warning(f"{r['subject']}: MST1 is below 40%. Write this paper three times for practice.")
        if EMAIL_ACTIVE and student["student_email"]:
            st.caption("A student practice email will be checked by the scheduler.")
        else:
            st.caption("For automatic email, configure Gmail and add this student's email in the roster.")
    st.stop()


st.header("Teacher dashboard")
st.caption("Choose a student; all attendance and marks entered below apply to that student.")
students = list_students()
labels = {f"{s['name']} · {s['student_id']}": s["student_id"] for s in students}
chosen = st.selectbox("Select student", list(labels))
sid = labels[chosen]
student = next(s for s in students if s["student_id"] == sid)
st.info(f"You are recording attendance and marks for: **{student['name']}** · ID **{sid}**")
records = get_subject_records(sid)

left, right = st.columns([1, 2])
with left:
    st.subheader("Take today's attendance")
    with st.form("attendance_form"):
        subject = st.selectbox("Subject", SUBJECTS)
        status = st.radio("Today's status", ["Present", "Absent"], horizontal=True)
        save_attendance = st.form_submit_button("Save attendance", type="primary")
    if save_attendance:
        old = next(r for r in get_subject_records(sid) if r["subject"] == subject)
        save_subject_record(
            sid, subject, int(old["periods_held"]) + 1,
            int(old["periods_attended"]) + (status == "Present"),
            old["mst1"], old["assignment1"],
        )
        st.success(f"{student['name']} marked {status.lower()} for {subject}.")
        st.rerun()
    st.caption("Each save adds one held period to this subject.")

with right:
    st.subheader("Marks for all subjects")
    st.caption("MST1 is out of 40; Assignment1 is out of 20. Alerts use MST1 < 16/40.")
    marks = record_table(records)[["Subject", "MST1 (/40)", "Assignment1 (/20)"]]
    edited = st.data_editor(
        marks, hide_index=True, use_container_width=True,
        key=f"marks_{sid}", disabled=["Subject"],
        column_config={
            "MST1 (/40)": st.column_config.NumberColumn(min_value=0, max_value=40, step=0.5),
            "Assignment1 (/20)": st.column_config.NumberColumn(min_value=0, max_value=20, step=0.5),
        },
    )
    if st.button("Save marks for this student", type="primary"):
        old_by_subject = {r["subject"]: r for r in get_subject_records(sid)}
        for _, row in edited.iterrows():
            old = old_by_subject[row["Subject"]]
            mst = None if pd.isna(row["MST1 (/40)"]) else float(row["MST1 (/40)"])
            assignment = None if pd.isna(row["Assignment1 (/20)"]) else float(row["Assignment1 (/20)"])
            save_subject_record(
                sid, row["Subject"], old["periods_held"], old["periods_attended"],
                mst, assignment,
            )
        st.success(f"Marks saved for {student['name']}.")
        st.rerun()

st.subheader(f"Current subject record · {student['name']}")
records = get_subject_records(sid)
st.dataframe(record_table(records), hide_index=True, use_container_width=True)
st.caption(
    "ML support risk is a classroom demo trained on synthetic labels; "
    "do not treat it as a validated prediction for real students."
)

attended, held, percent = attendance_total(records)
if percent is None:
    st.info("Overall attendance appears after at least one class is recorded.")
else:
    st.metric("Overall attendance", f"{percent:.2f}%", f"{attended} / {held} periods attended across all subjects")

for r in records:
    if r["mst1"] is not None and float(r["mst1"]) < 16:
        if EMAIL_ACTIVE and student["student_email"]:
            st.caption(f"{r['subject']}: student practice email is queued for the next scheduler check.")
        else:
            st.warning(f"{r['subject']} is below 40%; add the student's email and configure Gmail to send the alert.")

with st.expander("Automatic email status"):
    if EMAIL_ACTIVE:
        st.success(f"Gmail checks for changed attendance/marks every {EMAIL_INTERVAL} minute(s).")
        st.caption(
            "Parents receive the subject table and overall attendance; students receive "
            "an alert when MST1 is below 16/40. No duplicate email is sent when a student's "
            "record has not changed."
        )
    else:
        st.warning("Email sending is currently disabled.")
        st.code(EMAIL_MESSAGE)
    st.caption(
        "The Streamlit app must remain running. Use your own email addresses for a test "
        "run before adding parent contacts."
    )

with st.expander("Import student contacts"):
    st.caption("CSV columns: student_id,name,parent_email,student_email.")
    template = pd.DataFrame([{
        "student_id": "student01", "name": "Student 01",
        "parent_email": "parent@example.com", "student_email": "student@example.com",
    }])
    st.download_button(
        "Download roster CSV template", template.to_csv(index=False),
        "student_roster_template.csv", "text/csv",
    )
    uploaded = st.file_uploader("Upload roster CSV", type=["csv"])
    if uploaded:
        roster = pd.read_csv(uploaded, dtype=str).fillna("")
        required = {"student_id", "name", "parent_email", "student_email"}
        if not required.issubset(roster.columns):
            st.error("CSV must contain student_id, name, parent_email, student_email.")
        elif set(roster.student_id) - {s["student_id"] for s in students}:
            st.error("This demo accepts student01 through student20 only.")
        elif st.button("Import contacts"):
            for _, row in roster.iterrows():
                update_student(
                    row["student_id"], row["name"],
                    parent_email=row["parent_email"], student_email=row["student_email"],
                )
            st.success(f"Imported {len(roster)} student contacts.")
            st.rerun()

st.divider()
st.caption(
    "Overall attendance = total periods attended ÷ total periods held across subjects. "
    "Email checks run on the configured interval only while this app is running."
)
