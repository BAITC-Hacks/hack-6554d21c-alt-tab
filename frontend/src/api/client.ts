import { z } from 'zod'
import { healthSchema, sessionSchema, turnSchema, roomSchema, type VoiceApi, type TurnResult } from './types'

export class ApiError extends Error {
  constructor(message: string, public code: string, public retryable = false, public status = 0, public requestId?: string) {
    super(message); this.name = 'ApiError'
  }
}

export function normalizeTurn(result: TurnResult): TurnResult {
  if (!result.audio_url) return result
  return { ...result, audio_url: null, warnings: [...result.warnings, { stage: 'tts', code: 'unsupported_audio_url', message: 'Аудиофайл не используется в LiveKit. Текст и результат действия сохранены.' }] }
}
export function createLiveApi({ fetcher = globalThis.fetch.bind(globalThis), timeoutMs = 90_000 }: { fetcher?: typeof fetch; timeoutMs?: number } = {}): VoiceApi {
  async function request<T>(path: string, schema: z.ZodType<T>, init: RequestInit = {}, signal?: AbortSignal, requestId?: string): Promise<T> {
    const controller = new AbortController()
    let timedOut = false
    const cancel = () => controller.abort()
    signal?.addEventListener('abort', cancel, { once: true })
    if (signal?.aborted) cancel()
    const timer = setTimeout(() => { timedOut = true; controller.abort() }, timeoutMs)
    try {
      const response = await fetcher(`/api${path}`, { ...init, signal: controller.signal, credentials: 'same-origin' })
      const body: unknown = await response.json().catch(() => null)
      if (!response.ok) {
        const error = z.object({ error: z.object({ code: z.string(), message: z.string(), retryable: z.boolean() }) }).safeParse(body)
        if (error.success) throw new ApiError(error.data.error.message, error.data.error.code, error.data.error.retryable, response.status, requestId)
        const messages: Record<number, string> = { 404: 'Диалог не найден. Начните новый.', 413: 'Запись слишком большая. Запишите более короткую реплику.', 422: 'Сервер не принял данные запроса.', 429: 'Лимит запросов. Попробуйте позже.', 503: 'Сервис временно недоступен.' }
        throw new ApiError(messages[response.status] ?? `Сервер ответил ошибкой ${response.status}.`, 'http_error', response.status >= 500 || response.status === 429, response.status, requestId)
      }
      const parsed = schema.safeParse(body)
      if (!parsed.success) throw new ApiError('Ответ сервера не соответствует контракту. Результат запроса нужно проверить.', 'invalid_response', true, response.status, requestId)
      return parsed.data
    } catch (error) {
      if (error instanceof ApiError) throw error
      if (timedOut) throw new ApiError('Сервер не ответил за 90 секунд. Результат мог сохраниться; повтор будет с тем же ID.', 'timeout', true, 0, requestId)
      if (signal?.aborted) throw new ApiError('Запрос отменён.', 'cancelled', false, 0, requestId)
      throw new ApiError('Нет связи с сервером. Проверьте backend и соединение.', 'network_error', true, 0, requestId)
    } finally {
      clearTimeout(timer); signal?.removeEventListener('abort', cancel)
    }
  }
  const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  function checkTurn(result: TurnResult, sessionId: string, requestId: string): TurnResult {
    if (result.session_id !== sessionId || result.request_id !== requestId) {
      throw new ApiError('Ответ содержит неверный ID сессии или запроса.', 'invalid_response', true, 0, requestId)
    }
    return normalizeTurn(result)
  }
  return {
    health: signal => request('/health', healthSchema, {}, signal),
    createSession: signal => request('/sessions', sessionSchema, json({}), signal),
    async text(sessionId, requestId, text, signal) {
      if (!text.trim() || text.length > 4000) throw new ApiError('Введите от 1 до 4000 символов.', 'invalid_input')
      const result = await request(`/sessions/${encodeURIComponent(sessionId)}/turns`, turnSchema, json({ request_id: requestId, text: text.trim() }), signal, requestId)
      return checkTurn(result, sessionId, requestId)
    },
    async history(sessionId, signal) {
      const value = await request(`/sessions/${encodeURIComponent(sessionId)}/turns`, z.object({ turns: z.array(turnSchema) }), {}, signal)
      return value.turns.map(turn => checkTurn(turn, sessionId, turn.request_id))
    },
    async livekit(sessionId, signal) {
      const value = await request(`/sessions/${encodeURIComponent(sessionId)}/livekit`, roomSchema, json({}), signal)
      if (value.session_id !== sessionId) throw new ApiError('Комната принадлежит другой сессии.', 'invalid_response')
      return value
    },
  }
}
