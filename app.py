import streamlit as st
import pandas as pd
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- 1. CONFIGURATION & AUTH ---
MASTER_SHEET_ID = "1dzt0pUF1c3ffLh1_zxiCiwiYKO4-3jFkDx1ErR49m1Q"

def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

def get_quarters():
    today = datetime.today()
    curr_q_start = datetime(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    prev_q_end = curr_q_start - timedelta(days=1)
    prev_q_start = datetime(prev_q_end.year, 3 * ((prev_q_end.month - 1) // 3) + 1, 1)
    return {
        "recent": prev_q_end.strftime("%Y-%m-%d"),
        "preceding": prev_q_start.strftime("%Y-%m-%d")
    }

def fetch_ahrefs_metrics(target, date, api_key):
    url = "https://api.ahrefs.com/v3/site-explorer/metrics"
    params = {"target": target, "date": date}
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.get(url, params=params, headers=headers)
        return resp.json().get('metrics', {}) if resp.status_code == 200 else {}
    except:
        return {}

# --- 2. STREAMLIT UI ---
st.set_page_config(page_title="Ahrefs Reporting Tool", page_icon="🛡️")
st.title("🛡️ Ahrefs Competitor Reporting")

# Sidebar
api_key = st.sidebar.text_input("Ahrefs API V3 Key", type="password")

# --- 3. GOOGLE SHEETS TAB LOGIC ---
# We try to fetch tabs once at the start so the user can choose
existing_tabs = []
try:
    gc = get_gspread_client()
    sh = gc.open_by_key(MASTER_SHEET_ID.strip())
    existing_tabs = [ws.title for ws in sh.worksheets()]
except Exception as e:
    st.sidebar.error("Could not connect to Google Sheets. Check permissions.")

st.subheader("📁 Destination Settings")
tab_mode = st.radio("Tab Destination:", ["Existing Client (Update Tab)", "New Client (Create Tab)"], horizontal=True)

if tab_mode == "Existing Client (Update Tab)":
    target_tab = st.selectbox("Select Existing Tab", existing_tabs if existing_tabs else ["No tabs found"])
else:
    target_tab = st.text_input("New Tab Name (e.g., Client Name)")

st.divider()

# Analysis Inputs
col1, col2 = st.columns(2)
with col1:
    client_site = st.text_input("Client Domain", "example.com")
with col2:
    competitors = st.text_area("Competitors (Max 5, one per line)", "comp1.com\ncomp2.com")

# --- 4. EXECUTION ---
if st.button("Run Analysis & Export"):
    if not api_key:
        st.warning("Enter Ahrefs API Key.")
    elif not target_tab or target_tab == "No tabs found":
        st.warning("Please provide a valid tab name.")
    else:
        with st.spinner("Processing..."):
            dates = get_quarters()
            comp_list = [c.strip() for c in competitors.split("\n") if c.strip()][:5]
            all_domains = [client_site] + comp_list

            results = []
            for domain in all_domains:
                m_now = fetch_ahrefs_metrics(domain, dates['recent'], api_key)
                m_prev = fetch_ahrefs_metrics(domain, dates['preceding'], api_key)

                if m_now and m_prev:
                    results.append({
                        "Domain": domain,
                        "Ref. Domains": m_now.get('refdomains', 0),
                        "RD Change": m_now.get('refdomains', 0) - m_prev.get('refdomains', 0),
                        "Backlinks": m_now.get('backlinks', 0),
                        "Organic Keywords": m_now.get('org_keywords', 0),
                        "Last Updated": datetime.now().strftime("%Y-%m-%d %H:%M")
                    })

            if results:
                df = pd.DataFrame(results)
                st.dataframe(df)

                # Export Logic
                try:
                    # Refresh connection
                    gc = get_gspread_client()
                    sh = gc.open_by_key(MASTER_SHEET_ID.strip())

                    if tab_mode == "New Client (Create Tab)":
                        # Check if it exists anyway to avoid errors
                        if target_tab in [ws.title for ws in sh.worksheets()]:
                            worksheet = sh.worksheet(target_tab)
                        else:
                            worksheet = sh.add_worksheet(title=target_tab, rows="100", cols="20")
                    else:
                        worksheet = sh.worksheet(target_tab)

                    # Update data
                    data_to_upload = [df.columns.values.tolist()] + df.values.tolist()

                    # If updating existing, we might want to append or overwrite.
                    # Overwriting is safer for a clean 'structured' report.
                    worksheet.clear()
                    worksheet.update(data_to_upload)

                    st.success(f"✅ Exported successfully to tab: {target_tab}")
                    st.balloons()
                except Exception as e:
                    st.error(f"Export Error: {e}")
