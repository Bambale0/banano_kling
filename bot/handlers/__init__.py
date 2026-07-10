from .admin import admin_bp as admin_router
from .batch_generation import batch_bp as batch_generation_router
from .common import common_bp as common_router

try:
    # generation.py depends on aiogram/telegram-specific packages which are not
    # required for the VK bot process. Import it lazily and fall back to None
    # if the import fails to avoid pulling aiogram/pydantic into the VK server.
    from .generation import generation_bp as generation_router
except Exception:
    generation_router = None
from .image_analyzer import image_analyzer_bp as image_analyzer_router
from .payments import payments as payments_router
