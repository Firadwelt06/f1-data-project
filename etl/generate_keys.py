"""
generate_keys.py

One-time setup script. Generates two independent 32-byte keys
(one for AES-256 encryption, one for HMAC-SHA256 authentication)
and stores them in Windows Credential Locker via `keyring`.

WHY TWO SEPARATE KEYS:
Reusing the same key for both encryption and authentication is a
known cryptographic anti-pattern -- it can leak information between
the two operations. Using independent keys keeps them cryptographically
isolated from each other.

Run this ONCE. Re-running it will refuse to overwrite existing keys
(rotating keys makes existing backups unreadable unless you keep the
old keys around too, so this is a deliberate safety guard, not a bug).
"""

import base64
import os

import keyring

SERVICE_NAME = "f1_dba_project"
AES_KEY_NAME = "aes_key"
HMAC_KEY_NAME = "hmac_key"


def generate_and_store():
    existing_aes = keyring.get_password(SERVICE_NAME, AES_KEY_NAME)
    existing_hmac = keyring.get_password(SERVICE_NAME, HMAC_KEY_NAME)

    if existing_aes or existing_hmac:
        print(
            "Keys already exist in Windows Credential Locker under "
            f"service '{SERVICE_NAME}'. Refusing to overwrite.\n\n"
            "If you really want to rotate keys: back up your existing "
            "backups' readability by keeping a copy of the old keys "
            "somewhere safe first (e.g. Credential Manager export), "
            "delete the stored entries, then rerun this script.\n"
            "WARNING: rotating keys makes all backups encrypted under "
            "the old keys unreadable unless you retain those old keys."
        )
        return

    aes_key = os.urandom(32)   # 256-bit key for AES-256
    hmac_key = os.urandom(32)  # separate 256-bit key for HMAC-SHA256

    keyring.set_password(SERVICE_NAME, AES_KEY_NAME, base64.b64encode(aes_key).decode())
    keyring.set_password(SERVICE_NAME, HMAC_KEY_NAME, base64.b64encode(hmac_key).decode())

    print(f"Generated and stored AES-256 key and HMAC-SHA256 key under service '{SERVICE_NAME}'.")
    print("These live in Windows Credential Locker (Control Panel > Credential Manager),")
    print("not in any project file, .env, or anything that could end up in version control.")


if __name__ == "__main__":
    generate_and_store()
