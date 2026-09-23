import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { VoiceControls } from './VoiceControls'
import type { Health, VoiceApi } from '../api/types'
const fake = vi.hoisted(() => ({ opts: null as any, stop: vi.fn(), start: vi.fn() }))
vi.mock('../voice/livekit', () => ({ LiveVoice: class {
  constructor(opts: any) { fake.opts = opts }
  stop() { fake.stop(); fake.opts.onPhase('idle') }
  start() { fake.start(); fake.opts.onPhase('connected') }
} }))
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })
function setup() {
  const recover = vi.fn()
  render(<VoiceControls api={{} as VoiceApi} sessionId="session-1" disabled={false}
    health={{ voice_configured: true, voice_ready: false, missing_config: [] } as unknown as Health}
    mode="live" onTrace={vi.fn()} onRecover={recover} onActivity={vi.fn()} onStatus={vi.fn()}/>)
  fireEvent.click(screen.getByRole('button', { name: 'Начать разговор' }))
  return recover
}
it('recovers the final history when the user ends the conversation', () => {
  const recover = setup()
  fireEvent.click(screen.getByRole('button', { name: 'Завершить разговор' }))
  expect(recover).toHaveBeenCalledTimes(1)
})
it('keeps recovery polling on schedule while speakers change rapidly', () => {
  vi.useFakeTimers()
  const recover = setup()
  for (let i = 0; i < 5; i++) {
    act(() => { vi.advanceTimersByTime(1000); fake.opts.onSpeaking(i % 2 === 0) })
  }
  expect(recover).toHaveBeenCalledTimes(1)
})
