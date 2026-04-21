import streamlit as st
import sqlite3
import os
import uuid
from datetime import datetime
from PIL import Image
import io
import base64
import pandas as pd

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
        CREATE TABLE IF NOT EXISTS entries_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            petra_code TEXT NOT NULL,
            part_number TEXT,
            project_number TEXT,
            notes TEXT,
            image_path TEXT,
            timestamp TEXT NOT NULL
        )
    """)
    existing_tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    if "entries" in existing_tables and "entries_new" in existing_tables:
        count = conn.execute("SELECT COUNT(*) FROM entries_new").fetchone()[0]
        if count == 0:
            conn.execute("""
                INSERT INTO entries_new
                    (id, petra_code, part_number, project_number, notes, image_path, timestamp)
                SELECT id, petra_code, part_number, project_number, notes, image_path, timestamp
                FROM entries
            """)
        conn.execute("DROP TABLE entries")
        conn.execute("ALTER TABLE entries_new RENAME TO entries")
    elif "entries_new" in existing_tables:
        conn.execute("ALTER TABLE entries_new RENAME TO entries")
    conn.commit()
    conn.close()


def is_duplicate(petra_code, part_number, project_number):
    """Return (is_dup, reason) — checks petra_code+project and part_number+project combos."""
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

        if part_number and part_number.strip():
            part_dup = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE part_number = ? AND (project_number IS NULL OR project_number = '')",
                (part_number.strip(),)
            ).fetchone()[0]
            if part_dup > 0:
                conn.close()
                return True, f"Part Number '{part_number.strip()}' already exists with no project number."

    conn.close()
    return False, ""


def save_entry(petra_code, part_number, project_number, notes, image_path):
    conn = get_connection()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """INSERT INTO entries
           (petra_code, part_number, project_number, notes, image_path, timestamp)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            petra_code,
            part_number if part_number else None,
            project_number if project_number else None,
            notes if notes else None,
            image_path,
            timestamp,
        )
    )
    conn.commit()
    conn.close()


def delete_entries(ids):
    if not ids:
        return
    conn = get_connection()
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM entries WHERE id IN ({placeholders})", ids)
    conn.commit()
    conn.close()


def count_after_save(petra_code, part_number):
    conn = get_connection()
    petra_count = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE petra_code = ?", (petra_code,)
    ).fetchone()[0]
    part_count = 0
    if part_number:
        part_count = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE part_number = ?", (part_number,)
        ).fetchone()[0]
    conn.close()
    return petra_count, part_count


def get_all_entries():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM entries ORDER BY timestamp DESC").fetchall()
    conn.close()
    return rows


def get_critical_petra_codes():
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT petra_code,
               COUNT(*) AS total_count,
               MAX(timestamp) AS last_seen
        FROM entries
        GROUP BY petra_code
        HAVING COUNT(*) >= {ALARM_THRESHOLD}
        ORDER BY total_count DESC
    """).fetchall()
    conn.close()
    return rows


def get_critical_part_numbers():
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT part_number,
               COUNT(*) AS total_count,
               MAX(timestamp) AS last_seen
        FROM entries
        WHERE part_number IS NOT NULL AND part_number != ''
        GROUP BY part_number
        HAVING COUNT(*) >= {ALARM_THRESHOLD}
        ORDER BY total_count DESC
    """).fetchall()
    conn.close()
    return rows


def get_recurring_entries_full():
    """Return all individual entries belonging to any critical petra_code or part_number."""
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT id, project_number, petra_code, part_number, notes, timestamp
        FROM entries
        WHERE petra_code IN (
            SELECT petra_code FROM entries
            GROUP BY petra_code HAVING COUNT(*) >= {ALARM_THRESHOLD}
        )
        OR (
            part_number IS NOT NULL AND part_number != '' AND
            part_number IN (
                SELECT part_number FROM entries
                WHERE part_number IS NOT NULL AND part_number != ''
                GROUP BY part_number HAVING COUNT(*) >= {ALARM_THRESHOLD}
            )
        )
        ORDER BY petra_code, part_number, timestamp
    """).fetchall()
    conn.close()
    return rows


def build_excel_report():
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

    critical_petra = get_critical_petra_codes()
    critical_parts = get_critical_part_numbers()
    full_rows = get_recurring_entries_full()

    red_fill = PatternFill(start_color="C00000", end_color="C00000", fill_type="solid")
    white_bold = Font(color="FFFFFF", bold=True, size=12)
    center = Alignment(horizontal="center", vertical="center")
    thin = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    def style_sheet(ws):
        for cell in ws[1]:
            cell.fill = red_fill
            cell.font = white_bold
            cell.alignment = center
            cell.border = thin
        for col in ws.columns:
            max_len = max((len(str(c.value)) if c.value else 0) for c in col)
            ws.column_dimensions[col[0].column_letter].width = max_len + 6

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:

        # Sheet 1 — Full detail rows for recurring entries
        detail_data = [
            {
                "Project Number": r["project_number"] or "—",
                "Petra Code": r["petra_code"],
                "Part Number": r["part_number"] or "—",
                "Notes": r["notes"] or "—",
                "Submission Date": r["timestamp"],
            }
            for r in full_rows
        ]
        detail_df = pd.DataFrame(detail_data) if detail_data else pd.DataFrame(
            columns=["Project Number", "Petra Code", "Part Number", "Notes", "Submission Date"]
        )
        detail_df.to_excel(writer, index=False, sheet_name="Recurring Entries (Detail)")
        style_sheet(writer.sheets["Recurring Entries (Detail)"])

        # Sheet 2 — Summary: critical petra codes
        petra_rows = [
            {
                "Petra Code": r["petra_code"],
                "Total Occurrences": r["total_count"],
                "Last Reported Date": r["last_seen"],
            }
            for r in critical_petra
        ]
        petra_df = pd.DataFrame(petra_rows) if petra_rows else pd.DataFrame(
            columns=["Petra Code", "Total Occurrences", "Last Reported Date"]
        )
        petra_df.to_excel(writer, index=False, sheet_name="Critical Petra Codes")
        style_sheet(writer.sheets["Critical Petra Codes"])

        # Sheet 3 — Summary: critical part numbers
        part_rows = [
            {
                "Part Number": r["part_number"],
                "Total Occurrences": r["total_count"],
                "Last Reported Date": r["last_seen"],
            }
            for r in critical_parts
        ]
        parts_df = pd.DataFrame(part_rows) if part_rows else pd.DataFrame(
            columns=["Part Number", "Total Occurrences", "Last Reported Date"]
        )
        parts_df.to_excel(writer, index=False, sheet_name="Critical Part Numbers")
        style_sheet(writer.sheets["Critical Part Numbers"])

    output.seek(0)
    return output


def save_image(image_file):
    filename = f"{uuid.uuid4().hex}.png"
    filepath = os.path.join(UPLOAD_DIR, filename)
    img = Image.open(image_file)
    img.save(filepath)
    return filepath


# ─────────────────────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────────────────────

init_db()

st.set_page_config(
    page_title="Panel Workshop - Fault Reporter",
    page_icon="🏭",
    layout="wide"
)

col_l, col_c, col_r = st.columns([1, 2, 1])
with col_c:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=250)

st.title("🏭 Panel Workshop — Fault Reporter")

tab_submit, tab_dashboard, tab_admin = st.tabs(
    ["📋 Submit Entry", "📊 Dashboard", "🗑️ Admin / Delete"]
)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — SUBMIT ENTRY
# ─────────────────────────────────────────────────────────────────────────────
with tab_submit:
    st.header("Report a Faulty Part")
    st.markdown(
        "<div style='background-color:#e3f2fd;color:#0d47a1;padding:10px 16px;"
        "border-radius:6px;border-left:4px solid #1976d2;margin-bottom:12px;font-size:14px;'>"
        "Fields marked with <strong>*</strong> are required. All other fields are optional. "
        "The submission date and time are recorded automatically."
        "</div>",
        unsafe_allow_html=True,
    )

    with st.form("entry_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            petra_code = st.text_input(
                "Petra Code *",
                placeholder="Enter Petra Code (required)",
                help="The Petra code for the faulty part — this is the only required field"
            )
            part_number = st.text_input(
                "Part Number",
                placeholder="Enter Part Number (optional)",
            )

        with col2:
            project_number = st.text_input(
                "Project Number",
                placeholder="Enter Project Number (optional)",
            )

        notes = st.text_area(
            "Notes (optional)",
            placeholder="Describe the fault, observations, or any additional details...",
            height=120
        )

        st.subheader("Capture Image (optional)")
        capture_method = st.radio(
            "Choose capture method",
            options=[
                "📱 Use device camera / gallery (recommended for mobile — allows front/back camera switching)",
                "💻 Use in-browser camera (desktop default)",
            ],
            index=0,
            help="On mobile, the device camera option lets you choose front camera, back camera, or pick from your gallery."
        )

        camera_image = None
        if capture_method.startswith("📱"):
            camera_image = st.file_uploader(
                "Tap to open your camera or pick a photo",
                type=["png", "jpg", "jpeg"],
                accept_multiple_files=False,
                help="On mobile this opens your device's native picker — choose front camera, back camera, or an existing photo."
            )
        else:
            camera_image = st.camera_input("Take a photo of the faulty part")

        submitted = st.form_submit_button(
            "Submit Report", use_container_width=True, type="primary"
        )

        if submitted:
            if not petra_code.strip():
                st.error("Petra Code is required. Please enter a Petra Code before submitting.")
            else:
                dup, dup_reason = is_duplicate(
                    petra_code.strip(), part_number.strip(), project_number.strip()
                )
                if dup:
                    st.error(
                        f"⛔ Duplicate entry blocked: {dup_reason} "
                        "This combination has already been submitted. "
                        "Please verify the data before resubmitting."
                    )
                else:
                    image_path = None
                    if camera_image:
                        image_path = save_image(camera_image)

                    save_entry(
                        petra_code.strip(),
                        part_number.strip(),
                        project_number.strip(),
                        notes.strip(),
                        image_path,
                    )

                    petra_count, part_count = count_after_save(
                        petra_code.strip(), part_number.strip()
                    )

                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    st.success(f"✅ Entry submitted successfully! Recorded at: **{now_str}**")

                    alarm_petra = petra_count >= ALARM_THRESHOLD
                    alarm_part = part_number.strip() and part_count >= ALARM_THRESHOLD

                    if alarm_petra or alarm_part:
                        st.markdown(
                            "<div style='background-color:#FF0000;color:white;padding:30px;"
                            "border-radius:10px;text-align:center;font-size:22px;font-weight:bold;"
                            "margin-top:20px;border:4px solid #8B0000;"
                            "box-shadow:0 0 20px rgba(255,0,0,0.5);'>"
                            "⚠️ HIGH PRIORITY ⚠️<br><br>"
                            "This part has repeated issues.<br>"
                            "Please check EPLAN routing/definition."
                            "</div>",
                            unsafe_allow_html=True,
                        )
                        details = []
                        if alarm_petra:
                            details.append(
                                f"Petra Code <strong>'{petra_code}'</strong> has now been reported "
                                f"<strong>{petra_count}</strong> time(s)."
                            )
                        if alarm_part:
                            details.append(
                                f"Part Number <strong>'{part_number}'</strong> has now been reported "
                                f"<strong>{part_count}</strong> time(s)."
                            )
                        st.markdown(
                            "<div style='background-color:#fff3cd;color:#856404;padding:15px;"
                            "border-radius:8px;margin-top:10px;font-size:15px;"
                            "border-left:5px solid #ffc107;'>"
                            + "<br>".join(details) + "</div>",
                            unsafe_allow_html=True,
                        )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
with tab_dashboard:

    critical_petra = get_critical_petra_codes()
    critical_parts = get_critical_part_numbers()
    has_critical = len(critical_petra) > 0 or len(critical_parts) > 0

    st.markdown("## ⚠️ Critical Recurring Issues")
    st.caption(f"Items reported {ALARM_THRESHOLD} or more times.")

    if not has_critical:
        st.markdown(
            "<div style='background-color:#e8f5e9;color:#2e7d32;padding:16px;"
            "border-radius:8px;border-left:5px solid #43a047;font-size:15px;'>"
            "✅ No recurring issues detected. All parts are within acceptable submission limits."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='background-color:#b71c1c;color:white;padding:18px 22px;"
            "border-radius:10px;border:3px solid #7f0000;margin-bottom:12px;'>"
            f"<span style='font-size:20px;font-weight:bold;'>🚨 The following codes have been "
            f"reported {ALARM_THRESHOLD}+ times and require immediate EPLAN review.</span>"
            "</div>",
            unsafe_allow_html=True,
        )

        col_petra, col_parts = st.columns(2)

        with col_petra:
            st.markdown(
                "<div style='background-color:#fff3f3;border:2px solid #e53935;"
                "border-radius:8px;padding:10px 14px;'>"
                "<strong style='color:#b71c1c;font-size:15px;'>🔑 Recurring Petra Codes</strong>"
                "</div>",
                unsafe_allow_html=True,
            )
            if critical_petra:
                st.dataframe(
                    pd.DataFrame([{
                        "Petra Code": r["petra_code"],
                        "Occurrences": r["total_count"],
                        "Last Reported": r["last_seen"],
                    } for r in critical_petra]),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.info("None found.")

        with col_parts:
            st.markdown(
                "<div style='background-color:#fff3f3;border:2px solid #e53935;"
                "border-radius:8px;padding:10px 14px;'>"
                "<strong style='color:#b71c1c;font-size:15px;'>🔩 Recurring Part Numbers</strong>"
                "</div>",
                unsafe_allow_html=True,
            )
            if critical_parts:
                st.dataframe(
                    pd.DataFrame([{
                        "Part Number": r["part_number"],
                        "Occurrences": r["total_count"],
                        "Last Reported": r["last_seen"],
                    } for r in critical_parts]),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.info("None found.")

    st.markdown("---")
    st.markdown("## 📤 Export Critical Issues")
    st.markdown(
        "<div style='background-color:#1a237e;color:white;padding:16px 20px;"
        "border-radius:10px;border:2px solid #0d47a1;margin-bottom:14px;'>"
        "<strong style='font-size:16px;'>Generates an Excel file
