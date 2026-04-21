import streamlit as st
import sqlite3
import os
import uuid
from datetime import datetime
from PIL import Image
import io
import pandas as pd

# 1. إعدادات المسارات
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "workshop.db")
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
LOGO_PATH = os.path.join(APP_DIR, "petra_logo.png")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALARM_THRESHOLD = 3

# 2. وظائف قاعدة البيانات
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

def save_entry(p_code, p_num, prj_num, notes, img_path):
    conn = get_connection()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO entries (petra_code, part_number, project_number, notes, image_path, timestamp) VALUES (?,?,?,?,?,?)",
        (p_code, p_num, prj_num, notes, img_path, ts)
    )
    conn.commit()
    conn.close()

def get_all_entries():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM entries ORDER BY timestamp DESC").fetchall()
    conn.close()
    return rows

def get_counts(p_code):
    conn = get_connection()
    c = conn.execute("SELECT COUNT(*) FROM entries WHERE petra_code = ?", (p_code,)).fetchone()[0]
    conn.close()
    return c

# 3. واجهة التطبيق
init_db()
st.set_page_config(page_title="Panel Workshop", layout="wide")

# عرض اللوجو
col_l, col_c, col_r = st.columns([1, 2, 1])
with col_c:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=250)

st.title("🏭 Panel Workshop - Fault Reporter")

tab_submit, tab_dashboard, tab_admin = st.tabs(["Submit Entry", "Dashboard", "Admin / Delete"])

# --- TAB 1: SUBMIT ---
with tab_submit:
    st.header("Report a Faulty Part")
    with st.form("main_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            p_code = st.text_input("Petra Code *")
            p_num = st.text_input("Part Number")
        with c2:
            prj_num = st.text_input("Project Number")
            notes = st.text_area("Notes")
        
        st.subheader("Capture Photo")
        # حل مشكلة الكاميرا: خيارين واضحين
        cam_method = st.radio("Photo Source", ["Camera Scan", "Upload from Gallery/File"])
        img_file = st.camera_input("Scan Part") if cam_method == "Camera Scan" else st.file_uploader("Choose Image", type=['png', 'jpg', 'jpeg'])
        
        if st.form_submit_button("Submit Report", type="primary"):
            if not p_code.strip():
                st.error("Please enter Petra Code!")
            else:
                img_path = None
                if img_file:
                    fname = f"{uuid.uuid4().hex}.png"
                    img_path = os.path.join(UPLOAD_DIR, fname)
                    Image.open(img_file).save(img_path)
                
                save_entry(p_code.strip(), p_num.strip(), prj_num.strip(), notes.strip(), img_path)
                
                # تنبيه التكرار
                count = get_counts(p_code.strip())
                if count >= ALARM_THRESHOLD:
                    st.error(f"🚨 CRITICAL: Code {p_code} reported {count} times! Check EPLAN.")
                else:
                    st.success("Entry Saved!")
                st.rerun()

    st.markdown("---")
    st.header("Recent Submissions")
    for r in get_all_entries():
        with st.expander(f"📌 {r['timestamp']} | Petra: {r['petra_code']}"):
            ci, ct = st.columns([1, 2])
            with ci:
                if r['image_path'] and os.path.exists(r['image_path']):
                    st.image(r['image_path'], use_container_width=True)
            with ct:
                st.write(f"**Project:** {r['project_number'] or 'N/A'}")
                st.write(f"**Part #:** {r['part_number'] or 'N/A'}")
                st.info(f"**Notes:** {r['notes'] or 'No notes'}")

# --- TAB 2: DASHBOARD ---
with tab_dashboard:
    st.header("Reports & Analytics")
    data = get_all_entries()
    if data:
        df = pd.DataFrame([dict(r) for r in data])
        # زر الإكسل اللي كان في الصورة
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='All_Entries')
        
        st.download_button(
            label="📥 Export All Entries to Excel",
            data=output.getvalue(),
            file_name=f"Fault_Report_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.ms-excel",
            type="primary"
        )
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No data to show yet.")

# --- TAB 3: ADMIN ---
with tab_admin:
    st.header("Delete Records")
    all_r = get_all_entries()
    if all_r:
        choices = {f"[{r['id']}] {r['timestamp']} - {r['petra_code']}": r['id'] for r in all_r}
        selected = st.multiselect("Select entries to remove", list(choices.keys()))
        if st.button("Confirm Delete", type="primary"):
            conn = get_connection()
            for s in selected:
                conn.execute("DELETE FROM entries WHERE id = ?", (choices[s],))
            conn.commit()
            conn.close()
            st.success("Deleted!")
            st.rerun()
