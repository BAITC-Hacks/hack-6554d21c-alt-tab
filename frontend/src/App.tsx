import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { createLiveApi } from './api/client'
import { createMockApi, examples, type ExampleId } from './api/mock'
import type { Mode, VoiceApi } from './api/types'
import { TracePanel } from './components/TracePanel'
import { Icon } from './components/Icon'
import { languages, scenarioName } from './data/labels'
import { useConversation } from './useConversation'
import { VoiceControls } from './components/VoiceControls'

const defaultLiveApi = createLiveApi()
export function App({ liveApi = defaultLiveApi }: { liveApi?: VoiceApi }) {
  const [mode, setMode] = useState<Mode>('live')
  const [example, setExample] = useState<ExampleId>('office-ru')
  const exampleRef = useRef(example); exampleRef.current = example
  const mockApi = useMemo(() => createMockApi(() => exampleRef.current), [])
  const conversation = useConversation(mode === 'live' ? liveApi : mockApi)
  const { session, health, turns, busy, error, pending } = conversation
  const [draft, setDraft] = useState('')
  const [recordingActive, setRecordingActive] = useState(false)
  const [voiceStatus, setVoiceStatus] = useState<string | null>(null)
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => { end.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }) }, [turns.length, busy])
  const disabled = Boolean(busy || !session || pending || recordingActive)
  const effectiveMode = health?.mode ?? mode
  const status = voiceStatus ?? (busy === 'starting' ? 'Создание диалога' : busy === 'text' ? 'Обработка текста' : error ? 'Ошибка' : session ? 'Готов к разговору' : 'Нет соединения')

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!draft.trim() || disabled) return
    if (await conversation.send(draft)) setDraft('')
  }
  function changeMode(value: Mode) { if (value !== mode) { setDraft(''); setMode(value) } }
  function newDialog() { setDraft(''); void conversation.newDialog() }
  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="/" aria-label="Saqta Insurance">saqta<span>insurance</span></a><span className="topbar-caption">Лаборатория голосового сервиса</span><div className="topbar-right"><span className="language-note">Русский / Қазақша</span><div className="mode-switch" role="group" aria-label="Режим подключения"><button aria-pressed={mode === 'live'} disabled={Boolean(busy || recordingActive)} onClick={() => changeMode('live')}>Live</button><button aria-pressed={mode === 'mock'} disabled={Boolean(busy || recordingActive)} onClick={() => changeMode('mock')}>Mock</button></div></div></header>
    <main><div className="page-heading"><div><span className="eyebrow">Голосовой симулятор</span><h1>Разговор, который понятен.</h1><p>Говорите своими словами. Логика каждого ответа — рядом.</p></div><button className="button" disabled={Boolean(busy || recordingActive)} onClick={newDialog}><Icon name="plus"/>Новый диалог</button></div>
      {mode === 'mock' && <div className="mock-banner"><div><strong>Mock — демонстрация интерфейса</strong><p>Ответ определяется выбранным примером. Текст не анализируется; голос и реальные задержки недоступны.</p></div><label>Пример<select value={example} disabled={Boolean(busy || pending)} onChange={event => { const id = event.target.value as ExampleId; setExample(id); setDraft(examples.find(item => item.id === id)!.text) }}>{examples.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label></div>}
      {mode === 'live' && effectiveMode === 'mock' && <div className="mock-banner"><strong>Backend работает в Mock. Ответы не являются результатом живой маршрутизации.</strong></div>}
      <div className="workspace"><section className="conversation panel" aria-label="Разговор">
        <div className="panel-header"><div className="header-title"><span className="assistant-avatar"><Icon name="headphones"/></span><div><h2>Помощник Saqta</h2><p className="small muted">Страхование без сложных вопросов</p></div></div><span className={`badge ${effectiveMode === 'mock' ? 'amber' : 'green'}`}>{effectiveMode === 'mock' ? 'Mock' : 'Live'}</span></div>
        <div className="conversation-meta"><span className={`status-dot ${error ? 'failed' : busy ? 'working' : ''}`}/><span role="status">{status}</span><span className="turn-count">{turns.length ? `Ходов: ${turns.length}` : 'Новый разговор'}</span></div>
        <div className="message-feed" role="log" aria-label="Лента разговора" aria-live="polite">
          {turns.length === 0 && !pending && <div className="welcome"><div className="voice-emblem"><Icon name="mic"/><span/><span/><span/></div><h2>Начните с простого вопроса</h2><p>Об офисах, полисе или страховом случае.<br/>Можно говорить на русском и қазақша.</p><div className="suggestions">{['Где ваш офис в Алматы?', 'Полисімнің мерзімін тексергім келеді', 'Хочу записаться к врачу по ДМС'].map(text => <button key={text} disabled={disabled} onClick={() => setDraft(text)}>{text}<Icon name="arrow"/></button>)}</div></div>}
          {turns.map(turn => <article className={`turn ${conversation.selected?.result.turn_id === turn.result.turn_id ? 'selected' : ''}`} key={turn.result.turn_id}>
            <div className="message user-message"><span className="message-author">Вы <span>{languages[turn.result.language]}</span></span><p lang={turn.result.language === 'kk' ? 'kk' : 'ru'}>{turn.result.transcript}</p></div>
            <div className="message assistant-message"><span className="message-author">Saqta <span>{turn.result.mode === 'mock' ? 'Mock' : 'Live'}</span></span><p lang={turn.result.response_language}>{turn.result.reply}</p>{turn.result.warnings.filter(w => w.stage !== 'mock').map((w, i) => <p className="warning-note" key={i}>{w.message}</p>)}<button className="trace-link" aria-pressed={conversation.selected?.result.turn_id === turn.result.turn_id} onClick={() => conversation.selectTurn(turn.result.turn_id)}><Icon name="trace"/><span>Ход {turn.result.turn} · {turn.result.scenarios[0] ? scenarioName(turn.result.scenarios[0].scenario_id) : 'Без сценария'}</span><Icon name="arrow"/></button></div>
          </article>)}
          {pending && <div className="pending-message"><p>{pending.content}</p><span>{busy ? status : 'Ответ не получен'}</span></div>}
          <div ref={end}/>
        </div>
        <div className="composer">
          {error && <div className="error-box" role="alert"><strong>{error.message}</strong>{error.requestId && <p className="small">request_id: <code>{error.requestId}</code></p>}<p className="small">{error.code}</p>{error.retryable && <button className="button" disabled={Boolean(busy || recordingActive)} onClick={() => { void conversation.retry().then(ok => { if (ok) setDraft('') }) }}>Повторить запрос</button>}{pending && <p className="small">Повтор использует тот же ID. Чтобы начать заново, создайте новый диалог.</p>}</div>}
          {conversation.historyError && <div className="error-box" role="alert"><p>Не удалось восстановить трассу: {conversation.historyError}</p></div>}
          {mode === 'live' && session && <button className="trace-link" disabled={Boolean(busy)} onClick={() => { void conversation.recover() }}><Icon name="trace"/>Обновить историю</button>}
          <VoiceControls key={session?.session_id ?? mode} api={mode === 'live' ? liveApi : mockApi} sessionId={session?.session_id} disabled={Boolean(busy || !session || pending)} health={health} mode={mode} onTrace={conversation.receive} onRecover={() => { void conversation.recover() }} onActivity={setRecordingActive} onStatus={setVoiceStatus}/>
          <form onSubmit={submit}><label className="sr-only" htmlFor="message">Ваша реплика</label><div className="text-input"><textarea id="message" rows={2} maxLength={4000} value={draft} disabled={disabled} placeholder="Или напишите сообщение…" onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit() } }}/><button aria-label="Отправить реплику" className="send-button" type="submit" disabled={disabled || !draft.trim()}><Icon name="send"/></button></div><div className="input-footer"><span>Enter — отправить · Shift + Enter — новая строка</span><span>{draft.length}/4000</span></div></form>
        </div>
      </section><TracePanel turn={conversation.selected}/></div>
      <footer className="page-footer"><span>Симулятор Saqta Insurance · Синтетические данные</span><span>{session ? `Данные на ${session.as_of_date.split('-').reverse().join('.')}` : 'Ожидание подключения'}</span></footer>
    </main>
  </div>
}
