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
    try:
        resp = requests.get(url, params=params, headers=headers)
        return resp.json() if resp.status_code == 200 else None
    except:
        return None

# --- 2. UI SETUP ---
st.set_page_config(page_title="Advanced SEO Auditor", layout="wide")
st.title("🛡️ Advanced Competitor Intelligence Tool")

api_key = st.sidebar.text_input("Ahrefs API Key", type="password")

# --- 3. FIXED DATE CONTROLS ---
with st.sidebar.expander("📅 Reporting Period", expanded=True):
    date_mode = st.radio("Period Type", ["Quarterly", "Monthly"])
    today = datetime.today()

    if date_mode == "Quarterly":
        # Current Quarter (Completed)
        curr_q_start = datetime(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
        current_period_end = (curr_q_start - timedelta(days=1)).date()
        current_period_start = datetime(current_period_end.year, 3 * ((current_period_end.month - 1) // 3) + 1, 1).date()
        # Previous Quarter
        last_period_end = (datetime.combine(current_period_start, datetime.min.time()) - timedelta(days=1)).date()
        last_period_start = datetime(last_period_end.year, 3 * ((last_period_end.month - 1) // 3) + 1, 1).date()
    else:
        # Current Month (Completed)
        current_period_start = (today.replace(day=1) - timedelta(days=1)).replace(day=1).date()
        current_period_end = (today.replace(day=1) - timedelta(days=1)).date()
        # Previous Month
        last_period_start = (current_period_start - timedelta(days=1)).replace(day=1).date()
        last_period_end = (current_period_start - timedelta(days=1)).date()

    st.write(f"**Current Period:** {current_period_start} to {current_period_end}")
    st.write(f"**Comparison Period:** {last_period_start} to {last_period_end}")

# Tab logic
existing_tabs = []
try:
    gc = get_gspread_client()
    sh = gc.open_by_key(MASTER_SHEET_ID)
    existing_tabs = [ws.title for ws in sh.worksheets()]
except:
    st.sidebar.warning("Waiting for GSheet Auth...")

tab_mode = st.sidebar.radio("Sheet Mode", ["Existing Client", "New Client"])
target_tab = st.sidebar.selectbox("Select Tab", existing_tabs) if tab_mode == "Existing Client" else st.sidebar.text_input("New Tab Name")

client_site = st.text_input("Client Domain (e.g., example.com)")
competitors = st.text_area("Competitor Domains (one per line)")

# --- 4. EXECUTION ---
if st.button("Generate Full Audit & Export"):
    if not api_key or not target_tab:
        st.error("Please provide API Key and Tab Name.")
    else:
        with st.spinner("Fetching data from Ahrefs..."):
            domains = [client_site.strip()] + [c.strip() for c in competitors.split("\n") if c.strip()]

            summary_list = []
            top_new_kws = []
            site_changes = []

            for domain in domains:
                # A. SUMMARY STATS
                m_curr = fetch_ahrefs("site-explorer/metrics", {"target": domain, "date": current_period_end.isoformat()}, api_key)
                m_last = fetch_ahrefs("site-explorer/metrics", {"target": domain, "date": last_period_end.isoformat()}, api_key)

                curr_met = m_curr.get('metrics', {}) if m_curr else {}
                last_met = m_last.get('metrics', {}) if m_last else {}

                summary_list.append({
                    "Domain": domain,
                    "RD (Current)": curr_met.get('refdomains', 0),
                    "RD (Last)": last_met.get('refdomains', 0),
                    "RD Change": curr_met.get('refdomains', 0) - last_met.get('refdomains', 0),
                    "KW (Current)": curr_met.get('org_keywords', 0),
                    "KW (Last)": last_met.get('org_keywords', 0),
                    "KW Change": curr_met.get('org_keywords', 0) - last_met.get('org_keywords', 0)
                })

                # B. TOP NEW KEYWORDS
                # 1. Top 10 by Traffic Increase
                kw_gain_params = {
                    "target": domain,
                    "limit": 10,
                    "order_by": "traffic_change:desc",
                    "date": current_period_end.isoformat(),
                    "date_compared": last_period_end.isoformat()
                }
                gainer_res = fetch_ahrefs("site-explorer/organic-keywords", kw_gain_params, api_key)

                # 2. Top 10 Volume (New in Positions 1-3)
                top3_params = {
                    "target": domain,
                    "limit": 10,
                    "order_by": "volume:desc",
                    "where": f'[["position", "lte", 3], ["first_seen", "gt", "{last_period_end}"]]'
                }
                top3_res = fetch_ahrefs("site-explorer/organic-keywords", top3_params, api_key)

                for k in (gainer_res.get('keywords', []) if gainer_res else []):
                    top_new_kws.append({"Domain": domain, "Type": "Traffic Gainer", "Keyword": k['keyword'], "Volume": k['volume'], "Position": k['position'], "Traffic Change": k.get('traffic_change', 0)})

                for k in (top3_res.get('keywords', []) if top3_res else []):
                    top_new_kws.append({"Domain": domain, "Type": "New Top 3 Entry", "Keyword": k['keyword'], "Volume": k['volume'], "Position": k['position'], "URL": k['url']})

                # C. SITE CHANGES (New Pages)
                page_params = {"target": domain, "limit": 20, "where": f'[["first_seen", "gt", "{last_period_end}"]]'}
                pages_res = fetch_ahrefs("site-explorer/pages", page_params, api_key)
                for p in (pages_res.get('pages', []) if pages_res else []):
                    site_changes.append({"Domain": domain, "New Page URL": p['url'], "First Seen": p['first_seen']})

            # --- 5. STRUCTURED EXPORT ---
            try:
                gc = get_gspread_client()
                sh = gc.open_by_key(MASTER_SHEET_ID)

                if tab_mode == "New Client":
                    ws = sh.add_worksheet(title=target_tab, rows="1000", cols="20")
                else:
                    ws = sh.worksheet(target_tab)

                ws.clear()

                # Prepare the data blocks
                header = [
                    ["REPORT PERIOD:", f"{current_period_start} to {current_period_end}"],
                    ["COMPARISON PERIOD:", f"{last_period_start} to {last_period_end}"],
                    [""],
                    ["--- SUMMARY PERFORMANCE ---"]
                ]

                df_sum = pd.DataFrame(summary_list)
                df_kws = pd.DataFrame(top_new_kws)
                df_pages = pd.DataFrame(site_changes)

                # Combine all into one massive list for a single API call (faster)
                final_output = header + [df_sum.columns.tolist()] + df_sum.values.tolist() + [
                    [""], ["--- TOP NEW KEYWORDS (By Traffic Gain & Top 3 Vol) ---"],
                    [df_kws.columns.tolist()] + df_kws.values.tolist() if not df_kws.empty else [["No keywords found"]],
                    [""], ["--- SITE CHANGES (New Pages Discovered) ---"],
                    [df_pages.columns.tolist()] + df_pages.values.tolist() if not df_pages.empty else [["No new pages found"]]
                ]

                # Flattening the list-of-lists for gspread
                ws.update("A1", final_output)

                st.success(f"Successfully exported to {target_tab}!")
            except Exception as e:
                st.error(f"Spreadsheet Error: {e}")
