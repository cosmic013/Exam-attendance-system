"""
Database layer for Digital Examination Attendance and Verification System.
Handles SQLite initialization, schemas, audit logging, locking, and queries.
"""
import sqlite3
import os
from datetime import datetime

if os.environ.get('VERCEL'):
    import shutil
    BASE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'exam_attendance.db')
    DB_PATH = '/tmp/exam_attendance.db'
    if not os.path.exists(DB_PATH) and os.path.exists(BASE_DB):
        shutil.copy2(BASE_DB, DB_PATH)
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'exam_attendance.db')

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # 1. Exam Sessions table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS exam_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_code TEXT NOT NULL,
        course_name TEXT NOT NULL,
        exam_date TEXT NOT NULL,
        exam_session TEXT NOT NULL,
        room_number TEXT NOT NULL,
        qp_code TEXT NOT NULL,
        invigilator_name TEXT NOT NULL,
        invigilator_id TEXT NOT NULL,
        status TEXT DEFAULT 'IN_PROGRESS', -- 'IN_PROGRESS', 'LOCKED'
        locked_at TEXT,
        locked_by TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 2. Students table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        usn TEXT NOT NULL,
        student_name TEXT NOT NULL,
        desk_number TEXT NOT NULL,
        attendance_status TEXT DEFAULT 'PENDING', -- 'PENDING', 'PRESENT', 'ABSENT'
        qp_barcode TEXT,
        marked_at TEXT,
        marked_by TEXT,
        FOREIGN KEY (session_id) REFERENCES exam_sessions(id),
        UNIQUE(session_id, usn)
    )
    ''')

    # 3. Digital Audit Trail table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS audit_trail (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        usn TEXT,
        student_name TEXT,
        action_type TEXT NOT NULL, -- 'MARK_PRESENT', 'MARK_ABSENT', 'REDO_CORRECTION', 'LOCK_SUBMISSION', 'UNLOCK_OVERRIDE'
        old_status TEXT,
        new_status TEXT,
        qp_barcode TEXT,
        reason TEXT,
        invigilator_id TEXT NOT NULL,
        invigilator_name TEXT,
        timestamp TEXT NOT NULL,
        client_ip TEXT
    )
    ''')

    # 4. Evaluator Cross-Verification table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS evaluation_verifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usn TEXT NOT NULL,
        scanned_qp_barcode TEXT NOT NULL,
        session_id INTEGER,
        evaluator_name TEXT NOT NULL,
        evaluator_id TEXT NOT NULL,
        verification_status TEXT NOT NULL, -- 'VERIFIED_MATCH', 'DISCREPANCY_FLAGGED'
        details TEXT,
        timestamp TEXT NOT NULL
    )
    ''')

    # Audit trail is append-only: block UPDATE and DELETE at the database level
    cursor.execute('''
    CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_trail
    BEGIN SELECT RAISE(ABORT, 'audit_trail is append-only'); END
    ''')
    cursor.execute('''
    CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_trail
    BEGIN SELECT RAISE(ABORT, 'audit_trail is append-only'); END
    ''')

    # 5. Idempotency table so offline-queued scans can be safely replayed
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS processed_ops (
        op_id TEXT PRIMARY KEY,
        response TEXT NOT NULL,
        status_code INTEGER NOT NULL DEFAULT 200,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.commit()
    conn.close()

def seed_demo_data():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM exam_sessions')
    if cursor.fetchone()[0] == 0:
        now_str = datetime.now().strftime("%Y-%m-%d")
        cursor.execute('''
        INSERT INTO exam_sessions (
            course_code, course_name, exam_date, exam_session, room_number, qp_code, invigilator_name, invigilator_id, status
        ) VALUES (
            'CS801', 'Cloud Computing & Distributed Systems', ?, 'Morning (09:30 AM - 12:30 PM)', 'Room 302 (Block B)', 'QP-2026-CS801-A', 'Dr. Ramesh Sharma', 'INV-104', 'IN_PROGRESS'
        )
        ''', (now_str,))
        session_id_1 = cursor.lastrowid

        sample_students = [
            ("1MS21CS001", "Aakash Verma", "D-01"),
            ("1MS21CS002", "Ananya Hegde", "D-02"),
            ("1MS21CS003", "Bhavik Patel", "D-03"),
            ("1MS21CS004", "Deepak Kumar", "D-04"),
            ("1MS21CS005", "Divya Suresh", "D-05"),
            ("1MS21CS006", "Farhan Ahmed", "D-06"),
            ("1MS21CS007", "Ishaan Malhotra", "D-07"),
            ("1MS21CS008", "Kavya Nair", "D-08"),
            ("1MS21CS009", "Manish Rao", "D-09"),
            ("1MS21CS010", "Neha Kulkarni", "D-10"),
            ("1MS21CS011", "Pranav Joshi", "D-11"),
            ("1MS21CS012", "Pooja Hegde", "D-12"),
            ("1MS21CS013", "Rahul Sundaram", "D-13"),
            ("1MS21CS014", "Sneha Reddy", "D-14"),
            ("1MS21CS015", "Varun Bhat", "D-15"),
        ]

        for usn, name, desk in sample_students:
            cursor.execute('''
            INSERT INTO students (session_id, usn, student_name, desk_number, attendance_status)
            VALUES (?, ?, ?, ?, 'PENDING')
            ''', (session_id_1, usn, name, desk))

        cursor.execute('''
        INSERT INTO exam_sessions (
            course_code, course_name, exam_date, exam_session, room_number, qp_code, invigilator_name, invigilator_id, status
        ) VALUES (
            'IS702', 'Machine Learning & Neural Networks', ?, 'Afternoon (02:00 PM - 05:00 PM)', 'Room 405 (Block C)', 'QP-2026-IS702-B', 'Prof. Priya Venkatesh', 'INV-208', 'IN_PROGRESS'
        )
        ''', (now_str,))
        session_id_2 = cursor.lastrowid

        sample_students_2 = [
            ("1MS21IS001", "Aditya Sen", "D-01"),
            ("1MS21IS002", "Chirag Shah", "D-02"),
            ("1MS21IS003", "Gautam Iyer", "D-03"),
            ("1MS21IS004", "Harshita Das", "D-04"),
            ("1MS21IS005", "Kiran George", "D-05"),
        ]
        for usn, name, desk in sample_students_2:
            cursor.execute('''
            INSERT INTO students (session_id, usn, student_name, desk_number, attendance_status)
            VALUES (?, ?, ?, ?, 'PENDING')
            ''', (session_id_2, usn, name, desk))

        conn.commit()

    conn.close()

def log_audit(session_id, action_type, invigilator_id, invigilator_name, usn=None, student_name=None, old_status=None, new_status=None, qp_barcode=None, reason=None, client_ip="127.0.0.1", cursor=None):
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    insert_sql = '''
    INSERT INTO audit_trail (
        session_id, usn, student_name, action_type, old_status, new_status, qp_barcode, reason, invigilator_id, invigilator_name, timestamp, client_ip
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''
    params = (session_id, usn, student_name, action_type, old_status, new_status, qp_barcode, reason, invigilator_id, invigilator_name, now_ts, client_ip)

    if cursor:
        cursor.execute(insert_sql, params)
    else:
        conn = get_db()
        c = conn.cursor()
        c.execute(insert_sql, params)
        conn.commit()
        conn.close()
