import pandas as pd

def build_option_chain(options_df, ltp_data):

    live_df = pd.DataFrame(ltp_data).T

    if len(live_df) == 0:
        return None

    live_df = live_df.reset_index().rename(
        columns={"index": "instrument_token"}
    )

    merged = options_df.merge(live_df, on="instrument_token", how="left")

    return merged


def create_option_chain(df):

    ce = df[df.instrument_type == "CE"]
    pe = df[df.instrument_type == "PE"]

    ce = ce.rename(
        columns={
            "ltp": "ltp_CE",
            "oi": "oi_CE",
            "volume": "volume_CE",
        }
    )

    pe = pe.rename(
        columns={
            "ltp": "ltp_PE",
            "oi": "oi_PE",
            "volume": "volume_PE",
        }
    )

    chain = ce.merge(pe, on="strike")

    return chain.sort_values("strike")
