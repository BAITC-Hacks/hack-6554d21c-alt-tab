import { ApiError } from './client'
import type { TurnResult, VoiceApi } from './types'

export const examples = [
  { id: 'office-ru', label: 'Офис · русский', text: 'Где ваш офис в Алматы?' },
  { id: 'office-kk', label: 'Кеңсе · қазақша', text: 'Алматыдағы кеңселеріңіз қайда?' },
  { id: 'doctor-kk', label: 'Дәрігер · қазақша', text: 'Сақтандыру бойынша терапевтке жазып қойыңызшы' },
  { id: 'mixed', label: 'Несколько намерений · mixed', text: 'Маған терапевтке жазылу керек, и ещё список клиник в Алматы.' },
  { id: 'preview', label: 'Предпросмотр расторжения', text: 'Хочу расторгнуть полис SQ-OGPO-104501, продал машину.' },
  { id: 'handoff', label: 'Передача оператору', text: 'Соедините с оператором, деньги списались, а полиса нет.' },
  { id: 'clarify', label: 'Уточнение запроса', text: 'Мне нужно разобраться со страховкой.' },
] as const
export type ExampleId = typeof examples[number]['id']

export function createMockApi(getExample: () => ExampleId): VoiceApi {
  const sessions = new Map<string, { count: number; responses: Map<string, TurnResult> }>()
  return {
    async health() { return { status: 'ok', mode: 'mock', voice_ready: false, voice_configured: false, missing_config: [], models: {} } },
    async createSession() {
      const session_id = crypto.randomUUID()
      sessions.set(session_id, { count: 0, responses: new Map() })
      return { session_id, as_of_date: '2026-10-01' }
    },
    async text(sessionId, requestId, text, signal) {
      if (signal?.aborted) throw new ApiError('Запрос отменён.', 'cancelled')
      const session = sessions.get(sessionId)
      if (!session) throw new ApiError('Диалог не найден.', 'session_not_found', false, 404)
      const existing = session.responses.get(requestId)
      if (existing) return existing
      const result: TurnResult = {
        session_id: sessionId, request_id: requestId, turn_id: crypto.randomUUID(), turn: ++session.count, mode: 'mock', transcript: text,
        language: 'ru', response_language: 'ru', scenarios: [{ scenario_id: 'SC33', confidence: .92 }], alternatives: [],
        reason: 'Пример информационного запроса об офисе в Алматы.', is_continuation: false, decision: 'execute', active_scenario: 'SC33', queued_scenarios: [],
        slots: { city: 'Almaty' }, missing_slots: [], actions: [{ name: 'get_offices', mode: 'execute', status: 'ok', result: { address: 'проспект Абая, 150', hours: 'пн–пт 09:00–18:00, сб 10:00–15:00' } }],
        pending_confirmation: null, handoff: null, reply: 'Наш офис в Алматы: проспект Абая, 150. Работаем с понедельника по пятницу с девяти до восемнадцати, в субботу — с десяти до пятнадцати.', audio_url: null,
        latency_ms: { stt: null, triage: null, router: null, response: null, tts_first_audio: null, total: null }, server_processing_ms: null,
        warnings: [{ stage: 'mock', code: 'fixture', message: 'Демонстрационный ответ. Текст не анализируется, уверенность условная, STT и TTS не выполнялись.' }],
      }
      switch (getExample()) {
        case 'office-kk': Object.assign(result, { language: 'kk', response_language: 'kk', reply: 'Алматыдағы кеңсеміз Абай даңғылы, 150 мекенжайында. Дүйсенбіден жұмаға дейін сағат тоғыздан он сегізге дейін, сенбіде оннан он беске дейін жұмыс істейміз.' }); break
        case 'doctor-kk': Object.assign(result, { language: 'kk', response_language: 'kk', scenarios: [{ scenario_id: 'SC21', confidence: .91 }], reason: 'Пример запроса на запись к терапевту по ДМС.', decision: 'collect_slots', active_scenario: 'SC21', slots: { doctor_specialty: 'therapist' }, missing_slots: ['policy_number', 'city', 'preferred_date'], actions: [], reply: 'Әрине, терапевтке жазылуға көмектесемін. Полис нөміріңізді айтып жіберіңізші.' }); break
        case 'mixed': Object.assign(result, { language: 'mixed', response_language: 'kk', scenarios: [{ scenario_id: 'SC21', confidence: .91 }, { scenario_id: 'SC23', confidence: .87 }], alternatives: [{ scenario_id: 'SC22', confidence: .18 }], reason: 'Два намерения: запись к терапевту и список клиник. Сначала собираем данные для записи, затем возвращаемся к клиникам.', decision: 'collect_slots', active_scenario: 'SC21', queued_scenarios: ['SC23'], slots: { city: 'Almaty', doctor_specialty: 'therapist' }, missing_slots: ['policy_number', 'preferred_date'], actions: [], reply: 'Терапевтке жазылуға көмектесемін, содан кейін емханалар тізімін беремін. Полис нөміріңізді айтыңызшы.' }); break
        case 'preview': Object.assign(result, { scenarios: [{ scenario_id: 'SC28', confidence: .96 }], reason: 'Расторжение меняет состояние полиса, поэтому сначала нужен предпросмотр и явное согласие.', decision: 'confirm', active_scenario: 'SC28', slots: { policy_number: 'SQ-OGPO-104501', cancel_reason: 'Продажа автомобиля' }, actions: [{ name: 'cancel_policy', mode: 'preview', status: 'ok', result: { refund_amount: 11400 } }], pending_confirmation: { confirmation_id: `preview-${requestId}`, action: 'cancel_policy', parameters: { policy_number: 'SQ-OGPO-104501', cancel_reason: 'Продажа автомобиля' }, summary: 'Расторгнуть полис SQ-OGPO-104501. К возврату — 11 400 тенге.' }, reply: 'Подготовлен расчёт: к возврату одиннадцать тысяч четыреста тенге. Подтверждаете расторжение полиса?' }); break
        case 'handoff': Object.assign(result, { scenarios: [{ scenario_id: 'SC37', confidence: .98 }, { scenario_id: 'SC30', confidence: .90 }], reason: 'Клиент просит специалиста по вопросу списания оплаты без выданного полиса.', decision: 'handoff', active_scenario: 'SC37', queued_scenarios: ['SC30'], slots: {}, actions: [{ name: 'transfer_to_operator', mode: 'execute', status: 'ok', result: {} }], handoff: { queue: 'operator_general', summary: 'Клиент сообщил о списании оплаты без получения полиса и попросил соединить со специалистом. Платёж пока не проверен.' }, reply: 'Передаю специалисту ваш вопрос о платеже. Он увидит контекст разговора.' }); break
        case 'clarify': Object.assign(result, { scenarios: [{ scenario_id: 'SYS_UNCLEAR', confidence: .48 }], alternatives: [{ scenario_id: 'SC25', confidence: .4 }, { scenario_id: 'SC40', confidence: .35 }], reason: 'Недостаточно данных, чтобы отличить проверку полиса от вопроса об условиях.', decision: 'clarify', active_scenario: null, slots: {}, actions: [], reply: 'Вы хотите проверить действие полиса или уточнить его условия?' }); break
      }
      session.responses.set(requestId, result)
      return result
    },
    async history(sessionId) { return [...(sessions.get(sessionId)?.responses.values() ?? [])] },
    async livekit() { throw new ApiError('В Mock нет LiveKit. Переключитесь в Live.', 'mock_voice_unavailable') },
  }
}
