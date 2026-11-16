"""Gmail SMTP reports. Sending stays disabled until local secrets are configured."""
from datetime import datetime
from email.message import EmailMessage
import hashlib
import json
import logging
import smtplib
import ssl

from portal_db import connect, get_subject_records, list_students


def _digest(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _send_email(sender, app_password, recipient, subject, body):
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    context = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=25) as server:
        server.starttls(context=context)
        server.login(sender, app_password)
        server.send_message(message)


def _parent_report(student, records):
    held = sum(int(r["periods_held"] or 0) for r in records)
    attended = sum(int(r["periods_attended"] or 0) for r in records)
    overall = (100 * attended / held) if held else 0
    lines = [
        f"Student: {student['name']} ({student['student_id']})",
        f"Overall attendance: {overall:.1f}% ({attended} of {held} periods)",
        "",
        "Subject-wise attendance and marks:",
    ]
    for r in records:
        sh = int(r["periods_held"] or 0)
        sa = int(r["periods_attended"] or 0)
        pct = f"{100 * sa / sh:.1f}%" if sh else "No classes recorded"
        mst = f"{float(r['mst1']):g}/40" if r["mst1"] is not None else "Not entered"
        assignment = f"{float(r['assignment1']):g}/20" if r["assignment1"] is not None else "Not entered"
        lines.append(f"- {r['subject']}: attendance {pct} ({sa}/{sh}); MST1 {mst}; Assignment1 {assignment}")
    lines.extend(["", "This is an automated academic progress update from the student portal."])
    return "Daily attendance and marks update", "\n".join(lines)


def send_changed_reports(sender, app_password):
    """Check every configured interval and email only changed reports."""
    for student in list_students():
        sid = student["student_id"]
        records = get_subject_records(sid)
        populated = [r for r in records if int(r["periods_held"] or 0) > 0 or r["mst1"] is not None or r["assignment1"] is not None]
        if not populated:
            continue
        parent_data = [{k: r[k] for k in ("subject", "periods_held", "periods_attended", "mst1", "assignment1")} for r in records]
        parent_hash = _digest(parent_data)
        low = [r for r in records if r["mst1"] is not None and float(r["mst1"]) < 16]
        alert_data = [{"subject": r["subject"], "mst1": float(r["mst1"])} for r in low]
        alert_hash = _digest(alert_data) if low else ""
        try:
            with connect() as conn:
                state = conn.execute("SELECT * FROM email_delivery_state WHERE student_id=?", (sid,)).fetchone()
            if student["parent_email"] and (not state or state["parent_hash"] != parent_hash):
                subject, body = _parent_report(student, records)
                _send_email(sender, app_password, student["parent_email"], subject, body)
                with connect() as conn:
                    conn.execute("""INSERT INTO email_delivery_state(student_id,parent_hash,student_alert_hash)
                        VALUES(?,?,?) ON CONFLICT(student_id) DO UPDATE SET parent_hash=excluded.parent_hash""",
                        (sid, parent_hash, ""))
                logging.info("Parent progress email sent for %s", sid)
            if student["student_email"] and low and (not state or state["student_alert_hash"] != alert_hash):
                lines = [f"Your MST1 result is below 40% in these subjects:"]
                for r in low:
                    lines.append(f"- {r['subject']}: {float(r['mst1']):g}/40")
                    lines.append(f"  Please write the {r['subject']} paper three times for practice.")
                _send_email(sender, app_password, student["student_email"], "MST1 practice alert", "\n".join(lines))
                with connect() as conn:
                    conn.execute("""INSERT INTO email_delivery_state(student_id,parent_hash,student_alert_hash)
                        VALUES(?,?,?) ON CONFLICT(student_id) DO UPDATE SET student_alert_hash=excluded.student_alert_hash""",
                        (sid, "", alert_hash))
                logging.info("Low-MST alert email sent for %s", sid)
            elif not low:
                with connect() as conn:
                    conn.execute("""INSERT INTO email_delivery_state(student_id,parent_hash,student_alert_hash)
                        VALUES(?,?, '') ON CONFLICT(student_id) DO UPDATE SET student_alert_hash=''""", (sid, ""))
        except Exception:
            logging.exception("Could not send progress email for %s", sid)


def start_email_scheduler(sender, app_password, interval_minutes=1):
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(daemon=True, timezone="Asia/Kolkata")
    scheduler.add_job(
        send_changed_reports, "interval", minutes=max(1, int(interval_minutes)),
        args=[sender, app_password], id="student_progress_email_check",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    scheduler.start()
    return scheduler
