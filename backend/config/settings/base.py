from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------- Security ----------
SECRET_KEY = config("DJANGO_SECRET_KEY")
DEBUG = config("DJANGO_DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

PUBLIC_BASE_URL = config("PUBLIC_BASE_URL", default="http://localhost:8000")
ACK_TOKEN_TTL_SECONDS = config("ACK_TOKEN_TTL_SECONDS", default=86400, cast=int)

CELERY_BEAT_SCHEDULE = {
    "sweep-escalations": {
        "task": "apps.notifications.tasks.sweep_escalations",
        "schedule": 30.0,           # every 30s
    },
    "sweep-stuck-pending": {
        "task": "apps.notifications.tasks.sweep_stuck_pending",
        "schedule": 60.0,           # every 60s
    },
}


# ---------- Apps ----------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "corsheaders",
    "channels",
]

LOCAL_APPS = [
    "apps.tenants",
    "apps.accounts",
    "apps.incidents",
    "apps.notifications",
    "apps.api",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ---------- Middleware ----------
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",          # must be near top
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------- Templates ----------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------- Database (Supabase via individual fields) ----------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="postgres"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST"),
        "PORT": config("DB_PORT", default="6543"),
        "OPTIONS": {
            # Supabase requires SSL; local Docker Postgres sets DB_SSLMODE=disable
            "sslmode": config("DB_SSLMODE", default="require"),
            "connect_timeout": 10,
        },
        "CONN_MAX_AGE": 60,                     # reuse connections
        "CONN_HEALTH_CHECKS": True,
    }
}

# ---------- Redis (Upstash) ----------
REDIS_URL = config("REDIS_URL")
CELERY_BROKER_URL = config("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND")

# Django cache — uses Redis DB 0
# ssl_cert_reqs is only valid for TLS (Upstash rediss://); plain redis:// (local Docker) must not set it.
_CACHE_OPTIONS = {"ssl_cert_reqs": None} if REDIS_URL.startswith("rediss") else {}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": _CACHE_OPTIONS,
        "KEY_PREFIX":"dj"
    }
}

# Channels layer — WebSocket fan-out via Redis
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
            "symmetric_encryption_keys": [SECRET_KEY],
        },
    }
}

# ---------- Celery ----------
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 5 * 60                 # hard kill after 5 min
CELERY_TASK_SOFT_TIME_LIMIT = 4 * 60
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# Priority queues — critical never queues behind digest
CELERY_TASK_QUEUES = {
    "critical": {"exchange": "critical", "routing_key": "critical"},
    "default":  {"exchange": "default",  "routing_key": "default"},
    "digest":   {"exchange": "digest",   "routing_key": "digest"},
}
CELERY_TASK_DEFAULT_QUEUE = "default"

# Brevo daily quota (free tier = 300/day)
BREVO_DAILY_QUOTA = config("BREVO_DAILY_QUOTA", default=300, cast=int)
SMS_PROVIDER = config("SMS_PROVIDER", default="textlink")   # or "mock"

# Celery routing by priority
CELERY_TASK_ROUTES = {
    "apps.notifications.tasks.deliver_notification": {
        "queue": "default",   # actual queue chosen at apply_async time
    },
}


# ---------- DRF ----------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.api.authentication.ApiKeyAuthentication",       # for ingestion
        "rest_framework_simplejwt.authentication.JWTAuthentication",  # for dashboard
        "apps.api.authentication.ApiKeyAuthentication",
        "apps.api.auth_jwt.TenantJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    # Overridable so load tests (k6) can raise the ceiling without touching prod.
    "DEFAULT_THROTTLE_RATES": {"tenant": config("THROTTLE_TENANT_RATE", default="600/min")},
}

SPECTACULAR_SETTINGS = {
    "TITLE": "SysFlow API",
    "DESCRIPTION": "Event-driven alerting with ack-based escalation",
    "VERSION": "1.0.0",
}

# ---------- JWT ----------
from datetime import timedelta
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "SIGNING_KEY": SECRET_KEY,
}

# ---------- i18n / static ----------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------- Custom app config ----------
HMAC_SECRET_KEY = config("HMAC_SECRET_KEY")
VAPID_PRIVATE_KEY = config("VAPID_PRIVATE_KEY", default="")
VAPID_PUBLIC_KEY = config("VAPID_PUBLIC_KEY", default="")
VAPID_ADMIN_EMAIL = config("VAPID_ADMIN_EMAIL", default="")
BREVO_API_KEY = config("BREVO_API_KEY", default="")
# "brevo" (default), "smtp" (e.g. local Mailpit), or "mock".
# Non-brevo keeps load/chaos tests from spending provider quota.
EMAIL_PROVIDER = config("EMAIL_PROVIDER", default="brevo")
EMAIL_HOST = config("EMAIL_HOST", default="localhost")
EMAIL_PORT = config("EMAIL_PORT", default=25, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=False, cast=bool)
BREVO_SENDER_EMAIL = config("BREVO_SENDER_EMAIL", default="")
BREVO_SENDER_NAME = config("BREVO_SENDER_NAME", default="SysFlow")
TEXTLINK_API_KEY = config("TEXTLINK_API_KEY", default="")
# Real receivers for integration tests / manual verification
BREVO_EMAIL = config("BREVO_EMAIL", default="")
TEXTLINK_DEST = config("TEXTLINK_DEST", default="")