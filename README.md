# Digital Examination Attendance and Verification System

A secure, full-stack, enterprise-grade web application designed for universities, colleges, and examination authorities (such as the Office of the Controller of Examinations - COE).

---

## 🌟 Key Features Implemented

| # | Feature | Implementation Details |
|---|---|---|
| **1** | **Student Attendance Recording** | Invigilators select candidate USN from the room roster and scan the question paper barcode/QR code (via integrated HTML5 device camera or USB handheld barcode scanner). Automatically persists to the central database with exact timestamps. |
| **2** | **Duplicate Attendance Prevention** | If an invigilator attempts to mark a candidate who is already marked `PRESENT`, the system rejects the duplicate scan with a warning dialog detailing the earlier timestamp and barcode. |
| **3** | **Redo Attendance Option** | Supports controlled status corrections (`PRESENT`, `ABSENT`, or `PENDING`) with an explicit confirmation dialog and mandatory reason capture. |
| **4** | **Final Attendance Confirmation** | Interactive confirmation modal summarizing assigned candidates, present count, absent count, and pending count with expandable USN verification chips. |
| **5** | **Automatic Excel Report Generation** | Automatically generates official, styled COE `.xlsx` attendance sheets formatted with headers, summary stat counters, color-coded rows, and signature/seal blocks. |
| **6** | **Digital Audit Trail & Redo History** | Immutable historical audit log capturing all events (`MARK_PRESENT`, `MARK_ABSENT`, `REDO_CORRECTION`, `LOCK_SUBMISSION`, `UNLOCK_OVERRIDE`) with invigilator ID, IP, timestamps, and old $\to$ new states. |
| **7** | **Unmarked Student Warning** | Prominently warns the invigilator if any candidate remains in `PENDING` status prior to final submission to prevent accidental omissions. |
| **8** | **Attendance Locking After Submission** | Once submitted, records are locked against ordinary edits. Includes emergency administrative unlock override protected by a COE PIN set in the `COE_UNLOCK_PIN` environment variable. |
| **9** | **Automatic Progress Saving & Recovery** | Real-time database persistence combined with frontend `localStorage` caching ensures seamless recovery if a browser tab is accidentally refreshed or closed. Features auto-detecting network connectivity status. |
| **10** | **Paper Evaluation Cross-Verification** | Dedicated evaluator portal allowing evaluators to cross-verify physical answer scripts and question paper barcodes against centrally recorded room attendance, flagging discrepancies immediately. |

---

## 📡 Real-Time Sharing & Offline Sync

- **Live updates:** `GET /api/stream/<session_id>` (Server-Sent Events). Every mark / redo / lock in a room is pushed instantly to all open screens (invigilator, coordinator). Implemented in `events.py`.
- **Offline queue:** if a scan fails to send, it is stored on the device, shown as "Queued - not synced", and replayed automatically when the connection returns.
- **Safe replays:** each scan carries a `client_op_id`; the server stores the first response (`processed_ops` table), so a replay never duplicates attendance or audit entries.
- **Scanners:** camera (needs HTTPS on phones; localhost works) or USB/Bluetooth handheld scanner (types the code + Enter into the focused field).
- Run with threading on (default for `python run.py`); behind gunicorn use `-k gthread --threads 8`. For multiple server processes swap `events.py` for Redis pub/sub.

---

## 🏗️ System Architecture

```
exam_attendance_system/
├── app.py                   # Flask server, REST APIs, routing & error handling
├── database.py              # SQLite schema, WAL mode, queries & audit helpers
├── excel_generator.py       # OpenPyXL COE-styled official attendance sheet generator
├── run.py                   # One-click launcher with auto browser launch
├── test_system.py           # Automated unit & integration test suite (8 test cases)
├── generated_reports/       # Auto-saved COE .xlsx files
├── static/
│   ├── css/style.css        # Responsive portal UI styling & status badges
└── templates/
    ├── base.html            # Navigation bar, offline monitor, external CDN scripts
    ├── index.html           # Invigilator console, camera/barcode scanner & roster
    ├── audit.html           # Digital Audit Trail log viewer & search
    └── evaluator.html       # Paper evaluation cross-verification console
```

---

## 🚀 How to Run the Application

### 1. Prerequisites
Ensure Python 3.9+ is installed. Install required dependencies:
```bash
python -m pip install flask openpyxl
```

### 2. Start the Application
Run the launcher script:
```bash
cd "exam_attendance_system"
python run.py
```
The server will start at `http://127.0.0.1:5000` and automatically open your default browser.

---

## 🧪 Running the Automated Test Suite

A complete test suite is provided to verify all 10 features end-to-end:
```bash
python test_system.py
```
Expected output:
```
Ran 8 tests in ~0.8s
OK
```

---

## 🔒 Security & Verification Credentials

- **COE override PIN:** set `COE_UNLOCK_PIN` before starting. If unset, a random PIN is generated and printed once on the server console. Failed attempts are throttled (5 per 5 minutes per IP).
- **Secret key:** set `SECRET_KEY`; a random one is generated per run otherwise.
- **Network binding:** the server listens on `127.0.0.1` by default. Set `HOST=0.0.0.0` only on a trusted network (and put it behind HTTPS). Debug mode is off unless `FLASK_DEBUG=1`.
- **Barcode validation:** a scan must match the exam's question-paper code, otherwise it is rejected (HTTP 422).
- **Identity:** the invigilator recorded in the audit trail is the room's assigned invigilator from the database, never a value sent by the browser.
- **Audit trail** is append-only (database triggers block UPDATE and DELETE).
- **Known limit:** there is still no per-user login, and a shared question-paper barcode cannot prove a script belongs to a particular student; for that, print a unique booklet ID per student.
- **Database Engine**: SQLite with Write-Ahead Logging (`WAL`) and multi-connection concurrency support.
