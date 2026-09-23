// Real browser voice acceptance run: Chrome with a fake microphone that plays one WAV
// → Vite (5174) → API (8000) → LiveKit → worker → Soniox/GPT. Nothing is mocked.
//
// Prerequisites: `scripts/dev.py` running, `npm run dev` in frontend/, Google Chrome installed.
// Usage: node scripts/e2e_live_voice.mjs <utterance.wav> <output-dir>
// The WAV is played once (%noloop); put ~2 s of silence before speech so the greeting
// finishes, and trailing silence so STT can endpoint the utterance.
import { createRequire } from 'node:module'
import { writeFileSync } from 'node:fs'
const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { chromium } = require('playwright')
const [wav, outDir = '.'] = process.argv.slice(2)
if (!wav) { console.error('usage: node scripts/e2e_live_voice.mjs <utterance.wav> [output-dir]'); process.exit(2) }
const name = wav.replace(/\\/g, '/').split('/').pop().replace('.wav', '')
const logs = []
const log = (...a) => { const line = `${new Date().toISOString().slice(11, 23)} ${a.join(' ')}`; logs.push(line); console.log(line) }
const browser = await chromium.launch({
  channel: 'chrome', headless: true,
  args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
    `--use-file-for-fake-audio-capture=${wav}%noloop`, '--autoplay-policy=no-user-gesture-required'],
})
const context = await browser.newContext({ permissions: ['microphone'] })
const page = await context.newPage()
page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') log('console', m.type(), m.text().slice(0, 300)) })
page.on('pageerror', e => log('pageerror', e.message))
page.on('response', r => { if (r.status() >= 400) log('http', r.status(), r.url()) })
const t0 = Date.now()
await page.goto('http://127.0.0.1:5174/')
await page.getByRole('status').filter({ hasText: 'Готов к разговору' }).waitFor({ timeout: 20000 })
log('session ready')
await page.getByRole('button', { name: 'Начать разговор' }).click()
const tClick = Date.now()
let lastStatus = ''
let firstTurnAt = null
const deadline = Date.now() + 90000
while (Date.now() < deadline) {
  const status = await page.getByRole('status').textContent()
  if (status !== lastStatus) { log('status:', status); lastStatus = status }
  const turns = await page.locator('article.turn').count()
  const errors = await page.locator('.error-box').allTextContents()
  if (errors.length) log('error-box:', errors.join(' | '))
  if (turns > 0) { firstTurnAt = firstTurnAt ?? Date.now(); if (Date.now() - firstTurnAt > 6000) break }
  if (errors.some(e => /не подтвердил|Не удалось/.test(e))) break
  await page.waitForTimeout(500)
}
const audio = await page.evaluate(() => [...document.querySelectorAll('.remote-audio audio')].map(a => ({ paused: a.paused, currentTime: a.currentTime, readyState: a.readyState })))
log('remote audio elements:', JSON.stringify(audio))
const trace = await page.locator('details.technical pre').textContent().catch(() => null)
let result = null
if (trace) {
  result = JSON.parse(trace)
  log(`turn ${result.turn} transcript=${JSON.stringify(result.transcript)}`)
  log(`language=${result.language} response_language=${result.response_language} decision=${result.decision}`)
  log(`scenarios=${JSON.stringify(result.scenarios)} missing=${JSON.stringify(result.missing_slots)} slots=${JSON.stringify(result.slots)}`)
  log(`reply=${JSON.stringify(result.reply)}`)
  log(`latency=${JSON.stringify(result.latency_ms)} server_ms=${result.server_processing_ms}`)
  log(`first turn on screen ${((firstTurnAt - tClick) / 1000).toFixed(1)}s after click`)
}
await page.screenshot({ path: `${outDir}/${name}.png`, fullPage: true })
await page.getByRole('button', { name: 'Завершить разговор' }).click().catch(() => log('no stop button'))
await page.waitForTimeout(1500)
if (result) {
  const history = await page.evaluate(async id => (await fetch(`/api/sessions/${id}/turns`)).json(), result.session_id)
  log(`server history turns=${history.turns.length} ids=${history.turns.map(t => t.request_id).join(',')}`)
}
log(`total ${((Date.now() - t0) / 1000).toFixed(1)}s`)
writeFileSync(`${outDir}/${name}.log`, logs.join('\n'))
await browser.close()
process.exit(result ? 0 : 1)
