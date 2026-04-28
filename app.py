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
# Calculates a rolling 90-day window and a 90-day comparison window
today = datetime.today().date()
current_period_end = today - timedelta(days=2)  # Buffer for data freshness
current_period_start = current_period_end - timedelta(days=90)

last_period_end = current_period_start - timedelta(days=1)
last_period_start = last_period_end - timedelta(days=90)

# --- 3. UI SETUP ---
st.set_page_config(page_title="Ahrefs Quarterly Auditor", layout="wide")
st.title("🛡️ Automatic Quarterly Competitor Audit")

st.info(f"**Analysis Window:** {current_period_start} to {current_period_end} (90 Days)  \n"
        f"**Comparison Window:** {last_period_start} to {last_period_end} (90 Days)")

api_key = st.sidebar.text_input("Ahrefs API Key", type="password")

# Google Sheets Tab Sync
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
if st.button("Generate Quarterly Audit"):
    if not api_key or not target_tab or not client_site:
        st.error("Missing Ahrefs API Key, Client Domain, or Tab Name.")
    else:
        with st.spinner("Deep-diving into Ahrefs data..."):
            domains = [client_site.strip()] + [c.strip() for c in competitors.split("\n") if c.strip()]

            summary_list = []
            top_new_kws = []
            site_changes = []

            for domain in domains:
                # A. SUMMARY STATS (Metrics)
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

                # B. KEYWORD PERFORMANCE
                # Top 10 by Traffic Increase
                kw_gain_params = {
                    "target": domain, "limit": 10, "order_by": "traffic_change:desc",
                    "date": current_period_end.isoformat(), "date_compared": last_period_end.isoformat()
                }
                gainer_res = fetch_ahrefs("site-explorer/organic-keywords", kw_gain_params, api_key)

                # Top 10 Volume (New in Positions 1-3)
                top3_params = {
                    "target": domain, "limit": 10, "order_by": "volume:desc",
                    "where": f'[["position", "lte", 3], ["first_seen", "gt", "{last_period_end.isoformat()}"]]'
                }
                top3_res = fetch_ahrefs("site-explorer/organic-keywords", top3_params, api_key)

                for k in (gainer_res.get('keywords', []) if gainer_res else []):
                    top_new_kws.append({
                        "Domain": domain, "Type": "Traffic Gainer", "Keyword": k['keyword'],
                        "Volume": k['volume'], "Position": k['position'], "Traffic Change": k.get('traffic_change', 0)
                    })

                for k in (top3_res.get('keywords', []) if top3_res else []):
                    top_new_kws.append({
                        "Domain": domain, "Type": "New Top 3 Entry", "Keyword": k['keyword'],
                        "Volume": k['volume'], "Position": k['position'], "URL": k['url']
                    })

                # C. SITE CHANGES (New Pages)
                page_params = {"target": domain, "limit": 20, "where": f'[["first_seen", "gt", "{last_period_end.isoformat()}"]]'}
                pages_res = fetch_ahrefs("site-explorer/pages", page_params, api_key)
                for p in (pages_res.get('pages', []) if pages_res else []):
                    site_changes.append({"Domain": domain, "New Page URL": p['url'], "First Seen": p['first_seen']})

            # --- 5. ROBUST EXPORT TO SHEETS ---
            try:
                gc = get_gspread_client()
                sh = gc.open_by_key(MASTER_SHEET_ID)

                if tab_mode == "New Client":
                    ws = sh.add_worksheet(title=target_tab, rows="1000", cols="20")
                else:
                    ws = sh.worksheet(target_tab)

                ws.clear()

                df_sum = pd.DataFrame(summary_list)
                df_kws = pd.DataFrame(top_new_kws)
                df_pages = pd.DataFrame(site_changes)

                # Find the widest table to keep the sheet consistent
                widths = [len(df_sum.columns)]
                if not df_kws.empty: widths.append(len(df_kws.columns))
                if not df_pages.empty: widths.append(len(df_pages.columns))
                max_width = max(widths)

                def pad_row(row_list, width):
                    """Pads a row with empty strings so all rows have the same column count."""
                    return [str(x) if x is not None else "" for x in row_list] + [""] * (width - len(row_list))

                # Build the final output list
                final_output = [
                    pad_row(["QUARTERLY PERFORMANCE REPORT"], max_width),
                    pad_row(["CURRENT PERIOD:", f"{current_period_start} to {current_period_end}"], max_width),
                    pad_row(["COMPARISON PERIOD:", f"{last_period_start} to {last_period_end}"], max_width),
                    pad_row([""], max_width),
                    pad_row(["--- SUMMARY PERFORMANCE ---"], max_width),
                    pad_row(df_sum.columns.tolist(), max_width)
                ]

                for row in df_sum.values.tolist():
                    final_output.append(pad_row(row, max_width))

                # Add Keyword Section
                final_output.append(pad_row([""], max_width))
                final_output.append(pad_row(["--- TOP NEW KEYWORDS (By Traffic Gain & Top 3 Volume) ---"], max_width))
                if not df_kws.empty:
                    final_output.append(pad_row(df_kws.columns.tolist(), max_width))
                    for row in df_kws.values.tolist():
                        final_output.append(pad_row(row, max_width))
                else:
                    final_output.append(pad_row(["No new keywords found for this period"], max_width))

                # Add Site Changes Section
                final_output.append(pad_row([""], max_width))
                final_output.append(pad_row(["--- SITE CHANGES (New Pages Discovered) ---"], max_width))
                if not df_pages.empty:
                    final_output.append(pad_row(df_pages.columns.tolist(), max_width))
                    for row in df_pages.values.tolist():
                        final_output.append(pad_row(row, max_width))
                else:
                    final_output.append(pad_row(["No new pages discovered for this period"], max_width))

                # Batch Update Google Sheets
                ws.update("A1", final_output)

                st.success(f"Successfully exported to: {target_tab}")
            except Exception as e:
                st.error(f"Spreadsheet Error: {e}")
