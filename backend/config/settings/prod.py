from .base import *  # noqa

DEBUG = False
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", cast=Csv())

# HTTPS
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# CORS — locked to Vercel domain
CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", cast=Csv())

# Email — Brevo in prod
EMAIL_PROVIDER = "brevo"

# Logging to stdout (picked up by CloudWatch via Docker)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "apps":   {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}