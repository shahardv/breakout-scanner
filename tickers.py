"""Curated ticker universe: S&P 500 large-caps + NASDAQ-100. Deduped."""

SP500_TOP = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA", "BRK-B", "AVGO",
    "JPM", "LLY", "V", "XOM", "MA", "UNH", "COST", "HD", "PG", "JNJ",
    "ABBV", "WMT", "NFLX", "BAC", "CRM", "ORCL", "CVX", "MRK", "AMD", "KO",
    "ADBE", "PEP", "TMO", "ACN", "LIN", "CSCO", "MCD", "ABT", "WFC", "DHR",
    "CAT", "IBM", "GE", "DIS", "AMAT", "TXN", "QCOM", "VZ", "INTU", "PM",
    "AXP", "UNP", "PFE", "GS", "MS", "RTX", "ISRG", "NOW", "T", "BKNG",
    "SPGI", "PGR", "BLK", "LOW", "BA", "ELV", "MDT", "TJX", "VRTX", "C",
    "ETN", "DE", "CB", "AMGN", "ADP", "REGN", "BMY", "SCHW", "BSX", "MMC",
    "GILD", "SBUX", "LRCX", "ADI", "MU", "FI", "PLD", "PANW", "MO", "SYK",
    "CI", "TMUS", "NKE", "HCA", "KLAC", "ICE", "ANET", "EQIX", "ZTS", "SO",
    "CME", "PYPL", "DUK", "SHW", "AON", "USB", "CDNS", "MDLZ", "CL", "TGT",
    "CMG", "WM", "MCK", "EOG", "MAR", "PNC", "ITW", "CSX", "NOC", "FDX",
    "MCO", "WELL", "GD", "APD", "BDX", "EMR", "ORLY", "FCX", "TFC", "SNPS",
    "CARR", "AJG", "ROP", "PH", "PSX", "AZO", "NSC", "MPC", "AFL", "DHI",
    "PSA", "TRV", "TT", "MET", "GM", "F", "OXY", "VLO", "AIG", "URI",
    "CTAS", "FTNT", "HLT", "JCI", "AEP", "SLB", "ECL", "ROST", "PCAR", "STZ",
    "AMP", "TEL", "CPRT", "PAYX", "SRE", "MNST", "DLR", "CCI", "WMB", "PRU",
    "EW", "RSG", "DXCM", "MSI", "KMB", "OKE", "GIS", "EXC", "KMI", "AME",
    "CMI", "BK", "FAST", "VRSK", "ODFL", "DG", "DD", "CTSH", "GWW", "VICI",
    "HSY", "FIS", "EFX", "CNC", "ON", "RCL", "OTIS", "CSGP", "DAL", "NUE",
    "ALL", "IT", "BIIB", "EBAY", "ED", "GLW", "WBA", "WBD", "PCG", "PEG",
    "DOW", "ADM", "WTW", "KR", "VST", "EIX", "DVN", "HPQ", "FANG", "HAL",
]

NASDAQ100_EXTRA = [
    "ASML", "TEAM", "WDAY", "ZS", "MRVL", "PYPL", "FTNT", "CTAS", "ABNB", "BIDU",
    "DDOG", "MELI", "PDD", "JD", "BIIB", "ILMN", "DXCM", "WBD", "EA", "VRSK",
    "GFS", "ARM", "CDW", "TTD", "CRWD", "SMCI", "PLTR", "NET", "SNOW", "DASH",
    "SHOP", "MDB", "OKTA", "ROKU", "RIVN", "LCID", "COIN", "HOOD", "AFRM",
]

ALL_TICKERS = sorted(set(SP500_TOP + NASDAQ100_EXTRA))

# Tickers that are members of the NASDAQ-100 (used for the index filter on the
# frontend). Includes both the dedicated NASDAQ100_EXTRA list and large-cap names
# from SP500_TOP that are also part of the NASDAQ-100.
NASDAQ100 = set(NASDAQ100_EXTRA) | {
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA", "AVGO",
    "COST", "NFLX", "ADBE", "PEP", "CSCO", "AMD", "TMUS", "INTU", "QCOM",
    "TXN", "AMAT", "BKNG", "ISRG", "CMCSA", "HON", "VRTX", "PANW", "ADP",
    "GILD", "SBUX", "LRCX", "ADI", "MU", "MDLZ", "REGN", "KLAC", "SNPS",
    "CDNS", "MELI", "MAR", "ORLY", "MNST", "CTAS", "PYPL", "FTNT", "PDD",
    "ASML", "DXCM", "CSGP", "WDAY", "PCAR", "PAYX", "CPRT", "ROST", "FAST",
    "ODFL", "EA", "VRSK", "CTSH", "EXC", "GFS", "BIIB", "ON", "CRWD", "DDOG",
    "TEAM", "ZS", "MDB", "OKTA", "ARM", "ABNB", "BIDU", "ILMN", "JD", "CDW",
    "ROP", "WBD", "DLTR", "ANSS", "TTD",
}

SP500 = set(SP500_TOP)

