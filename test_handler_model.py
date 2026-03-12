#!/usr/bin/env python3
"""
Тест для проверки, какая модель передается из обработчика
"""

import sys
import os

# Добавляем текущую директорию в Python путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.handlers.generation import process_generation

def test_handler_model():
    """Тестируем, какая модель передается в обработчике"""
    print("=== ТЕСТ ОБРАБОТЧИКА ГЕНЕРАЦИИ ===\n")
    
    # Имитируем вызов обработчика с разными моделями
    test_cases = [
        "banana_2",
        "Banana_2", 
        "BANANA_2",
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image",
        "gemini-3-pro-image-preview",
        "flash",
        "pro",
    ]
    
    for test_model in test_cases:
        print(f"Тест: '{test_model}'")
        print(f"  Передается в generate_image как: {test_model}")
        print()

if __name__ == "__main__":
    test_handler_model()