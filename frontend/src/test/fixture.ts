export const turnFixture = {
  session_id: 'session-1', request_id: 'request-1', turn_id: 'turn-1', turn: 1,
  mode: 'live', transcript: 'Где ваш офис?', language: 'ru', response_language: 'ru',
  scenarios: [{ scenario_id: 'SC33', confidence: 0.92 }], alternatives: [],
  reason: 'Нужно уточнить город.', is_continuation: false, decision: 'collect_slots',
  active_scenario: 'SC33', queued_scenarios: [], slots: {}, missing_slots: ['city'],
  actions: [], pending_confirmation: null, handoff: null,
  reply: 'В каком городе вы ищете офис?', audio_url: null,
  latency_ms: { stt: null, triage: null, router: null, response: null, tts_first_audio: null, total: null },
  server_processing_ms: null, warnings: [],
}
