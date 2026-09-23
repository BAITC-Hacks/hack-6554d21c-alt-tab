import { z } from 'zod'

const id = z.string().min(1)
const scenarioId = z.string().regex(/^(SC(0[1-9]|[1-3][0-9]|40)|SYS_(UNCLEAR|OUT_OF_SCOPE|GOODBYE))$/)
const metric = z.number().finite().nonnegative().nullable()
const jsonObject = z.record(z.string(), z.json())
const scenario = z.object({ scenario_id: scenarioId, confidence: z.number().min(0).max(1) })
const actionBase = { name: id, mode: z.enum(['preview', 'execute']) }
export const actionSchema = z.discriminatedUnion('status', [
  z.object({ ...actionBase, status: z.literal('ok'), result: z.json() }),
  z.object({ ...actionBase, status: z.literal('error'), error: z.object({ code: id, message: z.string() }) }),
])
export const healthSchema = z.object({ status: z.literal('ok'), mode: z.enum(['live', 'mock']), voice_ready: z.boolean(), voice_configured: z.boolean().default(false), missing_config: z.array(z.string()).default([]), models: z.record(z.string(), z.unknown()).default({}) })
export const sessionSchema = z.object({ session_id: id, as_of_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/) })
export const turnSchema = z.object({
  session_id: id, request_id: id, turn_id: id, turn: z.number().int().positive(),
  mode: z.enum(['live', 'mock']), transcript: z.string(),
  language: z.enum(['ru', 'kk', 'mixed']), response_language: z.enum(['ru', 'kk']),
  scenarios: z.array(scenario), alternatives: z.array(scenario), reason: z.string(),
  is_continuation: z.boolean(),
  decision: z.enum(['collect_slots', 'execute', 'confirm', 'clarify', 'handoff', 'goodbye', 'out_of_scope']),
  active_scenario: scenarioId.nullable(), queued_scenarios: z.array(scenarioId),
  slots: jsonObject, missing_slots: z.array(z.string()), actions: z.array(actionSchema),
  pending_confirmation: z.object({ confirmation_id: id, action: id, parameters: jsonObject, summary: z.string() }).nullable(),
  handoff: z.object({ queue: z.enum(['operator_general', 'claims_team', 'medical_assistance_24_7', 'corporate_sales', 'complaints_team', 'security_team']), summary: z.string() }).nullable(),
  reply: z.string(), audio_url: z.string().nullable(),
  latency_ms: z.object({ stt: metric, triage: metric, router: metric, response: metric, tts_first_audio: metric, total: metric }),
  server_processing_ms: metric,
  warnings: z.array(z.object({ stage: z.string(), code: z.string(), message: z.string() })),
})
export type TurnResult = z.infer<typeof turnSchema>
export type Health = z.infer<typeof healthSchema>
export type Session = z.infer<typeof sessionSchema>
export type Mode = 'live' | 'mock'
export const roomSchema = z.object({
  room: id, token: id, ws_url: z.string().url().refine(value => /^wss?:/.test(value)),
  session_id: id, trace_topic: z.literal('saqta.trace'),
})
export type RoomCredentials = z.infer<typeof roomSchema>
export interface DisplayTurn { result: TurnResult; source: 'text' | 'voice' | 'history' }
export interface VoiceApi {
  health(signal?: AbortSignal): Promise<Health>
  createSession(signal?: AbortSignal): Promise<Session>
  text(sessionId: string, requestId: string, text: string, signal?: AbortSignal): Promise<TurnResult>
  history(sessionId: string, signal?: AbortSignal): Promise<TurnResult[]>
  livekit(sessionId: string, signal?: AbortSignal): Promise<RoomCredentials>
}
