# Daily Muslim Life Assistant — Implementation Plan

> Transforming the "Khutbah Live Translation" PWA into a comprehensive daily Muslim companion.

---

## 0. Architecture Decision

### Recommended: Option C — ES Modules (No Build Step)

**Decision: Use native ES modules without a build tool.**

Rationale:
- The current app is a single 2,789-line file that works perfectly as a PWA. Adding Vite/webpack introduces a build step that complicates deployment (currently just `python main.py`).
- Modern browsers (all browsers supporting PWAs) support ES modules natively. No build step means the dev loop stays as fast as it is today.
- The service worker stays simple — it caches actual files by path, no hashed bundles to track.
- Each module is a `.js` file in `frontend/js/` that exports functions/objects. `index.html` loads them with `<script type="module">`.
- CSS gets split into `frontend/css/` files, loaded via `<link>` tags.

**File structure after modularization:**

```
frontend/
├── index.html              (~600 lines: layout/HTML skeleton only)
├── sw.js                   (updated service worker)
├── manifest.webmanifest    (updated for new app name)
├── css/
│   ├── theme.css           (CSS custom properties, light/dark, contrast)
│   ├── layout.css          (grid, cards, buttons, responsive breakpoints)
│   ├── components.css      (sheets, toasts, badges, meters, etc.)
│   ├── quran.css           (quran player, verse display)
│   ├── tasbih.css          (ring counter, dhikr display)
│   ├── prayer.css          (prayer grid, settings)
│   └── a11y.css            (skip links, focus, sr-only, high contrast)
├── js/
│   ├── app.js              (entry point: imports all modules, boots app)
│   ├── core.js             ($, $$, show, toast, fmtTime, jget, escapeHtml)
│   ├── i18n.js             (I18N dict + t() + applyI18n())
│   ├── state.js            (global state: uiLang, LS, BC, settings)
│   ├── router.js           (screen navigation, history, back button)
│   ├── theme.js            (theme toggle, contrast, clock)
│   ├── quran.js            (SURAH data, reciters, audio player, alquran.cloud)
│   ├── tasbih.js           (TASBIH data, counter state, ring UI)
│   ├── prayer.js           (astronomical calculation, PRAY_METHODS, render)
│   ├── dhikr.js            (DHIKR array, home dhikr display)
│   ├── hijri.js            (hijri date rendering)
│   ├── khutbah-broadcast.js (broadcaster: session creation, WS, SR, audio streaming)
│   ├── khutbah-listen.js   (listener: WS, subtitles, TTS, history, export)
│   ├── ws.js               (Reconnecting WebSocket class)
│   ├── a11y.js             (privacy, contrast, focus trap, dynamic labels)
│   ├── nav.js              (back navigation, popstate, sheet stack)
│   ├── clock.js            (top clock, real-time tick)
│   └── pwa.js              (service worker registration)
├── assets/
│   ├── mosque-bg.jpg
│   └── CREDIT.txt
├── icon-192.png
└── icon-512.png
```

**Key principle:** The existing `index.html` gets *split*, not rewritten. Every line of CSS and JS is preserved, just moved into the appropriate file. The HTML becomes a clean skeleton with `<link>` and `<script type="module">` tags.

---

## 1. Backend Architecture — New Modules

All new backend code lives in `backend/` alongside existing files. Each new module is a standalone Python file.

### 1.1 Extend Existing

| Module | What Changes |
|--------|-------------|
| `main.py` | Add new API routes (`/api/quran/*`, `/api/adhkar`, `/api/prayer`, `/api/profile`). Mount new routers. Keep all existing routes. |
| `translator.py` | Add `ask_ai(prompt, context)` function for the AI assistant. Reuse the existing multi-provider chain (Gemini→Groq→OpenRouter). No new providers needed. |
| `quran_index.py` | Add `get_verse(surah, ayah)` and `search(query)` for the enhanced Quran search. Already has 6,236 normalized verses. |

### 1.2 New Modules

```
backend/
├── main.py                (modified: add routers)
├── translator.py          (modified: add ask_ai)
├── quran_index.py         (modified: add search)
├── data/
│   └── quran_index.json   (existing)
├── engines/
│   ├── __init__.py
│   ├── prayer.py          (Prayer Engine)
│   ├── quran.py           (Quran Engine)
│   ├── adhkar.py          (Adhkar Engine)
│   ├── reminder.py        (Reminder Engine)
│   ├── audio.py           (Audio Engine: TTS, adhan)
│   ├── ai_assistant.py    (AI Assistant Engine)
│   └── location.py        (Location Engine)
```

#### `engines/prayer.py` — Prayer Engine
- Wraps the existing astronomical calculation (currently in frontend JS) into a Python module
- Adds: sunrise/sunset, Qibla direction, Hijri date conversion, Ramadan schedule
- Endpoint: `GET /api/prayer?lat=&lng=&method=&date=`
- Reuses the exact same formulas from `frontend/index.html:1512-1578` (Julian date, sun position, angle-time)

#### `engines/quran.py` — Quran Engine
- Full surah/ayah metadata (names in AR/EN/FR, verse counts, juz data)
- Verse-of-the-day (random, cached, changes at Fajr time)
- Last-read position tracking
- Reading progress persistence
- Audio URL builder (reuses everyayah.com pattern from `index.html:1299-1301`)
- Endpoint: `GET /api/quran/verse-of-the-day`, `GET /api/quran/surahs`, `GET /api/quran/search?q=`

#### `engines/adhkar.py` — Adhkar Engine
- Morning/Evening adhkar (Azkar al-Sabah/Masa')
- Post-prayer adhkar (reuses existing TASBIH data from `index.html:1470-1476`)
- Sleep/wake adhkar
- Ramadan-specific adhkar
- JSON-based, loaded from `backend/data/adhkar.json` (new file, ~50KB)
- Endpoint: `GET /api/adhkar?category=morning|evening|post_prayer|sleep|ramadan`

#### `engines/reminder.py` — Reminder Engine
- Server-side: stores reminders in memory (ephemeral, per-connection)
- Client-side: uses `setTimeout` + Notification API (no push needed for personal use)
- Patterns: daily, weekly, specific time, before/after prayer
- Endpoint: `POST /api/reminder`, `GET /api/reminder`, `DELETE /api/reminder/{id}`
- Privacy: all reminders live in localStorage on the client. Backend is optional sync only.

#### `engines/audio.py` — Audio Engine
- Adhan audio URLs (free public domain sources, similar pattern to everyayah.com)
- TTS via browser `speechSynthesis` (already exists in `index.html:2370-2408`)
- Adhan scheduling: calculate next adhan, trigger Notification + optional audio
- Endpoint: `GET /api/audio/adhan?method=&lat=&lng=`

#### `engines/ai_assistant.py` — AI Assistant Engine
- Wraps `translator.ask_ai()` with Islamic-specific system prompts
- Features: ask about a verse, explain a hadith, dua requests, general Islamic Q&A
- Rate limiting: 10 requests/minute per IP (reuse existing pattern from `main.py`)
- Endpoint: `POST /api/ai/ask` with `{question, context?}`
- Response: `{answer, source?, confidence}`

#### `engines/location.py` — Location Engine
- Reverse geocoding (free: Nominatim/OpenStreetMap)
- City/timezone detection for auto prayer times
- Qibla direction from coordinates
- Endpoint: `GET /api/location/reverse?lat=&lng=`

---

## 2. Frontend Modules — New Files

### 2.1 Dashboard (`frontend/js/dashboard.js`)
- Home screen widget grid: next prayer, verse of the day, dhikr streak, quick actions
- Greeting based on time of day (Arabic/translated)
- Replaces current `screen-home` content

### 2.2 Quran Enhanced (`frontend/js/quran-extended.js`)
- Daily verse widget on dashboard
- Last-read bookmark (localStorage)
- Reading progress per surah (localStorage)
- Search by keyword (calls `/api/quran/search`)
- Tafsir links (external, to quran.com)

### 2.3 Adhkar Module (`frontend/js/adhkar.js`)
- Morning/Evening categories
- Post-prayer adhkar (auto-detected from prayer times)
- Custom dhikr creation
- Completion sound/vibration
- Streak tracking (localStorage)

### 2.4 Tasbih Enhanced (`frontend/js/tasbih-extended.js`)
- Extends existing tasbih (`index.html:1469-1507`)
- Custom phrases
- Multiple saved configurations
- Statistics (total dhikr count across sessions)
- Haptic feedback patterns

### 2.5 AI Assistant (`frontend/js/ai-assistant.js`)
- Chat-like interface (bottom sheet)
- Voice input via existing Web Speech API
- Pre-built prompts: "Explain this verse", "What's the dua for...", "Remind me of..."
- Response display with Arabic text + translation

### 2.6 Travel Mode (`frontend/js/travel.js`)
- Qibla compass (DeviceOrientation API)
- Adjusted prayer times for travel (Qasr)
- Travel dua collection
- Airport/mosque finder (external links)

### 2.7 Ramadan Mode (`frontend/js/ramadan.js`)
- Iftar/Suhoor countdown
- Ramadan calendar
- Ramadan-specific adhkar
- Quran reading schedule (30 juz in 30 days)

### 2.8 Kids Mode (`frontend/js/kids.js`)
- Simplified UI (large buttons, icons only)
- Basic dua cards
- Simple tasbih with animation
- Alphabet/numbers in Arabic

### 2.9 Driving Mode (`frontend/js/driving.js`)
- Voice-only interface (all TTS, no reading)
- Simplified navigation
- Auto-detect driving (speed > threshold from Geolocation API)
- Hands-free prayer time announcements

### 2.10 Learning (`frontend/js/learning.js`)
- Hadith of the day
- Salah tutorial (step-by-step with images)
- Basic Arabic phrases
- Seerah timeline

### 2.11 Memorization (`frontend/js/memorize.js`)
- Memorization mode: show verse, hide, check
- Spaced repetition tracking (localStorage)
- Audio playback for memorization
- Progress dashboard

### 2.12 Family (`frontend/js/family.js`)
- Family member profiles (localStorage)
- Shared tasbih goals
- Family prayer tracking
- Children's progress

---

## 3. Phase Plan (8 Phases)

### Phase 1: Foundation & Modularization
**Goal:** Split the monolith without breaking anything.

**Features:**
- Split `index.html` into `index.html` + CSS files + JS modules
- Create `app.js` as entry point that imports all modules
- Update service worker to cache the new file structure
- Update `manifest.webmanifest` (new name, description)
- Add `frontend/js/core.js` with shared utilities

**Reuses:** Everything (100% existing code, just reorganized)

**Files created/modified:**
- `frontend/index.html` → gutted to skeleton (~600 lines)
- `frontend/css/theme.css` (from lines 17-468)
- `frontend/css/layout.css` (from responsive breakpoints)
- `frontend/css/components.css` (sheets, toasts, badges)
- `frontend/css/quran.css`
- `frontend/css/tasbih.css`
- `frontend/css/prayer.css`
- `frontend/css/a11y.css`
- `frontend/js/app.js` (new entry point)
- `frontend/js/core.js` (from `index.html:1274-1283`)
- `frontend/js/i18n.js` (from `index.html:876-1269`)
- `frontend/js/state.js` (from `index.html:1718-1722`)
- `frontend/js/router.js` (from `index.html:1277-1278`, 2663-2755)
- `frontend/js/theme.js` (from `index.html:1728-1749`)
- `frontend/js/quran.js` (from `index.html:1287-1383`)
- `frontend/js/tasbih.js` (from `index.html:1469-1507`)
- `frontend/js/prayer.js` (from `index.html:1509-1667`)
- `frontend/js/dhikr.js` (from `index.html:1422-1451`)
- `frontend/js/hijri.js` (from `index.html:1453-1467`)
- `frontend/js/khutbah-broadcast.js` (from `index.html:1798-2053`)
- `frontend/js/khutbah-listen.js` (from `index.html:2182-2501`)
- `frontend/js/ws.js` (from `index.html:1687-1714`)
- `frontend/js/a11y.js` (from `index.html:2503-2661`)
- `frontend/js/nav.js` (from `index.html:2663-2755`)
- `frontend/js/clock.js` (from `index.html:2760-2779`)
- `frontend/js/pwa.js` (from `index.html:2781-2786`)
- `frontend/sw.js` (updated cache list)

**Complexity:** Medium — mostly mechanical extraction, testing is critical.

**Verification:** Every existing feature works identically. Run the app, test all flows.

---

### Phase 2: Core Daily Features
**Goal:** Prayer, Quran, Adhkar, Tasbih as first-class standalone features.

**Features:**
- **Dashboard home screen** with widget grid (next prayer, verse of the day, dhikr, quick actions)
- **Prayer engine backend** (`engines/prayer.py`) — Python-side calculation, Qibla direction
- **Prayer notifications** — Notification API at each prayer time (client-side, localStorage scheduled)
- **Quran verse of the day** — random verse shown on dashboard, loads from `/api/quran/verse-of-the-day`
- **Quran last-read bookmark** — resume where you left off
- **Adhkar categories** — morning/evening adhkar with complete text collections
- **Tasbih enhanced** — custom phrases, statistics, saved configs

**Reuses:**
- Prayer calculation: `index.html:1512-1578` → `engines/prayer.py` + `frontend/js/prayer.js`
- Quran data: `index.html:1287-1310` → `engines/quran.py`
- Tasbih: `index.html:1469-1507` → `frontend/js/tasbih-extended.js`
- Dhikr: `index.html:1422-1451` → `frontend/js/adhkar.js`

**Files created/modified:**
- `backend/engines/__init__.py`
- `backend/engines/prayer.py` (new)
- `backend/engines/quran.py` (new)
- `backend/engines/adhkar.py` (new)
- `backend/data/adhkar.json` (new, ~50KB — sourced from public domain Azkar collections)
- `frontend/js/dashboard.js` (new)
- `frontend/js/quran-extended.js` (new)
- `frontend/js/tasbih-extended.js` (new, extends `tasbih.js`)
- `frontend/js/adhkar.js` (new)
- `frontend/js/prayer-notifications.js` (new)
- `frontend/css/dashboard.css` (new)

**Complexity:** High — new backend engines + new frontend features + data files.

---

### Phase 3: Smart Features (AI + Voice + Reminders)
**Goal:** AI assistant, voice interaction, smart reminders.

**Features:**
- **AI Assistant chat** — ask Islamic questions, get answers from Gemini/Groq
- **Voice input** — ask questions by voice (Web Speech API, already used for khutbah)
- **Smart reminders** — set reminders with natural language ("remind me to pray Dhuhr", "daily Quran at 6am")
- **Adhan scheduler** — auto-detect prayer times, notify with adhan audio option
- **Dua request** — voice or text, AI finds relevant dua

**Reuses:**
- AI chain: `translator.py:77-84` (multi-provider) → `engines/ai_assistant.py`
- Speech recognition: `index.html:2082-2149` (Web Speech API) → `ai-assistant.js`
- TTS: `index.html:2370-2408` → already modularized

**Files created/modified:**
- `backend/engines/ai_assistant.py` (new)
- `backend/engines/reminder.py` (new)
- `backend/engines/audio.py` (new)
- `backend/translator.py` (add `ask_ai()` function)
- `frontend/js/ai-assistant.js` (new)
- `frontend/js/reminder.js` (new)
- `frontend/js/adhan-scheduler.js` (new)
- `frontend/css/ai-assistant.css` (new)

**Complexity:** High — AI integration, notification scheduling, voice pipeline.

---

### Phase 4: Specialized Modes (Travel, Ramadan, Kids, Driving)
**Goal:** Context-aware modes for specific situations.

**Features:**
- **Travel mode:** Qibla compass (DeviceOrientation), Qasr prayer calculation, travel duas
- **Ramadan mode:** Iftar/Suhoor countdown, Ramadan calendar, Quran 30-juz schedule, special adhkar
- **Kids mode:** Simplified UI, big buttons, basic dua cards, animated tasbih
- **Driving mode:** Voice-only interface, auto-detect speed, hands-free announcements

**Reuses:**
- Prayer engine: `engines/prayer.py` — add `qasr()` method
- Qibla: new calculation in `engines/prayer.py` (straightforward trig)
- TTS: existing `speak()` function
- Geolocation: existing `navigator.geolocation` pattern

**Files created/modified:**
- `backend/engines/prayer.py` (add travel calculations)
- `backend/data/adhkar.json` (add Ramadan section)
- `frontend/js/travel.js` (new)
- `frontend/js/ramadan.js` (new)
- `frontend/js/kids.js` (new)
- `frontend/js/driving.js` (new)
- `frontend/css/travel.css` (new)
- `frontend/css/kids.css` (new)

**Complexity:** Medium-High — mostly frontend, some trig for Qibla, UI complexity for kids.

---

### Phase 5: Advanced Features (Learning, Memorization, Family)
**Goal:** Educational and social features.

**Features:**
- **Hadith of the day** — curated collection, displayed on dashboard
- **Salah tutorial** — step-by-step guide with text (no images needed, ASCII diagrams or just clear text)
- **Basic Arabic phrases** — common Islamic phrases with pronunciation
- **Memorization mode** — show verse → hide → test yourself, spaced repetition
- **Family profiles** — localStorage-based, shared tasbih goals, progress tracking

**Reuses:**
- Quran audio: existing everyayah.com URLs for memorization playback
- Tasbih: extended for family goals
- Dashboard: add new widgets

**Files created/modified:**
- `backend/data/hadith.json` (new, ~30KB — public domain hadith collections)
- `backend/data/salah_steps.json` (new, ~5KB)
- `backend/data/arabic_phrases.json` (new, ~10KB)
- `frontend/js/learning.js` (new)
- `frontend/js/memorize.js` (new)
- `frontend/js/family.js` (new)
- `frontend/css/learning.css` (new)

**Complexity:** Medium — mostly data files and UI, no complex algorithms.

---

### Phase 6: Polish & Accessibility
**Goal:** Make everything production-ready.

**Features:**
- **Full RTL support** for all new screens (currently only Arabic UI is RTL)
- **WCAG 2.1 AA** compliance audit — focus management, ARIA labels, screen reader testing
- **Performance audit** — lazy-load non-critical modules, optimize images
- **Offline verification** — test all core features without network
- **i18n expansion** — add Turkish (tr), Urdu (ur), Bengali (bn) to all new features (currently only khutbah has these)
- **Error boundaries** — graceful degradation when features fail

**Reuses:**
- Existing accessibility code: `index.html:2503-2661` (skip links, contrast, focus trap)
- Existing i18n: `index.html:876-1269` — extend the pattern to new keys
- Existing offline: `sw.js` — extend cache list

**Files created/modified:**
- All frontend JS files (add i18n keys)
- `frontend/sw.js` (update cache list for all new files)
- `frontend/manifest.webmanifest` (update name, icons, screenshots)

**Complexity:** Medium — systematic but tedious.

---

### Phase 7: Testing & Quality Assurance
**Goal:** Ensure reliability across devices and browsers.

**Activities:**
- Unit tests for `engines/prayer.py` (compare with known values)
- Unit tests for `engines/quran.py` (verse lookup, search)
- Integration tests for API endpoints
- Frontend testing: manual checklist on Chrome, Firefox, Safari, iOS Safari
- PWA audit: Lighthouse score target ≥ 90
- Offline testing: disconnect network, verify all core features
- Memory profiling: check for leaks in long-running sessions
- Cross-browser: Web Speech API, Notification API, Geolocation, DeviceOrientation

**Files created/modified:**
- `backend/tests/test_prayer.py` (new)
- `backend/tests/test_quran.py` (new)
- `backend/tests/test_ai.py` (new)

**Complexity:** Medium.

---

### Phase 8: Deployment & Release
**Goal:** Ship it.

**Activities:**
- Update `Dockerfile` — no changes needed (Python backend unchanged, frontend is static)
- Update `render.yaml` — update service name, health check
- Update `README.md` — new feature list, setup instructions
- Create `manifest.webmanifest` screenshots for app store listing
- Test deployment on Render
- Tag release `v2.0.0`

**Files created/modified:**
- `render.yaml` (update)
- `README.md` (rewrite)
- `frontend/manifest.webmanifest` (update)

**Complexity:** Low.

---

## 4. Data Strategy

### localStorage Keys (Client-Side)

```
theme, contrast, uiLang, fontSize, voiceRate, voiceURI, showAr, simple
listenerLang, recvMode
prayerSet: {lat, lng, method, hanafi, auto, custom}
tasbih: {idx, count}
tasbihCustom: [{ar, tr}]
tasbihStats: {totalCount, sessions, streak}
quranReciter, quranLastRead: {surah, ayah}, quranProgress: {surah: %}
adhkarStreak: {morning: {date, count}, evening: {date, count}}
memorizeProgress: {surah:ayah: {level, nextReview, correct, wrong}}
familyProfiles: [{name, tasbihGoal, progress}]
reminders: [{id, text, time, repeat, enabled}]
bcPhrases, bcLangs
privacyAck
```

### Backend (No Database)
- All state is ephemeral (in-memory `ROOMS` dict, same as today)
- No user accounts, no persistent server-side storage
- The `engines/` modules are stateless — they compute on demand
- The only "data" files are JSON reference data in `backend/data/`

---

## 5. i18n Strategy

The existing I18N pattern (`I18N = {fr:{...}, en:{...}, nl:{...}, ar:{...}}`) is extended, not replaced. Each new module adds its keys using `Object.assign(I18N.fr, {...})`.

**New languages to add in Phase 6:** Turkish (tr), Urdu (ur), Bengali (bn), Malay/Indonesian (id) — these are the top Muslim-majority languages not yet covered.

**New i18n keys per module** (estimated):
- Dashboard: ~20 keys
- Quran extended: ~15 keys
- Adhkar: ~25 keys
- AI Assistant: ~15 keys
- Travel: ~20 keys
- Ramadan: ~20 keys
- Kids: ~15 keys
- Driving: ~10 keys
- Learning: ~15 keys
- Memorization: ~15 keys
- Family: ~15 keys

**Total new keys: ~185** × 4 languages = ~740 translations (4-5 languages).

---

## 6. PWA & Offline Strategy

### Service Worker Updates
The existing SW (`sw.js`, 50 lines) caches the app shell. After modularization:

```javascript
const CACHE = "daily-muslim-v1";
const SHELL = [
  "./",
  "./css/theme.css", "./css/layout.css", "./css/components.css",
  "./css/quran.css", "./css/tasbih.css", "./css/prayer.css", "./css/a11y.css",
  "./js/app.js", "./js/core.js", "./js/i18n.js", "./js/state.js",
  "./js/router.js", "./js/theme.js", "./js/quran.js", "./js/tasbih.js",
  "./js/prayer.js", "./js/dhikr.js", "./js/hijri.js",
  "./js/khutbah-broadcast.js", "./js/khutbah-listen.js",
  "./js/ws.js", "./js/a11y.js", "./js/nav.js", "./js/clock.js", "./js/pwa.js",
  "./manifest.webmanifest", "./api/icon-192.png", "./api/icon-512.png",
  "./assets/mosque-bg.jpg"
];
```

**Offline-capable features** (all work without network):
- Prayer times (astronomical calculation, pure JS/Python)
- Quran recitation audio (cached after first play via everyayah.com)
- Tasbih counter (localStorage)
- Adhkar (pre-loaded text)
- Dhikr reminders (localStorage + setTimeout)
- Hijri date (Intl API)
- Theme/settings (localStorage)

**Online-required features:**
- Khutbah translation (WebSocket + AI)
- AI assistant (Gemini/Groq API)
- Quran verse text from alquran.cloud (cached after first fetch)
- Reverse geocoding (Nominatim)

---

## 7. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Modularization breaks existing features | Phase 1 is entirely mechanical. Test every flow before proceeding. |
| Too many files for a personal project | Keep module count reasonable. Combine small modules (e.g., `hijri.js` + `dhikr.js` = one file if < 100 lines each). |
| AI assistant costs | Rate limit aggressively. Use free-tier models (gemini-2.5-flash-lite already configured). |
| PWA cache invalidation | Use versioned cache name (`daily-muslim-v1`). SW updates on new deploy. |
| Offline data bloat | localStorage limit (~5MB). Monitor usage. Don't cache full Quran text client-side. |
| Notification permission | Only request when user explicitly enables reminders. Don't spam. |

---

## 8. Implementation Order Summary

| Phase | Timeline | Key Deliverable |
|-------|----------|----------------|
| 1. Modularization | Week 1-2 | Clean file structure, all existing features work |
| 2. Core Daily | Week 3-5 | Dashboard, enhanced prayer/quran/adhkar/tasbih |
| 3. Smart Features | Week 6-8 | AI assistant, voice, reminders, adhan |
| 4. Specialized Modes | Week 9-11 | Travel, Ramadan, Kids, Driving |
| 5. Advanced | Week 12-14 | Learning, Memorization, Family |
| 6. Polish | Week 15-16 | RTL, a11y, i18n, performance |
| 7. Testing | Week 17-18 | QA, cross-browser, offline verification |
| 8. Deploy | Week 19 | Ship v2.0.0 |

**Total estimated effort: 19 weeks (part-time personal project pace)**
