"""Optional encrypted backups (threat-model C-12, SEC-83): AES-256-GCM, key derived by scrypt from a passphrase.

File format (version 1)::

    MAGIC (8 bytes, b"IIPENC01") | header length (4 bytes, big-endian) | header (UTF-8 JSON) | ciphertext + GCM tag

The header records the cipher, the KDF and its parameters (n, r, p), the 16-byte salt and the 12-byte nonce. The whole
prefix (magic, length and header) is the GCM associated data, so changing any header byte fails authentication too.

* The plaintext database never touches the disk: the online backup API copies into an in-memory database, which is
  integrity-checked and serialised, then encrypted.
* Restore decrypts and verifies everything in memory first (GCM tag, then SQLite ``integrity_check``). Only then is a
  temporary file written next to the destination and atomically renamed into place, so a wrong passphrase or a
  tampered file leaves the destination untouched (no partial restore). The destination must not already exist.
* The passphrase is never stored, logged or written into the file. Files are created 0600.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import getpass
import json
import os
import sqlite3
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from iip.store.db import connect

MAGIC = b"IIPENC01"
FORMAT_VERSION = 1
SCRYPT_N = 2**17  # threat-model C-12: n = 2^17, r = 8, p = 1
SCRYPT_R = 8
SCRYPT_P = 1
_ALLOWED_N = frozenset(2**k for k in range(14, 21))  # a crafted header cannot demand an absurd KDF cost
MIN_PASSPHRASE_CHARS = 12
_MAX_HEADER = 4096


class BackupDecryptError(Exception):
    """Wrong passphrase, tampered or truncated file, or not an IIP encrypted backup. Nothing was restored."""


@dataclass(frozen=True)
class _Header:
    n: int
    r: int
    p: int
    salt: bytes
    nonce: bytes

    def encode(self) -> bytes:
        return json.dumps(
            {
                "v": FORMAT_VERSION,
                "cipher": "AES-256-GCM",
                "kdf": "scrypt",
                "n": self.n,
                "r": self.r,
                "p": self.p,
                "salt": base64.b64encode(self.salt).decode(),
                "nonce": base64.b64encode(self.nonce).decode(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()


def _key(passphrase: str, h: _Header) -> bytes:
    return Scrypt(salt=h.salt, length=32, n=h.n, r=h.r, p=h.p).derive(passphrase.encode("utf-8"))


def _write_private(path: Path, data: bytes) -> None:
    """Write via a 0600 temporary file in the same directory, then rename atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".partial")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.chmod(path, 0o600)


def _snapshot(conn: sqlite3.Connection) -> bytes:
    mem = sqlite3.connect(":memory:")
    try:
        conn.backup(mem)
        if mem.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("backup failed integrity_check")
        image = bytearray(mem.serialize())
    finally:
        mem.close()
    # The live DB runs in WAL mode and the copy keeps its header's file-format bytes (18/19 = 2, "WAL"). An image in
    # WAL format cannot be deserialised or opened without its -wal file, so store it as a rollback-journal database
    # (bytes = 1). The content is unchanged; the app switches the restored file back to WAL when it opens it.
    if image[18:20] == b"\x02\x02":
        image[18:20] = b"\x01\x01"
    return bytes(image)


def encrypt_backup(conn: sqlite3.Connection, dest: Path, passphrase: str, *, scrypt_n: int = SCRYPT_N) -> Path:
    """Verified online backup of ``conn``, encrypted to ``dest`` (0600)."""
    if len(passphrase) < MIN_PASSPHRASE_CHARS:
        raise ValueError(f"passphrase must be at least {MIN_PASSPHRASE_CHARS} characters")
    if scrypt_n not in _ALLOWED_N:
        raise ValueError("scrypt n must be a power of two between 2^14 and 2^20")
    h = _Header(n=scrypt_n, r=SCRYPT_R, p=SCRYPT_P, salt=os.urandom(16), nonce=os.urandom(12))
    header = h.encode()
    prefix = MAGIC + struct.pack(">I", len(header)) + header
    ciphertext = AESGCM(_key(passphrase, h)).encrypt(h.nonce, _snapshot(conn), prefix)
    _write_private(dest, prefix + ciphertext)
    return dest


def _parse(blob: bytes) -> tuple[_Header, bytes, bytes]:
    if len(blob) < len(MAGIC) + 4 or not blob.startswith(MAGIC):
        raise BackupDecryptError("not an IIP encrypted backup (bad magic)")
    (hlen,) = struct.unpack(">I", blob[len(MAGIC) : len(MAGIC) + 4])
    if hlen > _MAX_HEADER or len(MAGIC) + 4 + hlen > len(blob):
        raise BackupDecryptError("corrupt header")
    start = len(MAGIC) + 4
    try:
        raw = json.loads(blob[start : start + hlen])
        h = _Header(
            n=int(raw["n"]),
            r=int(raw["r"]),
            p=int(raw["p"]),
            salt=base64.b64decode(raw["salt"], validate=True),
            nonce=base64.b64decode(raw["nonce"], validate=True),
        )
        ok = raw["v"] == FORMAT_VERSION and raw["cipher"] == "AES-256-GCM" and raw["kdf"] == "scrypt"
    except (ValueError, KeyError, TypeError) as exc:
        raise BackupDecryptError("corrupt header") from exc
    if not ok or h.n not in _ALLOWED_N or (h.r, h.p) != (SCRYPT_R, SCRYPT_P) or len(h.nonce) != 12 or len(h.salt) < 16:
        raise BackupDecryptError("unsupported header parameters")
    return h, blob[: start + hlen], blob[start + hlen :]


def decrypt_to_bytes(src: Path, passphrase: str) -> bytes:
    """Authenticated decryption of an encrypted backup into the SQLite database image (in memory only)."""
    h, prefix, ciphertext = _parse(src.read_bytes())
    try:
        return AESGCM(_key(passphrase, h)).decrypt(h.nonce, ciphertext, prefix)
    except InvalidTag as exc:
        raise BackupDecryptError("authentication failed: wrong passphrase or the file was modified") from exc


def restore_encrypted(src: Path, dest: Path, passphrase: str) -> Path:
    """Decrypt and verify in memory, then write ``dest`` atomically. ``dest`` must not exist (never overwrites)."""
    if dest.exists():
        raise FileExistsError(f"refusing to overwrite {dest}; choose a new destination")
    image = decrypt_to_bytes(src, passphrase)
    mem = sqlite3.connect(":memory:")
    try:
        try:
            mem.deserialize(image)
            ok = mem.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        except sqlite3.DatabaseError as exc:
            raise BackupDecryptError("decrypted payload is not a valid SQLite database") from exc
        if not ok:
            raise BackupDecryptError("decrypted database fails integrity_check")
        tmp = dest.with_name(dest.name + ".partial")
        tmp.unlink(missing_ok=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(tmp))
        try:
            mem.backup(target)
        finally:
            target.close()
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    finally:
        mem.close()
    return dest


def main(argv: list[str] | None = None) -> int:
    """``python -m iip.store.encrypted_backup backup|restore …`` — used by ``make backup-encrypted`` and
    ``make restore-encrypted``. The passphrase comes from ``IIP_BACKUP_PASSPHRASE`` or an interactive prompt."""
    ap = argparse.ArgumentParser(prog="iip.store.encrypted_backup")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--data-dir", type=Path, required=True)
    r = sub.add_parser("restore")
    r.add_argument("--backup", type=Path, help="encrypted file (default: the newest in <data-dir>/backups)")
    r.add_argument("--data-dir", type=Path, required=True)
    r.add_argument("--dest", type=Path, help="new database file (default: <data-dir>/restored-<UTC time>.db)")
    args = ap.parse_args(argv)

    def passphrase(confirm: bool) -> str:
        env = os.environ.get("IIP_BACKUP_PASSPHRASE")
        if env:
            return env
        first = getpass.getpass("Backup passphrase: ")
        if confirm and getpass.getpass("Repeat passphrase: ") != first:
            raise SystemExit("passphrases differ; nothing written")
        return first

    stamp = f"{dt.datetime.now(dt.UTC):%Y%m%dT%H%M%SZ}"
    try:
        if args.cmd == "backup":
            dest = args.data_dir / "backups" / f"iip-{stamp}.db.enc"
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(dest.parent, 0o700)
            print(encrypt_backup(connect(args.data_dir / "iip.db"), dest, passphrase(confirm=True)))
        else:
            src = args.backup or sorted((args.data_dir / "backups").glob("iip-*.db.enc"))[-1]
            dest = args.dest or args.data_dir / f"restored-{stamp}.db"
            print(f"restore OK: {restore_encrypted(src, dest, passphrase(confirm=False))} (from {src})")
    except (BackupDecryptError, ValueError, FileExistsError, IndexError) as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
