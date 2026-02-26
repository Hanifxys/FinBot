import os
import logging
from typing import Optional

class EncryptionManager:
    def __init__(self, key_env_var: str = "ENCRYPTION_KEY"):
        self.key = os.getenv(key_env_var, "")
        self._fernet = None
        if self.key:
            try:
                from cryptography.fernet import Fernet
                # If key looks like a raw secret, derive a Fernet key deterministically (SHA256 -> base64)
                if len(self.key) != 44:  # not a Fernet key
                    import base64, hashlib
                    digest = hashlib.sha256(self.key.encode()).digest()
                    self.key = base64.urlsafe_b64encode(digest)
                self._fernet = Fernet(self.key)
            except Exception as e:
                logging.error(f"Encryption init failed: {e}. Falling back to plaintext.")
                self._fernet = None

    def encrypt(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        if self._fernet is None:
            return text
        try:
            return self._fernet.encrypt(text.encode()).decode()
        except Exception:
            return text

    def decrypt(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        if self._fernet is None:
            return text
        try:
            return self._fernet.decrypt(text.encode()).decode()
        except Exception:
            return text
