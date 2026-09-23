# Saqta Voice Router — приложение

Основа голоса — ALTCALL: LiveKit + Soniox STT/TTS, LLM — `gpt-4.1-mini`.
Исходный [README кита](README.ru.md), JSON и `evaluate.py` сохранены без изменений.

## Текущее покрытие

Реализован первый этап: текстовый API, сессии, LLM-router по 40 сценариям + 3 системным намерениям,
слоты, трасса, идемпотентность и LiveKit-адаптер к тому же обработчику.
Исполняются чтение офисов, клиник и ответы из KB. Остальные действия возвращают явный
handoff — симуляцию. Полный исполнитель, идентификация, preview/confirm и работа с
очередью до завершения всех намерений ещё не реализованы. Это не готовность к сдаче.

Бизнес-дата: **2026-10-01**. Данные сессий только в памяти, после перезапуска сбрасываются.

Локальная конфигурация на 2026-09-23: `OPENAI_API_KEY` и `SONIOX_API_KEY` в `.env`
рабочие — живые вызовы OpenAI и Soniox STT/TTS прошли (см. «Проверки»).

## Подготовка (Windows, PowerShell)

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD '.cache/uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PWD '.cache/python'
uv sync --python 3.12 --all-extras --locked
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
powershell -ExecutionPolicy Bypass -File scripts/install-livekit.ps1
```

На новой машине в `.env` заполнить `OPENAI_API_KEY` и `SONIOX_API_KEY`.
В текущем checkout они уже заполнены; существующий `.env` не перезаписывать. Ключи в Git не попадают.
`.env` ALTCALL не копировать. Установщик скачивает официальный Windows LiveKit 1.13.7
в `.cache/livekit` и сверяет SHA-256 с опубликованным `checksums.txt`.
Альтернатива нативному LiveKit — Docker Desktop и `compose.yaml`.

## Запуск

```powershell
.venv/Scripts/python scripts/dev.py
```

Одна команда запускает локальный LiveKit, HTTP API и голосовой worker. API: <http://127.0.0.1:8000/docs>.
Интерфейс в `frontend/` делает тиммейт: [обновлённое задание](ТЗ/handoff-frontend.txt).
До его интеграции браузерного голосового экрана в этом checkout нет.

Только API, без голосового worker:

```powershell
.venv/Scripts/python scripts/dev.py --text-only
```

API стартует без ключей, но запрос к LLM возвращает 503. Mock-успеха вместо провайдера нет.
`health.voice_ready=false` пока означает, что живой голос не проверен; `voice_configured`
отдельно сообщает наличие настроек, без проверки действительности ключей.

После изменения `.env` перезапустить API и голосовой worker: настройки читаются
при старте. Во время обновления документации прежний API ещё возвращал
`voice_configured=false` и оба имени в `missing_config`, хотя файл уже заполнен.
Это снимок старого процесса, а не результат проверки новых ключей у провайдеров.
Повторный запуск выполнять после остановки прежних API/worker; если локальный
LiveKit уже работает, использовать `scripts/dev.py --external-livekit`.

## Архитектура

```text
Браузер ──WebRTC── локальный LiveKit ── Soniox STT
                                           │
                           backend.voice → HTTP /turns
                                           │
Текстовый ввод ─────────────────────── backend.service
                                           │
                                 GPT-4.1 mini router
                                           │
                               каталог / состояние / KB
                                           │
                       ответ + trace → LiveKit data channel
                                           │
                              Soniox TTS → WebRTC → браузер
```

Только HTTP-сервис хранит состояние. Worker не запускает вторую бизнес-логику.
Предварительная генерация по незавершённой STT-реплике отключена.
Повтор `request_id` возвращает сохранённый результат; другой текст с тем же ID даёт 409.
Полная задержка воспроизведения не выдумывается: backend возвращает `null`.

## Проверки

```powershell
.venv/Scripts/python -m pytest -q
.venv/Scripts/python scripts/smoke_transport.py  # API и LiveKit должны быть запущены
.venv/Scripts/python scripts/evaluate_router.py
.venv/Scripts/python evaluate.py artifacts/predictions.json dev_utterances.json
```

Тесты используют явные подмены LLM/HTTP: проверяют логику и совместимость SDK, не качество речи.
Оценка требует настоящего OpenAI, вызывает модель для всех 104 реплик и не передаёт ей `expected`.
Без реального прогона predictions и метрик нет.

Проверено 2026-09-23: 16 unit/integration тестов прошли; настоящий локальный HTTP
ответил 200, WebRTC-клиент подключился к отдельной тестовой комнате LiveKit и отключился.
Без ключа запрос к router дал ожидаемый 503. Живые STT/LLM/TTS и микрофон не проверены.

Проверено 2026-09-23 после перезапуска с ключами: `/api/health` → `voice_configured=true`.
Живой GPT-4.1 mini: RU «офис в Алматы» → SC33 (execute), KK «полисімді ұзарту» → SC27,
ответ на казахском; mixed «мен ДТП-ға түстім, что делать» → SC11, язык `mixed`.
Router 1.3–1.4 с на прогретом соединении (первый запрос ~9 с — холодный старт).
Soniox напрямую, без браузера: TTS RU/KK — первый звук ~0.9 с; STT распознал
синтезированные RU и KK фразы дословно. Микрофон в браузере, LiveKit-комната с
worker и autoplay не проверены: нет frontend.

Происхождение адаптации: [THIRD_PARTY.md](THIRD_PARTY.md). Контракт: [API v2](ТЗ/api-contract.md).
