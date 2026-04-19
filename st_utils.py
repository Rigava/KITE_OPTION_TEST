import json
import os
import datetime
import requests
import pandas as pd
import plotly.graph_objects as go
import numpy as np
from datetime import datetime
from io import StringIO

def get_instruments(enctoken):
    url = "https://api.kite.trade/instruments/NSE"
    headers = {"Cookie": f"enctoken={enctoken}"}
    resp = requests.get(url, headers=headers)
    df = pd.read_csv(StringIO(resp.text))
    # df = df[df['segment'] == 'INDICES']
    return df['name'].unique()

def get_token_by_name(symbol, enctoken):
    url = "https://api.kite.trade/instruments/NSE"
    headers = {"Cookie": f"enctoken={enctoken}"}
    df = pd.read_csv(StringIO(requests.get(url, headers=headers).text))
    # match = df[(df['name'].str.upper() == symbol.upper()) & (df['segment'] == 'INDICES')]
    match = df[(df['name'].str.upper() == symbol.upper())]
    return int(match['instrument_token'].values[0]) if not match.empty else None

def get_historical_data(enctoken,symbol,interval,from_date, to_date):
    token = get_token_by_name(symbol, enctoken)
    if not token:
        return None
    url = f"https://kite.zerodha.com/oms/instruments/historical/{token}/{interval}"
    params = {
    "from": from_date.strftime("%Y-%m-%d %H:%M:%S"),
    "to": to_date.strftime("%Y-%m-%d %H:%M:%S"),
    'oi':"1"
    }
    headers = {"Authorization": f"enctoken {enctoken}"}
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        candles = response.json()["data"]["candles"]
        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "open_interest"])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
    else:
        raise Exception(
            f"Kite API Error {response.status_code}\n"
            f"URL: {response.url}\n"
            f"Response: {response.text}"
        )

    return pd.DataFrame()
  
def plot_ohlc(df):
    fig = go.Figure()
    fig.add_candlestick(
        x=df['timestamp'],
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name="Price"
    )
    fig.update_layout(title="OHLC Chart", xaxis_title="Datetime", yaxis_title="Price")
    return fig

def AddSMAIndicators(df,indicators,fast,slow):
    if "SMA" in indicators: 
        df['SMAf']=df.close.rolling(fast).mean()
        df['SMAs']=df.close.rolling(slow).mean()
        df['buySignal']=np.where(df.SMAf>df.SMAs,1,0)
        df['sellSignal']=np.where(df.SMAf<df.SMAs,1,0)
        df['Decision Buy GC']= df.buySignal.diff()
        df['Decision Sell GC']= df.sellSignal.diff()
        df['price'] = df['close'].shift(-1)
        print('SMA indicators added')
    return df
