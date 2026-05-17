from functools import lru_cache
from pydantic import BaseModel
import os
class Settings(BaseModel):
    database_url: str = os.getenv('DATABASE_URL','sqlite:///./saas.db')
    jwt_secret: str = os.getenv('JWT_SECRET','dev-change-me')
    encryption_key: str = os.getenv('TOKEN_ENCRYPTION_KEY','')
    public_base_url: str = os.getenv('PUBLIC_BASE_URL','http://localhost:8000')
    telegram_api_base: str = os.getenv('TELEGRAM_API_BASE','https://api.telegram.org')
@lru_cache
def get_settings(): return Settings()
