import streamlit as st
import sqlite3
import os
import uuid
from datetime import datetime
from PIL import Image
import io
import pandas as pd

# الإعدادات الأساسية للمسارات
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "workshop.db")
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
LOGO_PATH = os.path.join(APP_DIR, "petra_logo.png")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALARM_THRESHOLD = 3

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            petra_code TEXT NOT NULL,
            part_number TEXT,
            project_number TEXT,
            notes TEXT,
            image_path TEXT,
            timestamp TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def is_duplicate(petra_code, part_number, project_number):
    conn = get_connection()
    pn = project_number.strip() if project_number and project_number.strip() else None
    
    if pn:
        petra_dup = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE petra_code = ? AND project_number = ?",
            (petra_code, pn)
        ).fetchone()[0]
        if petra_dup > 0:
            conn.close()
            return True, f"Petra Code '{petra_code}' already exists for Project '{pn}'."

        if part_number and part_number.strip():
            part_dup = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE part_number = ? AND project_number = ?",
                (part_number.strip(), pn)
            ).fetchone()[0]
            if part_dup > 0:
                conn.close()
                return True, f"Part Number '{part_number.strip()}' already exists for Project '{pn}'."
    else:
        petra_dup = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE petra_code = ? AND (project_number IS NULL OR project_number = '')",
            (petra_code,)
        ).fetchone()[0]
        if petra_dup > 0:
            conn.close()
            return True, f"Petra Code '{petra_code}' already exists with no project number."

    conn.close()
    return False, ""

def save_entry(petra_code, part_number, project_number, notes, image_path):
    conn = get_connection()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """INSERT INTO entries
           (petra_code, part_number, project_number, notes, image_path, timestamp)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (petra_code, part_number or None, project_number or None, notes or None, image_path, timestamp)
    )
    conn.commit()
    conn.close()

def delete_entries(ids):
    if not ids: return
    conn = get_connection()
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM entries WHERE id IN ({placeholders})", ids)
    conn.commit()
    conn.close()

def count_after_save(petra_code, part_number):
    conn = get_connection()
    p_count = conn.execute("SELECT COUNT(*) FROM entries WHERE petra_code = ?", (petra_code,)).fetchone()[0]
    pn_count = 0
    if part_number:
        pn_count = conn.execute("SELECT COUNT(*) FROM entries WHERE part_number = ?", (part_number,)).fetchone()[0]
    conn.close()
    return p_count, pn_count

def get_all_entries():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM entries ORDER BY timestamp DESC").fetchall()
    conn.close()
    return rows

def get_critical_petra_codes():
    conn = get_connection()
    rows = conn.execute(
        f"SELECT petra_code, COUNT(*) AS total_count, MAX(timestamp) AS last_seen "
        f"FROM entries GROUP BY petra_code HAVING COUNT(*) >= {ALARM_THRESHOLD} "
        "ORDER BY total_count DESC"
    ).fetchall()
    conn.close()
    return rows

def get_critical_part_numbers():
    conn = get_connection()
    rows = conn.execute(
        f"SELECT part_number, COUNT(*) AS total_count, MAX(timestamp) AS last_seen "
        f"FROM entries WHERE part_number IS NOT NULL AND part_number != '' "
        f"GROUP BY part_number HAVING COUNT(*) >= {ALARM_THRESHOLD} "
        "ORDER BY total_count DESC"
    ).fetchall()
    conn.close()
    return rows

def get_recurring_entries_full():
    conn = get_connection()
    t = str(ALARM_THRESHOLD)
    query = f"""
        SELECT id, project_number, petra_code, part_number, notes, timestamp FROM entries
        WHERE petra_code IN (SELECT petra_code FROM entries GROUP BY petra_code HAVING COUNT(*) >= {t})
        OR (part_number IS NOT NULL AND part_number != '' AND part_number IN 
        (SELECT part_number FROM entries WHERE part_number IS NOT NULL AND part_number != '' 
        GROUP BY part_number HAVING COUNT(*) >= {t}))
        ORDER BY petra_code, part_number, timestamp
    """
    rows = conn.execute(query).fetchall()
    conn.close()
    return rows

def build_excel_report():
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    critical_petra = get_critical_petra_codes()
    critical_parts = get_critical_part_numbers()
    full_rows = get_recurring_entries_full()
    
    red_fill = PatternFill(start_color="C00000", end_color="C00000", fill_type="solid")
    white_bold = Font(color="FFFFFF", bold=True)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        detail_df = pd.DataFrame([dict(r) for r in full_rows])
        detail_df.to_excel(writer, index=False, sheet_name="Details")
        
        petra_df = pd.DataFrame([dict(r) for r in critical_petra])
        petra_df.to_excel(writer, index=False, sheet_name="Critical Petra")
        
        parts_df = pd.DataFrame([dict(r) for r in critical_parts])
        parts_df.to_excel(writer, index=False, sheet_name="Critical Parts")
    
    output.seek(0)
    return output

def save_image(image_file):
    filename = uuid.uuid4().hex + ".png"
    filepath = os.path.join(UPLOAD_DIR, filename)
    img = Image.open(image_file)
    img.save(filepath)
    return filepath

# ─────────────────────────────────────────────────────────────────────────────
# APP INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

init_db()
st.set_page_config(page_title="Petra Panel Workshop", layout="wide")

st.title("🏭 Panel Workshop - Fault Reporter")

tab_submit, tab_dashboard, tab_admin = st.tabs(["Submit Entry", "Dashboard", "Admin"])

with tab_submit:
    with st.form("entry_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            petra_code = st.text_input("Petra Code *")
            part_number = st.text_input("Part Number")
        with col2:
            project_number = st.text_input("Project Number")
        
        notes = st.text_area("Notes")
        
        capture_method = st.radio("Capture Method", ["Device Camera / Gallery", "Browser Camera"])
        camera_image = st.file_uploader("Upload/Capture") if "Device" in capture_method else st.camera_input("Scan")
        
        if st.form_submit_button("Submit Report", type="primary"):
            if not petra_code.strip():
                st.error("Petra Code is required!")
            else:
                is_dup, reason = is_duplicate(petra_code.strip(), part_number.strip(), project_number.strip())
                if is_dup:
                    st.error(reason)
                else:
                    img_path = save_image(camera_image) if camera_image else None
                    save_entry(petra_code.strip(), part_number.strip(), project_number.strip(), notes.strip(), img_path)
                    st.success("Submitted successfully!")
                    st.rerun()

with tab_dashboard:
    st.header("Dashboard & Reports")
    if st.button("Download Excel Report"):
        data = build_excel_report()
        st.download_button("Click to Download", data, "report.xlsx")

with tab_admin:
    st.header("Delete Records")
    entries = get_all_entries()
    if entries:
        to_delete = st.multiselect("Select IDs", [r['id'] for r in entries])
        if st.button("Delete Selected"):
            delete_entries(to_delete)
            st.success("Deleted!")
            st.rerun()
