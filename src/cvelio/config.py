"""User settings and secrets. Settings live in ~/.config/cvelio/config.yaml, never in the repo."""
import functools
import os
import shutil
import subprocess
from pathlib import Path

import yaml

VOICES = ("implied", "first")
GENDERS = ("", "masculine", "feminine", "neutral")
DEFAULT_WATERMARK_FILL = 0.55  # FILL above this is watermarked; override in config.yaml


def home() -> Path:
    return Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config") / "cvelio"


def path() -> Path:
    return home() / "config.yaml"


@functools.cache
def load() -> dict:
    """Read the config and apply its `env` section as defaults for the environment."""
    try:
        data = yaml.safe_load(path().read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    for key, value in (data.get("env") or {}).items():
        os.environ.setdefault(str(key), str(value))
    return data


def save(data: dict) -> None:
    path().parent.mkdir(parents=True, exist_ok=True)
    header = "# Cvelio settings. Written by `make init`; safe to edit by hand.\n"
    path().write_text(header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    load.cache_clear()


def watermark_fill() -> float:
    """The FILL level above which built PDFs get the DRAFT/UNVERIFIED watermark.

    Read from `watermark_fill` in config.yaml, falling back to 0.55, so it can
    be tuned without editing the code.
    """
    try:
        return float(load().get("watermark_fill", DEFAULT_WATERMARK_FILL))
    except (TypeError, ValueError):
        return DEFAULT_WATERMARK_FILL


@functools.cache
def secret(env_name: str, name: str) -> str:
    """Find a secret: the environment first, then AWS Parameter Store if it is configured.

    Parameter Store is read with the caller's own AWS session, one parameter at a time,
    as <prefix>/<name>. `aws_ssm.names` in the config maps a name to a different parameter.
    """
    if os.getenv(env_name):
        return os.environ[env_name].strip()
    ssm = load().get("aws_ssm") or {}
    prefix = os.getenv("CVELIO_SSM_PREFIX") or ssm.get("prefix")
    if not prefix or not shutil.which("aws"):
        return ""
    command = ["aws", "ssm", "get-parameter", "--with-decryption", "--no-cli-pager", "--output", "text",
               "--query", "Parameter.Value", "--name", prefix.rstrip("/") + "/" + (ssm.get("names") or {}).get(name, name)]
    region = os.getenv("CVELIO_SSM_REGION") or ssm.get("region")
    if region:
        command += ["--region", region]
    run = subprocess.run(command, capture_output=True, text=True)
    return run.stdout.strip() if run.returncode == 0 else ""


def github_token() -> str:
    """A GitHub token from the environment, the secret store, the gh CLI or git's credential helper."""
    token = secret("GITHUB_TOKEN", "github")
    if not token and shutil.which("gh"):
        token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
    if not token and shutil.which("git"):
        run = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                             capture_output=True, text=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        token = next((line[9:] for line in run.stdout.splitlines() if line.startswith("password=")), "")
    return token
