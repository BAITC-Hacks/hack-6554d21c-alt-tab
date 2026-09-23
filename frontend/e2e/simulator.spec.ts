import { test, expect, type Page } from '@playwright/test'
import { turnFixture } from '../src/test/fixture'
import { mkdirSync } from 'node:fs'

async function backend(page: Page, options: { failOnce?: boolean; onRoom?: () => void } = {}) {
  let turn = 0, sessions = 0, attempts = 0
  const requestIds: string[] = []
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path === '/api/health') return route.fulfill({ json: { status: 'ok', mode: 'live', voice_ready: false, voice_configured: true, missing_config: [], models: {} } })
    if (path === '/api/sessions') return route.fulfill({ json: { session_id: 's-' + ++sessions, as_of_date: '2026-10-01' } })
    if (path.endsWith('/livekit')) { options.onRoom?.(); return route.fulfill({ status: 503, json: { error: { code: 'voice_unavailable', message: 'LiveKit недоступен в тесте', retryable: true } } }) }
    if (path.endsWith('/turns') && request.method() === 'GET') return route.fulfill({ json: { turns: [] } })
    if (path.endsWith('/turns')) {
      const data: { request_id: string; text: string } = request.postDataJSON()
      requestIds.push(data.request_id)
      if (options.failOnce && attempts++ === 0) return route.fulfill({ status: 503, json: { error: { code: 'provider_unavailable', message: 'Тестовая недоступность backend', retryable: true } } })
      return route.fulfill({ json: { ...turnFixture, session_id: path.split('/')[3], request_id: data.request_id, turn_id: 'browser-turn-' + ++turn, turn, transcript: data.text, audio_url: null } })
    }
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'Нет маршрута', retryable: false } } })
  })
  return requestIds
}
async function send(page: Page, text: string) {
  await page.getByLabel('Ваша реплика').fill(text)
  await page.getByRole('button', { name: 'Отправить реплику' }).click()
}
async function mock(page: Page) {
  await backend(page); await page.goto('/')
  await page.getByRole('button', { name: 'Mock', exact: true }).click()
  await expect(page.getByLabel('Ваша реплика')).toBeEnabled()
}
test('two Kazakh turns, mixed speech, topic switch, preview, handoff and new dialog in explicit Mock', async ({ page }) => {
  await mock(page)
  for (const example of ['office-kk', 'doctor-kk', 'mixed', 'preview', 'handoff']) {
    await page.getByRole('combobox', { name: 'Пример', exact: true }).selectOption(example)
    await page.getByRole('button', { name: 'Отправить реплику' }).click()
    await expect(page.getByLabel('Ваша реплика')).toHaveValue('')
  }
  await expect(page.getByText('Ходов: 5', { exact: true })).toBeVisible()
  await expect(page.getByText('Передача оператору — симуляция', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: /Ход 4 ·/ }).click()
  await expect(page.getByText('Ожидается подтверждение', { exact: true })).toBeVisible()
  await expect(page.getByText('Предпросмотр', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: /Ход 3 ·/ }).click()
  await expect(page.getByText('Смешанная речь → Қазақша', { exact: true })).toBeVisible()
  await expect(page.getByText('не измерено', { exact: true }).first()).toBeVisible()
  mkdirSync('.verification/screenshots', { recursive: true })
  await page.screenshot({ path: '.verification/screenshots/desktop.png', fullPage: true })
  await page.getByRole('button', { name: 'Новый диалог' }).click()
  await expect(page.getByRole('heading', { name: 'Начните с простого вопроса' })).toBeVisible()
  await expect(page.getByText('Ходов: 5', { exact: true })).toHaveCount(0)
})
test('backend failure is visible and retry uses the same request ID', async ({ page }) => {
  const requests = await backend(page, { failOnce: true }); await page.goto('/')
  await send(page, 'Офис в Алматы')
  await expect(page.getByRole('alert')).toContainText('Тестовая недоступность backend')
  await expect(page.getByRole('log')).not.toContainText('В каком городе вы ищете офис?')
  await page.getByRole('button', { name: 'Повторить запрос' }).click()
  await expect(page.getByRole('log')).toContainText('В каком городе вы ищете офис?')
  expect(requests).toHaveLength(2); expect(requests[0]).toBe(requests[1])
  await expect(page.getByLabel('Режим подключения').getByRole('button', { name: 'Live' })).toHaveAttribute('aria-pressed', 'true')
})
test('microphone refusal keeps text input usable', async ({ page }) => {
  await backend(page)
  await page.addInitScript(() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied', 'NotAllowedError') } })
  await page.goto('/')
  await page.getByRole('button', { name: 'Начать разговор' }).click()
  await expect(page.getByRole('alert')).toContainText('Доступ к микрофону запрещён')
  await send(page, 'Продолжим текстом')
  await expect(page.getByRole('log')).toContainText('В каком городе вы ищете офис?')
})
test('configured-but-unverified voice can be attempted and a token failure releases the real browser mic', async ({ page }) => {
  let roomRequests = 0
  await backend(page, { onRoom: () => roomRequests++ })
  await page.addInitScript(() => {
    const get = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    navigator.mediaDevices.getUserMedia = async constraints => {
      const stream = await get(constraints)
      ;(window as unknown as { testTracks: MediaStreamTrack[] }).testTracks = stream.getTracks()
      return stream
    }
  })
  await page.goto('/')
  await expect(page.getByText('Настройки есть; живой голос ещё не проверен.')).toBeVisible()
  await page.getByRole('button', { name: 'Начать разговор' }).click()
  await expect(page.getByRole('alert')).toContainText('LiveKit недоступен в тесте')
  expect(roomRequests).toBe(1)
  expect(await page.evaluate(() => (window as unknown as { testTracks: MediaStreamTrack[] }).testTracks.every(track => track.readyState === 'ended'))).toBe(true)
  await expect(page.getByLabel('Ваша реплика')).toBeEnabled()
})
test('text fallback does not request file audio or dispatch a voice room', async ({ page }) => {
  let roomRequests = 0
  await backend(page, { onRoom: () => roomRequests++ })
  const requests: string[] = []
  page.on('request', request => requests.push(new URL(request.url()).pathname))
  await page.goto('/'); await send(page, 'Офис')
  await expect(page.getByRole('log')).toContainText('В каком городе вы ищете офис?')
  await expect(page.getByText('От конца речи до ответа', { exact: true }).locator('..')).toContainText('не измерено')
  expect(roomRequests).toBe(0)
  expect(requests.some(path => path.startsWith('/api/audio/'))).toBe(false)
})
test('mobile layout fits without horizontal scrolling', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await mock(page)
  await page.getByRole('combobox', { name: 'Пример', exact: true }).selectOption('mixed')
  await page.getByRole('button', { name: 'Отправить реплику' }).click()
  await expect(page.getByText('Ходов: 1')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  mkdirSync('.verification/screenshots', { recursive: true })
  await page.screenshot({ path: '.verification/screenshots/mobile.png', fullPage: true })
})
