from dataclasses import dataclass
from typing import Protocol


@dataclass
class DeliveryQuote:
    provider: str
    price_rub: float
    eta_text: str
    raw: dict


class DeliveryProvider(Protocol):
    async def quote(
        self, *, city: str, address: str, weight_grams: int
    ) -> DeliveryQuote: ...

    async def create_order(self, *, shop_order: dict) -> dict: ...


class ManualDeliveryService:
    """Temporary delivery adapter until DPD and Yandex APIs are connected."""

    provider = "manual"

    async def quote(
        self, *, city: str, address: str, weight_grams: int
    ) -> DeliveryQuote:
        return DeliveryQuote(
            provider=self.provider,
            price_rub=0,
            eta_text="Стоимость и сроки согласуем с поддержкой",
            raw={},
        )

    async def create_order(self, *, shop_order: dict) -> dict:
        return {"provider": self.provider, "status": "pending_manual"}


manual_delivery_service = ManualDeliveryService()
