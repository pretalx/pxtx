# ruff: noqa: F405
import atexit
import os
import tempfile
from pathlib import Path

from pxtx.settings import *  # noqa: F403

tmpdir = tempfile.TemporaryDirectory()
BASE_DIR = Path(tmpdir.name)
DATA_DIR = BASE_DIR
LOG_DIR = DATA_DIR / "logs"
STATIC_ROOT = DATA_DIR / "static"

for directory in (BASE_DIR, DATA_DIR, LOG_DIR, STATIC_ROOT):
    directory.mkdir(parents=True, exist_ok=True)

atexit.register(tmpdir.cleanup)

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

STORAGES["staticfiles"]["BACKEND"] = (
    "django.contrib.staticfiles.storage.StaticFilesStorage"
)

DEBUG = False
DEBUG_PROPAGATE_EXCEPTIONS = True

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

SESSION_ENGINE = "django.contrib.sessions.backends.db"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}


class DisableMigrations:
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


if not os.environ.get("GITHUB_WORKFLOW", ""):
    MIGRATION_MODULES = DisableMigrations()

WHITENOISE_AUTOREFRESH = True
