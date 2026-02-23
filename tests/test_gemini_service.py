"""Тесты для gemini_service.py"""
import pytest
import asyncio
import base64
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from io import BytesIO


class TestGeminiServiceInit:
    """Тесты инициализации сервиса"""

    def test_service_initialization(self):
        """Тест: инициализация сервиса"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_api_key",
            nanobanana_key="test_nanobanana_key",
            openrouter_key="test_openrouter_key"
        )
        
        assert service.api_key == "test_api_key"
        assert service.nanobanana_key == "test_nanobanana_key"
        assert service.openrouter_key == "test_openrouter_key"

    def test_models_config(self):
        """Тест: проверка конфигурации моделей"""
        from bot.services.gemini_service import GeminiService
        
        assert "flash" in GeminiService.MODELS
        assert "pro" in GeminiService.MODELS
        assert "gemini-2.5-flash-image" in GeminiService.MODELS["flash"]
        assert "gemini-3-pro-image-preview" in GeminiService.MODELS["pro"]

    def test_native_models_config(self):
        """Тест: проверка нативных моделей"""
        from bot.services.gemini_service import GeminiService
        
        assert "flash" in GeminiService.NATIVE_MODELS
        assert "pro" in GeminiService.NATIVE_MODELS

    def test_resolutions_config(self):
        """Тест: проверка списка разрешений"""
        from bot.services.gemini_service import GeminiService
        
        assert "1K" in GeminiService.RESOLUTIONS
        assert "2K" in GeminiService.RESOLUTIONS
        assert "4K" in GeminiService.RESOLUTIONS

    def test_aspect_ratios_config(self):
        """Тест: проверка списка форматов"""
        from bot.services.gemini_service import GeminiService
        
        assert "1:1" in GeminiService.ASPECT_RATIOS
        assert "16:9" in GeminiService.ASPECT_RATIOS
        assert "9:16" in GeminiService.ASPECT_RATIOS
        assert "4K" in GeminiService.ASPECT_RATIOS


class TestGenerateImage:
    """Тесты основного метода generate_image"""

    @pytest.mark.asyncio
    async def test_generate_image_text_to_image(self):
        """Тест: текст-в-изображение"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        # Мокаем _generate_via_nanobanana
        with patch.object(service, '_generate_via_nanobanana', new_callable=AsyncMock) as mock_nb:
            # Симулируем base64 изображение
            mock_image = b'\x89PNG\r\n\x1a\n' + b'fake_image_data'
            mock_nb.return_value = mock_image
            
            result = await service.generate_image(
                prompt="A beautiful sunset",
                model="gemini-2.5-flash-image"
            )
            
            assert result == mock_image
            mock_nb.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_image_fallback_to_openrouter(self):
        """Тест: fallback на OpenRouter при ошибке Nano Banana"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key="test_openrouter"
        )
        
        with patch.object(service, '_generate_via_nanobanana', new_callable=AsyncMock) as mock_nb:
            with patch.object(service, '_generate_via_openrouter', new_callable=AsyncMock) as mock_or:
                mock_nb.return_value = None  # Nano Banana failed
                mock_or.return_value = b"openrouter_image_data"
                
                result = await service.generate_image(
                    prompt="A beautiful sunset",
                    model="gemini-2.5-flash-image"
                )
                
                mock_nb.assert_called_once()
                mock_or.assert_called_once()
                assert result == b"openrouter_image_data"

    @pytest.mark.asyncio
    async def test_generate_image_no_keys(self):
        """Тест: генерация без API ключей"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="",
            nanobanana_key="",
            openrouter_key=""
        )
        
        result = await service.generate_image(
            prompt="A beautiful sunset",
            model="gemini-2.5-flash-image"
        )
        
        assert result is None


class TestNanoBananaGeneration:
    """Тесты генерации через Nano Banana API"""

    @pytest.mark.asyncio
    async def test_nanobanana_payload_basic(self):
        """Тест: базовый payload для Nano Banana"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        mock_response = {
            "choices": [{
                "message": {
                    "content": "data:image/png;base64,SGVsbG9Xb3JsZA=="
                }
            }]
        }
        
        with patch.object(service, '_get_session', new_callable=AsyncMock) as mock_session:
            mock_session_instance = AsyncMock()
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            mock_session_instance.post = AsyncMock(return_value=mock_resp)
            mock_session.return_value = mock_session_instance
            
            # Вызываем метод для проверки payload (через generate_image)
            result = await service._generate_via_nanobanana(
                prompt="test prompt",
                model="gemini-2.5-flash-image"
            )
            
            # Проверяем, что post был вызван
            mock_session_instance.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_nanobanana_with_aspect_ratio(self):
        """Тест: Nano Banana с указанием формата"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        with patch.object(service, '_get_session', new_callable=AsyncMock) as mock_session:
            mock_session_instance = AsyncMock()
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={"choices": []})
            mock_session_instance.post = AsyncMock(return_value=mock_resp)
            mock_session.return_value = mock_session_instance
            
            result = await service._generate_via_nanobanana(
                prompt="test",
                aspect_ratio="16:9",
                resolution="2K"
            )
            
            assert mock_session_instance.post.called

    @pytest.mark.asyncio
    async def test_nanobanana_with_search(self):
        """Тест: Nano Banana с поисковым заземлением"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        with patch.object(service, '_get_session', new_callable=AsyncMock) as mock_session:
            mock_session_instance = AsyncMock()
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={"choices": []})
            mock_session_instance.post = AsyncMock(return_value=mock_resp)
            mock_session.return_value = mock_session_instance
            
            result = await service._generate_via_nanobanana(
                prompt="test",
                enable_search=True
            )
            
            assert mock_session_instance.post.called


class TestOpenRouterGeneration:
    """Тесты генерации через OpenRouter API"""

    @pytest.mark.asyncio
    async def test_openrouter_response_parsing(self):
        """Тест: парсинг ответа OpenRouter"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="",
            openrouter_key="test_openrouter"
        )
        
        # Симулируем base64 изображение
        test_image_data = b"fake_image_bytes"
        b64_image = base64.b64encode(test_image_data).decode("utf-8")
        
        mock_response = {
            "choices": [{
                "message": {
                    "images": [f"data:image/png;base64,{b64_image}"],
                    "content": ""
                }
            }]
        }
        
        with patch.object(service, '_get_session', new_callable=AsyncMock) as mock_session:
            mock_session_instance = AsyncMock()
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.text = AsyncMock(return_value='{"choices": [{"message": {"images": ["data:image/png;base64,' + b64_image + '"], "content": ""}}]}')
            mock_session_instance.post = AsyncMock(return_value=mock_resp)
            mock_session.return_value = mock_session_instance
            
            result = await service._generate_via_openrouter(
                prompt="test prompt",
                model="google/gemini-2.5-flash-image"
            )
            
            # Проверяем, что метод был вызван
            assert mock_session_instance.post.called

    @pytest.mark.asyncio
    async def test_openrouter_error_handling(self):
        """Тест: обработка ошибок OpenRouter"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="",
            openrouter_key="test_openrouter"
        )
        
        with patch.object(service, '_get_session', new_callable=AsyncMock) as mock_session:
            mock_session_instance = AsyncMock()
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            
            mock_resp = AsyncMock()
            mock_resp.status = 500  # Server error
            mock_resp.text = AsyncMock(return_value="Internal Server Error")
            mock_session_instance.post = AsyncMock(return_value=mock_resp)
            mock_session.return_value = mock_session_instance
            
            result = await service._generate_via_openrouter(
                prompt="test",
                model="test_model"
            )
            
            assert result is None


class TestImageEditing:
    """Тесты методов редактирования изображений"""

    @pytest.mark.asyncio
    async def test_edit_image(self):
        """Тест: редактирование изображения"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        test_image = b"fake_image_bytes"
        
        with patch.object(service, 'generate_image', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = b"edited_image"
            
            result = await service.edit_image(
                image_bytes=test_image,
                instruction="Add a red hat"
            )
            
            assert result == b"edited_image"
            mock_gen.assert_called_once()
            # Проверяем, что промпт содержит инструкцию
            call_args = mock_gen.call_args
            assert "Add a red hat" in str(call_args)

    @pytest.mark.asyncio
    async def test_add_element(self):
        """Тест: добавление элемента"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        with patch.object(service, 'edit_image', new_callable=AsyncMock) as mock_edit:
            mock_edit.return_value = b"result"
            
            result = await service.add_element(
                image_bytes=b"image",
                element="a red balloon"
            )
            
            assert result == b"result"
            # Проверяем, что вызов содержит правильную инструкцию
            call_args = mock_edit.call_args
            assert "add" in str(call_args).lower()

    @pytest.mark.asyncio
    async def test_remove_element(self):
        """Тест: удаление элемента"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        with patch.object(service, 'edit_image', new_callable=AsyncMock) as mock_edit:
            mock_edit.return_value = b"result"
            
            result = await service.remove_element(
                image_bytes=b"image",
                element="the person"
            )
            
            assert result == b"result"

    @pytest.mark.asyncio
    async def test_style_transfer(self):
        """Тест: передача стиля"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        with patch.object(service, 'edit_image', new_callable=AsyncMock) as mock_edit:
            mock_edit.return_value = b"styled_image"
            
            result = await service.style_transfer(
                image_bytes=b"image",
                style="impressionist"
            )
            
            assert result == b"styled_image"
            call_args = mock_edit.call_args
            assert "impressionist" in str(call_args).lower()

    @pytest.mark.asyncio
    async def test_replace_element(self):
        """Тест: замена элемента"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        with patch.object(service, 'edit_image', new_callable=AsyncMock) as mock_edit:
            mock_edit.return_value = b"result"
            
            result = await service.replace_element(
                image_bytes=b"image",
                old_element="the sky",
                new_element="a sunset"
            )
            
            assert result == b"result"


class TestReferenceImages:
    """Тесты работы с референсными изображениями"""

    @pytest.mark.asyncio
    async def test_generate_with_references(self):
        """Тест: генерация с референсными изображениями"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        ref_images = [b"ref1", b"ref2", b"ref3", b"ref4", b"ref5", b"ref6", b"ref7"]
        person_refs = [b"person1", b"person2", b"person3", b"person4", b"person5", b"person6"]
        
        with patch.object(service, 'generate_image', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = b"result"
            
            result = await service.generate_with_references(
                prompt="Create similar style",
                reference_images=ref_images,
                person_references=person_refs
            )
            
            # Проверяем, что вызов был
            assert mock_gen.called
            
            # Проверяем, что количество референсов ограничено (всего 14)
            call_kwargs = mock_gen.call_args.kwargs
            refs = call_kwargs.get('reference_images', [])
            assert len(refs) <= 14

    @pytest.mark.asyncio
    async def test_reference_limit_6_objects(self):
        """Тест: ограничение 6 объектов"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        # 10 референсов объектов (больше чем лимит 6)
        ref_images = [b"ref" + str(i).encode() for i in range(10)]
        
        with patch.object(service, 'generate_image', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = b"result"
            
            result = await service.generate_with_references(
                prompt="test",
                reference_images=ref_images
            )
            
            # Должно быть ограничено до 6
            call_kwargs = mock_gen.call_args.kwargs
            refs = call_kwargs.get('reference_images', [])
            assert len(refs) <= 6

    @pytest.mark.asyncio
    async def test_reference_limit_5_persons(self):
        """Тест: ограничение 5 персон"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        # 7 персон (больше чем лимит 5)
        person_refs = [b"person" + str(i).encode() for i in range(7)]
        
        with patch.object(service, 'generate_image', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = b"result"
            
            result = await service.generate_with_references(
                prompt="test",
                person_references=person_refs
            )
            
            call_kwargs = mock_gen.call_args.kwargs
            refs = call_kwargs.get('reference_images', [])
            assert len(refs) <= 5


class TestSearchGrounding:
    """Тесты поискового заземления"""

    @pytest.mark.asyncio
    async def test_generate_with_search(self):
        """Тест: генерация с поиском"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        with patch.object(service, 'generate_image', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = b"result"
            
            result = await service.generate_with_search(
                prompt="What is the weather today?",
                model="gemini-3-pro-image-preview",
                aspect_ratio="16:9"
            )
            
            assert result == b"result"
            call_kwargs = mock_gen.call_args.kwargs
            assert call_kwargs.get('enable_search') is True


class TestHighResolution:
    """Тесты генерации высокого разрешения"""

    @pytest.mark.asyncio
    async def test_generate_high_res_4k(self):
        """Тест: генерация 4K"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        with patch.object(service, 'generate_image', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = b"result"
            
            result = await service.generate_high_res(
                prompt="High quality landscape",
                resolution="4K",
                model="gemini-3-pro-image-preview",
                aspect_ratio="16:9"
            )
            
            assert result == b"result"
            call_kwargs = mock_gen.call_args.kwargs
            assert call_kwargs.get('resolution') == "4K"

    @pytest.mark.asyncio
    async def test_generate_high_res_2k(self):
        """Тест: генерация 2K"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        with patch.object(service, 'generate_image', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = b"result"
            
            result = await service.generate_high_res(
                prompt="Test",
                resolution="2K"
            )
            
            call_kwargs = mock_gen.call_args.kwargs
            assert call_kwargs.get('resolution') == "2K"


class TestGenerationStyles:
    """Тесты различных стилей генерации"""

    @pytest.mark.asyncio
    async def test_generate_photorealistic(self):
        """Тест: фотореалистичная генерация"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        with patch.object(service, 'generate_image', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = b"result"
            
            result = await service.generate_photorealistic(
                prompt="a cat"
            )
            
            assert result == b"result"
            # Проверяем, что промпт содержит фотографические термины
            call_args = mock_gen.call_args
            prompt_arg = str(call_args)
            assert "photorealistic" in prompt_arg.lower() or "camera" in prompt_arg.lower()

    @pytest.mark.asyncio
    async def test_generate_sticker(self):
        """Тест: генерация стикера"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        with patch.object(service, 'generate_image', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = b"result"
            
            result = await service.generate_sticker(
                prompt="a star"
            )
            
            call_args = mock_gen.call_args
            prompt_arg = str(call_args)
            assert "sticker" in prompt_arg.lower() or "transparent" in prompt_arg.lower()

    @pytest.mark.asyncio
    async def test_generate_product_photo(self):
        """Тест: генерация фото продукта"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        with patch.object(service, 'generate_image', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = b"result"
            
            result = await service.generate_product_photo(
                product_description="a red sneaker"
            )
            
            call_args = mock_gen.call_args
            prompt_arg = str(call_args)
            assert "product" in prompt_arg.lower() or "studio" in prompt_arg.lower()

    @pytest.mark.asyncio
    async def test_generate_with_text(self):
        """Тест: генерация с текстом"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        with patch.object(service, 'generate_image', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = b"result"
            
            result = await service.generate_with_text(
                text="Hello World",
                style="modern"
            )
            
            call_args = mock_gen.call_args
            prompt_arg = str(call_args)
            assert "Hello World" in prompt_arg

    @pytest.mark.asyncio
    async def test_generate_comic(self):
        """Тест: генерация комикса"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        with patch.object(service, 'generate_image', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = b"result"
            
            result = await service.generate_comic(
                prompt="a superhero flying"
            )
            
            call_args = mock_gen.call_args
            prompt_arg = str(call_args)
            assert "comic" in prompt_arg.lower()

    @pytest.mark.asyncio
    async def test_generate_minimalist(self):
        """Тест: минималистичная генерация"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        with patch.object(service, 'generate_image', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = b"result"
            
            result = await service.generate_minimalist(
                subject="a flower",
                position="center"
            )
            
            call_args = mock_gen.call_args
            prompt_arg = str(call_args)
            assert "minimalist" in prompt_arg.lower()


class TestMultiturnChat:
    """Тесты многоходового редактирования"""

    @pytest.mark.asyncio
    async def test_create_chat(self):
        """Тест: создание чата"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        # Мокаем client
        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_client.chats.create.return_value = mock_chat
        service._client = mock_client
        
        result = await service.create_chat(
            chat_id="test_chat_123",
            model="gemini-3-pro-image-preview"
        )
        
        assert result is True
        assert "test_chat_123" in service._chats

    @pytest.mark.asyncio
    async def test_send_message_to_chat(self):
        """Тест: отправка сообщения в чат"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        # Создаём мок чата
        mock_chat = MagicMock()
        mock_response = MagicMock()
        mock_part = MagicMock()
        mock_part.inline_data = MagicMock()
        mock_part.inline_data.data = b"image_data"
        mock_response.parts = [mock_part]
        mock_chat.send_message_async = AsyncMock(return_value=mock_response)
        
        service._chats["test_chat"] = mock_chat
        
        result = await service.send_message_to_chat(
            chat_id="test_chat",
            message="Make it brighter"
        )
        
        assert result == b"image_data"

    @pytest.mark.asyncio
    async def test_close_chat(self):
        """Тест: закрытие чата"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        service._chats["test_chat"] = MagicMock()
        
        result = await service.close_chat("test_chat")
        
        assert result is True
        assert "test_chat" not in service._chats


class TestServiceSession:
    """Тесты HTTP сессии"""

    @pytest.mark.asyncio
    async def test_get_session(self):
        """Тест: получение HTTP сессии"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        session = await service._get_session()
        
        assert session is not None

    @pytest.mark.asyncio
    async def test_close_session(self):
        """Тест: закрытие сессии"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        session = await service._get_session()
        
        await service.close()
        
        assert session.closed or service._session is None


class TestCompositeImages:
    """Тесты объединения изображений"""

    @pytest.mark.asyncio
    async def test_composite_images(self):
        """Тест: объединение двух изображений"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_key",
            nanobanana_key="test_nanobanana",
            openrouter_key=""
        )
        
        with patch.object(service, 'generate_image', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = b"composite_result"
            
            result = await service.composite_images(
                base_image=b"base",
                overlay_image=b"overlay",
                instruction="Place overlay on top of base"
            )
            
            assert result == b"composite_result"
            mock_gen.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
