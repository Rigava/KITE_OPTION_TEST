import pandas as pd
# Detect ATM strike & ATM window
def get_atm_strike(chain,spot_price=None):
    if spot_price is None:
        return None
    chain["distance"] = abs(chain["strike"] - spot_price)
    atm = chain.loc[chain.distance.idxmin(),"strike"]
    return atm

def atm_window(chain, atm, n=5):
    strikes = sorted(chain.strike.unique())
    idx = strikes.index(atm)
    selected = strikes[idx-n:idx+n+1]
    return chain[chain.strike.isin(selected)]

def calculate_pcr(chain):
    pe_oi = chain["oi_PE"].sum()
    ce_oi = chain["oi_CE"].sum()
    if ce_oi == 0:
        return None
    return pe_oi / ce_oi


def atm_straddle(chain, atm):
    row = chain[chain.strike == atm]
    ce = row["ltp_CE"].values[0]
    pe = row["ltp_PE"].values[0]
    return ce + pe


def get_atm(chain, spot):
    chain["distance"] = abs(chain["strike"] - spot)
    atm = chain.loc[chain.distance.idxmin(), "strike"]
    return atm

def get_atm(df):
    df["diff"] = (df["strike"] - df["spot"]).abs()
    atm = df.loc[df.groupby("timestamp")["diff"].idxmin(), ["timestamp", "strike"]]
    atm = atm.rename(columns={"strike": "atm_strike"})
    return df.merge(atm, on="timestamp", how="left")


def get_max_pain(df):
    # Unique strikes
    strikes = df["strike"].unique()
    pain_list = []

    for expiry_price in strikes:
        
        call_pain = 0
        put_pain = 0
        
        for _, row in df.iterrows():
            
            strike = row["strike"]
            oi_ce = row["oi_CE"]
            oi_pe = row["oi_PE"]
            
            # Call payoff
            if expiry_price > strike:
                call_pain += (expiry_price - strike) * oi_ce
            
            # Put payoff
            if expiry_price < strike:
                put_pain += (strike - expiry_price) * oi_pe
        
        total_pain = call_pain + put_pain
        
        pain_list.append({
            "expiry_price": expiry_price,
            "call_pain": call_pain,
            "put_pain": put_pain,
            "total_pain": total_pain
        })

    pain_df = pd.DataFrame(pain_list)
    # Max Pain Strike
    max_pain_strike = pain_df.loc[pain_df["total_pain"].idxmin(), "expiry_price"]
    # print("Max Pain Strike:", max_pain_strike)
    return max_pain_strike
