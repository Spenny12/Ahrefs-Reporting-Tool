import streamlit as st
import pandas as pd
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- 1. CONFIGURATION ---
MASTER_SHEET_ID = "1dzt0pUF1c3ffLh1_zxiCiwiYKO4-3jFkDx1ErR49m1Q"

def get_gspread_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return gspread.authorize(Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes))

def fetch_ahrefs(endpoint, params, api_key):
    url = f"https://api.ahrefs.com/v3/{endpoint}"
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(url, params=params, headers=headers)
    return resp.json() if resp.status_code == 200 else None

# --- 2. UI SETUP ---
st.set_page_config(page_title="SEO Competitor Pulse", layout="wide")
st.title("🛡️ SEO Competitor Pulse & Keyword Tracker")

api_key = st.sidebar.text_input("Ahrefs API Key", type="password")

# Google Sheets Tab Sync
existing_tabs = []
try:
    sh = get_gspread_client().open_by_key(MASTER_SHEET_ID)
    existing_tabs = [ws.title for ws in sh.worksheets()]
except:
    st.sidebar.error("GSheet Connection Pending...")

# --- 3. CONTROLS ---
with st.expander("📅 Date & Destination Settings", expanded=True):
    c1, c2, c3 = st.columns(3)
    with c1:
        date_mode = st.radio("Comparison Period", ["Last Quarter", "Custom Month"])
        if date_mode == "Last Quarter":
            today = datetime.today()
            curr_q_start = datetime(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
            end_date = (curr_q_start - timedelta(days=1)).date()
            start_date = datetime(end_date.year, 3 * ((end_date.month - 1) // 3) + 1, 1).date()
        else:
            start_date = st.date_input("Start Date", datetime.today() - timedelta(days=60))
            end_date = st.date_input("End Date", datetime.today() - timedelta(days=2))

    with c2:
        tab_mode = st.radio("Sheet Mode", ["Existing Client", "New Client"])
        target_tab = st.selectbox("Select Tab", existing_tabs) if tab_mode == "Existing Client" else st.text_input("New Tab Name")

    with c3:
        st.info(f"**Period:** {start_date} vs {end_date}")

col_cl, col_comp = st.columns(2)
with col_cl:
    client_site = st.text_input("Client Domain", "example.com")
with col_comp:
    competitors = st.text_area("Competitors (1 per line)", "comp1.com\ncomp2.com")

# --- 4. DATA PROCESSING ---
if st.button("🚀 Run Analysis & Export"):
    if not api_key or not target_tab:
        st.error("Missing API Key or Tab Name")
    else:
        with st.spinner("Fetching Ahrefs Data..."):
            comp_list = [c.strip() for c in competitors.split("\n") if c.strip()][:5]
            all_domains = [client_site] + comp_list

            summary_data = []
            new_keywords_report = []

            for domain in all_domains:
                # A. Summary Metrics
                m_now = fetch_ahrefs("site-explorer/metrics", {"target": domain, "date": end_date.isoformat()}, api_key)
                m_prev = fetch_ahrefs("site-explorer/metrics", {"target": domain, "date": start_date.isoformat()}, api_key)

                if m_now and m_prev:
                    now = m_now.get('metrics', {})
                    prev = m_prev.get('metrics', {})

                    summary_data.append({
                        "Entity": "CLIENT" if domain == client_site else "COMPETITOR",
                        "Domain": domain,
                        "Ref. Domains": now.get('refdomains', 0),
                        "RD Change": now.get('refdomains', 0) - prev.get('refdomains', 0),
                        "Total Keywords": now.get('org_keywords', 0),
                        "Keyword Change": now.get('org_keywords', 0) - prev.get('org_keywords', 0),
                        "Traffic Est.": now.get('org_traffic', 0)
                    })

                # B. New Keywords Identification
                # Note: This uses 'organic-keywords' to find queries ranking now that weren't before
                kw_params = {"target": domain, "limit": 1000, "where": f'[["first_seen", "gt", "{start_date}"]]'}
                new_kw_res = fetch_ahrefs("site-explorer/organic-keywords", kw_params, api_key)

                if new_kw_res and 'keywords' in new_kw_res:
                    for k in new_kw_res['keywords'][:20]: # Limit to top 20 new for readability
                        new_keywords_report.append({
                            "Domain": domain,
                            "New Keyword": k.get('keyword'),
                            "Position": k.get('position'),
                            "Volume": k.get('volume'),
                            "URL": k.get('url')
                        })

            # --- 5. STRUCTURED EXPORT ---
            try:
                sh = get_gspread_client().open_by_key(MASTER_SHEET_ID)
                if tab_mode == "New Client" and target_tab not in [ws.title for ws in sh.worksheets()]:
                    ws = sh.add_worksheet(title=target_tab, rows="500", cols="20")
                else:
                    ws = sh.worksheet(target_tab)

                ws.clear()

                # Build a human-readable layout
                df_sum = pd.DataFrame(summary_data)
                df_new = pd.DataFrame(new_keywords_report)

                # Header Section
                ws.update("A1", [[f"SEO Performance Report: {start_date} to {end_date}"]])
                ws.update("A2", [["SUMMARY METRICS"]])
                ws.update("A3", [df_sum.columns.values.tolist()] + df_sum.values.tolist())

                # Spacing
                new_kw_row = len(df_sum) + 6
                ws.update(f"A{new_kw_row}", [["TOP NEW KEYWORDS DISCOVERED"]])
                ws.update(f"A{new_kw_row + 1}", [df_new.columns.values.tolist()] + df_new.values.tolist())

                st.success(f"Report pushed to {target_tab}!")
                st.subheader("Summary Preview")
                st.table(df_sum)

            except Exception as e:
                st.error(f"GSheet Export Error: {e}")
