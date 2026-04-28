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

# --- 2. AUTOMATIC QUARTERLY DATES ---
today = datetime.today().date()
current_period_end = today - timedelta(days=2)
current_period_start = current_period_end - timedelta(days=90)
last_period_end = current_period_start - timedelta(days=1)
last_period_start = last_period_end - timedelta(days=90)

# --- 3. UI SETUP ---
st.set_page_config(page_title="Looker-Ready Ahrefs Auditor", layout="wide")
st.title("🛡️ Looker Studio SEO Data Exporter")

st.info(f"**Period:** {current_period_start} to {current_period_end} vs {last_period_start} to {last_period_end}")

api_key = st.sidebar.text_input("Ahrefs API Key", type="password")
client_name = st.text_input("Client Name (used for Tab Prefix)", "ClientName")
client_site = st.text_input("Client Domain")
competitors = st.text_area("Competitor Domains (one per line)")

# --- 4. EXECUTION ---
if st.button("Generate & Sync to Looker Sheets"):
    if not api_key or not client_site or not client_name:
        st.error("Missing mandatory inputs.")
    else:
        with st.spinner("Processing data for Looker Studio..."):
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
                    "Date_Synced": datetime.now().strftime("%Y-%m-%d"),
                    "Report_Period": f"{current_period_start} to {current_period_end}",
                    "Domain": domain,
                    "Entity": "Client" if domain == client_site.strip() else "Competitor",
                    "RD_Current": curr_met.get('refdomains', 0),
                    "RD_Last": last_met.get('refdomains', 0),
                    "RD_Change": curr_met.get('refdomains', 0) - last_met.get('refdomains', 0),
                    "KW_Current": curr_met.get('org_keywords', 0),
                    "KW_Last": last_met.get('org_keywords', 0),
                    "KW_Change": curr_met.get('org_keywords', 0) - last_met.get('org_keywords', 0)
                })

                # B. KEYWORDS
                kw_gain_params = {"target": domain, "limit": 10, "order_by": "traffic_change:desc", "date": current_period_end.isoformat(), "date_compared": last_period_end.isoformat()}
                gainer_res = fetch_ahrefs("site-explorer/organic-keywords", kw_gain_params, api_key)

                top3_params = {"target": domain, "limit": 10, "order_by": "volume:desc", "where": f'[["position", "lte", 3], ["first_seen", "gt", "{last_period_end.isoformat()}"]]'}
                top3_res = fetch_ahrefs("site-explorer/organic-keywords", top3_params, api_key)

                for k in (gainer_res.get('keywords', []) if gainer_res else []):
                    top_new_kws.append({"Domain": domain, "Entity": "Client" if domain == client_site.strip() else "Competitor", "Type": "Traffic Gainer", "Keyword": k['keyword'], "Volume": k['volume'], "Position": k['position'], "Traffic_Change": k.get('traffic_change', 0)})

                for k in (top3_res.get('keywords', []) if top3_res else []):
                    top_new_kws.append({"Domain": domain, "Entity": "Client" if domain == client_site.strip() else "Competitor", "Type": "New Top 3", "Keyword": k['keyword'], "Volume": k['volume'], "Position": k['position'], "URL": k['url']})

                # C. SITE CHANGES
                page_params = {"target": domain, "limit": 20, "where": f'[["first_seen", "gt", "{last_period_end.isoformat()}"]]'}
                pages_res = fetch_ahrefs("site-explorer/pages", page_params, api_key)
                for p in (pages_res.get('pages', []) if pages_res else []):
                    site_changes.append({"Domain": domain, "New_Page_URL": p['url'], "First_Seen": p['first_seen']})

            # --- 5. LOOKER-STUDIO FRIENDLY EXPORT ---
            try:
                gc = get_gspread_client()
                sh = gc.open_by_key(MASTER_SHEET_ID)

                def sync_to_tab(tab_name, dataframe):
                    try:
                        ws = sh.worksheet(tab_name)
                    except gspread.exceptions.WorksheetNotFound:
                        ws = sh.add_worksheet(title=tab_name, rows="1000", cols="20")

                    ws.clear()
                    # Looker needs headers in the first row and data immediately following
                    ws.update([dataframe.columns.tolist()] + dataframe.values.tolist())

                # Syncing 3 distinct tabs for 3 distinct Looker data sources
                sync_to_tab(f"{client_name}_Summary", pd.DataFrame(summary_list))
                sync_to_tab(f"{client_name}_Keywords", pd.DataFrame(top_new_kws))
                sync_to_tab(f"{client_name}_Pages", pd.DataFrame(site_changes))

                st.success(f"✅ Data Synced! In Looker Studio, connect to the tabs: {client_name}_Summary, {client_name}_Keywords, and {client_name}_Pages.")
            except Exception as e:
                st.error(f"Spreadsheet Error: {e}")
