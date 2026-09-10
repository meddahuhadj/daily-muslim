/**
 * Smoke test frontend — Daily Muslim.
 *
 * Charge l'application, capture toute erreur JS, puis vérifie que la
 * navigation et les interactions de base fonctionnent. C'est le test qui
 * aurait attrapé les bugs de démarrage (TDZ) qui rendaient l'app « morte ».
 *
 * Usage :
 *   # Le backend est déjà lancé :
 *   BASE_URL=http://localhost:8000 node smoke.mjs
 *
 *   # Le test démarre seul le backend (python main.py) :
 *   node smoke.mjs
 *
 * Exigences : node >= 18 et `npm install` dans ce dossier (playwright).
 */

import { chromium } from 'playwright';
import { execSync, spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const PORT = Number(process.env.PORT) || 8899;
const BASE_URL = process.env.BASE_URL || `http://127.0.0.1:${PORT}`;
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BACKEND = path.join(ROOT, 'backend');
const IS_WIN = process.platform === 'win32';

function isUp(url, timeoutMs = 15000) {
  return new Promise((resolve) => {
    const deadline = Date.now() + timeoutMs;
    const check = () => {
      const req = http.get(url, (res) => { res.resume(); resolve(true); req.destroy(); });
      req.on('error', () => {
        if (Date.now() > deadline) return resolve(false);
        req.destroy();
        setTimeout(check, 400);
      });
    };
    check();
  });
}

// Certains `.venv` sont cassés (stdlib incomplète) : on sonde les interpréteurs
// et on garde le premier capable d'importer les dépendances du backend.
// Chaque candidat est un tableau d'arguments (ex. ["py", "-3.12"]).
function pickPythonGlobal() {
  const venv = [IS_WIN
    ? path.join(BACKEND, '.venv', 'Scripts', 'python.exe')
    : path.join(BACKEND, '.venv', 'bin', 'python')];
  const candidates = [venv];
  if (IS_WIN) candidates.push(['py', '-3.12'], ['py', '-3.11'], ['py', '-3'], ['python']);
  else candidates.push(['python3']);
  return candidates;
}

function quoteArg(argv) {
  const parts = argv.map((a) => (/\s/.test(a) ? `"${a}"` : a));
  return parts.join(' ');
}

function findWorkingPython() {
  if (process.env.BACKEND_PYTHON) return [process.env.BACKEND_PYTHON];
  for (const argv of pickPythonGlobal()) {
    try {
      execSync(`${quoteArg(argv)} -c "import fastapi, dotenv, uvicorn; print('ok')"`,
        { cwd: BACKEND, stdio: 'pipe', timeout: 20000 });
      return argv;
    } catch { /* interpréteur suivant */ }
  }
  throw new Error('Aucun interpréteur Python ne peut importer les dépendances backend');
}

async function startServerIfNeeded() {
  const up = await isUp(`${BASE_URL}/healthz`);
  if (up) return null;
  const py = await findWorkingPython();
  console.log(`Backend non démarré → lancement: ${quoteArg(py)} main.py (cwd=${BACKEND})`);
  const child = spawn(py[0], [...py.slice(1), 'main.py'],
    { cwd: BACKEND, stdio: 'ignore', detached: false, env: {
      ...process.env,
      PORT: String(PORT),
      // MRI keys désactivées : l'assistant doit basculer sur son repli local
      // (déterministe, zéro coût, même si un `.env` réel est présent).
      GEMINI_API_KEY: '', GEMINI_API_KEYS: '', GROQ_API_KEY: '',
      OPENROUTER_API_KEY: '', AZURE_TRANSLATOR_KEY: '', AZURE_REGION: '',
    } });
  // Sous Windows, on ne peut pas tuer l'arbre sinon : on garde le pid direct.
  if (!(await isUp(`${BASE_URL}/healthz`, 30000))) {
    child.kill();
    throw new Error('Backend non joignable sur ' + BASE_URL);
  }
  return child;
}

const failures = [];
function check(name, ok, detail = '') {
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures.push(name);
}

// Parité salat : le calcul existe en double (JS frontend + Python backend).
// On compare les deux sur des villes/méthodes communes pour détecter toute
// divergence (tolérance 0,01 h ≈ 36 s).
async function checkPrayerParity(page) {
  const date = '2026-09-09';

  // Toutes les méthodes proposées par le frontend doivent donner les mêmes
  // horaires côté backend (le repli serveur doit être un miroir de l'app).
  const methods = await page.evaluate(() =>
    Object.keys(typeof PRAY_METHODS !== 'undefined' ? PRAY_METHODS : {}));
  for (const method of methods) {
    const fe = await page.evaluate(
      ({ date, method }) => {
        const [y, m, d] = date.split('-').map(Number);
        const tz = -new Date(y, m - 1, d, 12).getTimezoneOffset() / 60;
        return {
          tz,
          res: window.prayerTimesFor(new Date(y, m - 1, d), { lat: 48.856, lng: 2.352, method, hanafi: false }),
        };
      },
      { date, method });
    const be = await (await fetch(
      `${BASE_URL}/api/prayer-times?lat=48.856&lng=2.352&date=${date}&method=${method}&tz=${fe.tz}`,
    )).json();
    for (const k of ['fajr', 'sunrise', 'dhuhr', 'asr', 'maghrib', 'isha']) {
      const a = fe.res[k]; const b = be[k];
      if (a == null && b == null) continue;
      check(`Parité salat ${method}/${k} (Paris)`,
        a != null && b != null && Math.abs(a - b) < 0.01,
        a != null && b != null ? `${a} vs ${b}` : `front: ${a}, back: ${b}`);
    }
  }

  // Grille multi-villes sur les méthodes partagées.
  const cases = [
    { lat: 48.856, lng: 2.352, method: 'MWL' },      // Paris
    { lat: 21.4225, lng: 39.8262, method: 'MAKKAH' }, // La Mecque
    { lat: 30.0444, lng: 31.2357, method: 'EGYPT' },  // Le Caire
    { lat: 34.0522, lng: -118.2437, method: 'ISNA' }, // Los Angeles
    { lat: -1.2921, lng: 36.8219, method: 'MWL' },    // Nairobi
  ];
  for (const c of cases) {
    const fe = await page.evaluate(({ date, lat, lng, method }) => {
      const [y, m, d] = date.split('-').map(Number);
      const tz = -new Date(y, m - 1, d, 12).getTimezoneOffset() / 60;
      return {
        tz,
        res: window.prayerTimesFor(new Date(y, m - 1, d), { lat, lng, method, hanafi: false }),
      };
    }, { ...c, date });
    const be = await (await fetch(
      `${BASE_URL}/api/prayer-times?lat=${c.lat}&lng=${c.lng}&date=${date}&method=${c.method}&tz=${fe.tz}`,
    )).json();
    for (const k of ['fajr', 'sunrise', 'dhuhr', 'asr', 'maghrib', 'isha']) {
      const a = fe.res[k]; const b = be[k];
      if (a == null && b == null) continue;
      check(`Parité salat ${c.method}/${k} (${c.lat},${c.lng})`,
        a != null && b != null && Math.abs(a - b) < 0.01,
        a != null && b != null ? `${a} vs ${b}` : `front: ${a}, back: ${b}`);
    }
  }

  // Qibla : même formule des deux côtés.
  for (const c of cases) {
    const front = await page.evaluate(({ lat, lng }) => window.qiblaBearing(lat, lng), c);
    const be = await (await fetch(`${BASE_URL}/api/qibla?lat=${c.lat}&lng=${c.lng}`)).json();
    check(`Parité qibla (${c.lat},${c.lng})`,
      Math.abs(front - be.bearing) < 0.1, `${front.toFixed(2)} vs ${be.bearing}`);
  }
}

async function run() {
  const server = await startServerIfNeeded();

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const consoleErrors = [];
  const fatalErrors = [];
  page.on('pageerror', (e) => fatalErrors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });

  try {
    const resp = await page.goto(BASE_URL + '/', { waitUntil: 'networkidle', timeout: 15000 });
    check('Page sert HTTP 200', resp && resp.status() === 200, resp ? String(resp.status()) : 'no response');
    check('Titre attendu', /Daily Muslim/.test(await page.title()), await page.title());

    // Bandeau RGPD de première visite (peut recouvrir la nav).
    const bar = page.locator('#privacyBar');
    if (await bar.isVisible()) {
      await page.click('#btnPrivacyOk');
      await page.waitForTimeout(200);
    }

    const active = () => page.evaluate(() => {
      const s = document.querySelector('section:not(.hidden)');
      return s ? s.id : 'none';
    });

    // Navigation par la barre du bas.
    const navScreens = ['screen-prayer', 'screen-quran', 'screen-adhkar',
      'screen-progress', 'screen-settings', 'screen-home'];
    for (const s of navScreens) {
      await page.click(`.bottom-nav [data-screen="${s}"]`);
      await page.waitForTimeout(250);
      const got = await active();
      check(`Nav → ${s}`, got === s, `actif: ${got}, nav visible: ${await page.locator('#bottomNav').isVisible()}`);
    }

    // Écran prière : les 6 horaires calculés.
    await page.click('.bottom-nav [data-screen="screen-prayer"]');
    await page.waitForTimeout(300);
    const rows = await page.locator('section:not(.hidden) .prayer-cell').count();
    check('Horaires de prière rendus (≥ 5)', rows >= 5, `lignes: ${rows}`);

    // Écran adhkar : la catégorie « matin » se charge (API + repli embarqué).
    await page.click('.bottom-nav [data-screen="screen-adhkar"]');
    await page.waitForTimeout(250);
    await page.click('#adhkarCategories [data-cat="morning"]');
    await page.waitForSelector('#adhkarList .adhkar-item');
    await page.waitForTimeout(400); // laisse la réponse /api/adhkar arriver
    const dhikrCount = await page.locator('#adhkarList .adhkar-item').count();
    check('Adhkar : 4 dhikrs du matin', dhikrCount === 4, `items: ${dhikrCount}`);
    const tgt = (await page.locator('#adhkarList .adhkar-item').first().locator('.count-target').textContent()) || '';
    const c0 = (await page.locator('#adhkarList .adhkar-item').first().locator('.count-display').textContent()) || '';
    await page.locator('#adhkarList .adhkar-item').first().click();
    await page.waitForTimeout(120);
    const c1 = (await page.locator('#adhkarList .adhkar-item').first().locator('.count-display').textContent()) || '';
    check('Adhkar : objectif 100', /\/\s*100/.test(tgt), `target: ${tgt.trim()}`);
    check('Adhkar : compteur incrémenté au tap', Number(c1) === Number(c0) + 1, `${c0} → ${c1}`);
    await page.click('#adhkarBack');

    // i18n : l'interface bascule réellement en arabe (les clés ar existent).
    await page.evaluate(() => localStorage.setItem('uiLang', 'ar'));
    await page.reload();
    await page.waitForTimeout(350);
    const arLabel = (await page.locator('.bottom-nav [data-screen="screen-adhkar"] span[data-i18n="nav_adhkar"]').textContent()) || '';
    const arDir = await page.evaluate(() => document.documentElement.dir);
    check('i18n AR : label adhkar traduit', arLabel.trim() === 'الأذكار', `label: ${arLabel.trim()}`);
    check('i18n AR : direction RTL', arDir === 'rtl', `dir: ${arDir}`);
    await page.evaluate(() => localStorage.setItem('uiLang', 'fr'));
    await page.reload();
    await page.waitForTimeout(350);

    // Tasbih : le compteur s'incrémente au tap.
    await page.click('.bottom-nav [data-screen="screen-home"]');
    await page.waitForTimeout(250);
    await page.click('[data-screen="screen-tasbih"]');
    await page.waitForTimeout(300);
    const before = await page.locator('#tasbih-count').textContent();
    await page.click('#tasbih-ring');
    await page.waitForTimeout(120);
    const after = await page.locator('#tasbih-count').textContent();
    check(`Tasbih : le compteur s'incrémente au tap`, Number(after) > Number(before), `${before} → ${after}`);

    // Jeu enfants : lettres mélangées présentes.
    await page.click('.bottom-nav [data-screen="screen-home"]');
    await page.waitForTimeout(250);
    await page.click('[data-screen="screen-kids"]');
    await page.waitForTimeout(400);
    const letters = await page.locator('#wordPool .letter-card').count();
    check('Mode enfants : lettres générées', letters > 0, `lettres: ${letters}`);

    // Écran apprentissage : modules + leçons du module Coran.
    await page.click('.bottom-nav [data-screen="screen-home"]');
    await page.waitForTimeout(250);
    await page.click('[data-screen="screen-learning"]');
    await page.waitForTimeout(300);
    const learnCards = await page.locator('#screen-learning .learning-card').count();
    check('Apprentissage : 5 modules', learnCards === 5, `modules: ${learnCards}`);
    await page.click('#screen-learning .learning-card[data-module="quran_study"]');
    await page.waitForTimeout(300);
    const lessons = await page.locator('#learningContent .l-lesson').count();
    check('Apprentissage : leçons du module Coran', lessons > 0, `leçons: ${lessons}`);

    // Plan de mémorisation (hifz) : objectif, répétitions, mémorisation, révisions.
    await page.selectOption('#hifz-surah', '112');
    await page.waitForTimeout(150);
    await page.fill('#hifz-from', '1');
    await page.fill('#hifz-to', '4');
    await page.fill('#hifz-goal', '4');
    await page.click('#btnHifzSave');
    await page.waitForTimeout(200);
    const hifzStatus1 = (await page.textContent('#hifzStatus')) || '';
    check('Hifz : objectif défini (0/4)', /0\/4/.test(hifzStatus1), `statut: ${hifzStatus1.trim()}`);
    await page.click('#btnHifzRep');
    await page.click('#btnHifzRep');
    await page.waitForTimeout(200);
    const hifzStatus2 = (await page.textContent('#hifzStatus')) || '';
    const hifzBar = (await page.getAttribute('#hifzBar', 'style')) || '';
    check('Hifz : 2 répétitions → barre 50 %', /2\/4/.test(hifzStatus2) && /width:\s*50%/.test(hifzBar), `statut: ${hifzStatus2.trim()} | barre: ${hifzBar}`);
    await page.click('#btnHifzMark');
    await page.waitForTimeout(200);
    const hifzMini = (await page.textContent('#hifzMini')) || '';
    check('Hifz : 4 versets mémorisés', /4/.test(hifzMini), `mini: ${hifzMini.replace(/\s+/g, ' ').trim()}`);

    // Progrès : stats étendues (versets mémorisés + répétitions cette semaine).
    await page.click('.bottom-nav [data-screen="screen-progress"]');
    await page.waitForTimeout(300);
    const statsRows = await page.locator('#progressStats > div').count();
    const progressTxt = (await page.textContent('#progressStats')) || '';
    check('Progrès : 6 lignes de stats', statsRows >= 6, `lignes: ${statsRows}`);
    check('Progrès : versets mémorisés = 4', /versets mémorisés/.test(progressTxt) && /\b4\b/.test(progressTxt), '');

    // Écran voyage : horaires calculés sans géolocalisation.
    await page.click('.bottom-nav [data-screen="screen-home"]');
    await page.waitForTimeout(250);
    await page.click('[data-screen="screen-travel"]');
    await page.waitForTimeout(300);
    const travelRows = await page.locator('#travelPrayerList .kids-box').count();
    check('Voyage : horaires du lieu', travelRows >= 5, `horaires: ${travelRows}`);

    // Écran Coran : 114 sourates + recherche de versets via l'index backend.
    await page.click('.bottom-nav [data-screen="screen-quran"]');
    await page.waitForTimeout(250);
    const surahCount = await page.locator('#quran-surah option').count();
    check('Coran : 114 sourates', surahCount === 114, `sourates: ${surahCount}`);
    await page.fill('#quran-search-input', 'الناس');
    await page.waitForTimeout(700);
    const qSearchHits = await page.locator('#quran-search-results .quran-search-hit').count();
    check('Coran : recherche « الناس » (index backend)', qSearchHits > 0, `résultats: ${qSearchHits}`);

    // Assistant sans clé API : repli local propre, aucune erreur JS.
    await page.click('.bottom-nav [data-screen="screen-assistant"]');
    await page.waitForTimeout(250);
    const msgsBefore = await page.locator('#chatWindow .chat-msg').count();
    await page.fill('#chatInput', 'Salut');
    await page.click('#btnChatSend');
    await page.waitForTimeout(600);
    const msgsAfter = await page.locator('#chatWindow .chat-msg').count();
    const lastBot = ((await page.locator('#chatWindow .chat-msg.bot').last().textContent()) || '');
    check('Assistant : 2 messages ajoutés', msgsAfter === msgsBefore + 2, `${msgsBefore} → ${msgsAfter}`);
    check('Assistant : réponse locale (mode hors ligne)', /hors ligne|offline/i.test(lastBot), `texte: ${lastBot.slice(0, 50)}`);

    await checkPrayerParity(page);

    // PWA : le service worker s'enregistre et devient actif (installable).
    const sw = await page.evaluate(async () => {
      if (!('serviceWorker' in navigator)) return 'api-absente';
      try {
        const reg = await navigator.serviceWorker.ready;
        return reg.active ? 'actif' : 'pas-actif';
      } catch (e) { return 'erreur:' + String(e); }
    });
    check('PWA : service worker actif', sw === 'actif', sw);

    check('Aucune erreur JS fatale', fatalErrors.length === 0,
      fatalErrors.join(' | '));
    const realConsole = consoleErrors.filter((e) => !/favicon|Failed to load resource/.test(e));
    check('Aucune erreur console bloquante', realConsole.length === 0,
      realConsole.slice(0, 3).join(' | '));
  } finally {
    await browser.close();
    if (server) server.kill();
  }

  if (failures.length) {
    console.error(`\nÉCHEC (${failures.length})`);
    process.exit(1);
  }
  console.log('\nOK — tout fonctionne');
}

run().catch((err) => { console.error(err); process.exit(1); });