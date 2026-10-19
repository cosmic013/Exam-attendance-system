"""
Excel Attendance Sheet Generator for Controller of Examinations (COE).
Generates an official, publication-quality, styled .xlsx report using openpyxl.
"""
import os
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from datetime import datetime

def generate_coe_attendance_excel(session_data, students_list, output_path=None):
    """
    session_data: dict with keys:
        - course_code, course_name, exam_date, exam_session, room_number, qp_code,
          invigilator_name, invigilator_id, status, locked_at
    students_list: list of dicts with:
        - usn, student_name, desk_number, attendance_status, qp_barcode, marked_at
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "COE Attendance Sheet"
    ws.views.sheetView[0].showGridLines = True

    # Palette
    NAVY_BLUE = "1E3A8A"
    LIGHT_BLUE = "DBEAFE"
    EMERALD_GREEN = "059669"
    LIGHT_GREEN = "D1FAE5"
    CRIMSON = "DC2626"
    LIGHT_RED = "FEE2E2"
    GRAY_HEADER = "F3F4F6"
    BORDER_COLOR = "94A3B8"

    thin_border = Border(
        left=Side(style='thin', color=BORDER_COLOR),
        right=Side(style='thin', color=BORDER_COLOR),
        top=Side(style='thin', color=BORDER_COLOR),
        bottom=Side(style='thin', color=BORDER_COLOR)
    )
    thick_bottom = Border(bottom=Side(style='medium', color=NAVY_BLUE))

    # Row 1: Title Header
    ws.merge_cells("A1:H1")
    title_cell = ws["A1"]
    title_cell.value = "CONTROLLER OF EXAMINATIONS (COE) - OFFICIAL ATTENDANCE STATEMENT"
    title_cell.font = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    title_cell.fill = PatternFill(start_color=NAVY_BLUE, end_color=NAVY_BLUE, fill_type="solid")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    # Row 2: Subtitle
    ws.merge_cells("A2:H2")
    sub_cell = ws["A2"]
    sub_cell.value = "DIGITAL EXAMINATION ATTENDANCE & VERIFICATION RECORD"
    sub_cell.font = Font(name="Calibri", size=11, bold=True, color="1E3A8A")
    sub_cell.fill = PatternFill(start_color=LIGHT_BLUE, end_color=LIGHT_BLUE, fill_type="solid")
    sub_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 22

    # Exam Info Metadata Block (Rows 4 to 7)
    meta_keys = [
        ("Course Code & Name:", f"{session_data['course_code']} - {session_data['course_name']}", "Exam Date:", session_data['exam_date']),
        ("Exam Session:", session_data['exam_session'], "Room Number:", session_data['room_number']),
        ("Question Paper Code:", session_data['qp_code'], "Invigilator:", f"{session_data['invigilator_name']} ({session_data['invigilator_id']})"),
        ("Session Lock Status:", session_data['status'], "Submission Timestamp:", session_data.get('locked_at') or 'Draft / In Progress')
    ]

    current_row = 4
    for label1, val1, label2, val2 in meta_keys:
        ws.cell(row=current_row, column=1, value=label1).font = Font(name="Calibri", bold=True, size=10, color="334155")
        ws.cell(row=current_row, column=1).alignment = Alignment(vertical="center")
        
        ws.merge_cells(start_row=current_row, start_column=2, end_row=current_row, end_column=4)
        v1_cell = ws.cell(row=current_row, column=2, value=val1)
        v1_cell.font = Font(name="Calibri", bold=(label1 == "Course Code & Name:"), size=10)
        v1_cell.alignment = Alignment(vertical="center")

        ws.cell(row=current_row, column=5, value=label2).font = Font(name="Calibri", bold=True, size=10, color="334155")
        ws.cell(row=current_row, column=5).alignment = Alignment(vertical="center")

        ws.merge_cells(start_row=current_row, start_column=6, end_row=current_row, end_column=8)
        v2_cell = ws.cell(row=current_row, column=6, value=val2)
        v2_cell.font = Font(name="Calibri", bold=(label2 == "Session Lock Status:"), size=10)
        v2_cell.alignment = Alignment(vertical="center")
        
        ws.row_dimensions[current_row].height = 20
        current_row += 1

    # Row 9: Stats Summary Bar
    total_count = len(students_list)
    present_count = sum(1 for s in students_list if s['attendance_status'] == 'PRESENT')
    absent_count = sum(1 for s in students_list if s['attendance_status'] == 'ABSENT')
    pending_count = sum(1 for s in students_list if s['attendance_status'] == 'PENDING')
    pct = round((present_count / total_count * 100), 1) if total_count > 0 else 0.0

    current_row = 9
    ws.merge_cells(f"A{current_row}:B{current_row}")
    ws[f"A{current_row}"] = f"Total Candidates: {total_count}"
    ws[f"A{current_row}"].font = Font(bold=True, size=10)
    ws[f"A{current_row}"].fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    ws[f"A{current_row}"].alignment = Alignment(horizontal="center", vertical="center")

    ws.merge_cells(f"C{current_row}:D{current_row}")
    ws[f"C{current_row}"] = f"Total Present: {present_count}"
    ws[f"C{current_row}"].font = Font(bold=True, size=10, color="065F46")
    ws[f"C{current_row}"].fill = PatternFill(start_color=LIGHT_GREEN, end_color=LIGHT_GREEN, fill_type="solid")
    ws[f"C{current_row}"].alignment = Alignment(horizontal="center", vertical="center")

    ws.merge_cells(f"E{current_row}:F{current_row}")
    ws[f"E{current_row}"] = f"Total Absent: {absent_count}"
    ws[f"E{current_row}"].font = Font(bold=True, size=10, color="991B1B")
    ws[f"E{current_row}"].fill = PatternFill(start_color=LIGHT_RED, end_color=LIGHT_RED, fill_type="solid")
    ws[f"E{current_row}"].alignment = Alignment(horizontal="center", vertical="center")

    ws.merge_cells(f"G{current_row}:H{current_row}")
    ws[f"G{current_row}"] = f"Attendance Rate: {pct}%"
    ws[f"G{current_row}"].font = Font(bold=True, size=10, color="1E3A8A")
    ws[f"G{current_row}"].fill = PatternFill(start_color=LIGHT_BLUE, end_color=LIGHT_BLUE, fill_type="solid")
    ws[f"G{current_row}"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[current_row].height = 24

    # Row 11: Table Headers
    headers = [
        "Sl. No.", "USN / Reg No.", "Student Name", "Desk No.",
        "Attendance Status", "Scanned QP Barcode", "Verification Time", "Signature / Initial"
    ]
    table_header_row = 11
    ws.row_dimensions[table_header_row].height = 26

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=table_header_row, column=col_idx, value=header)
        cell.font = Font(name="Calibri", bold=True, size=10, color="FFFFFF")
        cell.fill = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border

    # Table Rows
    data_start_row = 12
    row_num = data_start_row
    for idx, s in enumerate(students_list, start=1):
        ws.row_dimensions[row_num].height = 22
        
        c1 = ws.cell(row=row_num, column=1, value=idx)
        c2 = ws.cell(row=row_num, column=2, value=s['usn'])
        c3 = ws.cell(row=row_num, column=3, value=s['student_name'])
        c4 = ws.cell(row=row_num, column=4, value=s['desk_number'])
        
        status = s['attendance_status']
        c5 = ws.cell(row=row_num, column=5, value=status)
        
        c6 = ws.cell(row=row_num, column=6, value=s.get('qp_barcode') or '-')
        c7 = ws.cell(row=row_num, column=7, value=s.get('marked_at') or '-')
        c8 = ws.cell(row=row_num, column=8, value="") # Signature space

        # Alignments
        c1.alignment = Alignment(horizontal="center", vertical="center")
        c2.alignment = Alignment(horizontal="center", vertical="center")
        c3.alignment = Alignment(horizontal="left", vertical="center")
        c4.alignment = Alignment(horizontal="center", vertical="center")
        c5.alignment = Alignment(horizontal="center", vertical="center")
        c6.alignment = Alignment(horizontal="center", vertical="center")
        c7.alignment = Alignment(horizontal="center", vertical="center")
        c8.alignment = Alignment(horizontal="center", vertical="center")

        # Fonts & borders
        for cell in [c1, c2, c3, c4, c5, c6, c7, c8]:
            cell.font = Font(name="Calibri", size=10)
            cell.border = thin_border

        # Highlight Status
        if status == 'PRESENT':
            c5.font = Font(name="Calibri", size=10, bold=True, color="065F46")
            c5.fill = PatternFill(start_color=LIGHT_GREEN, end_color=LIGHT_GREEN, fill_type="solid")
        elif status == 'ABSENT':
            c5.font = Font(name="Calibri", size=10, bold=True, color="991B1B")
            c5.fill = PatternFill(start_color=LIGHT_RED, end_color=LIGHT_RED, fill_type="solid")
        else:
            c5.font = Font(name="Calibri", size=10, bold=True, color="D97706")
            c5.fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")

        row_num += 1

    # Certification and Signatures Section
    cert_row = row_num + 2
    ws.merge_cells(f"A{cert_row}:H{cert_row}")
    cert_cell = ws[f"A{cert_row}"]
    cert_cell.value = (
        f"CERTIFICATION STATEMENT: I hereby certify that the attendance record for the room "
        f"{session_data['room_number']} in course {session_data['course_code']} has been conducted "
        f"and verified via digital barcode scanning. Total Present: {present_count}, Total Absent: {absent_count}."
    )
    cert_cell.font = Font(name="Calibri", italic=True, size=10, color="1E293B")
    cert_cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[cert_row].height = 28

    sign_row = cert_row + 3
    ws.cell(row=sign_row, column=1, value="____________________________").font = Font(bold=True)
    ws.cell(row=sign_row, column=4, value="____________________________").font = Font(bold=True)
    ws.cell(row=sign_row, column=7, value="____________________________").font = Font(bold=True)

    sign_title_row = sign_row + 1
    ws.cell(row=sign_title_row, column=1, value="Invigilator Signature").font = Font(bold=True, size=10)
    ws.cell(row=sign_title_row, column=4, value="Chief Superintendent").font = Font(bold=True, size=10)
    ws.cell(row=sign_title_row, column=7, value="COE Verification Seal").font = Font(bold=True, size=10)

    # Column Widths Auto-Adjust
    col_widths = {
        'A': 8,   # Sl No
        'B': 18,  # USN
        'C': 26,  # Student Name
        'D': 12,  # Desk No
        'E': 20,  # Attendance Status
        'F': 24,  # Scanned QP Barcode
        'G': 22,  # Verification Time
        'H': 22   # Signature
    }
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width

    if output_path is None:
        reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'generated_reports')
        os.makedirs(reports_dir, exist_ok=True)
        filename = f"Attendance_COE_{session_data['course_code']}_{session_data['room_number'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        output_path = os.path.join(reports_dir, filename)

    wb.save(output_path)
    return output_path
