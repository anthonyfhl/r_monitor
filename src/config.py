import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- Paths ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

# --- API Keys ---
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- HKMA API ---
HKMA_BASE = "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin"
HKMA_HIBOR_DAILY = f"{HKMA_BASE}/er-ir/hk-interbank-ir-daily"
HKMA_BASE_RATE = f"{HKMA_BASE}/er-ir/hkd-ir-effdates"
HKMA_FORWARD = f"{HKMA_BASE}/er-ir/hkd-fer-daily"

# --- FRED API ---
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
FRED_SERIES = {
    "fed_funds_effective": "DFF",
    "fed_funds_target_upper": "DFEDTARU",
    "fed_funds_target_lower": "DFEDTARL",
}

# --- NY Fed ---
NYFED_SOFR = "https://markets.newyorkfed.org/api/rates/secured/sofr/last/1.json"
NYFED_SOFR_HISTORY = "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json"

# --- Treasury ---
TREASURY_YIELD_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv"

# --- IB ---
IB_MARGIN_URL = "https://www.interactivebrokers.com/en/trading/margin-rates.php"

# --- FedWatch (via investing.com) ---
FEDWATCH_URL = "https://www.investing.com/central-banks/fed-rate-monitor"

# --- Bank websites for P-rate ---
BANK_URLS = {
    "HSBC": "https://www.hsbc.com.hk/investments/market-information/hk/lending-rate/",
    "DBS": "https://www.dbs.com.hk/personal/loans/home-loans/home-advice/interestrate.html",
}

# --- Display names ---
HIBOR_TENORS = ["Overnight", "1 Month", "3 Months", "12 Months"]

# --- HTTP ---
REQUEST_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
