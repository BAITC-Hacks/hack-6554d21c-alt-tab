import { z } from 'zod'
import type { LocalAudioTrack, Room, RemoteTrack } from 'livekit-client'
import { ApiError, normalizeTurn } from '../api/client'
import { turnSchema, type TurnResult, type VoiceApi } from '../api/types'
export type LiveKitSdk = Pick<typeof import('livekit-client'), 'Room' | 'LocalAudioTrack' | 'RoomEvent' | 'Track'>
export type VoicePhase = 'idle' | 'mic' | 'connecting' | 'connected' | 'reconnecting'
type Options = {
  api: VoiceApi; audioContainer: HTMLElement
  onPhase(phase: VoicePhase): void; onBlocked(value: boolean): void; onReady(value: boolean): void
  onSpeaking(value: boolean): void; onError(message: string, requestId?: string): void
  onTrace(result: TurnResult): void; onRecover(): void
}
export class LiveVoice {
  private epoch = 0
  private phase: VoicePhase = 'idle'
  private stream: MediaStream | null = null
  private localTrack: LocalAudioTrack | null = null
  private room: Room | null = null
  private remoteTracks = new Set<RemoteTrack>()
  private controller: AbortController | null = null
  private timers = new Set<ReturnType<typeof setTimeout>>()
  constructor(private opts: Options, private loadSdk: () => Promise<LiveKitSdk> = () => import('livekit-client')) {}
  private setPhase(phase: VoicePhase) { this.phase = phase; this.opts.onPhase(phase) }
  private timer(callback: () => void, ms: number) { const timer = setTimeout(callback, ms); this.timers.add(timer); return timer }
  stop() {
    ++this.epoch
    this.controller?.abort(); this.controller = null
    for (const timer of this.timers) clearTimeout(timer)
    this.timers.clear()
    const room = this.room; this.room = null
    this.localTrack?.stop(); this.localTrack = null
    this.stream?.getTracks().forEach(track => track.stop()); this.stream = null
    for (const track of this.remoteTracks) track.detach().forEach(element => element.remove())
    this.remoteTracks.clear(); this.opts.audioContainer.replaceChildren()
    if (room) void room.disconnect().catch(() => {})
    this.opts.onBlocked(false); this.opts.onReady(false); this.opts.onSpeaking(false); this.setPhase('idle')
  }
  private fail(message: string, requestId?: string) { this.stop(); this.opts.onError(message, requestId) }
  async start(sessionId: string) {
    if (this.phase !== 'idle') return
    if (!navigator.mediaDevices?.getUserMedia) { this.fail('Микрофон доступен только через HTTPS или localhost.'); return }
    const epoch = ++this.epoch, current = () => epoch === this.epoch
    this.controller = new AbortController()
    const signal = this.controller.signal
    this.setPhase('mic')
    const permissionTimer = this.timer(() => { if (current()) this.fail('Не дождались разрешения микрофона. Проверьте запрос браузера.') }, 15_000)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false })
      clearTimeout(permissionTimer)
      if (!current()) { stream.getTracks().forEach(track => track.stop()); return }
      this.stream = stream
      this.setPhase('connecting')
      const connectionTimer = this.timer(() => { if (current()) this.fail('Не удалось подключиться за 30 секунд. Проверьте backend и LiveKit.') }, 30_000)
      // The microphone is already authorized before a server room/agent is dispatched.
      const credentials = await this.opts.api.livekit(sessionId, signal)
      if (!current()) return
      if (credentials.session_id !== sessionId) throw new ApiError('Комната принадлежит другой сессии.', 'invalid_response')
      if (location.protocol === 'https:' && !credentials.ws_url.startsWith('wss:')) throw new ApiError('Для HTTPS требуется защищённый адрес LiveKit (WSS).', 'insecure_livekit_url')
      const sdk = await this.loadSdk()
      if (!current()) return
      const room = new sdk.Room({ adaptiveStream: false, dynacast: false }); this.room = room
      let ready = false
      let readyTimer: ReturnType<typeof setTimeout> | undefined
      const trusted = (participant?: { isAgent: boolean; identity: string }) => participant?.isAgent === true && participant.identity !== room.localParticipant.identity
      room.on(sdk.RoomEvent.TrackSubscribed, (track, _publication, participant) => {
        if (!current() || !trusted(participant) || track.kind !== sdk.Track.Kind.Audio) return
        this.remoteTracks.add(track)
        const element = track.attach(); element.autoplay = true
        this.opts.audioContainer.appendChild(element)
      })
      room.on(sdk.RoomEvent.TrackUnsubscribed, track => {
        if (!current()) return
        track.detach().forEach(element => element.remove()); this.remoteTracks.delete(track)
      })
      room.on(sdk.RoomEvent.AudioPlaybackStatusChanged, () => { if (current()) this.opts.onBlocked(!room.canPlaybackAudio) })
      room.on(sdk.RoomEvent.ActiveSpeakersChanged, participants => { if (current()) this.opts.onSpeaking(participants.some(trusted) && room.canPlaybackAudio) })
      room.on(sdk.RoomEvent.DataReceived, (payload, participant, _kind, topic) => {
        if (!current() || !trusted(participant) || payload.byteLength > 1024 * 1024) return
        if (!['saqta.trace', 'saqta.error', 'saqta.ready'].includes(topic ?? '')) return
        try {
          const data: unknown = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(payload))
          if (topic === credentials.trace_topic) {
            const parsed = turnSchema.safeParse(data)
            if (!parsed.success || parsed.data.session_id !== sessionId) { this.opts.onError('Получена некорректная трасса. Восстанавливаем историю.', undefined); this.opts.onRecover(); return }
            // A validated turn proves agent activity even if the ready packet was missed.
            ready = true; clearTimeout(readyTimer); this.opts.onReady(true)
            this.opts.onTrace(normalizeTurn(parsed.data))
          } else if (topic === 'saqta.ready') {
            const parsed = z.object({ session_id: z.literal(sessionId), mode: z.literal('live') }).safeParse(data)
            if (parsed.success) { ready = true; clearTimeout(readyTimer); this.opts.onReady(true); this.opts.onRecover() }
          } else {
            const parsed = z.object({ stage: z.enum(['voice', 'router']), message: z.string(), request_id: z.string().optional() }).safeParse(data)
            if (parsed.success) { this.opts.onError(parsed.data.message, parsed.data.request_id); this.opts.onRecover() }
          }
        } catch { this.opts.onError('Не удалось прочитать пакет агента. Восстанавливаем историю.', undefined); this.opts.onRecover() }
      })
      room.on(sdk.RoomEvent.Reconnecting, () => { if (current()) { this.setPhase('reconnecting'); this.opts.onSpeaking(false) } })
      room.on(sdk.RoomEvent.Reconnected, () => { if (current()) { this.setPhase('connected'); this.opts.onRecover() } })
      room.on(sdk.RoomEvent.Disconnected, () => { if (current()) { this.stop(); this.opts.onRecover() } })
      await room.connect(credentials.ws_url, credentials.token)
      if (!current()) { void room.disconnect(); return }
      const mediaTrack = stream.getAudioTracks()[0]
      if (!mediaTrack) throw new Error('Missing microphone track')
      const local = new sdk.LocalAudioTrack(mediaTrack); this.localTrack = local
      mediaTrack.addEventListener('ended', () => { if (current()) this.fail('Микрофон отключён. Подключите устройство и начните разговор снова.') })
      await room.localParticipant.publishTrack(local, { source: sdk.Track.Source.Microphone })
      if (!current()) { local.stop(); void room.disconnect(); return }
      clearTimeout(connectionTimer)
      this.setPhase('connected'); this.opts.onBlocked(!room.canPlaybackAudio); this.opts.onRecover()
      if (!ready) readyTimer = this.timer(() => { if (current()) this.fail('Комната подключена, но агент не подтвердил запуск за 30 секунд. Используйте текстовый ввод.') }, 30_000)
    } catch (error) {
      if (!current()) return
      const name = error instanceof DOMException ? error.name : ''
      const message = name === 'NotAllowedError' ? 'Доступ к микрофону запрещён. Разрешите его в настройках сайта или отправьте текст.'
        : name === 'NotFoundError' ? 'Микрофон не найден. Подключите устройство или отправьте текст.'
        : error instanceof ApiError ? error.message : 'Не удалось подключить голос. Проверьте микрофон, backend и доступность LiveKit.'
      this.fail(message)
    }
  }
  async startAudio() {
    const room = this.room, epoch = this.epoch
    if (!room) return
    try { await room.startAudio(); if (epoch === this.epoch) this.opts.onBlocked(!room.canPlaybackAudio) }
    catch { if (epoch === this.epoch) this.opts.onError('Браузер не включил звук. Проверьте разрешение воспроизведения.', undefined) }
  }
}
