"""Runtime configuration from environment (threat-model C-01, C-02, C-06). Secrets never appear in repr/logs."""

from __future__ import annotations

import ipaddress
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


class StartupRefused(SystemExit):
    """Raised (exit code 2) when configuration violates a security invariant."""

    def __init__(self, message: str) -> None:
        super().__init__(2)
        self.message = message

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class Settings:
    env: str = "prod"  # prod | dev | test
    host: str = "127.0.0.1"
    port: int = 8741
    data_dir: Path = field(default_factory=lambda: Path.home() / ".iip")
    auth: bool = True
    allow_non_loopback: bool = False
    dev_origins: tuple[str, ...] = ()
    max_body_bytes: int = 5 * 1024 * 1024
    llm_enabled: bool = False

    @property
    def db_path(self) -> Path:
        return self.data_dir / "iip.db"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "secrets" / "access-token"

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return frozenset({f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"})

    @property
    def allowed_origins(self) -> frozenset[str]:
        return frozenset({f"http://{h}" for h in self.allowed_hosts} | set(self.dev_origins))

    def __repr__(self) -> str:  # never print paths of secrets etc. beyond what is needed
        return f"Settings(env={self.env!r}, host={self.host!r}, port={self.port}, auth={self.auth})"


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def validate(settings: Settings) -> Settings:
    if settings.env not in {"prod", "dev", "test"}:
        raise StartupRefused(f"IIP_ENV must be prod, dev or test (got {settings.env!r})")
    if not settings.auth and settings.env != "test":
        raise StartupRefused("IIP_AUTH=off is only permitted with IIP_ENV=test")
    if not _is_loopback(settings.host):
        if not settings.allow_non_loopback:
            raise StartupRefused(
                f"Refusing to bind to non-loopback address {settings.host!r}. This app holds private financial data; "
                "set IIP_ALLOW_NON_LOOPBACK=1 only if you understand the exposure."
            )
        if not settings.auth:
            raise StartupRefused("Non-loopback binding requires the access token to be enabled")
    if settings.dev_origins and settings.env != "dev":
        raise StartupRefused("IIP_DEV_ORIGINS is only permitted with IIP_ENV=dev")
    return settings


def from_env(environ: dict[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    dev_origins = tuple(o.strip() for o in env.get("IIP_DEV_ORIGINS", "").split(",") if o.strip())
    return validate(
        Settings(
            env=env.get("IIP_ENV", "prod"),
            host=env.get("IIP_HOST", "127.0.0.1"),
            port=int(env.get("IIP_PORT", "8741")),
            data_dir=Path(env.get("IIP_DATA_DIR", str(Path.home() / ".iip"))),
            auth=env.get("IIP_AUTH", "on") != "off",
            allow_non_loopback=env.get("IIP_ALLOW_NON_LOOPBACK", "") == "1",
            dev_origins=dev_origins,
            llm_enabled=env.get("IIP_LLM", "off") == "on",
        )
    )


def ensure_access_token(settings: Settings) -> str:
    """Create the 256-bit access token on first run (mode 0600) and return it."""
    path = settings.token_path
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_urlsafe(32))
    os.chmod(path, 0o600)
    return path.read_text().strip()
