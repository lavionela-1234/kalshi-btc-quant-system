from __future__ import annotations
import base64
import time
from pathlib import Path
from urllib.parse import urlparse
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

class KalshiSigner:
    """RSA-PSS request signer for Kalshi authenticated REST and WebSocket requests."""

    def __init__(self, api_key_id: str, private_key_path: str):
        if not api_key_id or not private_key_path:
            raise ValueError("Kalshi API key ID and private-key path are required.")
        self.api_key_id = api_key_id
        pem = Path(private_key_path).read_bytes()
        self.private_key = serialization.load_pem_private_key(pem, password=None)

    def headers(self, method: str, url_or_path: str) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        parsed = urlparse(url_or_path)
        path = parsed.path if parsed.scheme else url_or_path.split("?")[0]
        message = f"{timestamp}{method.upper()}{path}".encode()
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
        }
