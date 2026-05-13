# core/settings/local.py
from core.settings.base import *

DEBUG = True
ALLOWED_HOSTS = ["*"]

# BrowsableAPI only in local
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] += [
    "rest_framework.renderers.BrowsableAPIRenderer",
]

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgresql://raguser:ragpassword@localhost:5432/ragdb",
    )
}

# Louder logging locally
for logger in LOGGING["loggers"].values():
    logger["level"] = "DEBUG"