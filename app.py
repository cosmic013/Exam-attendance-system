"""
Digital Examination Attendance and Verification System
Flask Web Application & REST API
"""
import os
import sys
from datetime import datetime
import json
import queue
import secrets
import hmac
import time
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, Response

# Ensure local imports work cleanly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from database import get_db, init_db, seed_demo_data, log_audit
from excel_generator import generate_coe_attendance_excel
import events

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static')
)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

# COE override PIN comes from the environment. If unset, a random one is generated
# at startup and printed once on the server console (never hardcoded / documented).
COE_UNLOCK_PIN = os.environ.get('COE_UNLOCK_PIN')
if not COE_UNLOCK_PIN:
    COE_UNLOCK_PIN = secrets.token_urlsafe(8)
    print(f" * COE unlock PIN for this run: {COE_UNLOCK_PIN}  (set COE_UNLOCK_PIN to choose your own)")

VALID_STATUSES = ('PRESENT', 'ABSENT', 'PENDING')
_unlock_failures = {}  # ip -> [timestamps]; simple brute-force throttle

# Initialize and seed database on startup
init_db()
seed_demo_data()

# ----------------- UI Pages -----------------

@app.route('/')
def index():
    session_id = request.args.get('session_id', type=int)
    conn = get_db()
    cursor = conn.cursor()

    # Get all sessions
    cursor.execute('SELECT * FROM exam_sessions ORDER BY id ASC')
    sessions = [dict(row) for row in cursor.fetchall()]

    if not sessions:
        conn.close()
        return "No exam sessions available.", 404

    # Select active session
    active_session = None
    if session_id:
        cursor.execute('SELECT * FROM exam_sessions WHERE id = ?', (session_id,))
        row = cursor.fetchone()
        if row:
            active_session = dict(row)

    if not active_session:
        active_session = sessions[0]

    # Get students for active session
    cursor.execute('''
        SELECT * FROM students 
        WHERE session_id = ? 
        ORDER BY desk_number ASC, usn ASC
    ''', (active_session['id'],))
    students = [dict(row) for row in cursor.fetchall()]

    # Compute summary stats
    total_count = len(students)
    present_count = sum(1 for s in students if s['attendance_status'] == 'PRESENT')
    absent_count = sum(1 for s in students if s['attendance_status'] == 'ABSENT')
    pending_count = sum(1 for s in students if s['attendance_status'] == 'PENDING')
    pct = round((present_count / total_count * 100), 1) if total_count > 0 else 0.0

    conn.close()

    stats = {
        'total': total_count,
        'present': present_count,
        'absent': absent_count,
        'pending': pending_count,
        'percentage': pct
    }

    return render_template('index.html', sessions=sessions, active_session=active_session, students=students, stats=stats)


@app.route('/audit')
def audit_view():
    session_id = request.args.get('session_id', type=int)
    conn = get_db()
    cursor = conn.cursor()

    # Fetch sessions for filter
    cursor.execute('SELECT id, course_code, room_number FROM exam_sessions ORDER BY id ASC')
    sessions = [dict(row) for row in cursor.fetchall()]

    query = '''
        SELECT a.*, s.course_code, s.room_number 
        FROM audit_trail a
        LEFT JOIN exam_sessions s ON a.session_id = s.id
    '''
    params = []
    if session_id:
        query += ' WHERE a.session_id = ?'
        params.append(session_id)
    
    query += ' ORDER BY a.id DESC LIMIT 300'
    cursor.execute(query, params)
    logs = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return render_template('audit.html', logs=logs, sessions=sessions, current_session_id=session_id)


@app.route('/evaluator')
def evaluator_view():
    conn = get_db()
    cursor = conn.cursor()
    
    # Get all verifications
    cursor.execute('''
        SELECT ev.*, s.course_code, s.room_number, s.exam_date
        FROM evaluation_verifications ev
        LEFT JOIN exam_sessions s ON ev.session_id = s.id
        ORDER BY ev.id DESC LIMIT 100
    ''')
    verifications = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return render_template('evaluator.html', verifications=verifications)


@app.route('/sample_barcodes')
def sample_barcodes():
    return render_template('sample_barcodes.html')



# ----------------- Real-time stream (Server-Sent Events) -----------------

@app.route('/api/stream/<int:session_id>')
def stream(session_id):
    """Live feed: every mark/redo/lock in this room is pushed to all open screens."""
    def gen():
        q = events.subscribe(session_id)
        try:
            yield 'retry: 3000\n\n'
            while True:
                try:
                    yield f'data: {q.get(timeout=15)}\n\n'
                except queue.Empty:
                    yield ': keepalive\n\n'
        finally:
            events.unsubscribe(session_id, q)
    return Response(gen(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def _identity(session, fallback_id, fallback_name):
    """Audit identity comes from the room's assigned invigilator on the server, not from the client."""
    if session:
        return session['invigilator_id'], session['invigilator_name']
    return fallback_id, fallback_name


def _replay(op_id):
    """Return the stored response if this offline-queued operation was already processed."""
    if not op_id:
        return None
    conn = get_db()
    row = conn.execute('SELECT response, status_code FROM processed_ops WHERE op_id = ?', (op_id,)).fetchone()
    conn.close()
    if row:
        return jsonify(json.loads(row['response'])), row['status_code']
    return None


def _remember(op_id, cursor, body, code=200):
    if op_id:
        cursor.execute('INSERT OR IGNORE INTO processed_ops (op_id, response, status_code) VALUES (?, ?, ?)',
                       (op_id, json.dumps(body), code))

# ----------------- API Endpoints -----------------

@app.route('/api/attendance/mark', methods=['POST'])
def mark_attendance():
    """
    Records student attendance as PRESENT with scanned QP Barcode.
    Feature 1: Student Attendance Recording
    Feature 2: Duplicate Attendance Prevention
    Feature 8: Attendance Locking Enforcement
    """
    data = request.get_json() or {}
    session_id = data.get('session_id')
    usn = (data.get('usn') or '').strip().upper()
    qp_barcode = (data.get('qp_barcode') or '').strip().upper()
    invigilator_id = data.get('invigilator_id', 'INV-ACTIVE')
    invigilator_name = data.get('invigilator_name', 'Room Invigilator')
    op_id = data.get('client_op_id')

    replayed = _replay(op_id)
    if replayed:
        return replayed

    if not session_id or not usn:
        return jsonify({'success': False, 'message': 'Session ID and USN are required.'}), 400

    if not qp_barcode:
        return jsonify({'success': False, 'message': 'Question paper barcode/QR code scan is required.'}), 400

    conn = get_db()
    cursor = conn.cursor()

    # 1. Check if session is locked
    cursor.execute('SELECT * FROM exam_sessions WHERE id = ?', (session_id,))
    session = cursor.fetchone()
    invigilator_id, invigilator_name = _identity(session, invigilator_id, invigilator_name)
    if not session:
        conn.close()
        return jsonify({'success': False, 'message': 'Exam session not found.'}), 404

    if session['status'] == 'LOCKED':
        conn.close()
        return jsonify({
            'success': False, 
            'locked': True,
            'message': 'This exam session is LOCKED. Attendance submission was finalized. Modifications are restricted.'
        }), 403

    # 1b. The scanned code must be this room's question paper
    if qp_barcode != (session['qp_code'] or '').strip().upper():
        conn.close()
        return jsonify({
            'success': False,
            'message': f'WRONG QUESTION PAPER: scanned code [{qp_barcode}] does not match this exam ({session["course_code"]}, expected {session["qp_code"]}).'
        }), 422

    # 2. Check student record
    cursor.execute('SELECT * FROM students WHERE session_id = ? AND usn = ?', (session_id, usn))
    student = cursor.fetchone()
    if not student:
        conn.close()
        return jsonify({'success': False, 'message': f'Student with USN {usn} is not assigned to this room.'}), 404

    # 3. Duplicate Attendance Prevention (Feature 2)
    if student['attendance_status'] == 'PRESENT':
        marked_time = student['marked_at'] or 'earlier'
        existing_barcode = student['qp_barcode'] or 'N/A'
        conn.close()
        return jsonify({
            'success': False,
            'duplicate': True,
            'message': f'DUPLICATE PREVENTED: Candidate {usn} ({student["student_name"]}) has ALREADY been marked PRESENT at {marked_time} with QP Barcode [{existing_barcode}]. Duplicate scan has been rejected.'
        }), 409

    # 4. Record attendance
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        UPDATE students
        SET attendance_status = 'PRESENT',
            qp_barcode = ?,
            marked_at = ?,
            marked_by = ?
        WHERE id = ?
    ''', (qp_barcode, now_ts, invigilator_name, student['id']))

    # 5. Log audit trail
    log_audit(
        session_id=session_id,
        action_type='MARK_PRESENT',
        invigilator_id=invigilator_id,
        invigilator_name=invigilator_name,
        usn=usn,
        student_name=student['student_name'],
        old_status=student['attendance_status'],
        new_status='PRESENT',
        qp_barcode=qp_barcode,
        reason='Initial barcode scan attendance verification',
        client_ip=request.remote_addr or '127.0.0.1',
        cursor=cursor
    )

    body = {
        'success': True,
        'message': f'Attendance marked PRESENT for {student["student_name"]} ({usn}). QP Barcode: {qp_barcode}',
        'student': {
            'usn': usn,
            'student_name': student['student_name'],
            'status': 'PRESENT',
            'qp_barcode': qp_barcode,
            'marked_at': now_ts
        }
    }
    _remember(op_id, cursor, body)
    conn.commit()
    conn.close()
    events.publish(session_id, {'type': 'attendance', 'usn': usn, 'status': 'PRESENT',
                                'qp_barcode': qp_barcode, 'marked_at': now_ts, 'by': invigilator_name})
    return jsonify(body)


@app.route('/api/attendance/mark_absent', methods=['POST'])
def mark_absent():
    data = request.get_json() or {}
    session_id = data.get('session_id')
    usn = (data.get('usn') or '').strip().upper()
    invigilator_id = data.get('invigilator_id', 'INV-ACTIVE')
    invigilator_name = data.get('invigilator_name', 'Room Invigilator')

    if not session_id or not usn:
        return jsonify({'success': False, 'message': 'Session ID and USN are required.'}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM exam_sessions WHERE id = ?', (session_id,))
    session = cursor.fetchone()
    invigilator_id, invigilator_name = _identity(session, invigilator_id, invigilator_name)
    if session and session['status'] == 'LOCKED':
        conn.close()
        return jsonify({'success': False, 'locked': True, 'message': 'Session is LOCKED. Cannot modify.'}), 403

    cursor.execute('SELECT * FROM students WHERE session_id = ? AND usn = ?', (session_id, usn))
    student = cursor.fetchone()
    if not student:
        conn.close()
        return jsonify({'success': False, 'message': 'Student not found in this room.'}), 404

    if student['attendance_status'] == 'PRESENT':
        conn.close()
        return jsonify({'success': False, 'message': f'{usn} is already marked PRESENT. Use the Redo option (with a reason) to correct it.'}), 409

    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        UPDATE students
        SET attendance_status = 'ABSENT',
            qp_barcode = NULL,
            marked_at = ?,
            marked_by = ?
        WHERE id = ?
    ''', (now_ts, invigilator_name, student['id']))

    log_audit(
        session_id=session_id,
        action_type='MARK_ABSENT',
        invigilator_id=invigilator_id,
        invigilator_name=invigilator_name,
        usn=usn,
        student_name=student['student_name'],
        old_status=student['attendance_status'],
        new_status='ABSENT',
        qp_barcode=None,
        reason='Invigilator verified candidate absent at desk',
        client_ip=request.remote_addr or '127.0.0.1',
        cursor=cursor
    )

    conn.commit()
    conn.close()
    events.publish(session_id, {'type': 'attendance', 'usn': usn, 'status': 'ABSENT',
                                'qp_barcode': None, 'marked_at': now_ts, 'by': invigilator_name})

    return jsonify({
        'success': True,
        'message': f'Candidate {student["student_name"]} ({usn}) marked ABSENT.',
        'student': {
            'usn': usn,
            'student_name': student['student_name'],
            'status': 'ABSENT',
            'marked_at': now_ts
        }
    })


@app.route('/api/attendance/redo', methods=['POST'])
def redo_attendance():
    """
    Feature 3: Redo Attendance Option
    Allows invigilator to redo attendance entry with explicit confirmation and reason.
    Feature 6: Logs full change history in Digital Audit Trail.
    """
    data = request.get_json() or {}
    session_id = data.get('session_id')
    usn = (data.get('usn') or '').strip().upper()
    new_status = data.get('new_status') # 'PRESENT', 'ABSENT', or 'PENDING'
    qp_barcode = (data.get('qp_barcode') or '').strip().upper() or None
    reason = (data.get('reason') or '').strip()
    invigilator_id = data.get('invigilator_id', 'INV-ACTIVE')
    invigilator_name = data.get('invigilator_name', 'Room Invigilator')

    if not session_id or not usn or not new_status:
        return jsonify({'success': False, 'message': 'Session, USN, and New Status are required.'}), 400

    if new_status not in VALID_STATUSES:
        return jsonify({'success': False, 'message': f'New status must be one of {", ".join(VALID_STATUSES)}.'}), 400

    if not reason:
        reason = "Correction made via Invigilator Redo option"

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM exam_sessions WHERE id = ?', (session_id,))
    session = cursor.fetchone()
    invigilator_id, invigilator_name = _identity(session, invigilator_id, invigilator_name)
    if session and session['status'] == 'LOCKED':
        conn.close()
        return jsonify({'success': False, 'locked': True, 'message': 'Session is LOCKED. Unlock required for redo.'}), 403

    cursor.execute('SELECT * FROM students WHERE session_id = ? AND usn = ?', (session_id, usn))
    student = cursor.fetchone()
    if not student:
        conn.close()
        return jsonify({'success': False, 'message': 'Student not found in this session.'}), 404

    if new_status == 'PRESENT':
        qp_barcode = qp_barcode or (session['qp_code'] or '').strip().upper()
        if qp_barcode != (session['qp_code'] or '').strip().upper():
            conn.close()
            return jsonify({'success': False, 'message': f'WRONG QUESTION PAPER: [{qp_barcode}] does not match expected {session["qp_code"]}.'}), 422

    old_status = student['attendance_status']
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute('''
        UPDATE students
        SET attendance_status = ?,
            qp_barcode = ?,
            marked_at = ?,
            marked_by = ?
        WHERE id = ?
    ''', (new_status, qp_barcode if new_status == 'PRESENT' else None, now_ts, invigilator_name, student['id']))

    log_audit(
        session_id=session_id,
        action_type='REDO_CORRECTION',
        invigilator_id=invigilator_id,
        invigilator_name=invigilator_name,
        usn=usn,
        student_name=student['student_name'],
        old_status=old_status,
        new_status=new_status,
        qp_barcode=qp_barcode if new_status == 'PRESENT' else None,
        reason=reason,
        client_ip=request.remote_addr or '127.0.0.1',
        cursor=cursor
    )

    conn.commit()
    conn.close()
    events.publish(session_id, {'type': 'attendance', 'usn': usn, 'status': new_status,
                                'qp_barcode': qp_barcode if new_status == 'PRESENT' else None,
                                'marked_at': now_ts, 'by': invigilator_name})

    return jsonify({
        'success': True,
        'message': f'Attendance for {usn} successfully corrected from {old_status} to {new_status}.',
        'student': {
            'usn': usn,
            'student_name': student['student_name'],
            'status': new_status,
            'qp_barcode': qp_barcode if new_status == 'PRESENT' else None,
            'marked_at': now_ts
        }
    })


@app.route('/api/session/summary/<int:session_id>')
def get_session_summary(session_id):
    """
    Feature 4 & 7: Returns grouped counts & student lists (Present, Absent, Pending)
    for final confirmation and unmarked student checks.
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM exam_sessions WHERE id = ?', (session_id,))
    session = cursor.fetchone()
    if not session:
        conn.close()
        return jsonify({'success': False, 'message': 'Session not found'}), 404

    cursor.execute('SELECT usn, student_name, desk_number, attendance_status, qp_barcode, marked_at FROM students WHERE session_id = ? ORDER BY desk_number ASC', (session_id,))
    students = [dict(row) for row in cursor.fetchall()]
    conn.close()

    present_list = [s for s in students if s['attendance_status'] == 'PRESENT']
    absent_list = [s for s in students if s['attendance_status'] == 'ABSENT']
    pending_list = [s for s in students if s['attendance_status'] == 'PENDING']

    return jsonify({
        'success': True,
        'session': dict(session),
        'total': len(students),
        'present_count': len(present_list),
        'absent_count': len(absent_list),
        'pending_count': len(pending_list),
        'present_list': present_list,
        'absent_list': absent_list,
        'pending_list': pending_list,
        'is_locked': session['status'] == 'LOCKED'
    })


@app.route('/api/session/confirm_lock', methods=['POST'])
def confirm_lock():
    """
    Feature 4: Final Attendance Confirmation
    Feature 5: Automatic Excel Report Generation
    Feature 7: Unmarked Student Warning
    Feature 8: Attendance Locking After Submission
    """
    data = request.get_json() or {}
    session_id = data.get('session_id')
    force_submit = data.get('force_submit', False)
    invigilator_id = data.get('invigilator_id', 'INV-ACTIVE')
    invigilator_name = data.get('invigilator_name', 'Room Invigilator')

    if not session_id:
        return jsonify({'success': False, 'message': 'Session ID is required.'}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM exam_sessions WHERE id = ?', (session_id,))
    session = cursor.fetchone()
    invigilator_id, invigilator_name = _identity(session, invigilator_id, invigilator_name)
    if not session:
        conn.close()
        return jsonify({'success': False, 'message': 'Session not found.'}), 404

    if session['status'] == 'LOCKED':
        conn.close()
        return jsonify({'success': True, 'message': 'Session is already locked.', 'already_locked': True})

    # Check for unmarked/pending students (Feature 7)
    cursor.execute("SELECT usn, student_name, desk_number FROM students WHERE session_id = ? AND attendance_status = 'PENDING'", (session_id,))
    pending_students = [dict(row) for row in cursor.fetchall()]

    if len(pending_students) > 0 and not force_submit:
        conn.close()
        return jsonify({
            'success': False,
            'warning': 'unmarked_students',
            'pending_count': len(pending_students),
            'pending_students': pending_students,
            'message': f'Warning: {len(pending_students)} student(s) still have unmarked/pending attendance! Review these students before final submission.'
        }), 400

    # Lock session
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        UPDATE exam_sessions
        SET status = 'LOCKED',
            locked_at = ?,
            locked_by = ?
        WHERE id = ?
    ''', (now_ts, invigilator_name, session_id))

    # Fetch updated students list
    cursor.execute('SELECT * FROM students WHERE session_id = ? ORDER BY desk_number ASC, usn ASC', (session_id,))
    students = [dict(row) for row in cursor.fetchall()]

    session_dict = dict(session)
    session_dict['status'] = 'LOCKED'
    session_dict['locked_at'] = now_ts

    # Auto generate COE Excel Report (Feature 5)
    report_file_path = generate_coe_attendance_excel(session_dict, students)
    report_filename = os.path.basename(report_file_path)

    # Log lock action in audit trail
    log_audit(
        session_id=session_id,
        action_type='LOCK_SUBMISSION',
        invigilator_id=invigilator_id,
        invigilator_name=invigilator_name,
        reason=f"Final attendance confirmed and submitted. Total Present: {sum(1 for s in students if s['attendance_status'] == 'PRESENT')}, Absent: {sum(1 for s in students if s['attendance_status'] == 'ABSENT')}. Excel generated: {report_filename}",
        client_ip=request.remote_addr or '127.0.0.1',
        cursor=cursor
    )

    conn.commit()
    conn.close()
    events.publish(session_id, {'type': 'locked', 'locked_at': now_ts, 'by': invigilator_name})

    return jsonify({
        'success': True,
        'message': 'Attendance successfully confirmed, finalized, and locked. Official COE Excel report generated.',
        'locked_at': now_ts,
        'report_filename': report_filename,
        'download_url': f'/download_report/{session_id}'
    })


@app.route('/api/session/unlock_override', methods=['POST'])
def unlock_override():
    """
    Feature 8: Authorized unlock for emergency adjustments
    """
    data = request.get_json() or {}
    session_id = data.get('session_id')
    auth_code = data.get('auth_code', '').strip()
    reason = data.get('reason', '').strip()
    invigilator_id = data.get('invigilator_id', 'COE-SUPER')
    invigilator_name = data.get('invigilator_name', 'Chief Superintendent')

    ip = request.remote_addr or 'unknown'
    now = time.time()
    recent = [t for t in _unlock_failures.get(ip, []) if now - t < 300]
    if len(recent) >= 5:
        return jsonify({'success': False, 'message': 'Too many failed attempts. Try again in a few minutes.'}), 429
    if not hmac.compare_digest(auth_code.encode(), COE_UNLOCK_PIN.encode()):
        recent.append(now)
        _unlock_failures[ip] = recent
        return jsonify({'success': False, 'message': 'Invalid COE Authorization PIN. Access denied.'}), 403
    _unlock_failures.pop(ip, None)

    if not reason:
        reason = "Authorized COE administrative override unlock"

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM exam_sessions WHERE id = ?', (session_id,))
    session = cursor.fetchone()
    if not session:
        conn.close()
        return jsonify({'success': False, 'message': 'Session not found.'}), 404

    cursor.execute('''
        UPDATE exam_sessions
        SET status = 'IN_PROGRESS',
            locked_at = NULL,
            locked_by = NULL
        WHERE id = ?
    ''', (session_id,))

    log_audit(
        session_id=session_id,
        action_type='UNLOCK_OVERRIDE',
        invigilator_id=invigilator_id,
        invigilator_name=invigilator_name,
        reason=f"Administrative Unlock Override: {reason}",
        client_ip=request.remote_addr or '127.0.0.1',
        cursor=cursor
    )

    conn.commit()
    conn.close()
    events.publish(session_id, {'type': 'unlocked'})

    return jsonify({
        'success': True,
        'message': 'Session has been unlocked. Invigilator can now make authorized corrections.'
    })


@app.route('/download_report/<int:session_id>')
def download_report(session_id):
    """
    Generates and downloads current COE Excel attendance report.
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM exam_sessions WHERE id = ?', (session_id,))
    session = cursor.fetchone()
    if not session:
        conn.close()
        return "Session not found", 404

    if session['status'] != 'LOCKED':
        conn.close()
        return "The official COE report is available only after attendance is confirmed and locked.", 409

    cursor.execute('SELECT * FROM students WHERE session_id = ? ORDER BY desk_number ASC, usn ASC', (session_id,))
    students = [dict(row) for row in cursor.fetchall()]
    conn.close()

    session_dict = dict(session)
    report_file_path = generate_coe_attendance_excel(session_dict, students)

    return send_file(
        report_file_path,
        as_attachment=True,
        download_name=f"COE_Attendance_{session_dict['course_code']}_{session_dict['room_number'].replace(' ', '_')}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.route('/api/evaluator/verify', methods=['POST'])
def evaluator_cross_verify():
    """
    Feature 10: Paper Evaluation Cross-Verification
    Evaluator checks question paper barcode & USN against exam attendance record.
    Flags discrepancies (e.g., student marked ABSENT or barcode mismatch).
    """
    data = request.get_json() or {}
    usn = (data.get('usn') or '').strip().upper()
    scanned_qp_barcode = (data.get('scanned_qp_barcode') or '').strip().upper()
    evaluator_name = data.get('evaluator_name', 'Dr. Evaluation Officer').strip()
    evaluator_id = data.get('evaluator_id', 'EVAL-101').strip()

    if not usn or not scanned_qp_barcode:
        return jsonify({'success': False, 'message': 'Both Student USN and Question Paper Barcode are required.'}), 400

    conn = get_db()
    cursor = conn.cursor()

    # Find the candidate's record. A USN can appear in several exams, so the evaluator
    # must say which one (course_code or session_id) when more than one exists.
    course_code = (data.get('course_code') or '').strip().upper()
    sel_session = data.get('session_id')
    sql = '''
        SELECT s.*, e.course_code, e.course_name, e.exam_date, e.exam_session, e.qp_code, e.room_number, e.status as session_status
        FROM students s
        JOIN exam_sessions e ON s.session_id = e.id
        WHERE s.usn = ?
    '''
    params = [usn]
    if course_code:
        sql += ' AND UPPER(e.course_code) = ?'
        params.append(course_code)
    if sel_session:
        sql += ' AND e.id = ?'
        params.append(sel_session)
    sql += ' ORDER BY s.id DESC'
    cursor.execute(sql, params)
    rows = cursor.fetchall()

    if len(rows) > 1:
        conn.close()
        codes = ', '.join(sorted({r['course_code'] for r in rows}))
        return jsonify({
            'success': False, 'status': 'AMBIGUOUS', 'is_valid': False,
            'details': f"USN '{usn}' appears in several exams ({codes}). Enter the course code of the paper being evaluated."
        }), 409
    record = rows[0] if rows else None

    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not record:
        status = 'DISCREPANCY_FLAGGED'
        details = f"DISCREPANCY: Candidate USN '{usn}' was not found in any exam attendance roster!"
        cursor.execute('''
            INSERT INTO evaluation_verifications (usn, scanned_qp_barcode, session_id, evaluator_name, evaluator_id, verification_status, details, timestamp)
            VALUES (?, ?, NULL, ?, ?, ?, ?, ?)
        ''', (usn, scanned_qp_barcode, evaluator_name, evaluator_id, status, details, now_ts))
        conn.commit()
        conn.close()
        return jsonify({
            'success': False,
            'status': status,
            'is_valid': False,
            'details': details
        })

    record_dict = dict(record)
    attendance_status = record_dict['attendance_status']
    recorded_qp_barcode = record_dict['qp_barcode'] or ''
    assigned_qp_code = record_dict['qp_code']

    # Cross-verification logic
    discrepancies = []

    if attendance_status == 'ABSENT':
        discrepancies.append(f"CRITICAL DISCREPANCY: Candidate {usn} was recorded as ABSENT in examination hall {record_dict['room_number']}, but a physical answer booklet is presented for evaluation!")
    elif attendance_status == 'PENDING':
        discrepancies.append(f"WARNING: Attendance for candidate {usn} was never completed/verified (Status: PENDING).")

    # Check QP Barcode match
    # Scanned barcode should match either the recorded barcode or the session's assigned QP series
    if recorded_qp_barcode and scanned_qp_barcode != recorded_qp_barcode:
        discrepancies.append(f"BARCODE MISMATCH: Evaluated paper barcode '{scanned_qp_barcode}' does not match examination hall scanned barcode '{recorded_qp_barcode}'.")
    elif not recorded_qp_barcode and scanned_qp_barcode != assigned_qp_code:
        discrepancies.append(f"BARCODE MISMATCH: Scanned QP Barcode '{scanned_qp_barcode}' does not match official QP Series '{assigned_qp_code}'.")

    if discrepancies:
        status = 'DISCREPANCY_FLAGGED'
        details = " | ".join(discrepancies)
        is_valid = False
    else:
        status = 'VERIFIED_MATCH'
        details = f"VERIFIED: Attendance status is PRESENT. QP Barcode matches examination room record ({scanned_qp_barcode})."
        is_valid = True

    cursor.execute('''
        INSERT INTO evaluation_verifications (usn, scanned_qp_barcode, session_id, evaluator_name, evaluator_id, verification_status, details, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (usn, scanned_qp_barcode, record_dict['session_id'], evaluator_name, evaluator_id, status, details, now_ts))

    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'status': status,
        'is_valid': is_valid,
        'details': details,
        'record': {
            'usn': usn,
            'student_name': record_dict['student_name'],
            'course_code': record_dict['course_code'],
            'course_name': record_dict['course_name'],
            'room_number': record_dict['room_number'],
            'exam_date': record_dict['exam_date'],
            'attendance_status': attendance_status,
            'recorded_qp_barcode': recorded_qp_barcode or record_dict['qp_code'],
            'marked_at': record_dict['marked_at'],
            'timestamp': now_ts
        }
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    print("=" * 65)
    print(" Digital Examination Attendance & Verification System ")
    print(f" Running on: http://{host}:{port}")
    print("=" * 65)
    app.run(host=host, port=port, debug=os.environ.get('FLASK_DEBUG') == '1', threaded=True)
