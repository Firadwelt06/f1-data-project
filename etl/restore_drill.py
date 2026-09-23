"""
restore_drill.py

Restore drill: verify integrity BEFORE decrypting, then restore into a
throwaway test schema (never the real f1_staging schema) to prove the
whole encrypted backup pipeline actually works end to end.

USAGE:
    python etl/restore_drill.py [path_to_enc_file] [target_db_name]

    path_to_enc_file  optional, defaults to the newest .enc file in backups/
    target_db_name    optional, defaults to 'f1_staging_restore_test'

WHY VERIFY-THEN-DECRYPT:
The HMAC tag is checked against (IV + ciphertext) BEFORE any attempt to
decrypt. This is the entire point of encrypt-then-MAC: a corrupted or
tampered file is rejected outright. We never try to interpret altered
bytes as valid ciphertext, which (with CBC + padding) can otherwise leak
information through padding-error side channels.

SAFETY NOTE:
This script runs DROP DATABASE IF EXISTS on the TARGET database before
recreating it, so the drill can be rerun repeatedly without manual
cleanup. The target is hardcoded to default to a throwaway name distinct
from the real schema -- pass a target_db_name explicitly if you want a
different throwaway name, but never point this at f1_staging.
"""

import base64
import gzip
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import keyring
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, hmac, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
MYSQL_PATH = os.getenv("MYSQL_PATH", "mysql")

SERVICE_NAME = "f1_dba_project"
AES_KEY_NAME = "aes_key"
HMAC_KEY_NAME = "hmac_key"

BACKUP_DIR = PROJECT_ROOT / "backups"
DEFAULT_TARGET_DB = "f1_staging_restore_test"

HMAC_TAG_SIZE = 32
IV_SIZE = 16


class BackupIntegrityError(RuntimeError):
    """Raised specifically when a backup file fails integrity verification
    (too small / truncated, or HMAC mismatch). Distinct from other
    RuntimeErrors (e.g. missing keys) so callers can decide to fall back
    to an older backup only for THIS category of failure."""


def load_keys() -> tuple[bytes, bytes]:
    aes_key_b64 = keyring.get_password(SERVICE_NAME, AES_KEY_NAME)
    hmac_key_b64 = keyring.get_password(SERVICE_NAME, HMAC_KEY_NAME)
    if not aes_key_b64 or not hmac_key_b64:
        raise RuntimeError("Encryption keys not found. Run generate_keys.py first.")
    return base64.b64decode(aes_key_b64), base64.b64decode(hmac_key_b64)


def list_backups_newest_first() -> list[Path]:
    candidates = sorted(BACKUP_DIR.glob("*.sql.gz.enc"), reverse=True)
    if not candidates:
        raise RuntimeError(f"No .sql.gz.enc backups found in {BACKUP_DIR}")
    return candidates


def verify_and_decrypt(blob: bytes, aes_key: bytes, hmac_key: bytes) -> bytes:
    if len(blob) < IV_SIZE + HMAC_TAG_SIZE:
        raise BackupIntegrityError("Backup file too small to be valid -- likely corrupted.")

    iv = blob[:IV_SIZE]
    ciphertext = blob[IV_SIZE:-HMAC_TAG_SIZE]
    tag = blob[-HMAC_TAG_SIZE:]

    # STEP 1: verify integrity BEFORE touching the ciphertext with AES.
    verifier = hmac.HMAC(hmac_key, hashes.SHA256(), backend=default_backend())
    verifier.update(iv + ciphertext)
    try:
        verifier.verify(tag)  # constant-time comparison, raises on mismatch
    except InvalidSignature:
        raise BackupIntegrityError(
            "HMAC verification FAILED. This backup file is corrupted or has "
            "been tampered with. Refusing to decrypt."
        )
    print("    HMAC verified OK -- file integrity confirmed.")

    # STEP 2: only now do we attempt decryption.
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded_data = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    return unpadder.update(padded_data) + unpadder.finalize()


def _write_defaults_file() -> Path:
    defaults_content = (
        "[client]\n"
        f'user="{DB_USER}"\n'
        f'password="{DB_PASSWORD}"\n'
        f'host="{DB_HOST}"\n'
        f"port={DB_PORT}\n"
    )
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".cnf", delete=False)
    tmp.write(defaults_content)
    tmp.close()
    return Path(tmp.name)


def create_target_database(target_db: str) -> None:
    tmp_path = _write_defaults_file()
    try:
        create_stmt = f"DROP DATABASE IF EXISTS `{target_db}`; CREATE DATABASE `{target_db}`;"
        result = subprocess.run(
            [MYSQL_PATH, f"--defaults-extra-file={tmp_path}", "-e", create_stmt],
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to (re)create target database: {result.stderr.decode(errors='replace')}"
            )
    finally:
        tmp_path.unlink(missing_ok=True)


def load_sql_into_db(sql_path: Path, target_db: str) -> None:
    tmp_path = _write_defaults_file()
    try:
        with open(sql_path, "rb") as sql_file:
            result = subprocess.run(
                [MYSQL_PATH, f"--defaults-extra-file={tmp_path}", target_db],
                stdin=sql_file,
                stderr=subprocess.PIPE,
            )
        if result.returncode != 0:
            raise RuntimeError(f"Restore failed: {result.stderr.decode(errors='replace')}")
    finally:
        tmp_path.unlink(missing_ok=True)


def main() -> None:
    if not all([DB_HOST, DB_USER, DB_PASSWORD]):
        raise RuntimeError("Missing required .env variables (DB_HOST, DB_USER, DB_PASSWORD).")

    args = sys.argv[1:]
    explicit_path = Path(args[0]) if len(args) >= 1 else None
    target_db = args[1] if len(args) >= 2 else DEFAULT_TARGET_DB

    # Explicit path = strict mode: no fallback. If you asked for THIS file,
    # substituting a different one silently would be worse than just failing.
    if explicit_path:
        candidates = [explicit_path]
        fallback_allowed = False
    else:
        candidates = list_backups_newest_first()
        fallback_allowed = True

    print(f"Target (throwaway) database: {target_db}")
    print()

    aes_key, hmac_key = load_keys()

    compressed_data = None
    used_backup = None
    skipped = []

    for i, candidate in enumerate(candidates):
        label = "requested backup" if not fallback_allowed else ("latest backup" if i == 0 else f"fallback #{i}")
        print(f"[Attempt] {label}: {candidate.name}")

        blob = candidate.read_bytes()
        try:
            compressed_data = verify_and_decrypt(blob, aes_key, hmac_key)
            used_backup = candidate
            break
        except BackupIntegrityError as e:
            print(f"  FAILED integrity check: {e}")
            skipped.append(candidate.name)
            if not fallback_allowed:
                raise
            print("  Falling back to next older backup...")
            continue

    if compressed_data is None:
        raise RuntimeError(
            f"All {len(candidates)} backup(s) failed integrity verification: "
            f"{', '.join(skipped)}. No usable backup found."
        )

    if skipped:
        print()
        print(
            f"*** NOTE: restored from '{used_backup.name}', NOT the most recent backup. "
            f"{len(skipped)} newer backup(s) failed integrity check and were skipped: "
            f"{', '.join(skipped)}. Investigate why those files are corrupted. ***"
        )

    print()
    print("[3/4] Decompressing and loading into MySQL...")
    tmp_sql = tempfile.NamedTemporaryFile(suffix=".sql", delete=False)
    tmp_sql_path = Path(tmp_sql.name)
    tmp_sql.close()

    try:
        with open(tmp_sql_path, "wb") as f:
            f.write(gzip.decompress(compressed_data))

        create_target_database(target_db)
        load_sql_into_db(tmp_sql_path, target_db)
    finally:
        tmp_sql_path.unlink(missing_ok=True)

    print(f"[4/4] Done. Restored '{used_backup.name}' into database: {target_db}")
    print()
    print("Next: compare row counts between f1_staging and the restored database.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(f"Restore drill failed: {e}", file=sys.stderr)
        sys.exit(1)