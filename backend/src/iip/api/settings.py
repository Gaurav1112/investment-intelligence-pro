"""Runtime configuration from environment (threat-model C-01, C-02, C-06). Secrets never appear in repr/logs."""

from __future__ import annotations

import ipaddress
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from iip.llm.config import LLMConfig, LLMConfigError, validate_config
from iip.llm.config import from_env as llm_from_env


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
    llm: LLMConfig = field(default_factory=LLMConfig)  # IIP_LLM=off|local|cloud (ADR-0007); off by default
    # Hosted mode (ADR-0013). Values come from the platform's encrypted environment, never from a file in the repo.
    deploy: str = "local"  # IIP_DEPLOY=local|vercel
    public_origin: str = ""  # IIP_PUBLIC_ORIGIN, e.g. https://example.vercel.app (exact origin, https only)
    db_url: str = ""  # IIP_DB_URL: libsql://<db>.turso.io (a local file only with IIP_ENV=test)
    db_auth_token: str = field(default="", repr=False)  # IIP_DB_AUTH_TOKEN
    access_token: str = field(default="", repr=False)  # IIP_ACCESS_TOKEN (>= 32 characters)

    @property
    def hosted(self) -> bool:
        return self.deploy == "vercel"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "iip.db"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "secrets" / "access-token"

    @property
    def allowed_hosts(self) -> frozenset[str]:
        if self.hosted:  # exactly the public host (C-02): a Vercel preview or deployment URL is refused
            return frozenset({urlsplit(self.public_origin).netloc.lower()})
        return frozenset({f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"})

    @property
    def allowed_origins(self) -> frozenset[str]:
        if self.hosted:
            return frozenset({self.public_origin})
        return frozenset({f"http://{h}" for h in self.allowed_hosts} | set(self.dev_origins))

    def __repr__(self) -> str:  # never print paths of secrets etc. beyond what is needed
        return (
            f"Settings(env={self.env!r}, deploy={self.deploy!r}, host={self.host!r}, port={self.port},"
            f" auth={self.auth})"
        )


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


MIN_HOSTED_TOKEN_CHARS = 32


def _validate_hosted(settings: Settings) -> None:
    """ADR-0013: single user, token-gated, HTTPS origin, remote database. Anything weaker refuses startup."""
    if settings.env not in {"prod", "test"}:
        raise StartupRefused("Hosted mode runs with IIP_ENV=prod (fixtures and API docs are local-only)")
    if not settings.auth:
        raise StartupRefused("Hosted mode requires the access token (IIP_AUTH=off is refused)")
    parts = urlsplit(settings.public_origin)
    bare = parts.path == "" and not parts.query and not parts.fragment and "@" not in parts.netloc
    if parts.scheme != "https" or not parts.netloc or not bare:
        raise StartupRefused("IIP_PUBLIC_ORIGIN must be a bare https origin such as https://<name>.vercel.app")
    if len(settings.access_token) < MIN_HOSTED_TOKEN_CHARS:
        raise StartupRefused(f"IIP_ACCESS_TOKEN must be at least {MIN_HOSTED_TOKEN_CHARS} characters")
    url = settings.db_url
    if url.startswith(("libsql://", "https://")):
        if not settings.db_auth_token:
            raise StartupRefused("IIP_DB_AUTH_TOKEN is required for a remote database")
    elif not (settings.env == "test" and url and not url.startswith(("http://", "ws://", "wss://"))):
        raise StartupRefused("IIP_DB_URL must be a libsql:// or https:// database URL")
    if settings.llm.mode == "local":
        raise StartupRefused("IIP_LLM=local is not available when hosted (no model server runs beside the app)")
    if settings.dev_origins:
        raise StartupRefused("IIP_DEV_ORIGINS is not permitted when hosted")


def validate(settings: Settings) -> Settings:
    if settings.env not in {"prod", "dev", "test"}:
        raise StartupRefused(f"IIP_ENV must be prod, dev or test (got {settings.env!r})")
    if settings.deploy not in {"local", "vercel"}:
        raise StartupRefused(f"IIP_DEPLOY must be local or vercel (got {settings.deploy!r})")
    if not settings.auth and settings.env != "test":
        raise StartupRefused("IIP_AUTH=off is only permitted with IIP_ENV=test")
    if settings.hosted:
        _validate_hosted(settings)
        try:
            validate_config(settings.llm)
        except LLMConfigError as exc:
            raise StartupRefused(f"LLM configuration refused: {exc}") from exc
        return settings
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
    try:  # SEC-75: a "local" LLM endpoint that is not loopback, or a cloud URL off the allowlist, refuses startup
        validate_config(settings.llm)
    except LLMConfigError as exc:
        raise StartupRefused(f"LLM configuration refused: {exc}") from exc
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
            llm=llm_from_env(env),
            deploy=env.get("IIP_DEPLOY", "local"),
            public_origin=env.get("IIP_PUBLIC_ORIGIN", ""),
            # The Vercel Turso integration injects TURSO_* (marked sensitive, so they cannot be copied); accept them.
            db_url=env.get("IIP_DB_URL") or env.get("TURSO_DATABASE_URL", ""),
            db_auth_token=env.get("IIP_DB_AUTH_TOKEN") or env.get("TURSO_AUTH_TOKEN", ""),
            access_token=env.get("IIP_ACCESS_TOKEN", ""),
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
