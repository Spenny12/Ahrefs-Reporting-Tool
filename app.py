import streamlit as st
import pandas as pd
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- 1. CONFIGURATION & AUTH ---
# The ID from the URL you provided
MASTER_SHEET_ID = "1dzt0pUF1c3ffLh1_zxiCiwiYKO4-3jFkDx1ErR49m1Q"

def get_gspread_client():
    """Authenticates using Streamlit Secrets."""
    # We include both Sheets and Drive scopes to ensure the file can be 'found'
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

def get_quarters():
    """Calculates the dates for the most recent completed quarter."""
    today = datetime.today()
    # Logic to find the start of the current quarter, then go back
    curr_q_start = datetime(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    prev_q_end = curr_q_start - timedelta(days=1)
    prev_q_start = datetime(prev_q_end.year, 3 * ((prev_q_end.month - 1) // 3) + 1, 1)
    return {
        "recent": prev_q_end.strftime("%Y-%m-%d"),
        "preceding": prev_q_start.strftime("%Y-%m-%d")
    }

def fetch_ahrefs_metrics(target, date, api_key):
    """Fetches high-level SEO metrics from Ahrefs V3."""
    url = "https://api.ahrefs.com/v3/site-explorer/metrics"
    params = {"target": target, "date": date}
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.get(url, params=params, headers=headers)
        if resp.status_code == 200:
            return resp.json().get('metrics', {})
        else:
            st.error(f"Ahrefs API Error ({resp.status_code}): {resp.text}")
            return {}
    except Exception as e:
        st.error(f"Request failed: {e}")
        return {}

# --- 2. STREAMLIT UI ---
st.set_page_config(page_title="Ahrefs Reporting Tool", page_icon="🛡️")

st.title("🛡️ Ahrefs Competitor Reporting")
st.markdown("Analyses client vs. competitors and exports results to the Shared Team Sheet.")

# Sidebar for API Key
api_key = st.sidebar.text_input("Ahrefs API V3 Key", type="password")
st.sidebar.markdown("---")
st.sidebar.write("🔒 **Robot Email:**")
st.sidebar.code("ahrefs-report-service@candour-clients-gmaps.iam.gserviceaccount.com")
st.sidebar.caption("Ensure this email is an 'Editor' on the Google Sheet.")

# Main Inputs
col1, col2 = st.columns(2)
with col1:
    client_site = st.text_input("Client Domain", "example.com")
with col2:
    competitors = st.text_area("Competitors (Max 5, one per line)", "comp1.com\ncomp2.com")

# --- 3. EXECUTION LOGIC ---
if st.button("Run Analysis & Export"):
    if not api_key:
        st.warning("Please provide an Ahrefs API Key in the sidebar.")
    elif not client_site:
        st.warning("Please provide a client domain.")
    else:
        with st.spinner("Processing SEO Data..."):
            # A. Setup Dates and Domains
            dates = get_quarters()
            comp_list = [c.strip() for c in competitors.split("\n") if c.strip()][:5]
            all_domains = [client_site] + comp_list

            # B. Fetch Data from Ahrefs
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
                        "Backlinks Change": m_now.get('backlinks', 0) - m_prev.get('backlinks', 0),
                        "Organic Keywords": m_now.get('org_keywords', 0),
                        "Analysis Date": datetime.now().strftime("%Y-%m-%d %H:%M")
                    })

            if not results:
                st.error("No data could be retrieved from Ahrefs. Check your API units or domain spelling.")
            else:
                df = pd.DataFrame(results)
                st.subheader("Data Preview")
                st.dataframe(df, use_container_width=True)

                # C. Export to Google Sheets
                try:
                    gc = get_gspread_client()

                    # Connect to sheet
                    sh = gc.open_by_key(MASTER_SHEET_ID.strip())

                    # Create a unique tab name
                    timestamp = datetime.now().strftime("%b%d_%H%M")
                    tab_name = f"{client_site[:10]}_{timestamp}"

                    # Add worksheet
                    worksheet = sh.add_worksheet(title=tab_name, rows="100", cols="20")

                    # Format data for gspread (Header + Rows)
                    data_to_upload = [df.columns.values.tolist()] + df.values.tolist()
                    worksheet.update(data_to_upload)

                    st.success(f"🚀 Success! Data exported to tab: **{tab_name}**")
                    st.balloons()

                except gspread.exceptions.SpreadsheetNotFound:
                    st.error("❌ Google Sheet Not Found. Verify the ID and that you've shared the sheet with the Robot Email.")
                except Exception as e:
                    st.error(f"❌ Google Sheets Error: {e}")
