# Daily Muslim Life Assistant

Assistant quotidien du musulman : **prières, Coran, adhkar, tasbih, Qibla, apprendre,
voyage, enfants, rappels** et la **traduction en direct du prêche (khutbah)**.

Application web **privée et déconnectée d'abord** : l'historique, les habitudes et les
réglages restent sur votre appareil (`localStorage`) ; aucun compte, aucune collecte de
données personnelles.

- **Frontend** : PWA en **un seul fichier HTML** (`frontend/index.html`, ~5 400 lignes),
  installable, responsive, sans étape de build. Service worker pour la coquille hors ligne.
- **Backend** : FastAPI + WebSocket (Python) — calcul astronomique des prières,
  assistant IA (chaîne Gemini → Groq → OpenRouter), sessions de traduction du prêche,
  géolocalisation, contenu pédagogique (Alcoran, tajwid, arabe, mémorisation).
- **Interface en 11 langues** : Français, English, Nederlands, العربية, Türkçe, Español,
  Português, اردو, Bahasa Indonesia, Deutsch, Italiano — RTL pour l'arabe et l'ourdou.

## Fonctionnalités (v2.0)

- **Accueil (dashboard)** : salutation + date hijrie, prochaine prière avec compte à
  rebours, reprise de lecture du Coran, rappels, grille de raccourcis, rappel dhikr.
- **Prières** : 6 horaires calculés **localement** (astronomie solaire, aucune donnée
  envoyée), 7 méthodes (CILE/UOIF, MWL, ISNA, Égypte, Amir, Karachistan, Makkah),
  réglage Asr Hanafi, localisation ou coordonnées manuelles, **notifications** avant chaque
  prière, heures de silence.
- **Coran** : lecteur de récitation (114 sourates, intervalle de versets, 5 qaris),
  stream **à la demande** depuis everyayah.com — jamais à l'ouverture. Mémorisation des
  versets consultés (lecture instantanée même hors réseau).
- **Adhkar** : 8 catégories (matin, soir, après-prière, sommeil, réveil, voyage,
  protection, gratitude), compteurs par dhikr avec vibration.
- **Tasbih** : anneau circulaire dégradé or, cycles 33-33-33 puis 34, historique du jour,
  statistiques intégrées.
- **Qibla** : boussole (capteurs de l'appareil) + calcul de la direction de la Kaaba.
- **Assistant IA** : chat contextuel (connaît les horaires de prière et la progression
  Coran), TTS des réponses, réponse locale offline, avertissement religieux.
- **Apprentissage & mémorisation** : plan de lecture, tajwid, arabe, mémorisation avec
  objectif quotidien personnalisable, compteur de répétitions, marquage des versets
  mémorisés (cumulatif), rappels de révision espacée, notes personnelles, statistiques du jour.
- **Progrès** : série (streak) + meilleure série, grille 7 jours, stats par activité
  (tasbih, adhkars, hifz : répétitions du jour / de la semaine, versets mémorisés, à réviser).
- **Qibla / Ramadan / Voyage / Enfants** : banner Ramadan, mode voyage (qasr & jamaʿ),
  alphabet arabe et quiz pour enfants.
- **Traduction du prêche (khutbah) en direct** : le diffuseur crée une session, l'imam est
  transcrit (micro navigateur, audio serveur via STT, ou saisie manuelle) puis traduit ;
  chaque fidèle reçoit la traduction **en privé sur ses écouteurs** en sous-titres et/ou TTS.
  Rien n'est diffusé en audio dans la salle.

## Accessibilité

- Contraste élevé (bouton `◐`, mémorisé), **mode senior** (grand texte + grandes zones
  tactiles), thème AMOLED, `prefers-reduced-motion` respecté, navigation clavier (lien
  d'évitement, `:focus-visible`, focus piégé au `Tab`, **Échap** pour fermer les feuilles).
- `role="dialog"` / `aria-modal`, `aria-live` sur la traduction en direct, libellés ARIA
  traduits et `dir="rtl"` selon la langue.

## Développement

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate ; Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python main.py            # http://localhost:8000
```

Tests (Gemini mocké, aucun appel réseau) :

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest tests    # 98 tests (prières ancrées sur aladhan.com, adhkars & Coran alignés)
```

Smoke test frontend (Playwright) — charge l'app, traque les erreurs JS et
vérifie navigation + interactions (hifz : objectif → répétitions → mémorisation,
mode hors-ligne de l'assistant sans clé API) ; démarre seul le backend si besoin :

```bash
cd frontend/tests
npm install
npm test                  # attendu : « OK — tout fonctionne », code 0
```

## Déploiement gratuit sur Render

Application **PWA** : manifeste, icônes, service worker (cache hors-ligne + affichage
instantané même quand l'instance Render est en veille), bandeau d'installation
(`beforeinstallprompt`), métas iOS pour une expérience plein écran.

Une seule instance persistante suffit (WebSockets longs + rooms en mémoire) :

1. **Pousser ce dépôt sur GitHub** (public ou privé).
2. **dashboard.render.com → « New » → « Blueprint »** → sélectionner le dépôt.
   Le fichier `render.yaml` crée seul le service web gratuit :
   - `name: daily-muslim`, `plan: free`, `runtime: docker`
   - health check `/healthz`, auto-déploiement à chaque `push`
3. Dans **Environment**, renseigner les secrets :
   - `GEMINI_API_KEY` (obligatoire pour la traduction du prêche / l'assistant) —
     sans clé, l'app fonctionne en mode dégradé (arabe diffusé sans traduction).
   - Facultatif : `PUBLIC_BASE_URL` (ex. `https://daily-muslim.onrender.com`),
     `DEFAULT_TARGET_LANGS` (ex. `fr,en,nl`), `GEMINI_MODEL`
     (défaut `gemini-2.5-flash-lite`, quota gratuit large).
4. **Pause du sommeil** : le plan gratuit s'endort après ~15 min d'inactivité et se
   réveille à la 1ʳᵉ visite (1ʳᵉ charge lente, puis rapide grâce au service worker).

Alternative équivalente : Railway / Fly.io / un VPS en imposant le `Dockerfile`.

Variables d'environnement : `GEMINI_API_KEY`, `GEMINI_MODEL` (défaut
`gemini-2.5-flash-lite`), `DEFAULT_TARGET_LANGS`, `PUBLIC_BASE_URL`.

## Notes de confidentialité & sécurité

- **Jamais de secret dans le dépôt** : `backend/.env` (clés API) est dans `.gitignore`.
- L'audio de la khutbah n'est jamais enregistré ; l'historique du direct disparaît à la fin
  de la session.
- Export / effacement total des données locales depuis **Réglages → Vos données** (RGPD).
- Pour partager le projet : `zip -r projet.zip . -x '*/.venv/*' '*/.git/*' '*.env' 'backend/data/quran_raw.json'`.