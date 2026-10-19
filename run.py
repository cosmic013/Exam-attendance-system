"""
Runner script for Digital Examination Attendance and Verification System
"""
import os
import sys
import webbrowser
import threading
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app import app

def open_browser():
    time.sleep(1.2)
    webbrowser.open('http://127.0.0.1:5000')

if __name__ == '__main__':
    print("=" * 70)
    print(" Digital Examination Attendance and Verification System ")
    print("=" * 70)
    print(" * Port: http://127.0.0.1:5000")
    print(" * Features Included:")
    print("   1. Student Attendance Recording (USN + QP Barcode/QR)")
    print("   2. Duplicate Attendance Prevention (Automatic rejection)")
    print("   3. Redo Attendance Option (With confirmation & audit)")
    print("   4. Final Attendance Confirmation (Summary Review & Approval)")
    print("   5. Automatic Excel Report Generation (COE .xlsx format)")
    print("   6. Digital Audit Trail and Redo History")
    print("   7. Unmarked Student Warning (Review before submission)")
    print("   8. Attendance Locking After Submission (COE Override Support)")
    print("   9. Automatic Progress Saving and Recovery (LocalStorage & DB)")
    print("  10. Paper Evaluation Cross-Verification (Discrepancy detection)")
    print("=" * 70)

    # Launch browser thread
    threading.Thread(target=open_browser, daemon=True).start()

    app.run(host=os.environ.get('HOST', '127.0.0.1'), port=5000, debug=False, threaded=True)
