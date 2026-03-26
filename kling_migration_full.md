Полная миграция motion-control (Kling) с PiAPI на Replicate

Цель: заменить вызовы модели motion-control через PiAPI/внутренние HTTP вызовы на использование официального клиента Replicate (https://replicate.com) и адаптировать серверную логику (создание задач, получение результатов, вебхуки, отмена, обработка файлов).

Кому полезно: разработчикам бота/сервиса, которые использовали api.piapi.ai (PiAPI) и хотят перейти на модель kwaivgi/kling-v2.6-motion-control на Replicate.

Содержимое документа:
- Короткое резюме изменений
- Технические требования и подготовка окружения
- Как формировать входные данные (image/video/prompt и т.д.)
- Примеры кода (синхронный/асинхронный, с вебхуком и без)
- Карта соответствия параметров PiAPI -> Replicate
- Обработка ответов, загрузка результатов на диск
- Вебхуки: как настроить и что поменять в обработчике
- Тестирование и CI
- Безопасность, секреты, расходы, откат

1. Короткое резюме

Replicate предоставляет SDK и HTTP API для запуска моделей. Вместо отправки POST запросов к api.piapi.ai и парсинга специфичной PiAPI-структуры мы будем использовать официальный пакет replicate (pip install replicate) и переменную окружения REPLICATE_API_TOKEN вместо PIAPI ключа. Replicate поддерживает синхронные короткие вызовы (replicate.run), создание предсказаний (replicate.predictions.create) и вебхуки для асинхронных уведомлений.

2. Подготовка окружения

- Установить клиент:

  python -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install replicate

- Установить токен репозитория как переменную окружения (не храните в коде):

  export REPLICATE_API_TOKEN="r8_FjT..."

  (В CI/CD — добавить переменную окружения REPLICATE_API_TOKEN)

3. Основные изменения в конфигурации проекта

- bot/config.py: заменить PIAPI_BASE_URL/PIAPI_API_KEY на использование REPLICATE_API_TOKEN. Можно держать совместимость, добавив опциональную ветку: если REPLICATE_API_TOKEN задан — использовать Replicate, иначе — fallback на PiAPI (пока временно).

- Пересмотреть места, где проект напрямую формировал HTTP-запросы к api.piapi.ai (например bot/services/kling_service.py). Заменить на вызовы через replicate SDK.

4. Сопоставление параметров (PiAPI -> Replicate)

- request body PiAPI (пример):
  - image_url / image_tail_url -> image (uri, локальный файл или data-uri)
  - video -> video (uri)
  - mode (std/pro) -> mode (тот же enum у модели kwaivgi/kling-v2.6-motion-control)
  - prompt -> prompt
  - keep_original_sound -> keep_original_sound (boolean)
  - character_orientation -> character_orientation (image/video)

Replicate принимает объект input со свойствами выше (см. schema модели). Для большинства полей названия совпадают или отличаются минимально — просто переименуйте в input.

5. Примеры кода

5.1. Быстрый синхронный пример (replicate.run)

import replicate

input = {
    "mode": "pro",
    "image": "https://example.com/my_ref_image.png",
    "video": "https://example.com/my_ref_video.mp4",
    "prompt": "A joyful dance",
    "keep_original_sound": True,
    "character_orientation": "image",
}

output = replicate.run(
    "kwaivgi/kling-v2.6-motion-control",
    input=input,
)

# output обычно содержит URL на итоговый файл (например .mp4)
print(output)  # может быть строка или dict, смотрите docs/модель

# Чтобы записать результат в файл, если output поддерживает .read() или возвращён URL:
if hasattr(output, 'read'):
    with open('output.mp4', 'wb') as f:
        f.write(output.read())
else:
    # если output.url или строка
    url = output.url if hasattr(output, 'url') else output
    # загрузить по URL стандартным способом (requests)
    import requests
    r = requests.get(url)
    r.raise_for_status()
    with open('output.mp4', 'wb') as f:
        f.write(r.content)

5.2. Асинхронный / ожидание через predictions.create + polling

import replicate
import time

client = replicate

prediction = client.predictions.create(
    model="kwaivgi/kling-v2.6-motion-control",
    input=input,
)

print('prediction id:', prediction.id)

# опционально – периодически обновляем статус
while True:
    prediction = client.predictions.get(prediction.id)
    print('status', prediction.status)
    if prediction.status in ('succeeded', 'failed', 'canceled'):
        break
    time.sleep(2)

if prediction.status == 'succeeded':
    # prediction.output может быть списком/объектом с url
    print('result', prediction.output)

5.3. Создание предсказания с вебхуком (рекомендуется для долгих задач)

callback_url = "https://my.app/webhooks/replicate"

prediction = replicate.predictions.create(
    model="kwaivgi/kling-v2.6-motion-control",
    input=input,
    webhook=callback_url,
    webhook_events_filter=["completed"],
)

# Replicate пришлёт POST с полной структурой prediction на URL, когда задача завершится

6. Файловые входы

- Hosted file: даём URL (удобно для больших файлов >256kb).
- Local file: можно передать open('./file.mp4','rb') и клиент сам загрузит файл.
- Data URI: base64, только для очень маленьких файлов (<1MB) — не рекомендуется для видео.

Пример загрузки локального файла:

input['image'] = open('./in.png', 'rb')
input['video'] = open('./in.mp4', 'rb')

7. Вебхуки и обработчики

- Replicate поддерживает webhook= при создании prediction. Replicate пришлёт JSON тела предсказания (prediction) на ваш endpoint при событиях (start, output, logs, completed), в зависимости от webhook_events_filter.
- Не отправляйте redirecting URL (Replicate не следует редиректам).
- Повторные попытки: Replicate будет ретраить при сетевых проблемах — убедитесь, что ваш обработчик идемпотентен.

Minimal webhook handler (Flask / aiohttp / FastAPI — пример на Flask):

from flask import Flask, request
app = Flask(__name__)

@app.route('/webhooks/replicate', methods=['POST'])
def replicate_webhook():
    data = request.json
    # data — это структура Prediction. Проверьте data['status'] и data['output']
    status = data.get('status')
    pred_id = data.get('id')
    if status == 'succeeded':
        output = data.get('output')
        # output может быть списком или объектом. Найдите URL к .mp4
        # Сохраните URL/загрузите файл/обновите запись в базе (task id -> результат)
    elif status in ('failed', 'canceled'):
        # лог, оповещение
        pass
    return '', 200

Примечание по верификации вебхуков: Replicate предоставляет способ проверки подписи webhook (см. документацию Replicate). Если требуется высокая безопасность, реализуйте верификацию (HMAC или заголовки подписи) на своем endpoint.

8. Обработка ошибок и отмена

- Для отмены prediction: prediction.cancel() или вызов HTTP /predictions/{id}/cancel.
- Обрабатывайте статусы prediction.status: starting, processing, succeeded, failed, canceled.

9. Миграция кода: пример преобразования service

- В bot/services/kling_service.py (примеры):
  - Удалить прямые HTTP POST к https://api.piapi.ai/api/v1/task (или оставить как fallback).
  - Добавить функции:
    - create_prediction(input) -> возвращает prediction.id
    - get_prediction(id) -> возвращает статус и output
    - cancel_prediction(id)
  - Логика: при создании задачи сохранять локально task_id -> prediction_id (в базе), при вебхуке обновлять статус и путь к result.

Пример: create_prediction wrapper

def create_kling_prediction(input: dict, webhook: Optional[str] = None):
    import replicate
    kwargs = {"model": "kwaivgi/kling-v2.6-motion-control", "input": input}
    if webhook:
        kwargs.update({"webhook": webhook, "webhook_events_filter": ["completed"]})
    pred = replicate.predictions.create(**kwargs)
    return pred.id

10. Тесты и CI

- В тестах (tests/test_kling_service.py) заменить фиктивные ответы PiAPI на ответы, имитирующие replicate.predictions.create/get. Используйте monkeypatch или vcr/httpretty для моков.
- В CI: добавить секрет REPLICATE_API_TOKEN в переменные окружения.

11. Стоимость и ограничения

- У Replicate модели платные — проверьте цену модели kwaivgi/kling-v2.6-motion-control на странице модели. Тестируйте на минимальных параметрах (mode: std) перед массовой миграцией.
- Ограничения по размеру входных файлов: image до 10MB, video до 100MB — соответствует документации модели.

12. Security / Secrets

- Никогда не храните REPLICATE_API_TOKEN в репозитории. Используйте секреты в CI и переменные окружения на сервере.
- Включите проверку вебхуков (если нужно) по подписи.

13. План отката

- Пока не удаляйте код с поддержкой PiAPI. Выполните хибридный режим — если REPLICATE_API_TOKEN не задан, используйте старый PiAPI-эндпоинт. Это позволит мягко откатиться.

14. Рекомендации по поэтапной миграции

1) Подготовить окружение: добавить REPLICATE_API_TOKEN в staging.
2) Реализовать новую service-обёртку (replicate) параллельно с существующей PiAPI-логикой.
3) Написать unit/integration тесты для replicate-обёртки.
4) Запустить в staging: часть запросов направлять на replicate (feature flag).
5) Наблюдать расходы, латентность, качество; корректировать параметры.
6) После успешного тестирования и мониторинга — переключить production на Replicate и удалить PiAPI код через pull request с сохранением rollback-плана.

15. Примеры полезных функций и утилит

- download_url_to_file(url, path)
- save_prediction_output_to_db(prediction)
- map_piapi_input_to_replicate(piapi_payload) -> replicate_input

16. Частые проблемы и превентивные меры

- Ошибка аутентификации: убедитесь, что REPLICATE_API_TOKEN экспонируется в среде процесса.
- Проблемы с upload: для больших файлов используйте URL-хостинг (S3) вместо передачи data-uri.
- Вебхуки: временные сбои — ваш endpoint должен быть доступен и идемпотентен.

17. Заключение

Миграция на Replicate упрощает работу с моделью (официальный SDK, предсказания/вебхуки), но требует внимательного управления секретами, тестирования на стоимость и поэтапного переключения. Рекомендуется реализовать поддержку обеих платформ на время перехода и тщательно протестировать обработчики вебхуков и сохранение результатов в базе.

---
Если хотите, могу:
- подготовить ПР с изменениями в bot/services/kling_service.py и bot/config.py, показывающий пример интеграции с replicate (функции create/get/cancel + пример webhook-handler);
- сгенерировать конкретный код для FastAPI webhook и unit-тесты для новой обёртки.
