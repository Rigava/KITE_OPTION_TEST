import streamlit as st
from kiteconnect import KiteTicker
import pandas as pd
import json
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

from option_chain import build_option_chain, create_option_chain
from metrics import (
    get_atm_strike, atm_window, atm_straddle,
    calculate_pcr, get_max_pain
)
import time
import pyarrow as pa
# ---------------- STOP WS ---------------- #
def stop_ws():
    if "kws" in st.session_state:
        try:
            st.session_state.kws.close()
        except:
            pass
        del st.session_state.kws

    st.session_state.ws_started = False

# ---------------- CONFIG ---------------- #
st.set_page_config(layout="wide")
st.title("📊 NIFTY 50 Live Tracker")

INDEX = "NIFTY"
INDEX_TOKEN = 256265

# Auto refresh every 60 sec (NO while loop)
st_autorefresh(interval=60 * 1000, key="refresh_main")

# ---------------- GLOBAL STORE (THREAD SAFE) ---------------- #
ltp_data_global = {}
spot_price_global = None

# ---------------- SESSION STATE ---------------- #
if "history_df" not in st.session_state:
    st.session_state.history_df = pd.DataFrame()

if "ws_started" not in st.session_state:
    st.session_state.ws_started = False

# ---------------- INPUT ---------------- #
default_enctoken = "Jq9GV9Bv1JZzWecGGhTnCO5nyDeIa//jaE/DsQ9n3zKKokeiWMA+yRyOXYgofs2sXJZvb+nlMpivri51CqSIuSGntCfsRsoGQ/wsJ4xPwi7JCt5x6BXnzA=="
ENCTOKEN = st.sidebar.text_input("Enter enctoken", value=default_enctoken, type="password")
USER_ID = st.sidebar.text_input("User ID", value="ZM1064")

# with open("loginCredential.json") as f:
#     api_key = json.load(f)["api_key"]
api_key =st.secrets['API_KEY']

stop_button = st.sidebar.button("🛑 Stop")
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

# 🔴 LIMIT STRIKES (VERY IMPORTANT)
options_df = options_df[
    (options_df["strike"] >= 22000) &
    (options_df["strike"] <= 24000)
]

token_list = options_df.instrument_token.tolist()
token_list.append(INDEX_TOKEN)
st.write(f"Total subscribed tokens:{len(token_list)}")


ltp_data = {}
spot_price = None
def on_ticks(ws, ticks):
    global ltp_data, spot_price
    for tick in ticks:
        token = tick["instrument_token"]
        if token == INDEX_TOKEN:
            spot_price = tick["last_price"]
        else:
            ltp_data[token] = {
                "ltp": tick["last_price"],
                "oi": tick["oi"],
                "volume": tick.get("volume", 0),
            }

def on_connect(ws, response):
    ws.subscribe(token_list)
    ws.set_mode(ws.MODE_FULL, token_list)

kws = KiteTicker(api_key=api_key, access_token=ENCTOKEN + "&user_id=" + USER_ID)

kws.on_ticks = on_ticks
kws.on_connect = on_connect
kws.connect(threaded=True)
# ---------------- READ LIVE DATA ---------------- #
# ltp_data = ltp_data_global
# spot_price = spot_price_global

# Debug
st.write("📊 Tokens received:", len(ltp_data))
st.write("📈 Spot:", spot_price)
# Wait up to 5 seconds for first tick
timeout = 5
start_time = time.time()

while len(ltp_data) == 0 or spot_price is None:
    if time.time() - start_time > timeout:
        st.warning("Still waiting for live data...")
        st.stop()

    time.sleep(0.5)

if stop_button:
    stop_ws()
    st.warning("WebSocket stopped")
    st.stop()
# ---------------- BUILD CHAIN ---------------- #
chain = build_option_chain(options_df, ltp_data)

if chain is None:
    st.warning("Building option chain...")
    st.stop()

oc = create_option_chain(chain)

# ---------------- METRICS ---------------- #
atm = get_atm_strike(oc, spot_price)

if atm is not None:
    atm_chain = atm_window(oc, atm, n=10)
    pcr = calculate_pcr(oc)
    straddle = atm_straddle(oc, atm)
    max_pain = get_max_pain(oc)

    atm_chain = atm_chain.copy()
    atm_chain["timestamp"] = datetime.now()
    atm_chain["spot"] = spot_price
    atm_chain["max_pain"] = max_pain

    # Save history
    if len(st.session_state.history_df) == 0:
        st.session_state.history_df = atm_chain
    else:
        st.session_state.history_df = pd.concat(
            [st.session_state.history_df, atm_chain],
            ignore_index=True
        )
else:
    st.warning("ATM not found yet")
    st.stop()

# ---------------- UI ---------------- #
col1, col2, col3, col4 = st.columns(4)

col1.metric("Spot", round(spot_price, 2))
col2.metric("Max Pain", max_pain)
col3.metric("PCR", round(pcr, 2) if pcr else "-")
col4.metric("Straddle", round(straddle, 2))
st.write(atm_chain.schema)

# ---------------- TABLES ---------------- #
with st.expander("📌 Current ATM Option Chain"):
    st.dataframe(pa.Table.from_pandas(atm_chain))

with st.expander("📈 Historical Data"):
    st.dataframe(st.session_state.history_df)

# ---------------- CHARTS ---------------- #
st.subheader(f"📊 ATM Strike Trend: {atm}")

hist_df = st.session_state.history_df
strike_df = hist_df[hist_df["strike"] == atm].sort_values("timestamp")

if len(strike_df) > 0:
    st.write("Price Trend")
    st.line_chart(strike_df.set_index("timestamp")[["ltp_CE","ltp_PE"]])

    st.write("OI Trend")
    st.line_chart(strike_df.set_index("timestamp")[["oi_CE","oi_PE"]])

#------------------------- OI Market Profile----------------------------------
st.subheader("Distribution of Open Interest across strikes")
import plotly.graph_objects as go
fig = go.Figure()
fig.add_bar(y=atm_chain["strike"],x=-atm_chain["oi_CE"],name="Call OI",orientation="h")
fig.add_bar(y=atm_chain["strike"],x=atm_chain["oi_PE"],name="Put OI",orientation="h")
# Center axis
fig.add_vline(x=0, line_width=2)
# Spot price line
fig.add_hline(y=spot_price,line_dash="dash",line_color="yellow",annotation_text="Spot Price")
# Max pain line
fig.add_hline(y=max_pain,line_dash="dot",line_color="white",annotation_text="Max Pain")

fig.update_layout(title="Options Open Interest Ladder",xaxis_title="Open Interest",yaxis_title="Strike Price",)

st.plotly_chart(fig, use_container_width=True)
