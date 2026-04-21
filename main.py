import streamlit as st
import sqlite3
import os
import uuid
from datetime import datetime
from PIL import Image
import io
import pandas as pd

# المسارات والبيانات الأساسية
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "workshop.db")
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
LOGO_PATH = os.path.join(APP_DIR, "petra_logo.png")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALARM_THRESHOLD = 3

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE
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
    pn = project_number.strip() if project_number else ""
    query = "SELECT COUNT(*) FROM entries WHERE petra_code = ? AND project_number = ?"
    dup = conn.execute(query, (petra_code, pn)).fetchone()[0]
    conn.close()
    return dup > 0

def save_entry(petra_code, part_number, project_number, notes, image_path):
    conn = get_connection()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO entries (petra_code, part_number, project_number, notes, image_path, timestamp) VALUES (?,?,?,?,?,?)",
        (petra_code, part_number, project_number, notes, image_path, timestamp)
    )
    conn.commit()
    conn.close()

def get_all_entries():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM entries ORDER BY timestamp DESC").fetchall()
    conn.close()
    return rows

def get_counts(petra_code):
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM entries WHERE petra_code = ?", (petra_code,)).fetchone()[0]
    conn.close()
    return count

def delete_entries(ids):
    conn = get_connection()
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM entries WHERE id IN ({placeholders})", ids)
    conn.commit()
    conn.close()

# ─────────────────────────────────────────────────────────────────────────────
# APP INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

init_db()
st.set_page_config(page_title="Petra Panel Workshop", layout="wide")

# عرض اللوجو
col_l, col_c, col_r = st.columns([1, 2, 1])
with col_c:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=250)

st.title("🏭 Panel Workshop - Fault Reporter")

tab_submit, tab_dashboard, tab_admin = st.tabs(["Submit Entry", "Dashboard", "Admin / Delete"])

with tab_submit:
    st.header("Report a Faulty Part")
    with st.form("entry_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            p_code = st.text_input("Petra Code *")
            p_num = st.text_input("Part Number")
        with c2:
            prj_num = st.text_input("Project Number")
            notes = st.text_area("Notes")
        
        st.subheader("Capture Image")
        method = st.radio("Method", ["Device Camera / Gallery", "In-App Camera"])
        img_file = st.file_uploader("Upload") if "Device" in method else st.camera_input("Take Photo")
        
        if st.form_submit_button("Submit Report", type="primary"):
            if not p_code.strip():
                st.error("Petra Code is required!")
            elif is_duplicate(p_code.strip(), p_num.strip(), prj_num.strip()):
                st.warning("This entry already exists!")
            else:
                img_path = None
                if img_file:
                    fname = uuid.uuid4().hex + ".png"
                    img_path = os.path.join(UPLOAD_DIR, fname)
                    Image.open(img_file).save(img_path)
                
                save_entry(p_code.strip(), p_num.strip(), prj_num.strip(), notes.strip(), img_path)
                st.success("Submitted successfully!")
                
                # فحص التكرار للإنذار
                total = get_counts(p_code.strip())
                if total >= ALARM_THRESHOLD:
                    st.error(f"🚨 ALERT: Petra Code {p_code} has been reported {total} times!")
                st.rerun()

    # عرض التسليمات "براني"
    st.markdown("---")
    st.header("Recent Submissions")
    all_data = get_all_entries()
    for row in all_data:
        with st.expander(f"{row['timestamp']} | Petra: {row['petra_code']} | Project: {row['project_number']}"):
            col_t, col_i = st.columns([2, 1])
            with col_t:
                st.write(f"**Part Number:** {row['part_number']}")
                st.write(f"**Notes:** {row['notes']}")
            with col_i:
                if row['image_path'] and os.path.exists(row['image_path']):
                    st.image(row['image_path'], use_container_width=True)

with tab_dashboard:
    st.header("Reports")
    # هنا يمكن إضافة كود الإكسل لاحقاً إذا احتجت

with tab_admin:
    st.header("Admin Management")
    entries = get_all_entries()
    if entries:
        # عرض تفاصيل كاملة في قائمة الحذف
        options = {f"ID: {r['id']} | {r['timestamp']} | Petra: {r['petra_code']}": r['id'] for r in entries}
        to_del = st.multiselect("Select entries to delete", list(options.keys()))
        if st.button("Delete Selected", type="primary"):
            delete_entries([options[x] for x in to_del])
            st.success("Deleted successfully!")
            st.rerun()
