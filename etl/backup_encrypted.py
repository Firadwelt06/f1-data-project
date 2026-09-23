"""
backup_encrypted.py

Produces an encrypted, integrity-protected backup of the f1_staging
MySQL schema.

PIPELINE: mysqldump -> gzip compress -> AES-256-CBC encrypt -> HMAC-SHA256 tag

WHY THIS ORDER:
- Compress BEFORE encrypt: encrypted bytes are high-entropy (look random),
  so gzip can't shrink them. Compressing the plaintext dump first gets the
  size reduction; encrypting the already-compressed bytes locks it down.
- Encrypt-then-MAC: the HMAC tag is computed over (IV + ciphertext), not
  the plaintext. On restore, the HMAC is checked FIRST, before any attempt
  to decrypt -- so a tampered/corrupted file is rejected before we ever
  try to make sense of it as ciphertext.

OUTPUT FILE LAYOUT (single binary file):
    [ 16 bytes IV ] [ ciphertext ] [ 32 bytes HMAC-SHA256 tag ]

SECURITY NOTE ON CREDENTIALS:
The DB password is never passed as a mysqldump command-line argument
(that would be visible to anything inspecting the process list, e.g.
`tasklist /v`). Instead we write a temporary --defaults-extra-file
containing the credentials, point mysqldump at it, then delete it
immediately afterward.
"""

import base64
import gzip
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import keyring
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
DB_NAME = os.getenv("DB_NAME")
MYSQLDUMP_PATH = os.getenv("MYSQLDUMP_PATH", "mysqldump")

SERVICE_NAME = "f1_dba_project"
AES_KEY_NAME = "aes_key"
HMAC_KEY_NAME = "hmac_key"

BACKUP_DIR = PROJECT_ROOT / "backups"


def load_keys() -> tuple[bytes, bytes]:
    aes_key_b64 = keyring.get_password(SERVICE_NAME, AES_KEY_NAME)
    hmac_key_b64 = keyring.get_password(SERVICE_NAME, HMAC_KEY_NAME)
    if not aes_key_b64 or not hmac_key_b64:
        raise RuntimeError(
            "Encryption keys not found in Windows Credential Locker. "
            "Run generate_keys.py once before using this script."
        )
    return base64.b64decode(aes_key_b64), base64.b64decode(hmac_key_b64)


def run_mysqldump(output_path: Path) -> None:
    escaped_password = DB_PASSWORD.replace("\\", "\\\\").replace('"', '\\"')
    defaults_content = (
        "[client]\n"
        f"user={DB_USER}\n"
        f'password="{escaped_password}"\n'
        f"host={DB_HOST}\n"
        f"port={DB_PORT}\n"
    )
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".cnf", delete=False)
    tmp.write(defaults_content)
    tmp.close()
    tmp_path = Path(tmp.name)

    try:
        with open(output_path, "wb") as out_file:
            result = subprocess.run(
                [
                    MYSQLDUMP_PATH,
                    f"--defaults-extra-file={tmp_path}",
                    "--single-transaction",
                    DB_NAME,
                ],
                stdout=out_file,
                stderr=subprocess.PIPE,
            )
        if result.returncode != 0:
            raise RuntimeError(f"mysqldump failed: {result.stderr.decode(errors='replace')}")
    finally:
        tmp_path.unlink(missing_ok=True)


def compress_file(src: Path, dst: Path) -> None:
    with open(src, "rb") as f_in, gzip.open(dst, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


def encrypt_then_mac(data: bytes, aes_key: bytes, hmac_key: bytes) -> bytes:
    iv = os.urandom(16)

    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded_data = padder.update(data) + padder.finalize()

    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()

    tag_generator = hmac.HMAC(hmac_key, hashes.SHA256(), backend=default_backend())
    tag_generator.update(iv + ciphertext)
    tag = tag_generator.finalize()

    return iv + ciphertext + tag


def main() -> None:
    if not all([DB_HOST, DB_USER, DB_PASSWORD, DB_NAME]):
        raise RuntimeError(
            "Missing one or more required .env variables "
            "(DB_HOST, DB_USER, DB_PASSWORD, DB_NAME)."
        )

    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    raw_sql_path = BACKUP_DIR / f"_tmp_{timestamp}.sql"
    gz_path = BACKUP_DIR / f"_tmp_{timestamp}.sql.gz"
    final_path = BACKUP_DIR / f"{DB_NAME}_{timestamp}.sql.gz.enc"

    try:
        print(f"[1/4] Running mysqldump for '{DB_NAME}'...")
        run_mysqldump(raw_sql_path)

        print("[2/4] Compressing dump...")
        compress_file(raw_sql_path, gz_path)

        print("[3/4] Encrypting with AES-256-CBC + HMAC-SHA256...")
        aes_key, hmac_key = load_keys()
        with open(gz_path, "rb") as f:
            compressed_data = f.read()
        encrypted_blob = encrypt_then_mac(compressed_data, aes_key, hmac_key)

        with open(final_path, "wb") as f:
            f.write(encrypted_blob)

        size_kb = final_path.stat().st_size / 1024
        print(f"[4/4] Done. Encrypted backup written to: {final_path} ({size_kb:.1f} KB)")

    finally:
        # Plaintext intermediates never persist, success or failure.
        raw_sql_path.unlink(missing_ok=True)
        gz_path.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(f"Backup failed: {e}", file=sys.stderr)
        sys.exit(1)
        