import asyncio
import io
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from bot.services.gemini_service import gemini_service
from bot.services.preset_manager import preset_manager

logger = logging.getLogger(__name__)


class BatchStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"  # Частично готово
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class BatchItem:
    index: int
    prompt: str
    status: BatchStatus = BatchStatus.PENDING
    result: Optional[bytes] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    @property
    def duration(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None


@dataclass
class BatchJob:
    id: str
    user_id: int
    mode: str  # grid_2x2, batch_6, variations_3
    base_preset_id: str
    base_prompt: str
    total_cost: int
    items: List[BatchItem] = field(default_factory=list)
    status: BatchStatus = BatchStatus.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    progress_callback: Optional[Callable] = None

    @property
    def progress_percent(self) -> int:
        if not self.items:
            return 0
        completed = sum(1 for i in self.items if i.status == BatchStatus.COMPLETED)
        return int(completed / len(self.items) * 100)

    @property
    def is_complete(self) -> bool:
        return all(
            i.status in (BatchStatus.COMPLETED, BatchStatus.FAILED) for i in self.items
        )


class BatchGenerationService:
    """Сервис пакетной генерации изображений Pro-уровня"""

    MAX_CONCURRENT = 3  # Ограничение параллельных запросов к API

    def __init__(self):
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        self._active_jobs: Dict[str, BatchJob] = {}
        self._executor = ThreadPoolExecutor(max_workers=4)

    def _get_batch_config(self, mode: str) -> Optional[Dict]:
        """Получает конфигурацию режима пакетной генерации"""
        try:
            presets_path = Path("data/presets.json")
            with open(presets_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("batch_modes", {}).get(mode)
        except Exception as e:
            logger.error(f"Failed to load batch config: {e}")
            return None

    async def create_batch_job(
        self,
        user_id: int,
        mode: str,
        preset_id: str,
        base_prompt: str,
        custom_params: Optional[Dict] = None,
    ) -> Optional[BatchJob]:
        """Создаёт задачу пакетной генерации"""

        # Получаем конфигурацию режима
        batch_config = self._get_batch_config(mode)
        if not batch_config:
            logger.error(f"Unknown batch mode: {mode}")
            return None

        # Получаем базовый пресет
        preset = preset_manager.get_preset(preset_id)
        if not preset:
            return None

        # Рассчитываем стоимость со скидкой
        total_cost = int(preset.cost * batch_config["cost_multiplier"])

        # Генерируем ID задачи
        job_id = f"batch_{user_id}_{int(time.time())}_{mode}"

        # Создаём элементы
        items = []
        for i in range(batch_config["count"]):
            variation_aspect = self._get_variation_aspect(batch_config, i)

            # Формируем промпт для каждого элемента
            item_prompt = self._format_item_prompt(
                batch_config, base_prompt, i, variation_aspect, custom_params
            )

            items.append(BatchItem(index=i, prompt=item_prompt))

        job = BatchJob(
            id=job_id,
            user_id=user_id,
            mode=mode,
            base_preset_id=preset_id,
            base_prompt=base_prompt,
            total_cost=total_cost,
            items=items,
        )

        self._active_jobs[job_id] = job
        return job

    def _get_variation_aspect(self, config: Dict, index: int) -> str:
        """Определяет аспект вариации для элемента"""
        aspects = config.get("variation_aspects", ["style"])
        return aspects[index % len(aspects)]

    def _format_item_prompt(
        self,
        config: Dict,
        base_prompt: str,
        index: int,
        variation_aspect: str,
        custom_params: Optional[Dict],
    ) -> str:
        """Формирует промпт для конкретного элемента пакета"""

        modifier = config.get("prompt_modifier", "{base_prompt}")

        # Для режима с отдельными стилями
        if config.get("styles_per_variation"):
            styles = [
                "realistic",
                "artistic",
                "abstract",
                "minimalist",
                "vibrant",
                "noir",
            ]
            style = styles[index % len(styles)]
            template = config.get("prompt_template", "Style {style}: {base_prompt}")
            return template.format(style=style, base_prompt=base_prompt)

        # Стандартная замена
        try:
            return modifier.format(
                base_prompt=base_prompt,
                index=index + 1,
                variation_aspect=variation_aspect,
                **(custom_params or {}),
            )
        except KeyError:
            return base_prompt

    async def execute_batch(
        self,
        job: BatchJob,
        progress_callback: Optional[Callable[[BatchJob], Any]] = None,
    ) -> BatchJob:
        """Выполняет пакетную генерацию с прогрессом"""

        job.status = BatchStatus.RUNNING
        job.progress_callback = progress_callback

        config = self._get_batch_config(job.mode)
        model = config.get("gemini_model", "gemini-2.5-flash-image")

        # Определяем стратегию выполнения
        if job.mode == "grid_2x2":
            # Для сетки — один запрос с инструкцией на 4 варианта
            await self._execute_grid_mode(job, model)
        else:
            # Для пакетов — параллельная генерация
            await self._execute_parallel_batch(job, model)

        # Финальная сборка
        await self._finalize_job(job)

        return job

    async def _execute_grid_mode(self, job: BatchJob, model: str):
        """Режим сетки 2×2 — один запрос, потом нарезка"""

        # Объединяем промпты с инструкцией для сетки
        combined_prompt = (
            f"Create a 2×2 grid image showing 4 variations of: {job.base_prompt}. "
            f"Each quadrant shows a different take with variations in lighting, angle, mood, and composition. "
            f"Consistent artistic style across all four. Clear separation between quadrants."
        )

        item = job.items[0]
        item.status = BatchStatus.RUNNING
        item.started_at = time.time()

        try:
            # Генерируем одно большое изображение
            result = await gemini_service.generate_image(
                prompt=combined_prompt,
                model=model,
                aspect_ratio="1:1",  # Квадрат для равных квадрантов
            )

            if result:
                # Нарезаем на 4 части
                quadrants = await self._split_image_grid(result, 2, 2)

                for i, quadrant in enumerate(quadrants):
                    if i < len(job.items):
                        job.items[i].result = quadrant
                        job.items[i].status = BatchStatus.COMPLETED
                        job.items[i].completed_at = time.time()

                    # Уведомляем о прогрессе
                    if job.progress_callback:
                        await job.progress_callback(job)
            else:
                for item in job.items:
                    item.status = BatchStatus.FAILED
                    item.error = "Generation failed"

        except Exception as e:
            logger.exception(f"Grid generation failed: {e}")
            for item in job.items:
                item.status = BatchStatus.FAILED
                item.error = str(e)

    async def _split_image_grid(
        self, image_bytes: bytes, rows: int, cols: int
    ) -> List[bytes]:
        """Нарезает изображение на сетку"""

        def _split():
            from PIL import Image

            img = Image.open(io.BytesIO(image_bytes))
            width, height = img.size

            cell_width = width // cols
            cell_height = height // rows

            quadrants = []
            for row in range(rows):
                for col in range(cols):
                    left = col * cell_width
                    upper = row * cell_height
                    right = left + cell_width
                    lower = upper + cell_height

                    quadrant = img.crop((left, upper, right, lower))

                    # Сохраняем в буфер
                    buf = io.BytesIO()
                    quadrant.save(buf, format="PNG")
                    quadrants.append(buf.getvalue())

            return quadrants

        # Выполняем в потоке (CPU-bound операция)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, _split)

    async def _execute_parallel_batch(self, job: BatchJob, model: str):
        """Параллельная генерация с ограничением конкурентности"""

        async def generate_item(item: BatchItem):
            async with self._semaphore:
                item.status = BatchStatus.RUNNING
                item.started_at = time.time()

                try:
                    result = await gemini_service.generate_image(
                        prompt=item.prompt, model=model
                    )

                    if result:
                        item.result = result
                        item.status = BatchStatus.COMPLETED
                    else:
                        item.status = BatchStatus.FAILED
                        item.error = "Empty response"

                except Exception as e:
                    logger.exception(f"Item {item.index} failed: {e}")
                    item.status = BatchStatus.FAILED
                    item.error = str(e)
                finally:
                    item.completed_at = time.time()

                    # Уведомляем о прогрессе
                    if job.progress_callback:
                        await job.progress_callback(job)

        # Запускаем все задачи параллельно (семафор ограничит)
        await asyncio.gather(*[generate_item(item) for item in job.items])

    async def _finalize_job(self, job: BatchJob):
        """Финализирует задачу — сборка галереи, метрики"""

        job.completed_at = time.time()

        successful = [i for i in job.items if i.status == BatchStatus.COMPLETED]

        if len(successful) == len(job.items):
            job.status = BatchStatus.COMPLETED
        elif successful:
            job.status = BatchStatus.PARTIAL
        else:
            job.status = BatchStatus.FAILED

        # Сохраняем в БД для истории
        await self._save_job_results(job)

    async def _save_job_results(self, job: BatchJob):
        """Сохраняет результаты в базу данных"""
        try:
            from bot.database import save_batch_job

            await save_batch_job(
                job_id=job.id,
                user_id=job.user_id,
                mode=job.mode,
                total_cost=job.total_cost,
                results_count=sum(
                    1 for i in job.items if i.status == BatchStatus.COMPLETED
                ),
                duration=job.completed_at - job.created_at
                if job.completed_at
                else None,
            )
        except Exception as e:
            logger.error(f"Failed to save batch job: {e}")

    async def create_gallery_preview(self, job: BatchJob) -> Optional[bytes]:
        """Создаёт превью-галерею из результатов"""

        successful = [i for i in job.items if i.result]
        if not successful:
            return None

        def _create_gallery():
            from PIL import Image, ImageDraw, ImageFont

            # Определяем разметку
            count = len(successful)
            if count <= 2:
                cols, rows = count, 1
            elif count <= 4:
                cols, rows = 2, 2
            else:
                cols, rows = 3, 2

            # Размер превью
            thumb_size = 512
            gallery_width = cols * thumb_size
            gallery_height = rows * thumb_size

            gallery = Image.new("RGB", (gallery_width, gallery_height), (240, 240, 240))

            for idx, item in enumerate(successful):
                if idx >= cols * rows:
                    break

                img = Image.open(io.BytesIO(item.result))
                img.thumbnail(
                    (thumb_size - 20, thumb_size - 20), Image.Resampling.LANCZOS
                )

                row = idx // cols
                col = idx % cols

                x = col * thumb_size + 10
                y = row * thumb_size + 10

                # Вставляем
                gallery.paste(img, (x, y))

                # Номер
                draw = ImageDraw.Draw(gallery)
                try:
                    font = ImageFont.truetype(
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20
                    )
                except:
                    font = ImageFont.load_default()

                draw.text((x + 5, y + 5), str(idx + 1), fill=(255, 255, 255), font=font)

            # Сохраняем
            buf = io.BytesIO()
            gallery.save(buf, format="JPEG", quality=85)
            return buf.getvalue()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, _create_gallery)

    async def upscale_selected(
        self, job_id: str, item_index: int, target_resolution: str = "4K"
    ) -> Optional[bytes]:
        """Апскейл выбранного изображения до высокого разрешения"""

        job = self._active_jobs.get(job_id)
        if not job:
            return None

        if item_index >= len(job.items):
            return None

        item = job.items[item_index]
        if not item.result:
            return None

        # Используем Gemini 3 Pro для апскейла
        upscale_prompt = (
            f"Faithfully upscale and enhance this image to {target_resolution} quality. "
            f"Preserve all details, enhance sharpness, add fine texture where appropriate. "
            f"Professional photo restoration and enhancement."
        )

        # Отправляем изображение на улучшение
        result = await gemini_service.generate_image(
            prompt=upscale_prompt,
            model="gemini-3-pro-image-preview",
            image_input=item.result,
        )

        return result

    def get_job(self, job_id: str) -> Optional[BatchJob]:
        """Получает активную задачу"""
        return self._active_jobs.get(job_id)

    def get_batch_modes(self) -> Dict[str, Dict]:
        """Получает все доступные режимы пакетной генерации"""
        config = self._get_batch_config("grid_2x2")  # Загружаем файл
        if not config:
            return {}

        try:
            presets_path = Path("data/presets.json")
            with open(presets_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("batch_modes", {})
        except:
            return {}

    async def cleanup_old_jobs(self, max_age_hours: int = 24):
        """Очищает старые задачи из памяти"""
        cutoff = time.time() - (max_age_hours * 3600)

        to_remove = [
            jid
            for jid, job in self._active_jobs.items()
            if job.completed_at and job.completed_at < cutoff
        ]

        for jid in to_remove:
            del self._active_jobs[jid]

        return len(to_remove)


# Глобальный сервис
batch_service = BatchGenerationService()
