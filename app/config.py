from datetime import timedelta
from pathlib import Path

BASE_URL = "https://auth.sonsofbane.com"
ESI_BASE = "https://esi.evetech.net"
SOB_ALLIANCE_ID = 99001969
USER_AGENT = "SoB-Audit-Tool/2.0 (web; contact: alliance leadership)"

REQUEST_DELAY = 0.05
AUTH_WORKERS = 5
ESI_WORKERS = 10

TTL_OVERVIEW = timedelta(hours=24)
TTL_ESI = timedelta(hours=24)
TTL_FAT_MONTH = timedelta(hours=2)
TTL_FINDER = timedelta(hours=6)

MONTH_ABBRS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

ROOT_DIR = Path(__file__).parent.parent
CACHE_DIR = ROOT_DIR / ".cache"
REPORTS_DIR = ROOT_DIR / "reports"
ENV_FILE = ROOT_DIR / "Auth.env"
STATIC_DIR = ROOT_DIR / "static"
