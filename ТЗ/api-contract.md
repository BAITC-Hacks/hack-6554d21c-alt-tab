# Контракт frontend ↔ backend v2 — LiveKit

**Статус: текстовый API и LiveKit-адаптер реализованы; живой голос не проверен.** Владелец — участник backend. Frontend реализует API-клиент и явные mock-ответы по этому документу. Переход v1 → v2 выполнен по прямому указанию пользователя; обновлён handoff для frontend.

## Транспорт MVP — LiveKit (решение пользователя)

GPT-4.1 mini + Soniox STT/TTS + отдельный локальный LiveKit. Адаптация голосового
конвейера ALTCALL. React/TypeScript подключается к WebRTC-комнате через `livekit-client`.
HTTP нужен для создания сессии, токена комнаты и текстового резерва.

| Метод | Запрос | Результат |
|---|---|---|
| `GET /api/health` | — | `status`, `mode`, `voice_ready`, `voice_configured`, `missing_config`, `models` |
| `POST /api/sessions` | `{}` | `{"session_id":"uuid","as_of_date":"2026-10-01"}` |
| `POST /api/sessions/{id}/turns` | `{"request_id":"uuid","text":"Где ваш офис?"}` | `TurnResult` |
| `GET /api/sessions/{id}/turns` | — | `{"turns":[TurnResult,...]}` для восстановления трассы |
| `POST /api/sessions/{id}/livekit` | `{}` | `{"room":"saqta-uuid","token":"JWT","ws_url":"ws://127.0.0.1:7880","session_id":"uuid","trace_topic":"saqta.trace"}` |

`POST /audio` из v1 заменён LiveKit и отвечает 501 `transport_changed`; `GET /api/audio`
не используется. `audio_url` в TurnResult остаётся `null`: звук идёт по WebRTC.
Текстовый резерв возвращает текст без озвучивания.

Frontend получает разрешение микрофона ДО вызова `/livekit`, подключает комнату и
публикует микрофон. `TrackSubscribed` прикрепляет remote audio, `TrackUnsubscribed`
удаляет элементы. `AudioPlaybackStatusChanged` показывает кнопку `room.startAudio()`
при блокировке autoplay. При завершении — `room.disconnect()` и освобождение треков.

DataReceived: проверять topic и отправителя-агента (не локального участника).
- `saqta.trace`: UTF-8 JSON с полным `TurnResult`.
- `saqta.error`: `{"stage":"voice|router","message":"...","request_id":"..."}`; request_id может отсутствовать.
- `saqta.ready`: `{"session_id":"...","mode":"live"}` после старта voice session;
  это не доказательство успешного STT/TTS.

При потерянном пакете брать историю через GET `/turns` и дедуплицировать по `turn_id`.
Worker отправляет распознанную реплику в тот же `/turns`; состояние в одном HTTP-процессе.
Не запускать несколько uvicorn workers с независимой памятью.

Ключи Soniox/OpenAI и signing secret остаются на сервере. Браузеру выдаётся только
токен конкретной комнаты на 15 минут. Localhost разрешён для микрофона; удалённый
демо-доступ требует HTTPS/WSS и отдельной настройки LiveKit, сейчас не выполненной.

`voice_ready` пока всегда false: живой голос ещё не подтверждён. `voice_configured`
показывает только наличие настроек. UI может предложить попытку соединения, но обязан
показывать ошибки и не называть конфигурацию живой проверкой. Mock-режим явный.

## TurnResult

Пример формы для запроса об офисе без города. Значения уверенности ниже иллюстрируют типы, не являются результатом измерения модели. Для удобства UI один объект служит и ответом, и трассировкой.

```json
{
  "session_id": "s-demo",
  "request_id": "r-demo",
  "turn_id": "t-demo",
  "turn": 1,
  "mode": "live",
  "transcript": "Где ваш офис?",
  "language": "ru",
  "response_language": "ru",
  "scenarios": [{"scenario_id": "SC33", "confidence": 0.92}],
  "alternatives": [],
  "reason": "Клиент спрашивает адрес офиса; для поиска нужен город.",
  "is_continuation": false,
  "decision": "collect_slots",
  "active_scenario": "SC33",
  "queued_scenarios": [],
  "slots": {},
  "missing_slots": ["city"],
  "actions": [],
  "pending_confirmation": null,
  "handoff": null,
  "reply": "В каком городе вы ищете офис?",
  "audio_url": null,
  "latency_ms": {
    "stt": null,
    "triage": null,
    "router": null,
    "response": null,
    "tts_first_audio": null,
    "total": null
  },
  "server_processing_ms": null,
  "warnings": []
}
```

`language`: `ru | kk | mixed`. `response_language`: `ru | kk`. Допустимые ID — только из `scenarios.json` и `system_intents`. `scenarios` — решение router в порядке приоритета; `active_scenario` — исполняемый сейчас сценарий либо `null`. `alternatives` имеют ту же форму, что элементы `scenarios`. `confidence` — число от 0 до 1.

`decision`: `collect_slots | execute | confirm | clarify | handoff | goodbye | out_of_scope`. UI отображает каждое значение, но не принимает бизнес-решение вместо сервера. `queued_scenarios` — массив ID; `slots` — JSON-объект с типами из `slots.json`.

Элемент `actions`: `{"name":"cancel_policy","mode":"preview","status":"ok","result":{}}`. `mode`: `preview | execute`; `status`: `ok | error`. При ошибке вместо `result` — `error` из `actions.json`. Нельзя писать `execute:ok`, если выполнялся только preview.

`pending_confirmation`: `null` либо `{"confirmation_id":"uuid","action":"cancel_policy","parameters":{},"summary":"..."}`. Ответ пользователя приходит обычной следующей репликой. Сервер проверяет наличие pending, явное согласие и неизменность параметров. Уточнение параметров отменяет старый preview. Frontend не отправляет `confirmed:true` по собственной эвристике.

`handoff`: `null` либо `{"queue":"operator_general","summary":"..."}`. Очередь — из `actions.json`. UI пишет «Передача оператору — симуляция» и показывает контекст. `audio_url` — относительный same-origin URL либо `null`; объект `warnings` ниже не должен содержать секреты провайдера.

## Задержки

Каждая метрика — неотрицательное число миллисекунд либо `null`. Backend ставит фактические замеры, никогда демонстрационные константы. Frontend показывает `null` как «не измерено», а не `0 мс`.

`stt`, `triage`, `router`, `response` — отдельные этапы сервера. `tts_first_audio` — время от начала TTS до первых полученных аудиоданных. Для файлового TTS полное время скачивания не выдаётся за время первого аудио. `server_processing_ms` — полная обработка HTTP-запроса; сумма стадий может отличаться.

Backend возвращает `latency_ms.total: null`: сервер не знает, когда браузер действительно начал воспроизведение. Frontend локально дополняет трассу только если может измерить окончание речи и начало фактического воспроизведения одним `performance.now()`, сохраняя `total_basis: "vad_end_to_playing" | "recording_stop_to_playing" | "text_submit_to_playing"`. В LiveKit событие подключения аудиотрека само по себе не является началом каждого ответа; без отдельного измерения оставлять total=null. Только первый вариант — заявленная голосовая E2E-метрика. При ручном stop явно подписать оценку «от остановки записи», не обещать точность до конца речи. Не складывать часы сервера и браузера.

Кнопка ручного воспроизведения появляется, если autoplay запрещён. В этом случае total включает задержку пользователя; такой замер пометить, а не улучшать статистику скрытым исключением.

## Ошибки и состояние

1. Сервер владеет историей и данными сессии. «Новый диалог» создаёт новую сессию со свежей копией mock-данных; исходные JSON на диске не изменяются.
2. Один `request_id` в одной сессии — один результат. Повтор возвращает тот же результат без нового LLM-вызова и изменения данных; разные запросы сессии обрабатываются последовательно. Frontend блокирует двойную отправку.
3. HTTP 404 — сессия не найдена; 413 — слишком большое аудио; 422 — некорректный ввод; 429 — лимит; 503 — недоступен провайдер. Формат: `{"error":{"code":"provider_unavailable","message":"...","retryable":true}}`.
4. Ошибка STT не запускает router. Ошибка LLM не запускает действие. Если действие уже выполнено, а TTS упал, вернуть `TurnResult` с текстом, `audio_url:null` и `warnings:[{"stage":"tts","code":"provider_unavailable","message":"Не удалось озвучить ответ"}]`; не повторять действие ради аудио.
5. Frontend mock-ответы лежат отдельно и помечены `mode:"mock"`. Режим не включается автоматически при отказе настоящего backend. Backend не должен читать `expected` из dev-набора.
