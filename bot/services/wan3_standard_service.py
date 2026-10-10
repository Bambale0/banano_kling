"""Standard KIE Wan 3.0 adapter; the documented input contract matches Prime.

Provider identity and the retail tariff key remain distinct. Shared reference,
hidden edit-prompt and payload validation preserve the complete 14-field input.
"""
from bot.config import config
from bot.services.wan3_prime_service import Wan3PrimeService


class Wan3StandardService(Wan3PrimeService):
    MODEL_NAME = "wan/3-0-video"
    INTERNAL_MODEL_KEY = "wan_3"


wan3_standard_service = Wan3StandardService(kie_key=config.KIE_AI_API_KEY)
