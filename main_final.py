import streamlit as st
from kiteconnect import KiteTicker
import pandas as pd
from datetime import datetime
import time
import pyarrow as pa
import plotly.graph_objects as go

from option_chain import build_option_chain, create_option_chain
from metrics import (
    get_atm_strike, atm_window, atm_straddle,
    calculate_pcr, get_max_pain
)

# ---------------- CONFIG ---------------- #
st.set_page_config(layout="wide")
st.title("📊 NIFTY 50 Live Tracker")

INDEX = "NIFTY"
INDEX_TOKEN = 256265

api_key = st.secrets['API_KEY']

ENCTOKEN = st.sidebar.text_input("Enter enctoken", type="password")
USER_ID = st.sidebar.text_input("User ID")

# ---------------- SESSION STATE INIT ---------------- #
if "kws" not in st.session_state:
    st.session_state.kws = None

if "ws_started" not in st.session_state:
    st.session_state.ws_started = False

if "ltp_data" not in st.session_state:
    st.session_state.ltp_data = {}

if "spot_price" not in st.session_state:
    st.session_state.spot_price = None

if "history_df" not in st.session_state:
    st.session_state.history_df = pd.DataFrame()

# ---------------- LOAD INSTRUMENTS ---------------- #
@st.cache_data
def load_instruments():
    return pd.read_csv("https://api.kite.trade/instruments")

def get_weekly_options(df, index):
    df = df[df["name"] == index]
    expiry = min(df["expiry"].unique())
    df = df[df["expiry"] == expiry]
    return df[["instrument_token","strike","instrument_type"]], expiry

df = load_instruments()
options_df, expiry = get_weekly_options(df, INDEX)

options_df = options_df[
    (options_df["strike"] >= 22000) &
    (options_df["strike"] <= 24000)
]

token_list = options_df.instrument_token.tolist()
token_list.append(INDEX_TOKEN)

st.write(f"Subscribed tokens: {len(token_list)}")

# ---------------- WS CALLBACKS ---------------- #
def on_ticks(ws, ticks):
    for tick in ticks:
        token = tick["instrument_token"]

        if token == INDEX_TOKEN:
            st.session_state.spot_price = tick["last_price"]
        else:
            st.session_state.ltp_data[token] = {
                "ltp": tick["last_price"],
                "oi": tick["oi"],
                "volume": tick.get("volume", 0),
            }

def on_connect(ws, response):
    ws.subscribe(token_list)
    ws.set_mode(ws.MODE_FULL, token_list)

def on_close(ws, code, reason):
    st.session_state.ws_started = False
    print("WS Closed:", code, reason)

def on_error(ws, error):
    print("WS Error:", error)

# ---------------- START WS ONLY ONCE ---------------- #
if (
    not st.session_state.ws_started
    and ENCTOKEN
    and USER_ID
):
    kws = KiteTicker(api_key=api_key,
                     access_token=ENCTOKEN + "&user_id=" + USER_ID)

    kws.on_ticks = on_ticks
    kws.on_connect = on_connect
    kws.on_close = on_close
    kws.on_error = on_error

    kws.connect(threaded=True)

    st.session_state.kws = kws
    st.session_state.ws_started = True

# ---------------- SAFE DATA CHECK (NO WHILE LOOP) ---------------- #
if len(st.session_state.ltp_data) == 0 or st.session_state.spot_price is None:
    st.warning("Waiting for live data...")
    st.stop()

ltp_data = st.session_state.ltp_data
spot_price = st.session_state.spot_price

# ---------------- BUILD OPTION CHAIN ---------------- #
chain = build_option_chain(options_df, ltp_data)

if chain is None:
    st.warning("Building option chain...")
    st.stop()

oc = create_option_chain(chain)

# ---------------- METRICS ---------------- #
atm = get_atm_strike(oc, spot_price)

if atm is None:
    st.warning("ATM not found yet")
    st.stop()

atm_chain = atm_window(oc, atm, n=10)
pcr = calculate_pcr(oc)
straddle = atm_straddle(oc, atm)
max_pain = get_max_pain(oc)

atm_chain = atm_chain.copy()
atm_chain["timestamp"] = datetime.now()
atm_chain["spot"] = spot_price
atm_chain["max_pain"] = max_pain

# ---------------- SAVE HISTORY ---------------- #
if len(st.session_state.history_df) == 0:
    st.session_state.history_df = atm_chain
else:
    st.session_state.history_df = pd.concat(
        [st.session_state.history_df, atm_chain],
        ignore_index=True
    )

# ---------------- UI METRICS ---------------- #
col1, col2, col3, col4 = st.columns(4)

col1.metric("Spot", round(spot_price, 2))
col2.metric("Max Pain", max_pain)
col3.metric("PCR", round(pcr, 2) if pcr else "-")
col4.metric("Straddle", round(straddle, 2))

# ---------------- TABLES ---------------- #
tbl = pa.Table.from_pandas(atm_chain)

with st.expander("📌 Current ATM Option Chain"):
    st.dataframe(tbl)

with st.expander("📈 Historical Data"):
    st.write(st.session_state.history_df)

# ---------------- CHARTS ---------------- #
st.subheader(f"📊 ATM Strike Trend: {atm}")

hist_df = st.session_state.history_df
strike_df = hist_df[hist_df["strike"] == atm].sort_values("timestamp")

if len(strike_df) > 0:
    st.write("Price Trend")
    st.line_chart(strike_df.set_index("timestamp")[["ltp_CE","ltp_PE"]])

    st.write("OI Trend")
    st.line_chart(strike_df.set_index("timestamp")[["oi_CE","oi_PE"]])

# ---------------- OI PROFILE ---------------- #
st.subheader("Distribution of Open Interest across strikes")

fig = go.Figure()

fig.add_bar(
    y=atm_chain["strike"],
    x=-atm_chain["oi_CE"],
    name="Call OI",
    orientation="h"
)

fig.add_bar(
    y=atm_chain["strike"],
    x=atm_chain["oi_PE"],
    name="Put OI",
    orientation="h"
)

fig.add_vline(x=0, line_width=2)

fig.add_hline(
    y=spot_price,
    line_dash="dash",
    annotation_text="Spot Price"
)

fig.add_hline(
    y=max_pain,
    line_dash="dot",
    annotation_text="Max Pain"
)

fig.update_layout(
    title="Options Open Interest Ladder",
    xaxis_title="Open Interest",
    yaxis_title="Strike Price",
)

st.plotly_chart(fig, use_container_width=True)
