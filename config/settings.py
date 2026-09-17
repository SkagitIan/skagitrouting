from pathlib import Path
import os
from urllib.parse import urlparse

import dj_database_url
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEBUG = os.getenv("DEBUG", "false").lower() == "true"
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY and not DEBUG:
    raise ImproperlyConfigured("SECRET_KEY is required outside local development.")
SECRET_KEY = SECRET_KEY or "proprietary-routing-local-only-change-me"

ALLOWED_HOSTS = [host.strip() for host in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",") if host.strip()]
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("PROPRIETARY_DATABASE_URL")
if not DATABASE_URL:
    raise ImproperlyConfigured("DATABASE_URL or PROPRIETARY_DATABASE_URL is required.")
if urlparse(DATABASE_URL).scheme not in {"postgres", "postgresql", "postgis"}:
    raise ImproperlyConfigured("The proprietary product requires PostgreSQL/PostGIS.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "routing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600)}

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "America/Los_Angeles")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/routing/"
LOGOUT_REDIRECT_URL = "/login/"

OPENSKAGIT_API_URL = os.getenv("OPENSKAGIT_API_URL", "").rstrip("/")
OPENSKAGIT_API_TOKEN = os.getenv("OPENSKAGIT_API_TOKEN", "")
OPENSKAGIT_API_TIMEOUT = float(os.getenv("OPENSKAGIT_API_TIMEOUT", "12"))
VALHALLA_URL = os.getenv("VALHALLA_URL", "")
PICTOMETRY_COUNTY_HOST = os.getenv("PICTOMETRY_COUNTY_HOST", "http://geocorvm1.skagit.local").rstrip("/")
PICTOMETRY_VIEWER_PATH = os.getenv("PICTOMETRY_VIEWER_PATH", "/Html5ViewerProd/Resources/3rdPartyMaps/Pictometry.aspx")
CYCLOMEDIA_BASE_URL = os.getenv("CYCLOMEDIA_BASE_URL", "https://atlasapi.cyclomedia.com/api/PanoramaRendering/")
CYCLOMEDIA_API_KEY = os.getenv("CYCLOMEDIA_API_KEY", "")
CYCLOMEDIA_USERNAME = os.getenv("CYCLOMEDIA_USERNAME", "")
CYCLOMEDIA_PASSWORD = os.getenv("CYCLOMEDIA_PASSWORD", "")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
