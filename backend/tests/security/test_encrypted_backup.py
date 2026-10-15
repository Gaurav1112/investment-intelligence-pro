"""SEC-83: encrypted backup round-trip; wrong passphrase; tampered ciphertext (one bit flipped) → GCM authentication
failure; no partial restore. All rows are TEST sentinels, not user data."""

import os
import sqlite3
import stat
from pathlib import Path

import pytest

from iip.store import encrypted_backup as eb
from iip.store.db import connect, migrate

PASS = "correct horse battery staple"
SENTINEL = "SENTINEL-sec83-7f3a"
FAST_N = 2**14  # the format records n; tests use the smallest allowed cost to stay quick


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    c = connect(tmp_path / "live.db")
    migrate(c, "2026-10-15T00:00:00+00:00")
    c.execute("INSERT INTO settings(key, value_json) VALUES (?, ?)", ("sec83", f'"{SENTINEL}"'))
    c.commit()
    return c


def _backup(db: sqlite3.Connection, tmp_path: Path, n: int = FAST_N) -> Path:
    return eb.encrypt_backup(db, tmp_path / "b" / "iip.db.enc", PASS, scrypt_n=n)


def test_sec83_round_trip_restores_identical_data(db: sqlite3.Connection, tmp_path: Path) -> None:
    enc = _backup(db, tmp_path)
    assert stat.S_IMODE(enc.stat().st_mode) == 0o600
    raw = enc.read_bytes()
    assert raw.startswith(eb.MAGIC)
    assert SENTINEL.encode() not in raw and b"SQLite format 3" not in raw  # no plaintext in the file
    assert PASS.encode() not in raw
    out = eb.restore_encrypted(enc, tmp_path / "restored.db", PASS)
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    r = sqlite3.connect(out)
    assert r.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert r.execute("SELECT value_json FROM settings WHERE key='sec83'").fetchone()[0] == f'"{SENTINEL}"'
    r.close()


def test_sec83_default_kdf_cost_is_the_threat_model_value(db: sqlite3.Connection, tmp_path: Path) -> None:
    enc = _backup(db, tmp_path, n=eb.SCRYPT_N)
    h, _, _ = eb._parse(enc.read_bytes())
    assert (h.n, h.r, h.p) == (2**17, 8, 1) and len(h.salt) == 16 and len(h.nonce) == 12
    assert eb.restore_encrypted(enc, tmp_path / "r.db", PASS).exists()


def test_sec83_wrong_passphrase_fails_cleanly_and_restores_nothing(db: sqlite3.Connection, tmp_path: Path) -> None:
    enc = _backup(db, tmp_path)
    dest = tmp_path / "restored.db"
    with pytest.raises(eb.BackupDecryptError, match="authentication failed"):
        eb.restore_encrypted(enc, dest, "wrong horse battery staple")
    assert not dest.exists()
    assert not list(tmp_path.glob("restored.db*"))  # not even a .partial file


@pytest.mark.parametrize("where", ["ciphertext", "tag", "header"])
def test_sec83_one_flipped_bit_fails_authentication_with_no_partial_restore(
    db: sqlite3.Connection, tmp_path: Path, where: str
) -> None:
    enc = _backup(db, tmp_path)
    blob = bytearray(enc.read_bytes())
    _, prefix, _ = eb._parse(bytes(blob))
    pos = {"ciphertext": len(prefix) + 100, "tag": len(blob) - 1, "header": prefix.index(b'"nonce"') - 3}[where]
    blob[pos] ^= 0x01
    bad = tmp_path / "tampered.enc"
    bad.write_bytes(bytes(blob))
    dest = tmp_path / "restored.db"
    with pytest.raises(eb.BackupDecryptError):
        eb.restore_encrypted(bad, dest, PASS)
    assert not dest.exists() and not list(tmp_path.glob("restored.db*"))


def test_sec83_truncated_or_foreign_files_are_rejected(db: sqlite3.Connection, tmp_path: Path) -> None:
    enc = _backup(db, tmp_path)
    blob = enc.read_bytes()
    for i, data in enumerate([blob[:20], b"SQLite format 3\x00" + b"\x00" * 100, blob[:-16]]):
        p = tmp_path / f"bad{i}.enc"
        p.write_bytes(data)
        with pytest.raises(eb.BackupDecryptError):
            eb.restore_encrypted(p, tmp_path / f"out{i}.db", PASS)
        assert not (tmp_path / f"out{i}.db").exists()


def test_sec83_never_overwrites_an_existing_destination(db: sqlite3.Connection, tmp_path: Path) -> None:
    enc = _backup(db, tmp_path)
    dest = tmp_path / "existing.db"
    dest.write_bytes(b"keep me")
    with pytest.raises(FileExistsError):
        eb.restore_encrypted(enc, dest, PASS)
    assert dest.read_bytes() == b"keep me"


def test_sec83_short_passphrase_and_absurd_kdf_cost_refused(db: sqlite3.Connection, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        eb.encrypt_backup(db, tmp_path / "x.enc", "short", scrypt_n=FAST_N)
    with pytest.raises(ValueError):
        eb.encrypt_backup(db, tmp_path / "x.enc", PASS, scrypt_n=2**30)
    assert not (tmp_path / "x.enc").exists()


def test_sec83_cli_round_trip_with_env_passphrase(
    db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What `make backup-encrypted` / `make restore-encrypted` run (passphrase from IIP_BACKUP_PASSPHRASE)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    live = connect(data_dir / "iip.db")
    db.backup(live)
    live.close()
    monkeypatch.setenv("IIP_BACKUP_PASSPHRASE", PASS)
    monkeypatch.setattr(eb, "SCRYPT_N", FAST_N)
    monkeypatch.setattr(eb.encrypt_backup, "__defaults__", None)
    monkeypatch.setattr(eb.encrypt_backup, "__kwdefaults__", {"scrypt_n": FAST_N})
    assert eb.main(["backup", "--data-dir", str(data_dir)]) == 0
    assert len(list((data_dir / "backups").glob("iip-*.db.enc"))) == 1
    assert stat.S_IMODE(os.stat(data_dir / "backups").st_mode) == 0o700
    dest = tmp_path / "cli-restored.db"
    assert eb.main(["restore", "--data-dir", str(data_dir), "--dest", str(dest)]) == 0
    assert sqlite3.connect(dest).execute("SELECT COUNT(*) FROM settings WHERE key='sec83'").fetchone()[0] == 1
    monkeypatch.setenv("IIP_BACKUP_PASSPHRASE", "wrong passphrase entirely")
    assert eb.main(["restore", "--data-dir", str(data_dir), "--dest", str(tmp_path / "nope.db")]) == 1
    assert not (tmp_path / "nope.db").exists()
