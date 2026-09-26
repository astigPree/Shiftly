"""Isolated test configuration. Never opens the developer's SQLite database."""
import os

os.environ["DEBUG"] = "true"
os.environ.setdefault("SECRET_KEY", "shiftly-tests-only-not-for-deployment")

from .settings import *  # noqa: F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
if os.environ.get("TEST_DATABASE_URL"):
    from urllib.parse import unquote, urlparse

    database = urlparse(os.environ["TEST_DATABASE_URL"])
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(database.path.lstrip("/")),
        "USER": unquote(database.username or ""),
        "PASSWORD": (Path(os.environ["DATABASE_PASSWORD_FILE"]).read_text().strip()
                     if os.environ.get("DATABASE_PASSWORD_FILE") else unquote(database.password or "")),
        "HOST": database.hostname,
        "PORT": database.port or 5432,
    }}
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
LOGGING = {"version": 1, "disable_existing_loggers": False,
           "handlers": {"null": {"class": "logging.NullHandler"}},
           "loggers": {"django.request": {"handlers": ["null"], "propagate": False}}}
