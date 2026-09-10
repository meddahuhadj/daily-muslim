/**
 * Audit i18n statique — simule l'assemblage des dictionnaires I18N
 * (const I18N + Object.assign) et rapporte les dérives silencieuses :
 *   - langues principales (fr/en/nl/ar) qui perdent des clés par rapport à fr
 *   - attributs data-i18n sans clé correspondante
 *   - appels t("...") sans clé
 * Usage : node audit-i18n.mjs
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const html = readFileSync(
  path.resolve(path.dirname(fileURLToPath(import.meta.url)), 'index.html'), 'utf8');

const MAIN = ['fr', 'en', 'nl', 'ar'];
const ALL = [...MAIN, 'tr', 'es', 'pt', 'ur', 'id', 'de', 'it'];

function findBlock(src, i) {
  // src[i] est '{' : renvoie l'index de fin (le '}' fermant), hors chaînes.
  let depth = 0, inStr = null, esc = false;
  for (let j = i; j < src.length; j++) {
    const ch = src[j];
    if (inStr) {
      if (esc) esc = false;
      else if (ch === '\\') esc = true;
      else if (ch === inStr) inStr = null;
      continue;
    }
    if (ch === "'" || ch === '"') { inStr = ch; continue; }
    if (ch === '{') depth++;
    else if (ch === '}') { depth--; if (depth === 0) return j; }
  }
  throw new Error('bloc non fermé');
}

const baseStart = html.indexOf('const I18N = ');
if (baseStart < 0) throw new Error('const I18N introuvable');
const openBrace = html.indexOf('{', baseStart);
const baseEnd = findBlock(html, openBrace);
const I18N = Function('return (' + html.slice(openBrace, baseEnd + 1) + ')')();

// Applique les Object.assign dans l'ordre du fichier.
const re = /Object\.assign\(I18N\.(\w+),\s*(\{)/g;
let m;
while ((m = re.exec(html)) !== null) {
  const lang = m[1];
  const brace = m.index + m[0].lastIndexOf('{');
  const end = findBlock(html, brace);
  const partial = Function('return (' + html.slice(brace, end + 1) + ')')();
  for (const k of Object.keys(partial)) {
    if (!I18N[lang]) I18N[lang] = {};
    I18N[lang][k] = partial[k];
  }
}
// Langues dérivées : clone de fr puis overrides.
re.lastIndex = 0;
const cloneRe = /I18N\[lang\]=\s*Object\.assign\(\{\},\s*I18N\.fr\)/;
if (cloneRe.test(html)) {
  for (const lang of ['tr', 'es', 'pt', 'ur', 'id', 'de', 'it']) {
    I18N[lang] = { ...I18N.fr };
  }
}
for (const lang of ALL) {
  if (!I18N[lang]) I18N[lang] = {};
}

const issues = [];
const frKeys = Object.keys(I18N.fr || {}).sort();
for (const lang of MAIN.filter(l => l !== 'fr')) {
  const missing = frKeys.filter(k => !(k in (I18N[lang] || {})));
  const empty = frKeys.filter(k => (k in (I18N[lang] || {})) && I18N[lang][k] === '');
  if (missing.length) issues.push(`${lang}: ${missing.length} clés manquantes → ${missing.join(', ')}`);
  if (empty.length) issues.push(`${lang}: ${empty.length} clés vides → ${empty.join(', ')}`);
}
for (const lang of ALL) {
  const empty = Object.keys(I18N[lang] || {}).filter(k => I18N[lang][k] === '');
  if (empty.length) issues.push(`${lang}: ${empty.length} clés vides → ${empty.join(', ')}`);
}

const attrs = [...html.matchAll(/data-i18n=\"([^\"]+)\"/g)].map(x => x[1]);
const attrSet = [...new Set(attrs)].sort();
const noFr = attrSet.filter(k => !(k in I18N.fr));
if (noFr.length) issues.push(`data-i18n sans clé fr → ${noFr.join(', ')}`);

const calls = [...html.matchAll(/\bt\(\s*[\"']([A-Za-z0-9_.\-]+)[\"']\s*\)/g)].map(x => x[1]);
const callSet = [...new Set(calls)].sort();
const callNoFr = callSet.filter(k => !(k in I18N.fr));
if (callNoFr.length) issues.push(`t() sans clé fr → ${callNoFr.join(', ')}`);

console.log('Clés fr :', frKeys.length);
console.log('Langues :', ALL.map(l => `${l} (${Object.keys(I18N[l] || {}).length})`).join(', '));
console.log('--- Résultat ---');
if (issues.length) {
  console.log('ÉCHEC :');
  for (const line of issues) console.log('  - ' + line);
  process.exit(1);
}
console.log('OK : parité fr/en/nl/ar, toutes les références résolues.');