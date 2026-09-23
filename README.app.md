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
Интерфейс в `frontend/` (тиммейт, влит в `main` из `codex/frontend-simulator`): Vite на 5174
с proxy `/api` → 8000. Запуск отдельным процессом: `npm ci && npm run dev` в `frontend/`,
затем открыть <http://127.0.0.1:5174>. Подробности — [frontend/README.md](frontend/README.md).
Автоматический браузерный прогон голоса: `scripts/e2e_live_voice.mjs` (см. «Проверки»).

Только API, без голосового worker:

```powershell
.venv/Scripts/python scripts/dev.py --text-only
```

API стартует без ключей, но запрос к LLM возвращает 503. Mock-успеха вместо провайдера нет.
`health.voice_ready` = все настройки голоса заданы (браузерный голос на этой конфигурации
проверен 2026-09-23, см. «Проверки»); `voice_configured` — то же наличие настроек.
Действительность ключей у провайдеров health не проверяет.

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

Результат реального прогона 2026-09-23 (gpt-4.1-mini, без контекста сессии, 104/104 вызовов успешны):

| Группа | n | primary_acc | full_match |
|---|---|---|---|
| all | 104 | 0.971 | 0.952 |
| lang=kk | 45 | 1.000 | 0.978 |
| lang=mixed | 7 | 1.000 | 0.857 |
| lang=ru | 52 | 0.942 | 0.942 |
| type=multi_intent | 13 | 0.923 | 0.846 |
| type=unclear | 3 | 0.333 | 0.333 |

intent_recall (multi-intent) 0.923. Ошибки — 5: два раза пропущено второе намерение
(U083, U090), один лишний сценарий (U030), два коротких неясных запроса вместо
`SYS_UNCLEAR` отнесены к сценарию (U102, U104). Dev-набор — диагностика, не цель
подгонки; predictions и отчёт лежат в `artifacts/` (не в Git).

Проверено 2026-09-23: 16 unit/integration тестов прошли; настоящий локальный HTTP
ответил 200, WebRTC-клиент подключился к отдельной тестовой комнате LiveKit и отключился.
Без ключа запрос к router дал ожидаемый 503. Живые STT/LLM/TTS и микрофон не проверены.

Проверено 2026-09-23 после перезапуска с ключами: `/api/health` → `voice_configured=true`.
Живой GPT-4.1 mini: RU «офис в Алматы» → SC33 (execute), KK «полисімді ұзарту» → SC27,
ответ на казахском; mixed «мен ДТП-ға түстім, что делать» → SC11, язык `mixed`.
Router 1.3–1.4 с на прогретом соединении (первый запрос ~9 с — холодный старт).
Soniox напрямую, без браузера: TTS RU/KK — первый звук ~0.9 с; STT распознал
синтезированные RU и KK фразы дословно.

Проверено 2026-09-23 в браузере на frontend тиммейта (коммит 76d46b8): headless Chrome
с fake-микрофоном, в который подан WAV из Soniox TTS, → Vite → API → LiveKit → worker.
Повтор: при запущенных `scripts/dev.py` и `npm run dev` выполнить
`node scripts/e2e_live_voice.mjs <реплика.wav> <папка для лога и скриншота>`
(нужен установленный Chrome; WAV — 2 с тишины, речь, тишина для endpointing).
Четыре реплики распознаны дословно и озвучены; трасса пришла по data channel и в
истории сервера:

| Реплика | STT | Router | Ответ |
| --- | --- | --- | --- |
| RU «Где ближайший офис в Алматы?» | дословно | SC33 execute, `city=Almaty` | адрес и часы, RU |
| KK «Алматыдағы кеңселеріңіз қайда?» | дословно | SC33 execute | адрес и часы, KK |
| KK «терапевтке жазып қойыңызшы» | дословно | SC21 collect_slots | просит номер полиса, KK |
| mixed «терапевтке жазылу керек, и ещё список клиник» | дословно | SC21 + очередь SC23, `city`, `doctor_specialty` | KK; язык помечен `kk`, не `mixed` |

От нажатия «Начать разговор» до ответа на экране 9,6–11,1 с, из них приветствие агента
и 2 с тишины перед репликой; router 2,0–3,3 с, ответ 0,7–2,5 с. `stt`, `tts_first_audio`
и сквозная задержка по-прежнему `null`: worker их не измеряет. В одном из шести прогонов
первый ход получил 503 от LLM: интерфейс показал ошибку с `request_id`, агент озвучил
«Не удалось обработать реплику», фиктивного ответа не было; причина теперь пишется в лог API.
После ухода клиента worker
не завершает job сам; LiveKit закрывает комнату через 20 с и помечает job `JS_FAILED`.

Происхождение адаптации: [THIRD_PARTY.md](THIRD_PARTY.md). Контракт: [API v2](ТЗ/api-contract.md).
