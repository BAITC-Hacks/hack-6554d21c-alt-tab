import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useConversation } from './useConversation'
import { turnSchema, type TurnResult, type VoiceApi } from './api/types'
import { turnFixture } from './test/fixture'
function api(): VoiceApi {
  let id = 0
  return { health: async () => ({ status: 'ok', mode: 'live', voice_ready: false, voice_configured: true, missing_config: [], models: {} }), createSession: async () => ({ session_id: 'session-' + ++id, as_of_date: '2026-10-01' }), history: vi.fn().mockResolvedValue([]), livekit: vi.fn(), text: vi.fn() }
}
describe('recovered voice history', () => {
  it('deduplicates data packets and recovered history by turn_id and preserves turn order', async () => {
    const client = api()
    const first = turnSchema.parse(turnFixture), second = turnSchema.parse({ ...turnFixture, turn_id: 'turn-2', turn: 2, request_id: 'request-2' })
    vi.mocked(client.history).mockResolvedValue([first, second])
    const { result } = renderHook(() => useConversation(client))
    await waitFor(() => expect(result.current.session?.session_id).toBe('session-1'))
    act(() => { result.current.receive(second); result.current.receive(second) })
    await act(async () => { await result.current.recover() })
    expect(result.current.turns.map(turn => turn.result.turn_id)).toEqual(['turn-1', 'turn-2'])
  })
  it('ignores old history and old voice packets after a new dialog', async () => {
    const client = api(); let resolve!: (turns: TurnResult[]) => void
    vi.mocked(client.history).mockImplementation(() => new Promise(res => { resolve = res }))
    const { result } = renderHook(() => useConversation(client))
    await waitFor(() => expect(result.current.session?.session_id).toBe('session-1'))
    let recovering!: Promise<void>
    act(() => { recovering = result.current.recover() })
    await act(async () => { await result.current.newDialog() })
    await act(async () => { resolve([turnSchema.parse(turnFixture)]); await recovering })
    act(() => result.current.receive(turnSchema.parse(turnFixture)))
    expect(result.current.session?.session_id).toBe('session-2')
    expect(result.current.turns).toHaveLength(0)
  })
})
