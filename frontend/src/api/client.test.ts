import { afterEach, describe, expect, it, vi } from 'vitest'
import { createLiveApi, ApiError } from './client'
import { turnFixture } from '../test/fixture'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })
describe('REST contract', () => {
  it('sends text with its idempotency key and preserves unmeasured values', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(turnFixture))
    const result = await createLiveApi({ fetcher }).text('session-1', 'request-1', 'Где ваш офис?')
    expect(fetcher.mock.calls[0][0]).toBe('/api/sessions/session-1/turns')
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ request_id: 'request-1', text: 'Где ваш офис?' })
    expect(result.latency_ms.total).toBeNull()
  })
  it('sends actual WebM as multipart without overriding the boundary', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(turnFixture))
    await createLiveApi({ fetcher }).audio('session-1', 'request-1', new Blob(['voice'], { type: 'audio/webm;codecs=opus' }))
    const options = fetcher.mock.calls[0][1]
    expect(options.body.get('request_id')).toBe('request-1')
    expect(options.body.get('audio').name).toBe('recording.webm')
    expect(options.body.get('audio').type).toBe('audio/webm;codecs=opus')
    expect(options.headers).toBeUndefined()
  })
  it('preserves provider errors instead of returning a successful mock', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ error: { code: 'provider_unavailable', message: 'Речь недоступна', retryable: true } }, { status: 503 }))
    await expect(createLiveApi({ fetcher }).text('session-1', 'request-1', 'Сәлем')).rejects.toMatchObject({ status: 503, code: 'provider_unavailable', requestId: 'request-1', retryable: true })
  })
  it('rejects broken responses and out-of-contract scenario IDs', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ ...turnFixture, scenarios: [{ scenario_id: 'SC99', confidence: 2 }] }))
    await expect(createLiveApi({ fetcher }).text('session-1', 'request-1', 'Офис')).rejects.toMatchObject({ code: 'invalid_response' })
  })
  it('does not load provider or cross-origin audio URLs', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ ...turnFixture, audio_url: 'https://provider.example/private.mp3' }))
    await expect(createLiveApi({ fetcher }).text('session-1', 'request-1', 'Офис')).rejects.toMatchObject({ code: 'invalid_response' })
  })
  it('rejects a response for a different request/session', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ ...turnFixture, request_id: 'other' }))
    await expect(createLiveApi({ fetcher }).text('session-1', 'request-1', 'Офис')).rejects.toMatchObject({ code: 'invalid_response' })
  })
  it('times out without retrying a mutation automatically', async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn((_url, options) => new Promise<Response>((_resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }))
    const pending = createLiveApi({ fetcher, timeoutMs: 100 }).text('session-1', 'request-1', 'Офис')
    const check = expect(pending).rejects.toMatchObject({ code: 'timeout', requestId: 'request-1', retryable: true })
    await vi.advanceTimersByTimeAsync(101)
    await check
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
  it('validates empty and oversized text before making a request', async () => {
    const fetcher = vi.fn()
    const api = createLiveApi({ fetcher })
    await expect(api.text('s', 'r', ' ')).rejects.toBeInstanceOf(ApiError)
    await expect(api.text('s', 'r', 'я'.repeat(4001))).rejects.toBeInstanceOf(ApiError)
    expect(fetcher).not.toHaveBeenCalled()
  })
})
