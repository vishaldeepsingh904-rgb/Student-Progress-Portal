"""SQLite storage and demo-account setup for the student portal."""
import hashlib
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "student_portal.db"
SUBJECTS = [
    "Programming in Python",
    "Software Engineering",
    "Computer Networks (CN)",
    "Formal Language & Automata Theory (FLAT)",
    "Enterprise Resource Planning (ERP)",
    "Database Management Systems (DBMS)",
]


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt.hex() + ":" + digest.hex()


def _verify(password: str, saved: str) -> bool:
    salt_hex, digest_hex = saved.split(":", 1)
    return _hash(password, bytes.fromhex(salt_hex)) == saved


def init_db():
    with connect() as conn:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY, name TEXT NOT NULL,
            parent_phone TEXT NOT NULL DEFAULT '', student_phone TEXT NOT NULL DEFAULT '',
            parent_email TEXT NOT NULL DEFAULT '', student_email TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('teacher','student')),
            student_id TEXT UNIQUE REFERENCES students(student_id)
        );
        CREATE TABLE IF NOT EXISTS results (
            student_id TEXT NOT NULL REFERENCES students(student_id), subject TEXT NOT NULL,
            attendance REAL NOT NULL CHECK(attendance >= 0 AND attendance <= 100),
            marks REAL NOT NULL CHECK(marks >= 0), total_marks REAL NOT NULL CHECK(total_marks > 0),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(student_id, subject)
        );
        CREATE TABLE IF NOT EXISTS subject_records (
            student_id TEXT NOT NULL REFERENCES students(student_id),
            subject TEXT NOT NULL,
            periods_held INTEGER NOT NULL DEFAULT 0 CHECK(periods_held >= 0),
            periods_attended INTEGER NOT NULL DEFAULT 0 CHECK(periods_attended >= 0 AND periods_attended <= periods_held),
            mst1 REAL CHECK(mst1 IS NULL OR (mst1 >= 0 AND mst1 <= 40)),
            assignment1 REAL CHECK(assignment1 IS NULL OR (assignment1 >= 0 AND assignment1 <= 20)),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(student_id, subject)
        );
        CREATE TABLE IF NOT EXISTS email_delivery_state (
            student_id TEXT PRIMARY KEY REFERENCES students(student_id),
            parent_hash TEXT NOT NULL DEFAULT '',
            student_alert_hash TEXT NOT NULL DEFAULT ''
        );
        """)
        student_columns = {r["name"] for r in conn.execute("PRAGMA table_info(students)").fetchall()}
        if "parent_email" not in student_columns:
            conn.execute("ALTER TABLE students ADD COLUMN parent_email TEXT NOT NULL DEFAULT ''")
        if "student_email" not in student_columns:
            conn.execute("ALTER TABLE students ADD COLUMN student_email TEXT NOT NULL DEFAULT ''")
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM users WHERE username='teacher'").fetchone():
            conn.execute("INSERT INTO users VALUES(?,?,?,NULL)", ("teacher", _hash("teach123"), "teacher"))
        for i in range(1, 21):
            sid = f"student{i:02}"
            if not conn.execute("SELECT 1 FROM students WHERE student_id=?", (sid,)).fetchone():
                conn.execute("INSERT INTO students(student_id,name) VALUES(?,?)", (sid, f"Student {i:02}"))
            if not conn.execute("SELECT 1 FROM users WHERE username=?", (sid,)).fetchone():
                conn.execute("INSERT INTO users VALUES(?,?,?,?)", (sid, _hash("student123"), "student", sid))


def authenticate(username: str, password: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if row and _verify(password, row["password_hash"]):
        return {"username": row["username"], "role": row["role"], "student_id": row["student_id"]}
    return None


def list_students():
    with connect() as conn:
        return conn.execute("SELECT * FROM students ORDER BY student_id").fetchall()


def get_subject_records(student_id):
    with connect() as conn:
        found = {r["subject"]: dict(r) for r in conn.execute(
            "SELECT * FROM subject_records WHERE student_id=?", (student_id,)
        ).fetchall()}
    return [found.get(subject, {
        "student_id": student_id, "subject": subject, "periods_held": 0,
        "periods_attended": 0, "mst1": None, "assignment1": None,
    }) for subject in SUBJECTS]


def save_subject_record(student_id, subject, periods_held, periods_attended, mst1, assignment1):
    with connect() as conn:
        conn.execute("""INSERT INTO subject_records
            (student_id,subject,periods_held,periods_attended,mst1,assignment1)
            VALUES(?,?,?,?,?,?) ON CONFLICT(student_id,subject) DO UPDATE SET
            periods_held=excluded.periods_held, periods_attended=excluded.periods_attended,
            mst1=excluded.mst1, assignment1=excluded.assignment1,
            updated_at=CURRENT_TIMESTAMP""",
            (student_id, subject, int(periods_held), int(periods_attended), mst1, assignment1))


def update_student(student_id, name, parent_phone=None, student_phone=None, parent_email=None, student_email=None):
    student_id = str(student_id).strip()
    name = str(name or "").strip()
    with connect() as conn:
        old = conn.execute("SELECT * FROM students WHERE student_id=?", (student_id,)).fetchone()
        if not old:
            return
        parent_phone = old["parent_phone"] if parent_phone is None else str(parent_phone or "").strip()
        student_phone = old["student_phone"] if student_phone is None else str(student_phone or "").strip()
        parent_email = old["parent_email"] if parent_email is None else str(parent_email or "").strip()
        student_email = old["student_email"] if student_email is None else str(student_email or "").strip()
        conn.execute("""UPDATE students SET name=?,parent_phone=?,student_phone=?,parent_email=?,student_email=?
            WHERE student_id=?""", (name or student_id, parent_phone, student_phone, parent_email, student_email, student_id))
