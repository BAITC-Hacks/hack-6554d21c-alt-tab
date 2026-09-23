# Повторное использование ALTCALL

Источник: пользовательский репозиторий `C:/Users/Admin/PROJECTS/ALTCALL.ONLINE`,
проверенный коммит `5d504312` (23 сентября 2026). Донор не изменялся.

| Исходник | Использование |
|---|---|
| `src/voice_agent/config.py` | GPT-4.1 mini, Soniox TTS `tts-rt-v2`, голос Arthur |
| `src/voice_agent/agent.py`: `stt_params`, `build_session` | Параметры Soniox `stt-rt-v5`, RU/KK, endpointing, prewarm TTS, локальная VAD в `backend/voice.py` |
| `admin-ui/src/lib/livekit-session.ts` | Полная копия транспортного хука в `ТЗ/reference/livekit-session.ts` для адаптации владельцем frontend |
| `src/voice_agent/admin/app.py` | Подход выдачи подписанного токена комнаты; новая реализация без БД и tenant-логики |

LLM-router Saqta, HTTP-контракт и состояние страховых сценариев написаны для кита.
CRM, SIP, биллинг, БД, `.env` и записи звонков не переносились.
Использование донорского кода основано на прямом указании владельца проекта;
эта запись не назначает ему новую лицензию.

Внешние библиотеки устанавливаются из `uv.lock`; их лицензии остаются у правообладателей.
LiveKit Windows скачивается из официального release с проверкой контрольной суммы.
