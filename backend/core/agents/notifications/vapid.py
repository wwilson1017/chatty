"""VAPID key management for Web Push notifications."""

import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
_VAPID_FILE = _DATA_DIR / "vapid_keys.json"
_keys: dict | None = None


def _load_or_generate() -> dict:
    global _keys
    if _keys is not None:
        return _keys

    if _VAPID_FILE.exists():
        try:
            _keys = json.loads(_VAPID_FILE.read_text(encoding="utf-8"))
            return _keys
        except Exception:
            logger.warning("Failed to read VAPID keys, regenerating")

    from py_vapid import Vapid

    vapid = Vapid()
    vapid.generate_keys()
    raw_priv = vapid.private_pem()
    raw_pub = vapid.public_key

    import base64
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    pub_bytes = vapid._private_key.public_key().public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint
    )
    pub_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode()

    priv_bytes = vapid._private_key.private_numbers().private_value.to_bytes(32, "big")
    priv_b64 = base64.urlsafe_b64encode(priv_bytes).rstrip(b"=").decode()

    _keys = {"public_key": pub_b64, "private_key": priv_b64}

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(_DATA_DIR), suffix=".json")
    try:
        os.write(fd, json.dumps(_keys, indent=2).encode())
        os.close(fd)
        os.replace(tmp_path, str(_VAPID_FILE))
    except Exception:
        os.close(fd) if not os.get_inheritable(fd) else None
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    logger.info("Generated VAPID keys at %s", _VAPID_FILE)
    return _keys


def get_vapid_public_key() -> str:
    return _load_or_generate()["public_key"]


def get_vapid_private_key() -> str:
    return _load_or_generate()["private_key"]


def get_vapid_claims() -> dict:
    subject = os.environ.get("VAPID_SUBJECT", "mailto:notifications@chatty.local")
    return {"sub": subject}
