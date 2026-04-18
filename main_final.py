from datetime import datetime
from typing import Dict, List, Optional

import requests
from datetime import timedelta, datetime
import pandas as pd
import streamlit as st

import plotly.graph_objects as go

from option_chain import create_option_chain
from metrics import (
    get_atm_strike, atm_window, atm_straddle,
    calculate_pcr, get_max_pain
)

# ---------------- CONFIG ---------------- #
st.set_page_config(layout="wide")
st.title("📊 Nifty Options Live Tracker")

# ------------Try to import kiteconnect but continue gracefully if missing
try:
    from kiteconnect import KiteConnect
    KITE_AVAILABLE = True
except Exception:
    KITE_AVAILABLE = False

def try_create_kite_client(api_key: str, access_token: str) -> Optional[KiteConnect]:
    if not KITE_AVAILABLE:
        return None
    try:
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        return kite
    except Exception:
        return None

INDEX = "NIFTY"
INDEX_TOKEN = 256265
# -----------------------------------AUTOREFRESH-----------------------------#
# st_autorefresh(interval=60 * 1000, key="refresh_main") 
def get_spot_with_kite(kite: KiteConnect, index_token: int) -> Optional[float]:
    # Best-effort: try to fetch LTP for the index token. Different environments/methods exist; try common ones.
    try:
        # kite.ltp accepts a list of instrument tokens (or strings) and returns mapping
        res = kite.ltp([str(index_token)])
        # res example: {"256265": {"last_price": 18000.0, ...}}
        # or {"NSE:xxx": {...}}
        for v in res.values():
            if isinstance(v, dict) and "last_price" in v:
                return float(v["last_price"])
    except Exception:
        pass
    try:
        # Try treating as integer token directly
        res = kite.ltp([index_token])
        for v in res.values():
            if isinstance(v, dict) and "last_price" in v:
                return float(v["last_price"])
    except Exception:
        pass
    # As a last try, call quote with NSE prefix if tradingsymbol known; the caller can pass symbol instead.
    return None
def get_historical_data(instrument_token, interval,api_key,access_token,from_date, to_date):
    if not instrument_token:
        raise Exception(f"Instrument token not found for {instrument_token}")
    url = f"https://api.kite.trade/instruments/historical/{instrument_token}/{interval}"
    # Headers
    headers = {"X-Kite-Version": "3","Authorization": f"token {api_key}:{access_token}"}
    params = {"from": from_date.strftime("%Y-%m-%d"),"to": to_date.strftime("%Y-%m-%d"),"oi":"1"}
    r = requests.get(url, headers=headers, params=params)

    if r.status_code != 200:
        raise Exception(f"Historical API failed: {r.text}")

    candles = r.json()["data"]["candles"]

    df = pd.DataFrame(
        candles,
        columns=["Datetime","Open", "High", "Low", "Close", "Volume","OI"]
    )

    df["Datetime"] = pd.to_datetime(df["Datetime"])
    return df
# ---------------- SESSION STATE INIT ---------------- #

# session state defaults
if "index_name" not in st.session_state:
    st.session_state.index_name = "NIFTY"
if "strike_range" not in st.session_state:
    st.session_state.strike_range = 200

# ---------------- INPUT for KITE API---------------- #
api_key = st.secrets['API_KEY']
access_token = st.secrets['ACCESS_TOKEN']


# ---------------- Initialise Client ---------------- #
kite_client = None
if api_key and access_token and KITE_AVAILABLE:
    kite_client = try_create_kite_client(api_key, access_token)
    if kite_client:
        st.sidebar.success("Kite client initialized")
    else:
        st.sidebar.warning("Kite client could not be initialized with the provided token")
elif not KITE_AVAILABLE:
    st.sidebar.warning("kiteconnect package not available — live LTP/OI will be disabled")


index_token = 256265

spot = None
if kite_client and index_token:
    spot = get_spot_with_kite(kite_client, index_token)

spot_input = None
if spot is None:
    spot_input = st.number_input("Spot price (could not fetch automatically)", value=0.0, step=1.0)
    if spot_input > 0:
        spot = float(spot_input)
else:
    st.write(f"Detected spot price: {spot}")

if spot is None or spot == 0:
    st.warning("Spot price is required to filter strikes. Enter manually or fix access token/client initialization.")


# ---------------- LOAD INSTRUMENTS ---------------- #
@st.cache_data
def load_instruments():
    return pd.read_csv("https://api.kite.trade/instruments")

def get_weekly_options(df, index):
    df = df[df["name"] == index]
    expiry = min(df["expiry"].unique())
    df = df[df["expiry"] == expiry]
    return df[["instrument_token","strike","instrument_type"]], expiry

st.sidebar.text_input("Index name", value=st.session_state.index_name, key="index_name")
st.sidebar.number_input("Strike range (+/-)", min_value=50, max_value=5000, step=50, value=st.session_state.strike_range, key="strike_range")


# Show token list that includes index token--# We can show the instrument tokens used in the filtered options
instruments_df = load_instruments()
options_df, expiry = get_weekly_options(instruments_df, st.session_state.index_name)
low = max(0, spot - st.session_state.strike_range)
high = spot + st.session_state.strike_range
options_filtered = options_df[(options_df["strike"] >= low) & (options_df["strike"] <= high)].copy()
token_list = options_filtered["instrument_token"].astype(str).tolist()
if index_token:
    token_list.append(str(index_token))
with st.expander("Token list (filtered):"):
    st.write(f"Total subscribed tokens: {len(token_list)}")
    st.write(token_list)

# ---------------- FETCH INSTRUMENT DATA---------------- #
end = datetime.now()
start = end - timedelta(days=1)
historical_data = {}
latest_data = []
for _, row in options_filtered.iterrows():
    df = get_historical_data(row["instrument_token"],"5minute",api_key,access_token,start,end)
# to get the last row of the historical data and extract details
    latest = df.iloc[-1]
    latest_data.append({
            "strike": row["strike"],
            "instrument_type": row["instrument_type"],
            "ltp": latest["Close"],
            "oi": latest["OI"],
            "volume": latest["Volume"]})
    # Store the full historical data for the token in a dictionary for later analysis
    df['strike'] = row["strike"]
    df['type'] = row["instrument_type"]
    historical_data[row["instrument_token"]] = df


# ---------------- BUILD Option CHAIN ---------------- #
latest_chain_data = pd.DataFrame(latest_data)

option_chain = create_option_chain(latest_chain_data)
with st.expander("Latest Option Chain"):
    st.dataframe(option_chain)
with st.expander("Historical Data frame"):
    st.write(historical_data)
# pe_oi = option_chain["oi_PE"].sum()
# ce_oi = option_chain["oi_CE"].sum()
# pcr = pe_oi / ce_oi if ce_oi != 0 else 0
# # st.write("PCR:", round(pcr,2))

# ---------------- METRICS ---------------- #
atm = get_atm_strike(option_chain, spot_price)
if atm is None:
    st.warning("ATM not found yet")

atm_chain = atm_window(option_chain, atm, n=10)
pcr = calculate_pcr(option_chain)
straddle = atm_straddle(option_chain, atm)
max_pain = get_max_pain(option_chain)

atm_chain = atm_chain.copy()
atm_chain["timestamp"] = datetime.now()
atm_chain["spot"] = spot_price
atm_chain["max_pain"] = max_pain
# st.write(atm_chain)


# ---------------- UI ---------------- #
col1, col2, col3, col4 = st.columns(4)

col1.metric("Spot", round(spot_price, 2))
col2.metric("Max Pain", max_pain)
col3.metric("PCR", round(pcr, 2) if pcr else "-")
col4.metric("Straddle", round(straddle, 2))

# tbl = pa.Table.from_pandas(atm_chain)

# ---------------- TABLES ---------------- #
with st.expander("📌 Current ATM Option Chain"):
    st.dataframe(atm_chain)

with st.expander("📈 Historical Data"):
    st.write(historical_data)

# ---------------- CHARTS ---------------- #
st.subheader(f"📊 Selected Strike Trend - Historical")

# hist_df = st.session_state.history_df
# strike_df = hist_df[hist_df["strike"] == atm].sort_values("timestamp")

# if len(strike_df) > 0:
#     st.write("Price Trend")
#     st.line_chart(strike_df.set_index("timestamp")[["ltp_CE","ltp_PE"]])

#     st.write("OI Trend")
#     st.line_chart(strike_df.set_index("timestamp")[["oi_CE","oi_PE"]])

# ---------------- OI PROFILE ---------------- #
st.subheader("Distribution of Open Interest across strikes")

fig = go.Figure()

fig.add_bar(y=atm_chain["strike"], x=-atm_chain["oi_CE"], name="Call OI", orientation="h")
fig.add_bar(y=atm_chain["strike"], x=atm_chain["oi_PE"], name="Put OI", orientation="h")

fig.add_vline(x=0, line_width=2)
fig.add_hline(y=spot_price, line_dash="dash", line_color="yellow", annotation_text="Spot Price")
fig.add_hline(y=max_pain, line_dash="dot", line_color="white", annotation_text="Max Pain")

fig.update_layout(
    title="Options Open Interest Ladder",
    xaxis_title="Open Interest",
    yaxis_title="Strike Price",
)

st.plotly_chart(fig, use_container_width=True)
