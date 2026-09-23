import { afterEach, describe, expect, it, vi } from 'vitest'
import { createLiveApi, ApiError } from './client'
import { turnFixture } from '../test/fixture'
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })
describe('REST v2 contract', () => {
  it('sends text with its idempotency key and preserves unmeasured values', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(turnFixture))
    const result = await createLiveApi({ fetcher }).text('session-1', 'request-1', 'Где ваш офис?')
    expect(fetcher.mock.calls[0][0]).toBe('/api/sessions/session-1/turns')
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ request_id: 'request-1', text: 'Где ваш офис?' })
    expect(result.latency_ms.total).toBeNull()
  })
  it('preserves provider errors without a mock fallback', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ error: { code: 'provider_unavailable', message: 'Речь недоступна', retryable: true } }, { status: 503 }))
    await expect(createLiveApi({ fetcher }).text('session-1', 'request-1', 'Сәлем')).rejects.toMatchObject({ status: 503, code: 'provider_unavailable', requestId: 'request-1', retryable: true })
  })
  it('rejects out-of-contract scenario IDs', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ ...turnFixture, scenarios: [{ scenario_id: 'SC99', confidence: 2 }] }))
    await expect(createLiveApi({ fetcher }).text('session-1', 'request-1', 'Офис')).rejects.toMatchObject({ code: 'invalid_response' })
  })
  it('preserves executed actions while discarding unsupported file audio', async () => {
    const actions = [{ name: 'cancel_policy', mode: 'execute', status: 'ok', result: {} }]
    const fetcher = vi.fn().mockResolvedValue(Response.json({ ...turnFixture, actions, audio_url: 'https://provider.example/private.mp3' }))
    const result = await createLiveApi({ fetcher }).text('session-1', 'request-1', 'Офис')
    expect(result.actions).toEqual(actions); expect(result.reply).toBe('В каком городе вы ищете офис?')
    expect(result.audio_url).toBeNull()
    expect(result.warnings).toContainEqual(expect.objectContaining({ code: 'unsupported_audio_url' }))
  })
  it('rejects a response for a different request', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ ...turnFixture, request_id: 'other' }))
    await expect(createLiveApi({ fetcher }).text('session-1', 'request-1', 'Офис')).rejects.toMatchObject({ code: 'invalid_response' })
  })
  it('fetches history and validates the owning session', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(Response.json({ turns: [turnFixture] })).mockResolvedValueOnce(Response.json({ turns: [{ ...turnFixture, session_id: 'other' }] }))
    const api = createLiveApi({ fetcher })
    expect(await api.history('session-1')).toHaveLength(1)
    expect(fetcher.mock.calls[0][0]).toBe('/api/sessions/session-1/turns')
    await expect(api.history('session-1')).rejects.toMatchObject({ code: 'invalid_response' })
  })
  it('obtains a room token without sending speech provider keys', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ room: 'saqta-s1', token: 'room-token', ws_url: 'ws://127.0.0.1:7880', session_id: 'session-1', trace_topic: 'saqta.trace' }))
    const room = await createLiveApi({ fetcher }).livekit('session-1')
    expect(room.room).toBe('saqta-s1')
    expect(fetcher.mock.calls[0][0]).toBe('/api/sessions/session-1/livekit')
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({})
  })
  it('exposes configured speech independently of verified voice readiness', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ status: 'ok', mode: 'live', voice_ready: false, voice_configured: true, missing_config: [], models: { llm: 'server-selected' } }))
    expect(await createLiveApi({ fetcher }).health()).toMatchObject({ voice_ready: false, voice_configured: true })
  })
  it('times out without automatically repeating a mutation', async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn((_url, options) => new Promise<Response>((_resolve, reject) => { options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))) }))
    const pending = createLiveApi({ fetcher, timeoutMs: 100 }).text('session-1', 'request-1', 'Офис')
    const check = expect(pending).rejects.toMatchObject({ code: 'timeout', requestId: 'request-1', retryable: true })
    await vi.advanceTimersByTimeAsync(101); await check; expect(fetcher).toHaveBeenCalledTimes(1)
  })
  it('validates text before making a request', async () => {
    const fetcher = vi.fn(); const api = createLiveApi({ fetcher })
    await expect(api.text('s', 'r', ' ')).rejects.toBeInstanceOf(ApiError)
    await expect(api.text('s', 'r', 'я'.repeat(4001))).rejects.toBeInstanceOf(ApiError)
    expect(fetcher).not.toHaveBeenCalled()
  })
})
