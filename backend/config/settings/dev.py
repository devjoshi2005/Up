from .base import *  # noqa

DEBUG = True
ALLOWED_HOSTS = ["*"]

CORS_ALLOW_HEADERS = [
    "accept", "authorization", "content-type",
    "x-api-key", "idempotency-key",
]

# CORS — allow Next.js dev server
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
CORS_ALLOW_CREDENTIALS = True

# Dev-only apps
INSTALLED_APPS += ["django_extensions"] if False else []   # toggle when needed

# Email — console in dev (no Brevo calls)
EMAIL_PROVIDER = "console"