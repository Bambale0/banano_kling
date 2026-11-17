"""Encrypted adapter around atomic owner+fingerprint Astro SQL checkpoints."""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class EncryptedCheckpointStore:
    def __init__(self, store, *, key: bytes | str):
        self.store = store
        self.cipher = Fernet(key)

    def _decrypt(self, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return self.cipher.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Astro checkpoint ciphertext invalid") from exc

    async def read(self, *, owner_id: int, fingerprint: str, section_id: str) -> str | None:
        value = await self.store.read(owner_id=owner_id, fingerprint=fingerprint,
                                      section_id=section_id)
        return self._decrypt(value)

    async def save_if_absent(
        self, *, owner_id: int, fingerprint: str, section_id: str, text: str,
    ) -> str:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Cannot checkpoint an empty report section")
        encoded = self.cipher.encrypt(text.encode("utf-8")).decode("ascii")
        sealed = await self.store.save_if_absent(
            owner_id=owner_id, fingerprint=fingerprint,
            section_id=section_id, text=encoded,
        )
        return self._decrypt(sealed)

    async def delete_owner(self, *, owner_id: int) -> int:
        return await self.store.delete_owner(owner_id=owner_id)

    async def purge_expired(self) -> int:
        return await self.store.purge_expired()
