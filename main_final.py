from datetime import datetime
from typing import Dict, List, Optional
from datetime import datetime
import requests
from datetime import timedelta
import pandas as pd
import streamlit as st

import plotly.graph_objects as go

from option_chain import create_option_chain
from metrics import (get_atm_strike, atm_window, atm_straddle, calculate_pcr, get_max_pain)

from st_utils import get_historical_data, get_instruments,plot_ohlc

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
index_token = 256265
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
# if "strike_range" not in st.session_state:
#     st.session_state.strike_range = 200
def highlight_levels(row):
    if row["strike"] == max_pain:
        return ["background-color: purple"] * len(row)
    elif row["strike"] == round(spot/50)*50:
        return ["background-color: green"] * len(row)
    return [""] * len(row)
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
def enforce_kite_limits(interval, from_date, to_date):
    max_days = {
        "minute": 60,
        "3minute": 60,
        "5minute": 60,
        "15minute": 60,
        "hour": 180,
        "day": 5000
    }
    allowed_days = max_days.get(interval, 60)
    actual_days = (to_date - from_date).days
    if actual_days > allowed_days:
        from_date = to_date - timedelta(days=allowed_days)
    return from_date, to_date
# --- SIDEBAR CONFIG ---
st.sidebar.text_input("Index name", value=st.session_state.index_name, key="index_name")
strike_range = st.sidebar.number_input("Strike range (+/-)", min_value=50, max_value=5000, step=50, value=200, key="strike_range")
from_date = st.sidebar.date_input("From Date", datetime.today() - timedelta(days=10))
to_date = st.sidebar.date_input("To Date" , datetime.today())
interval = st.sidebar.selectbox("Interval", ["day", "5minute", "15minute", "hour"])

# Show token list that includes index token--# We can show the instrument tokens used in the filtered options
instruments_df = load_instruments()
options_df, expiry = get_weekly_options(instruments_df, st.session_state.index_name)
low = max(0, spot - strike_range)
high = spot + strike_range
options_filtered = options_df[(options_df["strike"] >= low) & (options_df["strike"] <= high)].copy()
token_list_full = options_df["instrument_token"].astype(str).tolist()
token_list = options_filtered["instrument_token"].astype(str).tolist()
if index_token:
    token_list.append(str(index_token))
with st.expander("Token list (filtered):"):
    st.write(f"Total tokens: {len(token_list_full)}")
    st.write(f"Total subscribed tokens: {len(token_list)}")
    st.write(options_filtered)

strikes  = options_filtered["strike"].unique()
selected_strikes = st.sidebar.selectbox("Select strikes for historical analysis", strikes)

# ---------------- FETCH INSTRUMENT DATA---------------- #
if st.button("Fetch Data"):
    from_date, to_date = enforce_kite_limits(interval, from_date, to_date)
    # end = datetime.now()
    # start = end - timedelta(days=3)
    historical_dd = []
    latest_data = []
    for _, row in options_filtered.iterrows():
        df = get_historical_data(row["instrument_token"],interval,api_key,access_token,from_date,to_date)
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
        df['token'] = row["instrument_token"]   
        historical_dd.append(df)
        
    # ---------------- METRICS ---------------- #
    latest_chain_data = pd.DataFrame(latest_data)
    option_chain = create_option_chain(latest_chain_data)
    atm = get_atm_strike(option_chain, spot)
    if atm is None:
        st.warning("ATM not found yet")
    
    atm_chain = option_chain.copy() 
    # atm_window(option_chain, atm, n=20)
    pcr = calculate_pcr(option_chain)
    straddle = atm_straddle(option_chain, atm)
    max_pain = get_max_pain(option_chain)
    
    atm_chain = atm_chain.copy()
    atm_chain["timestamp"] = datetime.now()
    atm_chain["spot"] = spot
    atm_chain["max_pain"] = max_pain
    
    # ---------------- Pvot the historical data by CE and PE side-by-side-----merge for each (Datetime, strike) pair ---------------- #
    hist_df = pd.concat(historical_dd,names=['token'])
    # Step 1: Set index and pivot
    merged_df = hist_df.pivot_table(index=['Datetime', 'strike'], columns='type', values=['Close', 'Volume', 'OI'])
    merged_df.columns = [f"{col[0]}_{col[1]}" for col in merged_df.columns]
    merged_df = merged_df.reset_index()
    merged_df['spot']=spot
    merged_df['max_pain'] = max_pain

    with st.expander("📈 Historical Data - download chain for analysis"):
        st.dataframe(merged_df)
    

    
    
    
    # ---------------- UI ---------------- #
    col1, col2, col3, col4, col5 = st.columns(5)
    
    col1.metric("Spot", round(spot, 0))
    col2.metric("Max Pain", max_pain)
    col3.metric("PCR", round(pcr, 2) if pcr else "-")
    col4.metric("Straddle", round(straddle, 0))
    col5.metric("ATM", round(atm, 0))
    
    
    # ---------------- TABLES ---------------- #
    with st.expander("📌 Current ATM Option Chain"):
       st.dataframe(atm_chain.style.apply(highlight_levels, axis=1))
    
    # with st.expander("📈 Historical Data"):
    #     st.dataframe(hist_df)
    
    # ---------------- CHARTS ---------------- #
    st.subheader(f"📊 ATM Strike Trend - Historical")
    strike_df_ce = hist_df[(hist_df["strike"] == atm) & (hist_df["type"] == "CE")].sort_values("Datetime")
    strike_df_pe = hist_df[(hist_df["strike"] == atm) & (hist_df["type"] == "PE")].sort_values("Datetime")
    if len(strike_df_ce) > 0:
        st.write(f"Price Trend for atm strike {atm}")
    
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=strike_df_ce["Datetime"], y=strike_df_ce["Close"], name="Price CE"))
        fig1.add_trace(go.Scatter(x=strike_df_pe["Datetime"], y=strike_df_pe["Close"], name="Price PE"))
        fig1.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"]),
                                       dict(bounds=[15.5,9.25], pattern="hour")
                                      ])
        st.plotly_chart(fig1, width='stretch')
    
        st.write("OI Trend")
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=strike_df_ce["Datetime"], y=strike_df_ce["OI"], name="OI CE"))
        fig2.add_trace(go.Scatter(x=strike_df_pe["Datetime"], y=strike_df_pe["OI"], name="OI PE"))
        fig2.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"]),
                                        dict(bounds=[15.5,9.25], pattern="hour")
                                      ])
        st.plotly_chart(fig2, width='stretch')
    
    # ---------------- OI PROFILE ---------------- #
    st.subheader("Latest option chain")
    
    fig = go.Figure()
    
    fig.add_bar(y=atm_chain["strike"], x=-atm_chain["oi_CE"], name="Call OI", orientation="h")
    fig.add_bar(y=atm_chain["strike"], x=atm_chain["oi_PE"], name="Put OI", orientation="h")
    
    fig.add_vline(x=0, line_width=2)
    fig.add_hline(y=spot, line_dash="dash", line_color="yellow", annotation_text="Spot Price")
    fig.add_hline(y=max_pain, line_dash="dot", line_color="red", annotation_text="Max Pain")
    
    fig.update_layout(
        title="Options Open Interest Ladder",
        xaxis_title="Open Interest",
        yaxis_title="Strike Price",
    )
    
    st.plotly_chart(fig, width='stretch')
    
    # ---------------- CHARTS for Selected strikes---------------- #
    st.subheader(f"📊 Strike Trend - Historical")
    # strikes = hist_df['strike'].unique()
    # selected_strikes = st.selectbox("select the strike to display the trend",strikes)
    strike_df_ce = hist_df[(hist_df["strike"] == selected_strikes) & (hist_df["type"] == "CE")].sort_values("Datetime")
    strike_df_pe = hist_df[(hist_df["strike"] == selected_strikes) & (hist_df["type"] == "PE")].sort_values("Datetime")
    if len(strike_df_ce) > 0:
        st.write(f"Price Trend for atm strike {selected_strikes}")
    
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=strike_df_ce["Datetime"], y=strike_df_ce["Close"], name="Price CE"))
        fig3.add_trace(go.Scatter(x=strike_df_pe["Datetime"], y=strike_df_pe["Close"], name="Price PE"))
        fig3.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"]),
                                       dict(bounds=[15.5,9.25], pattern="hour")
                                      ])
        st.plotly_chart(fig3, width='stretch')
    
        st.write(f"OI Trend for atm strike {selected_strikes}")
    
        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(x=strike_df_ce["Datetime"], y=strike_df_ce["OI"], name="OI CE"))
        fig4.add_trace(go.Scatter(x=strike_df_pe["Datetime"], y=strike_df_pe["OI"], name="OI PE"))
        fig4.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"]),
                                       dict(bounds=[15.5,9.25], pattern="hour")
                                      ])
        st.plotly_chart(fig4, width='stretch')
