from core.settings.base import *

DEBUG = True
ALLOWED_HOSTS = ["*"]

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgresql://raguser:ragpassword@localhost:5432/ragdb",
    )
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],
]

WHITENOISE_ROOT = BASE_DIR / "staticfiles"

SPECTACULAR_SETTINGS = {
    **SPECTACULAR_SETTINGS,
    "SERVE_INCLUDE_SCHEMA": True,
}

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

LOGGING = {
    **LOGGING,
    "loggers": {
        name: {**cfg, "level": "DEBUG"}
        for name, cfg in LOGGING["loggers"].items()
    },
}