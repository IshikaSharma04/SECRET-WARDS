
import os
import hmac
import hashlib
import base64


def load_secret() -> bytes:
    secret = os.getenv("RAKSHA_SECRET")

    if not secret or not secret.strip():
        raise RuntimeError("RAKSHA_SECRET is missing")

    return secret.encode("utf-8")


def generate_pseudonym(canonical_key: str, secret: bytes) -> str:
    if not isinstance(canonical_key, str) or not canonical_key.strip():
        raise ValueError("Invalid canonical patient key")

    if not isinstance(secret, bytes) or not secret:
        raise ValueError("Invalid secret")

    patient_key = canonical_key.encode("utf-8")
    message = b"RAKSHA:PSEUDONYM:v1:" + patient_key

    digest = hmac.new(secret, message, hashlib.sha256).digest()

    # 16 bytes = 128 bits
    short_digest = digest[:16]

    encoded_id = base64.b32encode(short_digest).decode("ascii")
    encoded_id = encoded_id.rstrip("=")

    return "PAT_" + encoded_id
