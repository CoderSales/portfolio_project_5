"""Run project tests without production databases, mail, or storage services."""

import tempfile
from pathlib import Path

from .settings import *  # noqa: F401,F403


SECRET_KEY = "portfolio-project-5-tests-only-not-a-production-secret"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "TEST": {"NAME": ":memory:"},
    }
}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DEFAULT_FROM_EMAIL = "accounts@example.invalid"
EMAIL_HOST_USER = ""
EMAIL_HOST_PASSWORD = ""
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "portfolio-project-5-auth-tests",
    }
}
DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
MEDIA_URL = "/media/"
STATIC_URL = "/static/"
MEDIA_ROOT = Path(tempfile.gettempdir()) / "portfolio-project-5-test-media"
STATIC_ROOT = Path(tempfile.gettempdir()) / "portfolio-project-5-test-static"
STRIPE_PUBLIC_KEY = ""
STRIPE_SECRET_KEY = ""
STRIPE_WH_SECRET = ""
