"""
Django settings for FlatFinder.

Configuration comes from environment variables (loaded from `.env` if present).
The database is chosen by DATABASE_URL: PostgreSQL in Docker, SQLite otherwise (PLAN §2 decision 9).
"""
import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _env_bool(name, default=False):
    return os.environ.get(name, str(int(default))).strip().lower() in ("1", "true", "yes", "on")


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = _env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "flatfinder.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
                "core.boundary.ui.context.flatfinder_context",
            ],
        },
    },
]

WSGI_APPLICATION = "flatfinder.wsgi.application"

# --- Database (decision 9) ---------------------------------------------------
# DATABASE_URL unset -> SQLite file next to manage.py, for teammates without Postgres.
if os.environ.get("DATABASE_URL"):
    DATABASES = {"default": dj_database_url.config(conn_max_age=60)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Bookmarks live in the session (decision 10). Database-backed sessions need no extra setup.
# The cookie ends with the browser session, matching UC-05's "session only" assumption.
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

LANGUAGE_CODE = "en-sg"
TIME_ZONE = "Asia/Singapore"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

# --- FlatFinder settings -----------------------------------------------------
DATA_RAW_DIR = BASE_DIR / "data" / "raw"

# Fit Score (PLAN §4, decision 2): price and lease use fixed weights; the user's
# budget and lease inputs only set thresholds.
FIT_SCORE_FIXED_WEIGHTS = {"price": 5, "lease": 5}
ANCHOR_RADIUS_M = 3000           # anchor sub-score falls to 0 at this distance (decision 4)
AMENITY_RADIUS_M = 1000          # "nearest amenities within 1 km" (FR 2.3)
WEIGHT_MIN, WEIGHT_MAX = 1, 10   # importance scale (decision 1)
DEFAULT_ANCHOR_WEIGHT = 5

RESULTS_PER_PAGE = 20            # decision 12
MAP_PIN_MIN_ZOOM = 14            # area counts below, flat pins from here up (decision 12)
MAP_PIN_LIMIT = 500
MAP_MIN_ZOOM, MAP_MAX_ZOOM = 11, 19  # the range OneMap's basemap tiles cover Singapore at

# MapGateway (PLAN §5): base-map tiles and attribution, passed to MapUI via the template.
MAP_TILE_URL = "https://www.onemap.gov.sg/maps/tiles/Default/{z}/{x}/{y}.png"
MAP_TILE_ATTRIBUTION = (
    '<img src="https://www.onemap.gov.sg/web-assets/images/logo/om_logo.png" '
    'style="height:20px;width:20px;display:inline"/>&nbsp;'
    '<a href="https://www.onemap.gov.sg/" target="_blank" rel="noopener">OneMap</a>&nbsp;&copy;&nbsp;contributors'
    '&nbsp;&#124;&nbsp;<a href="https://www.sla.gov.sg/" target="_blank" rel="noopener">Singapore Land Authority</a>'
)

# OneMap gateways (server-side only; the token never reaches the browser).
ONEMAP_BASE_URL = "https://www.onemap.gov.sg"
ONEMAP_EMAIL = os.environ.get("ONEMAP_EMAIL", "")
ONEMAP_PASSWORD = os.environ.get("ONEMAP_PASSWORD", "")
ONEMAP_TIMEOUT_S = 5

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "core": {"level": "INFO"},
    },
}
