import streamlit as st
import pandas as pd
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- SETTINGS & AUTH ---
# Replace this with your actual Shared Google Sheet ID (from the URL)
MASTER_SHEET_ID = "YOUR_SHARED_GOOGLE_SHEET_ID_HERE"

def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
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
    resp = requests.get(url, params=params, headers=headers)
    return resp.json().get('metrics', {}) if resp.status_code == 200 else {}

# --- UI ---
st.title("🛡️ Ahrefs Competitor Tool")
st.info("Results are exported to the shared team Google Sheet.")

api_key = st.sidebar.text_input("Ahrefs API Key", type="password")
client_site = st.text_input("Client Domain", "example.com")
competitors = st.text_area("Competitors (Max 5, one per line)", "comp1.com\ncomp2.com")

if st.button("Run & Export"):
    if not api_key:
        st.error("Please enter an Ahrefs API Key.")
    else:
        with st.spinner("Analyzing data..."):
            dates = get_quarters()
            comp_list = [c.strip() for c in competitors.split("\n") if c.strip()][:5]
            all_domains = [client_site] + comp_list
            
            results = []
            for domain in all_domains:
                m_now = fetch_ahrefs_metrics(domain, dates['recent'], api_key)
                m_prev = fetch_ahrefs_metrics(domain, dates['preceding'], api_key)
                
                results.append({
                    "Domain": domain,
                    "Ref. Domains": m_now.get('refdomains', 0),
                    "RD Change": m_now.get('refdomains', 0) - m_prev.get('refdomains', 0),
                    "Backlinks": m_now.get('backlinks', 0),
                    "Keywords": m_now.get('org_keywords', 0),
                    "Date Pulled": datetime.now().strftime("%Y-%m-%d")
                })
            
            df = pd.DataFrame(results)
            st.table(df)

            # --- EXPORT TO SHARED SHEET ---
            gc = get_gspread_client()
            sh = gc.open_by_key(MASTER_SHEET_ID)
            tab_name = f"{client_site}_{datetime.now().strftime('%M%S')}"
            
            worksheet = sh.add_worksheet(title=tab_name, rows="100", cols="20")
            worksheet.update([df.columns.values.tolist()] + df.values.tolist())
            st.success(f"✅ Exported to tab: {tab_name}")
