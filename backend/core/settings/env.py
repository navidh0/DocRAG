from __future__ import annotations

import os
import environ
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # → backend/
ROOT_DIR = BASE_DIR.parent                                # → project root

env = environ.Env()

_ENV_LOCAL = ROOT_DIR / ".env.local"
_ENV_FILE = _ENV_LOCAL if _ENV_LOCAL.exists() else ROOT_DIR / ".env"

if _ENV_FILE.exists():
    environ.Env.read_env(_ENV_FILE)
elif "SECRET_KEY" not in os.environ:
    raise RuntimeError(
        f"No .env.local or .env found at {ROOT_DIR} and SECRET_KEY is not in the environment. "
        "Create a .env.local for local dev or inject env vars for Docker/CI."
    )