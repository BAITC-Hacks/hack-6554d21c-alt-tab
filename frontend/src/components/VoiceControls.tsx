import { useEffect, useRef, useState } from 'react'
import { LiveVoice, type VoicePhase } from '../voice/livekit'
import type { Health, TurnResult, VoiceApi } from '../api/types'
import { Icon } from './Icon'
export function VoiceControls({ api, sessionId, disabled, health, mode, onTrace, onRecover, onActivity, onStatus }: {
  api: VoiceApi; sessionId?: string; disabled: boolean; health: Health | null; mode: 'live' | 'mock'
  onTrace(result: TurnResult): void; onRecover(): void; onActivity(active: boolean): void; onStatus(status: string | null): void
}) {
  const [phase, setPhase] = useState<VoicePhase>('idle'), [blocked, setBlocked] = useState(false), [ready, setReady] = useState(false), [speaking, setSpeaking] = useState(false)
  const [error, setError] = useState<{ message: string; requestId?: string } | null>(null)
  const container = useRef<HTMLDivElement>(null), voice = useRef<LiveVoice | null>(null)
  const callbacks = useRef({ onTrace, onRecover, onActivity, onStatus }); callbacks.current = { onTrace, onRecover, onActivity, onStatus }
  useEffect(() => {
    const instance = new LiveVoice({
      api, audioContainer: container.current!,
      onPhase: value => { setPhase(value); callbacks.current.onActivity(value !== 'idle') },
      onBlocked: setBlocked, onReady: setReady, onSpeaking: setSpeaking,
      onError: (message, requestId) => setError({ message, requestId }),
      onTrace: result => callbacks.current.onTrace(result), onRecover: () => callbacks.current.onRecover(),
    })
    voice.current = instance
    return () => { instance.stop(); voice.current = null }
  }, [api])
  useEffect(() => {
    const status = phase === 'mic' ? 'Ожидание микрофона' : phase === 'connecting' ? 'Подключение голоса' : phase === 'reconnecting' ? 'Восстановление соединения' : phase === 'connected' ? speaking && !blocked ? 'Говорит помощник' : ready ? 'Голосовой разговор' : 'Ожидание агента' : null
    callbacks.current.onStatus(status)
  }, [phase, ready, speaking, blocked])
  useEffect(() => {
    if (phase !== 'connected' && phase !== 'reconnecting') return
    const timer = setInterval(() => callbacks.current.onRecover(), 4000)
    return () => clearInterval(timer)
  }, [phase])
  useEffect(() => {
    const stop = () => voice.current?.stop()
    window.addEventListener('pagehide', stop)
    return () => window.removeEventListener('pagehide', stop)
  }, [])
  function start() { if (!sessionId) return; setError(null); void voice.current?.start(sessionId) }
  const configured = health?.voice_configured === true
  const connecting = phase === 'mic' || phase === 'connecting'
  return <div className="voice-section">
    <div ref={container} className="remote-audio" aria-hidden="true"/>
    {error && <div className="error-box" role="alert"><p>{error.message}</p>{error.requestId && <p>request_id: <code>{error.requestId}</code></p>}</div>}
    {blocked && <div className="audio-notice"><p>Браузер заблокировал автоматический звук.</p><button className="button" onClick={() => { void voice.current?.startAudio() }}><Icon name="play"/>Включить звук</button></div>}
    <div className="voice-controls">
      {phase === 'idle'
        ? <button className="button primary" disabled={disabled || !configured || mode === 'mock'} onClick={start}><Icon name="mic"/>Начать разговор</button>
        : <button className={`button recording ${connecting ? 'connecting' : ''}`} onClick={() => { voice.current?.stop(); callbacks.current.onRecover() }}><Icon name="stop"/>{connecting ? 'Отменить подключение' : 'Завершить разговор'}</button>}
      <p className={`small ${phase === 'idle' ? 'muted' : 'voice-state'}`}>
        {phase !== 'idle' && <span className={`live-dot ${connecting || (phase === 'connected' && !ready) ? 'waiting' : speaking && !blocked ? 'speaking' : ''}`} aria-hidden="true"/>}
        {mode === 'mock' ? 'Голос доступен только в Live'
          : phase === 'mic' ? 'Разрешите доступ к микрофону в браузере.'
          : phase === 'connecting' ? 'Подключаемся к голосовому каналу…'
          : phase === 'reconnecting' ? 'Восстанавливаем соединение…'
          : phase === 'connected' ? (!ready ? 'Соединение есть. Ждём помощника…' : speaking && !blocked ? 'Говорит помощник.' : 'Слушаю. Говорите своими словами.')
          : configured ? health?.voice_ready ? 'Голос настроен. Можно подключиться.' : 'Настройки есть; живой голос ещё не проверен.' : 'Голос не настроен. Используйте текст.'}
      </p>
    </div>
    {mode === 'live' && !configured && Boolean(health?.missing_config.length) && <details className="small muted"><summary>Чего не хватает для голоса</summary><p>{health!.missing_config.join(', ')}</p></details>}
  </div>
}
