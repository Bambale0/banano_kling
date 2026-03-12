#!/usr/bin/env python3
"""
Тестовый скрипт для проверки логики выбора модели Gemini
"""

import sys
import os

# Добавляем текущую директорию в Python путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.services.gemini_service import GeminiService

def test_model_mapping():
    """Тестируем логику выбора модели"""
    print("=== ТЕСТ ЛОГИКИ ВЫБОРА МОДЕЛИ ===\n")
    
    # Создаем сервис без ключей для тестирования логики
    service = GeminiService(api_key="", nanobanana_key="", openrouter_key="")
    
    print("Доступные модели в сервисе:")
    for key, value in service.MODELS.items():
        print(f"  {key}: {value}")
    
    print("\nТестируем различные варианты входных параметров:\n")
    
    test_cases = [
        "banana_2",
        "Banana_2", 
        "BANANA_2",
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image",
        "gemini-3-pro-image-preview",
        "flash",
        "pro",
        "banana_2_model",
        "test_banana_2",
    ]
    
    for test_model in test_cases:
        print(f"Тест: '{test_model}'")
        
        # Имитируем логику из generate_image метода
        or_model = service.MODELS.get("flash")  # Default to flash
        
        # Use Pro model for explicit 'pro' requests or when 4K is requested
        if "pro" in test_model.lower():
            or_model = service.MODELS.get("pro")  # Use pro model
        
        # Check if the model is specifically "banana_2" and use the correct mapping
        if test_model.lower() == "banana_2" or "banana_2" in test_model.lower():
            or_model = service.MODELS.get("banana_2")
            print(f"  Banana 2 model detected, using: {or_model}")
        else:
            print(f"  Using OpenRouter model mapping: {test_model} -> {or_model}")
        
        print()

if __name__ == "__main__":
    test_model_mapping()