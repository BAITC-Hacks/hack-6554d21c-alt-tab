# Saqta Simulator Implementation Plan

**Goal:** Deliver the approved one-page voice simulator with an honest trace and REST integration.
**Architecture:** Typed REST adapter and separate explicit fixture adapter feed one session controller. Recording, playback and trace presentation are independent modules.
**Tech Stack:** React, TypeScript, Vite, Vitest, Testing Library, Playwright.
**Spec:** DESIGN.md

## Global constraints

- Touch frontend/** only. Keep dependencies and lockfile there.
- No provider secrets or direct provider requests in the browser.
- REST multipart voice, 60 seconds / 10 MiB, 4000 text characters.
- Server owns business decisions; no silent fallback to mock.
- Russian labels, full Kazakh support; no source-material references in UI.
- All latency measurements are real or null. No pretend zeroes.

## Review focus

- Microphone promise resolving after unmount or cancellation must release tracks.
- A timed-out POST may already have executed: retry keeps request_id.
- A new session must ignore late old-session results and stop old audio.
- Playback failure must not erase a successfully executed turn.
- Invalid server payloads and external audio URLs must fail visibly.

## Task 1: Shell and contract adapter

Files: package.json, package-lock.json, vite.config.ts, tsconfig.json, index.html, src/main.tsx, src/App.tsx, src/styles.css, src/api/{types,client,validation}.ts, src/api/client.test.ts.

Interface: VoiceApi.health(signal?), createSession(signal?), text(sessionId, requestId, text, signal?), audio(sessionId, requestId, blob, signal?) return typed promises. ApiError preserves code, retryable, HTTP status and request_id.

- [ ] Configure build/test and write client tests for JSON/multipart, structured error, timeout, bad payload and external audio URL.
- [ ] Run tests and confirm missing functionality fails; implement adapter and schema guards.
- [ ] Build minimal responsive shell with separate conversation/trace regions and readable Live/Mock mode.
- [ ] Run tests and production build; commit scaffold; create early draft PR.

## Task 2: Conversation, trace, and explicit mock

Files: src/api/mock.ts, src/data/catalog.ts, src/components/{Conversation,TracePanel,Icon}.tsx, src/useConversation.ts, src/App.test.tsx.

Interface: Conversation consumes session/controller state. TracePanel consumes TurnResult plus an optional local PlaybackMeasurement. Mock implements the same VoiceApi without routing arbitrary text or faking live audio.

- [ ] Test failed POST does not create a mock turn; retry reuses request_id; new session clears selected trace; pending confirmation and handoff are rendered from server data.
- [ ] Implement fixture selector, session state, text input, per-turn selection, all trace fields and null latency presentation.
- [ ] Show dates from session data and fixture status explicitly; copy scenario labels from supplied catalog into frontend-owned metadata.
- [ ] Run tests and build; commit.

## Task 3: Recording, playback, and browser acceptance

Files: src/voice/{recorder,playback}.ts and tests, src/components/VoiceControls.tsx, e2e/simulator.spec.ts, playwright.config.ts, README.md.

Interface: recorder.start/stop/cancel owns tracks and timing; playback reports first playing once per turn with basis recording_stop_to_playing or text_submit_to_playing, plus manual-delay flag.

- [ ] Write tests for MIME negotiation, denied/no-device input, late mic permission, size/time limits, track release and playback event timing.
- [ ] Implement controls and accessible state messages, manual play fallback and response-audio error handling.
- [ ] Browser acceptance: two KK, mixed, topic switch, new dialog, preview, handoff, backend failure, microphone denial and blocked autoplay, mobile layout.
- [ ] Try real local backend; record actual integration outcome with identifiers, without claiming synthetic audio is a real voice check.
- [ ] Run clean npm ci, test and build; inspect screenshots; obtain independent code review; fix important findings.
- [ ] Update PR with integration and verification evidence; document commands and remaining external blockers.
