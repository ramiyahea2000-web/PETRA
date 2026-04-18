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
                INSERT INTO entries_new (id, petra_code, part_number, project_number, notes, image_path, timestamp)
                SELECT id, petra_code, part_number, project_number, notes, image_path, timestamp
                FROM entries
            """)
        conn.execute("DROP TABLE entries")
        conn.execute("ALTER TABLE entries_new RENAME TO entries")
    elif "entries_new" in existing_tables:
        conn.execute("ALTER TABLE entries_new RENAME TO entries")
    conn.commit()
    conn.close()


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
    rows = conn.execute(
        "SELECT * FROM entries ORDER BY timestamp DESC"
    ).fetchall()
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


def build_excel_report():
    critical_petra = get_critical_petra_codes()
    critical_parts = get_critical_part_numbers()

    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
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

        red_fill = PatternFill(start_color="C00000", end_color="C00000", fill_type="solid")
        white_bold = Font(color="FFFFFF", bold=True, size=12)
        center = Alignment(horizontal="center", vertical="center")
        thin = Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin"),
        )

        for sheet_name in ["Critical Petra Codes", "Critical Part Numbers"]:
            ws = writer.sheets[sheet_name]
            for cell in ws[1]:
                cell.fill = red_fill
                cell.font = white_bold
                cell.alignment = center
                cell.border = thin
            for col in ws.columns:
                max_len = max((len(str(cell.value)) if cell.value else 0) for cell in col)
                ws.column_dimensions[col[0].column_letter].width = max_len + 6

    output.seek(0)
    return output


def save_image(image_file):
    filename = f"{uuid.uuid4().hex}.png"
    filepath = os.path.join(UPLOAD_DIR, filename)
    img = Image.open(image_file)
    img.save(filepath)
    return filepath


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

tab_submit, tab_dashboard = st.tabs(["📋 Submit Entry", "📊 Dashboard"])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — SUBMIT ENTRY
# ─────────────────────────────────────────────────────────────────────────────
with tab_submit:
    st.header("Report a Faulty Part")
    st.markdown(
        "<div style='background-color:#e3f2fd;color:#0d47a1;padding:10px 16px;"
        "border-radius:6px;border-left:4px solid #1976d2;margin-bottom:12px;font-size:14px;'>"
        "Fields marked with <strong>*</strong> are required. All other fields are optional."
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
                help="The part number of the faulty component"
            )

        with col2:
            project_number = st.text_input(
                "Project Number",
                placeholder="Enter Project Number (optional)",
                help="The associated project number"
            )

        notes = st.text_area(
            "Notes (optional)",
            placeholder="Describe the fault, observations, or any additional details...",
            height=120
        )

        st.subheader("Capture Image (optional)")
        camera_image = st.camera_input(
            "Take a photo of the faulty part",
            help="Use your camera to capture the faulty part"
        )

        submitted = st.form_submit_button("Submit Report", use_container_width=True, type="primary")

        if submitted:
            if not petra_code.strip():
                st.error("Petra Code is required. Please enter a Petra Code before submitting.")
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

                st.success("✅ Entry submitted successfully!")

                alarm_petra = petra_count >= ALARM_THRESHOLD
                alarm_part = part_number.strip() and part_count >= ALARM_THRESHOLD

                if alarm_petra or alarm_part:
                    st.markdown(
                        "<div style='"
                        "background-color:#FF0000;color:white;padding:30px;"
                        "border-radius:10px;text-align:center;font-size:22px;"
                        "font-weight:bold;margin-top:20px;border:4px solid #8B0000;"
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

    # ── Section 1: Critical Recurring Issues ─────────────────────────────────
    st.markdown("## ⚠️ Critical Recurring Issues")
    st.caption(f"Items that have been reported {ALARM_THRESHOLD} or more times are listed below.")

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
            "<span style='font-size:20px;font-weight:bold;'>🚨 The following codes have been "
            f"reported {ALARM_THRESHOLD}+ times and require immediate EPLAN routing/definition review.</span>"
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
                petra_df = pd.DataFrame([
                    {
                        "Petra Code": r["petra_code"],
                        "Occurrences": r["total_count"],
                        "Last Reported": r["last_seen"],
                    }
                    for r in critical_petra
                ])
                st.dataframe(petra_df, use_container_width=True, hide_index=True)
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
                parts_df = pd.DataFrame([
                    {
                        "Part Number": r["part_number"],
                        "Occurrences": r["total_count"],
                        "Last Reported": r["last_seen"],
                    }
                    for r in critical_parts
                ])
                st.dataframe(parts_df, use_container_width=True, hide_index=True)
            else:
                st.info("None found.")

    # ── Section 2: Export Critical Issues ────────────────────────────────────
    st.markdown("---")
    st.markdown("## 📤 Export Critical Issues")

    st.markdown(
        "<div style='background-color:#1a237e;color:white;padding:16px 20px;"
        "border-radius:10px;border:2px solid #0d47a1;margin-bottom:14px;'>"
        "<strong style='font-size:16px;'>Generate an Excel report containing all Petra Codes "
        "and Part Numbers that have been reported 3 or more times, with full occurrence details.</strong>"
        "</div>",
        unsafe_allow_html=True,
    )

    if has_critical:
        excel_data = build_excel_report()
        st.download_button(
            label="📥 Download Critical Issues Report (Excel)",
            data=excel_data,
            file_name=f"Critical_Issues_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )
        total_critical = len(critical_petra) + len(critical_parts)
        st.caption(
            f"Report will include {len(critical_petra)} Petra Code(s) and "
            f"{len(critical_parts)} Part Number(s) — {total_critical} item(s) total."
        )
    else:
        st.info("No critical issues to export yet. The export button will appear once items reach the threshold.")

    # ── Section 3: All Entries ────────────────────────────────────────────────
    st.markdown("---")
    st.header("📋 All Submitted Entries")

    entries = get_all_entries()

    if not entries:
        st.info("No entries yet. Submit your first fault report using the 'Submit Entry' tab.")
    else:
        st.write(f"**Total entries:** {len(entries)}")
        search_term = st.text_input("🔍 Search by Petra Code, Part Number, or Project Number", "")

        filtered = entries
        if search_term:
            s = search_term.lower()
            filtered = [
                e for e in entries
                if s in (e["petra_code"] or "").lower()
                or s in (e["part_number"] or "").lower()
                or s in (e["project_number"] or "").lower()
            ]

        st.write(f"Showing **{len(filtered)}** record(s)")

        for entry in filtered:
            label = f"📄 {entry['timestamp']} | Petra: {entry['petra_code']}"
            if entry["part_number"]:
                label += f" | Part: {entry['part_number']}"
            if entry["project_number"]:
                label += f" | Project: {entry['project_number']}"

            with st.expander(label, expanded=False):
                col_info, col_img = st.columns([2, 1])

                with col_info:
                    st.markdown(f"**🕐 Timestamp:** {entry['timestamp']}")
                    st.markdown(f"**🔑 Petra Code:** `{entry['petra_code']}`")
                    st.markdown(f"**🔩 Part Number:** `{entry['part_number'] or '—'}`")
                    st.markdown(f"**📁 Project Number:** `{entry['project_number'] or '—'}`")
                    st.markdown(f"**📝 Notes:** {entry['notes'] if entry['notes'] else '_No notes provided_'}")

                with col_img:
                    if entry["image_path"] and os.path.exists(entry["image_path"]):
                        st.image(entry["image_path"], caption="Captured Photo", use_container_width=True)
                    else:
                        st.markdown("_No image captured_")
