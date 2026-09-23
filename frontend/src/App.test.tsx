import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { ApiError } from './api/client'
import { turnSchema, type VoiceApi } from './api/types'
import { turnFixture } from './test/fixture'

function api(overrides: Partial<VoiceApi> = {}): VoiceApi {
  return { health: async () => ({ status: 'ok', mode: 'live', voice_ready: false, voice_configured: false, missing_config: [], models: {} }), createSession: vi.fn().mockResolvedValue({ session_id: 'session-1', as_of_date: '2026-10-01' }), text: vi.fn().mockImplementation(async (_s, requestId, text) => turnSchema.parse({ ...turnFixture, request_id: requestId, transcript: text })), history: vi.fn().mockResolvedValue([]), livekit: vi.fn(), ...overrides }
}
async function ready() { await waitFor(() => expect(screen.getByLabelText('Ваша реплика')).toBeEnabled()) }
function send(text: string) { fireEvent.change(screen.getByLabelText('Ваша реплика'), { target: { value: text } }); fireEvent.click(screen.getByRole('button', { name: 'Отправить реплику' })) }

describe('conversation lifecycle', () => {
  it('shows a backend error, preserves the input, and retries with the same request ID', async () => {
    const text = vi.fn().mockRejectedValueOnce(new ApiError('Речь недоступна', 'provider_unavailable', true, 503)).mockImplementation(async (_s, requestId, transcript) => turnSchema.parse({ ...turnFixture, request_id: requestId, transcript }))
    render(<App liveApi={api({ text })} />)
    await ready(); send('Сәлем, кеңсе қайда?')
    expect(await screen.findByRole('alert')).toHaveTextContent('Речь недоступна')
    expect(screen.queryByText('В каком городе вы ищете офис?')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Ваша реплика')).toHaveValue('Сәлем, кеңсе қайда?')
    fireEvent.click(screen.getByRole('button', { name: 'Повторить запрос' }))
    expect(await screen.findByText('В каком городе вы ищете офис?')).toBeInTheDocument()
    expect(text.mock.calls[0][1]).toBe(text.mock.calls[1][1])
  })
  it('renders unknown latency honestly and resets history for a new dialog', async () => {
    const client = api()
    render(<App liveApi={client} />)
    await ready(); send('Где ваш офис?')
    await screen.findByText('В каком городе вы ищете офис?')
    expect(screen.getAllByText('не измерено').length).toBeGreaterThan(1)
    fireEvent.click(screen.getByRole('button', { name: 'Новый диалог' }))
    await waitFor(() => expect(screen.queryByText('В каком городе вы ищете офис?')).not.toBeInTheDocument())
    expect(client.createSession).toHaveBeenCalledTimes(2)
  })
  it('renders pending preview without claiming an action was executed', async () => {
    const client = api({ text: async (_s, r, t) => turnSchema.parse({ ...turnFixture, request_id: r, transcript: t, decision: 'confirm', actions: [{ name: 'cancel_policy', mode: 'preview', status: 'ok', result: { refund_amount: 11400 } }], pending_confirmation: { confirmation_id: 'c1', action: 'cancel_policy', parameters: { policy_number: 'SQ-OGPO-104501' }, summary: 'Расторжение полиса SQ-OGPO-104501' } }) })
    render(<App liveApi={client} />); await ready(); send('Расторгнуть полис')
    expect(await screen.findByText('Ожидается подтверждение')).toBeInTheDocument()
    expect(screen.getByText('Предпросмотр')).toBeInTheDocument()
    expect(screen.queryByText('Выполнено')).not.toBeInTheDocument()
    expect(screen.getByText('Расторжение полиса SQ-OGPO-104501')).toBeInTheDocument()
  })
  it('marks an operator handoff as simulated and displays its context', async () => {
    const client = api({ text: async (_s, r, t) => turnSchema.parse({ ...turnFixture, request_id: r, transcript: t, decision: 'handoff', handoff: { queue: 'claims_team', summary: 'Клиент оспаривает сумму выплаты.' } }) })
    render(<App liveApi={client} />); await ready(); send('Позовите оператора')
    expect(await screen.findByText('Передача оператору — симуляция')).toBeInTheDocument()
    expect(screen.getByText('Клиент оспаривает сумму выплаты.')).toBeInTheDocument()
    expect(screen.getByText('Урегулирование страховых случаев')).toBeInTheDocument()
  })
  it('blocks rapid double submit until the pending request finishes', async () => {
    const client = api({ text: vi.fn(() => new Promise<never>(() => {})) })
    render(<App liveApi={client} />); await ready(); send('Офис')
    fireEvent.click(screen.getByRole('button', { name: 'Отправить реплику' }))
    expect(client.text).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('status')).toHaveTextContent('Обработка текста')
  })
})
