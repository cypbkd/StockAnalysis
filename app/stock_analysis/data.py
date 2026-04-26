"""
Shared market data fetching (yfinance) and watchlist rule configuration.
Used by both Lambda handlers and the local report generator script.
"""
import logging
import warnings
from datetime import datetime, timedelta
from typing import Dict, List

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)


COMPANY_NAMES: Dict[str, str] = {
    # Mega-cap tech
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "GOOGL": "Alphabet",
    "GOOG": "Alphabet (C)", "META": "Meta Platforms", "AMZN": "Amazon", "TSLA": "Tesla",
    # Semiconductors & hardware
    "AMD": "AMD", "INTC": "Intel", "QCOM": "Qualcomm", "TXN": "Texas Instruments",
    "AMAT": "Applied Materials", "LRCX": "Lam Research", "KLAC": "KLA Corp",
    "MCHP": "Microchip Technology", "MU": "Micron Technology", "NXPI": "NXP Semiconductors",
    "ON": "ON Semiconductor", "ADI": "Analog Devices", "AVGO": "Broadcom",
    "SWKS": "Skyworks Solutions", "QRVO": "Qorvo", "SMCI": "Super Micro Computer",
    "FSLR": "First Solar", "ENPH": "Enphase Energy", "STX": "Seagate Technology",
    "WDC": "Western Digital", "HPQ": "HP Inc", "HPE": "Hewlett Packard Enterprise",
    # Software & IT services
    "ORCL": "Oracle", "IBM": "IBM", "ACN": "Accenture", "NOW": "ServiceNow",
    "INTU": "Intuit", "ADBE": "Adobe", "CRM": "Salesforce", "PANW": "Palo Alto Networks",
    "FTNT": "Fortinet", "SNPS": "Synopsys", "CDNS": "Cadence Design",
    "ADSK": "Autodesk", "CTSH": "Cognizant", "EPAM": "EPAM Systems",
    "AKAM": "Akamai Technologies", "ANSS": "ANSYS", "PTC": "PTC Inc",
    "GDDY": "GoDaddy", "CDW": "CDW", "GEN": "Gen Digital", "TDY": "Teledyne Technologies",
    "TYL": "Tyler Technologies", "TRMB": "Trimble", "FICO": "Fair Isaac",
    "IT": "Gartner", "ROP": "Roper Technologies", "MSCI": "MSCI",
    "VRSN": "VeriSign", "FFIV": "F5", "ZBRA": "Zebra Technologies",
    "TER": "Teradyne", "KEYS": "Keysight Technologies", "NTAP": "NetApp",
    "GLW": "Corning", "TEL": "TE Connectivity", "JKHY": "Jack Henry & Associates",
    "FDS": "FactSet Research", "PAYC": "Paycom Software", "MPWR": "Monolithic Power Systems",
    # Internet & consumer tech
    "NFLX": "Netflix", "EBAY": "eBay", "ETSY": "Etsy", "MTCH": "Match Group",
    "EXPE": "Expedia", "TTWO": "Take-Two Interactive", "EA": "Electronic Arts",
    "UBER": "Uber", "ABNB": "Airbnb",
    # Financials — banks
    "JPM": "JPMorgan Chase", "BAC": "Bank of America", "WFC": "Wells Fargo",
    "C": "Citigroup", "GS": "Goldman Sachs", "MS": "Morgan Stanley",
    "BK": "Bank of New York Mellon", "USB": "U.S. Bancorp", "PNC": "PNC Financial",
    "TFC": "Truist Financial", "MTB": "M&T Bank", "RF": "Regions Financial",
    "HBAN": "Huntington Bancshares", "KEY": "KeyCorp", "CFG": "Citizens Financial",
    "FITB": "Fifth Third Bancorp",
    # Financials — asset managers & exchanges
    "BLK": "BlackRock", "BX": "Blackstone", "SPGI": "S&P Global", "MCO": "Moody's",
    "NDAQ": "Nasdaq", "CME": "CME Group", "ICE": "Intercontinental Exchange",
    "CBOE": "Cboe Global Markets", "SCHW": "Charles Schwab", "AMP": "Ameriprise Financial",
    "TROW": "T. Rowe Price", "BEN": "Franklin Resources", "IVZ": "Invesco",
    "STT": "State Street", "MKTX": "MarketAxess", "RJF": "Raymond James",
    # Financials — insurance & diversified
    "V": "Visa", "MA": "Mastercard", "AXP": "American Express", "PYPL": "PayPal",
    "COF": "Capital One", "SYF": "Synchrony Financial",
    "BRK.B": "Berkshire Hathaway", "PGR": "Progressive", "CB": "Chubb",
    "ALL": "Allstate", "TRV": "Travelers", "HIG": "Hartford Financial",
    "AFL": "Aflac", "MET": "MetLife", "PRU": "Prudential Financial",
    "AIG": "American International Group", "ACGL": "Arch Capital Group",
    "AIZ": "Assurant", "GL": "Globe Life", "CINF": "Cincinnati Financial",
    "PFG": "Principal Financial", "WTW": "Willis Towers Watson",
    "AON": "Aon", "MMC": "Marsh & McLennan", "AJG": "Arthur J. Gallagher",
    "BRO": "Brown & Brown", "EG": "Everest Group",
    "CPAY": "Corpay", "FIS": "Fidelity National Info Services",
    "GPN": "Global Payments", "FI": "Fiserv",
    # Health care — pharma & biotech
    "JNJ": "Johnson & Johnson", "LLY": "Eli Lilly", "MRK": "Merck",
    "ABBV": "AbbVie", "PFE": "Pfizer", "BMY": "Bristol-Myers Squibb",
    "AMGN": "Amgen", "GILD": "Gilead Sciences", "BIIB": "Biogen",
    "REGN": "Regeneron", "VRTX": "Vertex Pharmaceuticals", "MRNA": "Moderna",
    "INCY": "Incyte", "VTRS": "Viatris", "SOLV": "Solventum",
    # Health care — devices & services
    "ABT": "Abbott", "TMO": "Thermo Fisher", "DHR": "Danaher",
    "ISRG": "Intuitive Surgical", "MDT": "Medtronic", "SYK": "Stryker",
    "BSX": "Boston Scientific", "EW": "Edwards Lifesciences", "BDX": "Becton Dickinson",
    "IDXX": "IDEXX Laboratories", "HOLX": "Hologic", "DXCM": "DexCom",
    "PODD": "Insulet", "RMD": "ResMed", "ALGN": "Align Technology",
    "GEHC": "GE HealthCare", "ZBH": "Zimmer Biomet", "RVTY": "Revvity",
    "MTD": "Mettler-Toledo", "WAT": "Waters Corp", "WST": "West Pharmaceutical Services",
    "COO": "Cooper Companies", "STE": "STERIS", "BAX": "Baxter International",
    "TECH": "Bio-Techne", "BIO": "Bio-Rad Laboratories", "HSIC": "Henry Schein",
    "ZTS": "Zoetis", "DVA": "DaVita", "MOH": "Molina Healthcare",
    # Health care — managed care
    "UNH": "UnitedHealth", "ELV": "Elevance Health", "HUM": "Humana",
    "CI": "Cigna", "CNC": "Centene", "CVS": "CVS Health", "HCA": "HCA Healthcare",
    "IQV": "IQVIA", "DGX": "Quest Diagnostics", "LH": "Labcorp",
    "COR": "Cencora", "MCK": "McKesson", "CAH": "Cardinal Health",
    "UHS": "Universal Health Services", "DOC": "Healthpeak Properties",
    # Industrials — defense & aerospace
    "RTX": "RTX", "LMT": "Lockheed Martin", "GD": "General Dynamics",
    "NOC": "Northrop Grumman", "BA": "Boeing", "HII": "Huntington Ingalls",
    "LHX": "L3Harris Technologies", "LDOS": "Leidos", "HWM": "Howmet Aerospace",
    "TDG": "TransDigm Group", "TXT": "Textron",
    # Industrials — machinery & equipment
    "CAT": "Caterpillar", "DE": "Deere", "ETN": "Eaton", "EMR": "Emerson Electric",
    "HON": "Honeywell", "GE": "GE Aerospace", "ITW": "Illinois Tool Works",
    "PH": "Parker Hannifin", "ROK": "Rockwell Automation", "DOV": "Dover",
    "AME": "AMETEK", "IR": "Ingersoll Rand", "PCAR": "PACCAR",
    "CMI": "Cummins", "WAB": "Wabtec", "ALLE": "Allegion",
    "SWK": "Stanley Black & Decker", "SNA": "Snap-on",
    "GNRC": "Generac", "TT": "Trane Technologies",
    # Industrials — transportation
    "UPS": "UPS", "FDX": "FedEx", "UNP": "Union Pacific", "NSC": "Norfolk Southern",
    "CSX": "CSX", "JBHT": "J.B. Hunt Transport", "EXPD": "Expeditors International",
    "CHRW": "C.H. Robinson", "ODFL": "Old Dominion Freight",
    "DAL": "Delta Air Lines", "UAL": "United Airlines", "LUV": "Southwest Airlines",
    "NCLH": "Norwegian Cruise Line", "RCL": "Royal Caribbean", "CCL": "Carnival",
    # Industrials — staffing, services & misc
    "ADP": "ADP", "CTAS": "Cintas", "PAYX": "Paychex", "BR": "Broadridge Financial",
    "VRSK": "Verisk Analytics", "EFX": "Equifax",
    "CPRT": "Copart", "URI": "United Rentals", "FAST": "Fastenal",
    "AXON": "Axon Enterprise", "ROL": "Rollins", "PWR": "Quanta Services",
    "BLDR": "Builders FirstSource", "GWW": "W.W. Grainger",
    "JBL": "Jabil", "J": "Jacobs Solutions", "IEX": "IDEX Corp",
    "PNR": "Pentair", "NDSN": "Nordson", "HAS": "Hasbro",
    "VLTO": "Veralto",
    # Consumer discretionary
    "AMZN": "Amazon", "TSLA": "Tesla", "HD": "Home Depot", "LOW": "Lowe's",
    "MCD": "McDonald's", "SBUX": "Starbucks", "NKE": "Nike",
    "TJX": "TJX Companies", "TGT": "Target", "COST": "Costco",
    "BKNG": "Booking Holdings", "MAR": "Marriott", "HLT": "Hilton",
    "LVS": "Las Vegas Sands", "WYNN": "Wynn Resorts", "MGM": "MGM Resorts",
    "CMG": "Chipotle", "YUM": "Yum! Brands", "DPZ": "Domino's Pizza",
    "DRI": "Darden Restaurants", "ORLY": "O'Reilly Automotive", "AZO": "AutoZone",
    "BBY": "Best Buy", "ULTA": "Ulta Beauty", "LULU": "Lululemon",
    "GRMN": "Garmin", "DECK": "Deckers Outdoor", "TSCO": "Tractor Supply",
    "TPR": "Tapestry", "RL": "Ralph Lauren", "KMX": "CarMax",
    "LEN": "Lennar", "DHI": "D.R. Horton", "PHM": "PulteGroup", "NVR": "NVR Inc",
    "POOL": "Pool Corp", "LYV": "Live Nation", "APTV": "Aptiv",
    "BWA": "BorgWarner", "GPC": "Genuine Parts", "LKQ": "LKQ Corp",
    "MHK": "Mohawk Industries", "EXPE": "Expedia", "BBWI": "Bath & Body Works",
    "GM": "General Motors", "F": "Ford Motor",
    # Consumer staples
    "PG": "Procter & Gamble", "KO": "Coca-Cola", "PEP": "PepsiCo",
    "PM": "Philip Morris", "MO": "Altria", "MDLZ": "Mondelēz",
    "WMT": "Walmart", "KMB": "Kimberly-Clark", "GIS": "General Mills",
    "CL": "Colgate-Palmolive", "KHC": "Kraft Heinz", "HSY": "Hershey",
    "STZ": "Constellation Brands", "MNST": "Monster Beverage",
    "KDP": "Keurig Dr Pepper", "KR": "Kroger", "HRL": "Hormel Foods",
    "TSN": "Tyson Foods", "SJM": "J.M. Smucker", "CAG": "Conagra Brands",
    "CPB": "Campbell Soup", "MKC": "McCormick", "TAP": "Molson Coors",
    "ADM": "Archer-Daniels-Midland", "SYY": "Sysco", "KVUE": "Kenvue",
    "K": "Kellanova",
    # Communication services
    "GOOGL": "Alphabet", "GOOG": "Alphabet (C)", "META": "Meta Platforms",
    "NFLX": "Netflix", "DIS": "Walt Disney", "CMCSA": "Comcast",
    "VZ": "Verizon", "T": "AT&T", "TMUS": "T-Mobile",
    "CHTR": "Charter Communications", "WBD": "Warner Bros. Discovery",
    "FOXA": "Fox Corp (A)", "FOX": "Fox Corp (B)",
    "NWSA": "News Corp (A)", "NWS": "News Corp (B)",
    "OMC": "Omnicom Group", "EA": "Electronic Arts",
    # Energy
    "XOM": "ExxonMobil", "CVX": "Chevron", "COP": "ConocoPhillips",
    "EOG": "EOG Resources", "SLB": "SLB", "HAL": "Halliburton",
    "MPC": "Marathon Petroleum", "PSX": "Phillips 66", "VLO": "Valero Energy",
    "OXY": "Occidental Petroleum", "DVN": "Devon Energy", "BKR": "Baker Hughes",
    "FANG": "Diamondback Energy", "APA": "APA Corp", "EQT": "EQT Corp",
    "CTRA": "Coterra Energy", "OKE": "ONEOK", "KMI": "Kinder Morgan",
    "WMB": "Williams Companies", "TRGP": "Targa Resources",
    "TPL": "Texas Pacific Land", "GEV": "GE Vernova",
    # Materials
    "LIN": "Linde", "APD": "Air Products", "SHW": "Sherwin-Williams",
    "ECL": "Ecolab", "FCX": "Freeport-McMoRan", "NUE": "Nucor",
    "DD": "DuPont", "DOW": "Dow Inc", "LYB": "LyondellBasell",
    "PPG": "PPG Industries", "EMN": "Eastman Chemical", "ALB": "Albemarle",
    "CF": "CF Industries", "MOS": "Mosaic", "NEM": "Newmont",
    "AMCR": "Amcor", "AVY": "Avery Dennison", "BALL": "Ball Corp",
    "IP": "International Paper", "PKG": "Packaging Corp of America",
    "VMC": "Vulcan Materials", "MLM": "Martin Marietta Materials",
    "STLD": "Steel Dynamics", "IFF": "International Flavors & Fragrances",
    "CTVA": "Corteva",
    # Utilities
    "NEE": "NextEra Energy", "SO": "Southern Company", "DUK": "Duke Energy",
    "D": "Dominion Energy", "AEP": "American Electric Power", "SRE": "Sempra",
    "EXC": "Exelon", "XEL": "Xcel Energy", "ES": "Eversource Energy",
    "ETR": "Entergy", "WEC": "WEC Energy", "PEG": "Public Service Enterprise",
    "EIX": "Edison International", "DTE": "DTE Energy", "AWK": "American Water Works",
    "ATO": "Atmos Energy", "LNT": "Alliant Energy", "CMS": "CMS Energy",
    "CNP": "CenterPoint Energy", "NI": "NiSource", "PNW": "Pinnacle West",
    "EVRG": "Evergy", "FE": "FirstEnergy", "PPL": "PPL Corp",
    "AES": "AES Corp", "PCG": "PG&E", "CEG": "Constellation Energy",
    "NRG": "NRG Energy", "VST": "Vistra",
    # Real estate
    "PLD": "Prologis", "AMT": "American Tower", "EQIX": "Equinix",
    "CCI": "Crown Castle", "PSA": "Public Storage", "SPG": "Simon Property Group",
    "WELL": "Welltower", "O": "Realty Income", "DLR": "Digital Realty",
    "AVB": "AvalonBay Communities", "EQR": "Equity Residential",
    "SBAC": "SBA Communications", "IRM": "Iron Mountain", "INVH": "Invitation Homes",
    "VICI": "VICI Properties", "VTR": "Ventas", "ESS": "Essex Property Trust",
    "MAA": "Mid-America Apartment", "UDR": "UDR Inc",
    "EXR": "Extra Space Storage", "ARE": "Alexandria Real Estate",
    "CSGP": "CoStar Group", "CBRE": "CBRE Group", "REG": "Regency Centers",
    "FRT": "Federal Realty", "CPT": "Camden Property Trust",
    "KIM": "Kimco Realty", "HST": "Host Hotels & Resorts",
    "WY": "Weyerhaeuser", "DOC": "Healthpeak Properties",
    # Personal portfolio / watchlist extras
    "SOFI": "SoFi Technologies", "PLTR": "Palantir",
}


def load_watchlists(table_name: str) -> Dict[str, Dict]:
    """Load watchlist definitions from DynamoDB (version="latest" items).

    Each item must have: watchlistId (str), version="latest", name (str), tickers (list[str]).
    Returns the same shape as the old WATCHLISTS constant.
    """
    import boto3
    from boto3.dynamodb.conditions import Attr

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    response = table.scan(FilterExpression=Attr("version").eq("latest"))
    items = list(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = table.scan(
            FilterExpression=Attr("version").eq("latest"),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    watchlists: Dict[str, Dict] = {}
    for item in items:
        wl_id = item["watchlistId"]
        watchlists[wl_id] = {
            "name": item["name"],
            "tickers": list(item["tickers"]),
        }

    logger.info("Loaded %d watchlists from %s", len(watchlists), table_name)
    return watchlists

RULE_CONFIGS: Dict[str, Dict] = {
    "ma_stack": {
        "name": "MA Stack",
        "priority": "high",
        "rule_summary": "All MAs aligned bullishly and RSI not overheated — close > EMA-20 > SMA-50, RSI < 75",
        "rule_def": {
            "logic": "and",
            "name": "Bullish MA Stack",
            "description": "Price above EMA-20, EMA-20 above SMA-50, RSI below 75 — full bullish MA alignment without being overbought.",
            "source_text": "Flag names where close > EMA-20 > SMA-50 and RSI < 75 — all MAs stacked bullishly, not overheated.",
            "conditions": [
                {"field": "close", "op": ">", "value_from": "ema_20"},
                {"field": "ema_20", "op": ">", "value_from": "sma_50"},
                {"field": "rsi_14", "op": "<", "value": 75},
            ],
        },
    },
    "golden_cross": {
        "name": "Golden Cross",
        "priority": "high",
        "rule_summary": "SMA-20 above SMA-50 with price following through — classic bullish trend confirmation",
        "rule_def": {
            "logic": "and",
            "name": "Golden Cross State",
            "description": "SMA-20 crossed above SMA-50 and price is above SMA-20 with RSI in healthy range — trend confirmed.",
            "source_text": "Find names where SMA-20 > SMA-50, close > SMA-20, and RSI < 70 — golden cross with price follow-through.",
            "conditions": [
                {"field": "sma_20", "op": ">", "value_from": "sma_50"},
                {"field": "close", "op": ">", "value_from": "sma_20"},
                {"field": "rsi_14", "op": "<", "value": 70},
            ],
        },
    },
    "dead_cross": {
        "name": "Dead Cross",
        "priority": "high",
        "rule_summary": "SMA-20 below SMA-50 with price below SMA-20 — bearish trend warning",
        "rule_def": {
            "logic": "and",
            "name": "Dead Cross State",
            "description": "SMA-20 has crossed below SMA-50 and price is below SMA-20 — full bearish MA alignment, trend deteriorating.",
            "source_text": "Find names where SMA-20 < SMA-50 and close < SMA-20 — dead cross confirmed with price breaking down.",
            "conditions": [
                {"field": "sma_20", "op": "<", "value_from": "sma_50"},
                {"field": "close", "op": "<", "value_from": "sma_20"},
            ],
        },
    },
    "ath_breakout": {
        "name": "ATH Breakout",
        "priority": "high",
        "rule_summary": "Price at or above 52-week high with volume at least 1.5x the 20-day average",
        "rule_def": {
            "logic": "and",
            "name": "ATH Breakout",
            "description": "Flag tickers where price breaches the 52-week high on accumulating volume (≥1.5× avg).",
            "source_text": "Flag the ticker when volume accumulates and the price breaches all-time high.",
            "conditions": [
                {"field": "close", "op": ">=", "value_from": "high_52w"},
                {"field": "volume_ratio", "op": ">=", "value": 1.5},
            ],
        },
    },
    "near_ath": {
        "name": "Near-ATH Consolidation",
        "priority": "high",
        "rule_summary": "Within 3% of 52-week high, quiet volume, RSI not overheated — coiling before breakout",
        "rule_def": {
            "logic": "and",
            "name": "Near-ATH Consolidation",
            "description": "Price within 3% of 52-week high with quiet volume and RSI below 65 — tight coil before breakout.",
            "source_text": "Find names within 3% of their 52-week high on quiet volume with RSI under 65.",
            "conditions": [
                {"field": "close_to_ath_pct", "op": "<=", "value": 3.0},
                {"field": "volume_ratio", "op": "<", "value": 1.2},
                {"field": "rsi_14", "op": "<", "value": 65},
            ],
        },
    },
    "oversold_dip": {
        "name": "Oversold Dip",
        "priority": "high",
        "rule_summary": "Long-term trend intact (above 50DMA) but RSI dipped into oversold territory — dip-buy setup",
        "rule_def": {
            "logic": "and",
            "name": "Oversold Dip in Uptrend",
            "description": "Price held above 50DMA (trend intact) while RSI dipped below 40 (short-term oversold).",
            "source_text": "Find names above the 50DMA with RSI below 40 — classic dip-buy into trend support.",
            "conditions": [
                {"field": "close", "op": ">", "value_from": "sma_50"},
                {"field": "rsi_14", "op": "<", "value": 40},
            ],
        },
    },
    "pre_earnings_momentum": {
        "name": "Pre-Earnings Momentum",
        "priority": "high",
        "rule_summary": "Earnings within 7 days, price above 20DMA, RSI above 55 — pre-earnings run setup",
        "rule_def": {
            "logic": "and",
            "name": "Pre-Earnings Momentum",
            "description": "Upcoming earnings (≤7 days) with price above 20DMA and RSI above 55.",
            "source_text": "Find names heading into earnings on positive price and momentum — pre-earnings run plays.",
            "conditions": [
                {"field": "earnings_in_days", "op": "<=", "value": 7},
                {"field": "close", "op": ">", "value_from": "sma_20"},
                {"field": "rsi_14", "op": ">=", "value": 55},
            ],
        },
    },
    "high_vol_day": {
        "name": "High-Volume Day",
        "priority": "high",
        "rule_summary": "Volume at least 2x average with RSI above 55 and price above 20DMA — institutional buying",
        "rule_def": {
            "logic": "and",
            "name": "High-Volume Momentum Day",
            "description": "Big volume day (≥2× avg) with momentum confirming direction — institutional accumulation signal.",
            "source_text": "Flag names with volume at least 2x average, RSI above 55, and price above the 20DMA.",
            "conditions": [
                {"field": "volume_ratio", "op": ">=", "value": 2.0},
                {"field": "rsi_14", "op": ">=", "value": 55},
                {"field": "close", "op": ">", "value_from": "sma_20"},
            ],
        },
    },
    "strong_trending_day": {
        "name": "Strong Trending Day",
        "priority": "high",
        "rule_summary": "Single-day gain of 3%+ with volume confirmation inside an uptrend — momentum breakout",
        "rule_def": {
            "logic": "and",
            "name": "Strong Trending Day",
            "description": "Strong single-day gain (≥3%) on volume at least 1.5x average while above the 20DMA — momentum breakout.",
            "source_text": "Flag names with a 3%+ day on volume at least 1.5x average while above the 20DMA.",
            "conditions": [
                {"field": "change_percent", "op": ">=", "value": 3.0},
                {"field": "close", "op": ">", "value_from": "sma_20"},
                {"field": "volume_ratio", "op": ">=", "value": 1.5},
            ],
        },
    },
    "near_52w_support": {
        "name": "Near 52-Week Support",
        "priority": "high",
        "rule_summary": "Price within 5% of 52-week low with RSI cooling — potential support bounce",
        "rule_def": {
            "logic": "and",
            "name": "Near 52-Week Support",
            "description": "Price within 5% of the 52-week floor with RSI below 45 — testing major long-term support, potential reversal.",
            "source_text": "Find names within 5% of their 52-week low with RSI under 45 — buyers historically step in near the annual floor.",
            "conditions": [
                {"field": "close_to_support_pct", "op": "<=", "value": 5.0},
                {"field": "rsi_14", "op": "<", "value": 45},
            ],
        },
    },
    "pivot_s1_bounce": {
        "name": "Pivot S1 Bounce",
        "priority": "high",
        "rule_summary": "Price holding within 3% above S1 pivot support with RSI not stretched — classic intraday support hold",
        "rule_def": {
            "logic": "and",
            "name": "Pivot S1 Bounce",
            "description": "Price just above S1 pivot support (within 3%) with RSI below 50 — holding support after a test.",
            "source_text": "Find names where price is within 3% above S1 and RSI < 50 — pivot support holding, potential bounce entry.",
            "conditions": [
                {"field": "close_to_s1_pct", "op": ">=", "value": 0.0},
                {"field": "close_to_s1_pct", "op": "<=", "value": 3.0},
                {"field": "rsi_14", "op": "<", "value": 50},
            ],
        },
    },
    "pivot_r1_breakout": {
        "name": "Pivot R1 Breakout",
        "priority": "high",
        "rule_summary": "Price broke above R1 pivot resistance on above-average volume — resistance turned support",
        "rule_def": {
            "logic": "and",
            "name": "Pivot R1 Breakout",
            "description": "Price closed above R1 pivot resistance on volume at least 1.5x average — clean resistance breakout.",
            "source_text": "Flag names where price closed above R1 on elevated volume — pivot resistance broken, next target R2.",
            "conditions": [
                {"field": "close_to_r1_pct", "op": "<=", "value": 0.0},
                {"field": "volume_ratio", "op": ">=", "value": 1.5},
            ],
        },
    },
    "td_buy": {
        "name": "TD Buy Setup",
        "priority": "high",
        "rule_summary": "9 consecutive closes below close[i-4] — 神奇九转 exhaustion signal, potential reversal up",
        "rule_def": {
            "logic": "and",
            "name": "TD Sequential Buy Setup",
            "description": "Nine consecutive closes each below the close four bars prior — classic DeMark exhaustion signal indicating selling pressure may be spent.",
            "source_text": "Flag when 9 consecutive bars close below close[i-4] — TD Sequential buy setup (神奇九转买入).",
            "conditions": [
                {"field": "td_buy_setup", "op": ">=", "value": 9},
            ],
        },
    },
    "td_sell": {
        "name": "TD Sell Setup",
        "priority": "high",
        "rule_summary": "9 consecutive closes above close[i-4] — 神奇九转 exhaustion signal, potential reversal down",
        "rule_def": {
            "logic": "and",
            "name": "TD Sequential Sell Setup",
            "description": "Nine consecutive closes each above the close four bars prior — DeMark exhaustion signal indicating buying pressure may be spent.",
            "source_text": "Flag when 9 consecutive bars close above close[i-4] — TD Sequential sell setup (神奇九转卖出).",
            "conditions": [
                {"field": "td_sell_setup", "op": ">=", "value": 9},
            ],
        },
    },
}


def compute_rsi(series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2) if not rsi.empty else float("nan")


def fetch_market_data(tickers: List[str]) -> Dict[str, dict]:
    """Download 90 days of daily OHLCV data and compute technicals for each ticker."""
    import pandas as pd
    import yfinance as yf

    end = datetime.now()
    start = end - timedelta(days=365)

    logger.info("Downloading market data for %d tickers (%s to %s)",
                len(tickers), start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    yf_tickers = [t.replace(".", "-") for t in tickers]
    ticker_map = {yf_sym: orig for yf_sym, orig in zip(yf_tickers, tickers)}

    raw = yf.download(
        yf_tickers,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    logger.info("yfinance download complete: %d rows, %d columns", len(raw), len(raw.columns))

    is_multi = isinstance(raw.columns, pd.MultiIndex)
    results: Dict[str, dict] = {}
    skipped_insufficient: list = []
    skipped_error: list = []

    for yf_sym, orig_ticker in ticker_map.items():
        try:
            if is_multi:
                close_s = raw[("Close", yf_sym)].dropna()
                high_s = raw[("High", yf_sym)].dropna()
                low_s = raw[("Low", yf_sym)].dropna()
                vol_s = raw[("Volume", yf_sym)].dropna()
            else:
                close_s = raw["Close"].dropna()
                high_s = raw["High"].dropna()
                low_s = raw["Low"].dropna()
                vol_s = raw["Volume"].dropna()

            if len(close_s) < 21:
                skipped_insufficient.append(orig_ticker)
                continue

            close_today = float(close_s.iloc[-1])
            close_prev = float(close_s.iloc[-2])
            change_pct = round((close_today - close_prev) / close_prev * 100, 2)
            sma_20 = round(float(close_s.iloc[-20:].mean()), 2)
            sma_50 = round(float(close_s.iloc[-50:].mean()), 2) if len(close_s) >= 50 else sma_20
            ema_20 = round(float(close_s.ewm(span=20, adjust=False).mean().iloc[-1]), 2)
            rsi = compute_rsi(close_s)
            avg_vol = float(vol_s.iloc[-20:].mean()) if len(vol_s) >= 20 else float(vol_s.mean())
            high_52w = round(float(close_s.iloc[-252:].max()), 2)
            low_52w = round(float(close_s.iloc[-252:].min()), 2)
            volume_today = float(vol_s.iloc[-1]) if len(vol_s) > 0 else 0.0
            volume_ratio = round(volume_today / avg_vol, 2) if avg_vol > 0 else 1.0
            close_to_ath_pct = round((high_52w - close_today) / high_52w * 100, 2) if high_52w > 0 else 0.0
            close_to_support_pct = round((close_today - low_52w) / low_52w * 100, 2) if low_52w > 0 else 0.0

            # Pivot points from prior session's High/Low/Close
            prev_high = float(high_s.iloc[-2]) if len(high_s) >= 2 else float(high_s.iloc[-1])
            prev_low = float(low_s.iloc[-2]) if len(low_s) >= 2 else float(low_s.iloc[-1])
            pivot = round((prev_high + prev_low + close_prev) / 3, 2)
            pivot_r1 = round(2 * pivot - prev_low, 2)
            pivot_r2 = round(pivot + (prev_high - prev_low), 2)
            pivot_s1 = round(2 * pivot - prev_high, 2)
            pivot_s2 = round(pivot - (prev_high - prev_low), 2)
            # % distance: positive = above S1/below R1, negative = below S1/above R1
            close_to_s1_pct = round((close_today - pivot_s1) / pivot_s1 * 100, 2) if pivot_s1 > 0 else 0.0
            close_to_r1_pct = round((pivot_r1 - close_today) / pivot_r1 * 100, 2) if pivot_r1 > 0 else 0.0

            # TD Sequential: count consecutive closes vs close[i-4]
            td_buy = 0
            td_sell = 0
            for i in range(4, len(close_s)):
                c, c4 = float(close_s.iloc[i]), float(close_s.iloc[i - 4])
                if c < c4:
                    td_buy += 1
                    td_sell = 0
                elif c > c4:
                    td_sell += 1
                    td_buy = 0
                else:
                    td_buy = 0
                    td_sell = 0

            results[orig_ticker] = {
                "close": round(close_today, 2),
                "change_percent": change_pct,
                "sma_20": sma_20,
                "sma_50": sma_50,
                "ema_20": ema_20,
                "rsi_14": rsi,
                "volume": volume_today,
                "avg_volume_20d": avg_vol,
                "high_52w": high_52w,
                "low_52w": low_52w,
                "volume_ratio": volume_ratio,
                "close_to_ath_pct": close_to_ath_pct,
                "close_to_support_pct": close_to_support_pct,
                "pivot_point": pivot,
                "pivot_r1": pivot_r1,
                "pivot_r2": pivot_r2,
                "pivot_s1": pivot_s1,
                "pivot_s2": pivot_s2,
                "close_to_s1_pct": close_to_s1_pct,
                "close_to_r1_pct": close_to_r1_pct,
                "td_buy_setup": td_buy,
                "td_sell_setup": td_sell,
            }
        except Exception as exc:
            skipped_error.append(orig_ticker)
            logger.warning("Failed to compute metrics for %s: %s", orig_ticker, exc)

    if skipped_insufficient:
        logger.warning("Skipped %d tickers with <21 days of data: %s",
                       len(skipped_insufficient), ", ".join(skipped_insufficient))
    if skipped_error:
        logger.warning("Skipped %d tickers due to errors: %s",
                       len(skipped_error), ", ".join(skipped_error))
    logger.info("fetch_market_data complete: %d/%d tickers returned metrics",
                len(results), len(tickers))
    return results
