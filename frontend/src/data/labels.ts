import catalog from './scenarios.json'
import slots from './slots.json'
import type { TurnResult } from '../api/types'
export const scenarioName = (id: string) => (catalog as Record<string, string>)[id] ?? id
export const languages = { ru: 'Русский', kk: 'Қазақша', mixed: 'Смешанная речь' }
export const decisions: Record<TurnResult['decision'], string> = { collect_slots: 'Уточнение данных', execute: 'Выполнение сценария', confirm: 'Подтверждение действия', clarify: 'Уточнение запроса', handoff: 'Передача оператору', goodbye: 'Разговор завершён', out_of_scope: 'Вне услуг компании' }
export const queues: Record<string, string> = { operator_general: 'Общая очередь', claims_team: 'Урегулирование страховых случаев', medical_assistance_24_7: 'Медицинская помощь 24/7', corporate_sales: 'Корпоративное страхование', complaints_team: 'Работа с обращениями', security_team: 'Служба безопасности' }
const slotNames: Record<string, string> = { city: 'Город', phone: 'Телефон', iin: 'ИИН', policy_number: 'Номер полиса', claim_number: 'Номер заявления', payment_date: 'Дата платежа', payment_amount: 'Сумма платежа', doctor_specialty: 'Специализация врача', preferred_date: 'Желаемая дата', cancel_reason: 'Причина расторжения', product: 'Продукт', email: 'Электронная почта', full_name: 'Имя клиента', vehicle_plate: 'Госномер', topic: 'Тема обращения', language: 'Язык', client_id: 'Клиент', refund_amount: 'Сумма возврата' }
export const slotName = (name: string) => slotNames[name] ?? name
export const slotPrompt = (name: string) => slots.find(slot => slot.name === name)?.prompt.ru
export const actionName = (name: string) => ({ cancel_policy: 'Расторжение полиса', get_offices: 'Поиск офиса', find_client: 'Поиск клиента', transfer_to_operator: 'Передача оператору', book_appointment: 'Запись к врачу', list_clinics: 'Поиск клиник', get_policy: 'Проверка полиса', get_claim: 'Проверка страхового случая', check_payment: 'Проверка платежа', send_sms: 'Отправка SMS', create_policy: 'Оформление полиса', create_claim: 'Регистрация страхового случая' } as Record<string, string>)[name] ?? name
export const formatMs = (value: number | null) => value === null ? 'не измерено' : `${Math.round(value).toLocaleString('ru-RU')} мс`
export const formatValue = (value: unknown) => typeof value === 'string' ? value : value === null ? '—' : typeof value === 'boolean' ? value ? 'Да' : 'Нет' : JSON.stringify(value)
