import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, normalizeTurn } from './api/client'
import type { DisplayTurn, Health, Session, TurnResult, VoiceApi } from './api/types'
type Pending = { id: string; sessionId: string; content: string }
export function useConversation(api: VoiceApi) {
  const [session, setSession] = useState<Session | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [turns, setTurns] = useState<DisplayTurn[]>([])
  const [selectedId, selectTurn] = useState<string | null>(null)
  const [busy, setBusy] = useState<'starting' | 'text' | null>('starting')
  const [error, setError] = useState<ApiError | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  const locked = useRef(false), generation = useRef(0)
  const abort = useRef<AbortController | null>(null)
  const sessionAbort = useRef<AbortController | null>(null)
  const historyBusy = useRef(false)
  const newDialog = useCallback(async () => {
    const epoch = ++generation.current
    abort.current?.abort(); sessionAbort.current?.abort()
    const controller = new AbortController(); sessionAbort.current = controller; abort.current = controller
    locked.current = true; historyBusy.current = false
    setBusy('starting'); setSession(null); setHealth(null); setError(null); setHistoryError(null); setPending(null); setTurns([]); selectTurn(null)
    void api.health(controller.signal).then(value => { if (epoch === generation.current) setHealth(value) }).catch(() => {})
    try { const value = await api.createSession(controller.signal); if (epoch === generation.current) setSession(value) }
    catch (e) { if (epoch === generation.current) setError(e instanceof ApiError ? e : new ApiError('Не удалось создать диалог.', 'session_error', true)) }
    finally { if (epoch === generation.current) { locked.current = false; setBusy(null) } }
  }, [api])
  useEffect(() => { void newDialog(); return () => { ++generation.current; abort.current?.abort(); sessionAbort.current?.abort() } }, [newDialog])
  const merge = useCallback((values: TurnResult[], source: DisplayTurn['source']) => {
    if (!session || !values.length) return
    const valid = values.filter(value => value.session_id === session.session_id).map(normalizeTurn)
    if (!valid.length) return
    setTurns(previous => {
      const map = new Map(previous.map(turn => [turn.result.turn_id, turn]))
      for (const result of valid) if (!map.has(result.turn_id)) map.set(result.turn_id, { result, source })
      return [...map.values()].sort((a, b) => a.result.turn - b.result.turn)
    })
    if (source !== 'history') selectTurn(valid.at(-1)!.turn_id)
    else selectTurn(previous => previous ?? valid.at(-1)!.turn_id)
  }, [session])
  const recover = useCallback(async () => {
    if (!session || historyBusy.current) return
    const epoch = generation.current
    historyBusy.current = true
    try {
      const values = await api.history(session.session_id, sessionAbort.current?.signal)
      if (epoch === generation.current) { merge(values, 'history'); setHistoryError(null) }
    } catch (e) {
      if (epoch === generation.current) setHistoryError(e instanceof Error ? e.message : 'Не удалось восстановить трассу.')
    } finally { if (epoch === generation.current) historyBusy.current = false }
  }, [api, session, merge])
  const execute = useCallback(async (request: Pending) => {
    if (locked.current) return false
    const epoch = generation.current, controller = new AbortController(); abort.current = controller
    locked.current = true; setError(null); setPending(request); setBusy('text')
    try {
      const result = await api.text(request.sessionId, request.id, request.content, controller.signal)
      if (epoch !== generation.current) return false
      merge([result], 'text'); setPending(null)
      return true
    } catch (e) {
      if (epoch === generation.current) {
        const failure = e instanceof ApiError ? e : new ApiError('Не удалось получить ответ. Повторите запрос с тем же ID.', 'network_error', true)
        failure.requestId ??= request.id; setError(failure)
      }
      return false
    } finally { if (epoch === generation.current) { locked.current = false; setBusy(null) } }
  }, [api, merge])
  function send(content: string) {
    if (!session || locked.current || pending) return Promise.resolve(false)
    return execute({ id: crypto.randomUUID(), sessionId: session.session_id, content })
  }
  return { session, health, turns, selected: turns.find(t => t.result.turn_id === selectedId) ?? null, selectTurn, busy, error, historyError, pending, newDialog, send, retry: () => pending ? execute(pending) : newDialog(), recover, receive: (result: TurnResult) => merge([result], 'voice') }
}
