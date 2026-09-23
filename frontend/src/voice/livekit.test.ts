import { afterEach, describe, expect, it, vi } from 'vitest'
import { RoomEvent, Track } from 'livekit-client'
import { LiveVoice, type LiveKitSdk } from './livekit'
import { turnFixture } from '../test/fixture'
import type { VoiceApi } from '../api/types'
class FakeRoom {
  static last: FakeRoom
  handlers = new Map<string, ((...args: any[]) => void)[]>()
  localParticipant = { identity: 'browser', publishTrack: vi.fn().mockResolvedValue({}) }
  canPlaybackAudio = true
  connect = vi.fn().mockResolvedValue(undefined)
  disconnect = vi.fn().mockResolvedValue(undefined)
  startAudio = vi.fn().mockImplementation(async () => { this.canPlaybackAudio = true })
  on(event: string, fn: (...args: any[]) => void) { this.handlers.set(event, [...(this.handlers.get(event) ?? []), fn]); return this }
  emit(event: string, ...args: any[]) { this.handlers.get(event)?.forEach(fn => fn(...args)) }
  constructor() { FakeRoom.last = this }
}
class FakeLocalTrack { constructor(private track: MediaStreamTrack) {} stop() { this.track.stop() } }
const sdk = { Room: FakeRoom, LocalAudioTrack: FakeLocalTrack, RoomEvent, Track } as unknown as LiveKitSdk
function setup(get?: () => Promise<MediaStream>) {
  const stop = vi.fn(), track = Object.assign(new EventTarget(), { stop })
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] } as unknown as MediaStream
  const getUserMedia = vi.fn(get ?? (async () => stream))
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } })
  const api = { livekit: vi.fn().mockResolvedValue({ room: 'room', token: 'secret-room-token', ws_url: 'ws://127.0.0.1:7880', session_id: 'session-1', trace_topic: 'saqta.trace' }) } as unknown as VoiceApi
  const onTrace = vi.fn(), onError = vi.fn(), onReady = vi.fn(), onBlocked = vi.fn(), onPhase = vi.fn(), onRecover = vi.fn()
  const container = document.createElement('div')
  const voice = new LiveVoice({ api, audioContainer: container, onTrace, onError, onReady, onBlocked, onPhase, onRecover, onSpeaking: vi.fn() }, async () => sdk)
  return { voice, api, stop, stream, onTrace, onError, onReady, onBlocked, onPhase, getUserMedia, container, onRecover }
}
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers() })
describe('LiveKit lifecycle v2', () => {
  it('obtains mic permission before requesting a room token and publishes the acquired track', async () => {
    const r = setup(); await r.voice.start('session-1')
    expect(r.getUserMedia.mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(r.api.livekit).mock.invocationCallOrder[0])
    expect(FakeRoom.last.localParticipant.publishTrack).toHaveBeenCalledTimes(1)
    r.voice.stop(); expect(r.stop).toHaveBeenCalled(); expect(FakeRoom.last.disconnect).toHaveBeenCalled()
  })
  it('does not request a room if mic permission is denied', async () => {
    const r = setup(async () => { throw new DOMException('denied', 'NotAllowedError') })
    await r.voice.start('session-1')
    expect(r.api.livekit).not.toHaveBeenCalled(); expect(r.onError).toHaveBeenCalledWith(expect.stringContaining('запрещён'), undefined)
  })
  it('releases microphone granted after cancellation and never dispatches a room', async () => {
    let resolve!: (value: MediaStream) => void
    const r = setup(() => new Promise(res => { resolve = res }))
    const pending = r.voice.start('session-1'); r.voice.stop(); resolve(r.stream); await pending
    expect(r.stop).toHaveBeenCalled(); expect(r.api.livekit).not.toHaveBeenCalled()
  })
  it('accepts only valid session traces from a remote agent and ignores other senders/topics', async () => {
    const r = setup(); await r.voice.start('session-1')
    const room = FakeRoom.last, bytes = new TextEncoder().encode(JSON.stringify(turnFixture))
    room.emit(RoomEvent.DataReceived, bytes, { identity: 'stranger', isAgent: false }, undefined, 'saqta.trace')
    room.emit(RoomEvent.DataReceived, bytes, { identity: 'browser', isAgent: true }, undefined, 'saqta.trace')
    room.emit(RoomEvent.DataReceived, bytes, { identity: 'agent', isAgent: true }, undefined, 'other.topic')
    expect(r.onTrace).not.toHaveBeenCalled()
    room.emit(RoomEvent.DataReceived, bytes, { identity: 'agent', isAgent: true }, undefined, 'saqta.trace')
    expect(r.onTrace).toHaveBeenCalledWith(expect.objectContaining({ turn_id: 'turn-1' }))
    room.emit(RoomEvent.DataReceived, new TextEncoder().encode(JSON.stringify({ ...turnFixture, session_id: 'other' })), { identity: 'agent', isAgent: true }, undefined, 'saqta.trace')
    expect(r.onTrace).toHaveBeenCalledTimes(1)
    r.voice.stop()
  })
  it('keeps an active agent connected when its ready packet was lost', async () => {
    vi.useFakeTimers()
    const r = setup(); await r.voice.start('session-1')
    FakeRoom.last.emit(RoomEvent.DataReceived, new TextEncoder().encode(JSON.stringify(turnFixture)), { identity: 'agent', isAgent: true }, undefined, 'saqta.trace')
    vi.advanceTimersByTime(31_000)
    expect(FakeRoom.last.disconnect).not.toHaveBeenCalled()
    expect(r.onReady).toHaveBeenLastCalledWith(true)
    r.voice.stop()
  })
  it('exposes room readiness without treating it as a measured voice result', async () => {
    const r = setup(); await r.voice.start('session-1')
    FakeRoom.last.emit(RoomEvent.DataReceived, new TextEncoder().encode(JSON.stringify({ session_id: 'session-1', mode: 'live' })), { identity: 'agent', isAgent: true }, undefined, 'saqta.ready')
    expect(r.onReady).toHaveBeenCalledWith(true); expect(r.onTrace).not.toHaveBeenCalled()
    r.voice.stop()
  })
  it('shows autoplay block and calls startAudio on explicit user action', async () => {
    const r = setup(); await r.voice.start('session-1')
    FakeRoom.last.canPlaybackAudio = false; FakeRoom.last.emit(RoomEvent.AudioPlaybackStatusChanged)
    expect(r.onBlocked).toHaveBeenLastCalledWith(true)
    await r.voice.startAudio(); expect(FakeRoom.last.startAudio).toHaveBeenCalledTimes(1)
    expect(r.onBlocked).toHaveBeenLastCalledWith(false)
    r.voice.stop()
  })
  it('attaches only remote-agent audio and removes it on unsubscribe and stop', async () => {
    const r = setup(); await r.voice.start('session-1')
    const element = document.createElement('audio'), track = { kind: 'audio', attach: () => element, detach: () => [element] }
    FakeRoom.last.emit(RoomEvent.TrackSubscribed, track, {}, { identity: 'agent', isAgent: true })
    expect(r.container.contains(element)).toBe(true)
    FakeRoom.last.emit(RoomEvent.TrackUnsubscribed, track)
    expect(r.container.childElementCount).toBe(0)
    r.voice.stop()
  })
  it('requests history after reconnect and reports server error request IDs', async () => {
    const r = setup(); await r.voice.start('session-1')
    FakeRoom.last.emit(RoomEvent.Reconnected); expect(r.onRecover).toHaveBeenCalled()
    FakeRoom.last.emit(RoomEvent.DataReceived, new TextEncoder().encode(JSON.stringify({ stage: 'router', message: 'Router недоступен', request_id: 'voice-r1' })), { identity: 'agent', isAgent: true }, undefined, 'saqta.error')
    expect(r.onError).toHaveBeenCalledWith('Router недоступен', 'voice-r1')
    r.voice.stop()
  })
})
