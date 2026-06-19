# 🌿 Plant Doctor — Analyseur de santé des plantes

Application web **optimisée pour smartphone** : prenez une photo d'une plante
avec l'appareil photo de votre téléphone, l'IA de vision de **Claude** analyse
son état de santé, détecte maladies / parasites / carences, et propose des
**solutions concrètes**.

> ℹ️ Le dépôt contient aussi `app.py`, un générateur Intrastat indépendant.
> L'application décrite ici est `plante_sante_app.py`.

## ✨ Fonctionnalités

**Analyse**
- 📷 Plusieurs photos (jusqu'à 4) via la caméra **arrière** ou la galerie, orientation EXIF corrigée
- 🪴 Identification (nom commun, latin, famille) + 🩺 score de santé sur 100
- 🔬 Analyse détaillée : 💧 arrosage, ☀️ lumière, 🧪 fertilisation, 🪴 substrats, ✂️ taille/rempotage
- 🔍 Détection des problèmes (maladies, parasites, carences, stress) + 👵 astuces de grand-mère
- 🖼️ Illustrations (schéma IA + photos d'exemples) · 🔔 rappel d'arrosage (.ics)
- 📄 Export **PDF** (avec photos intégrées) · 🌐 multilingue **FR / EN / DE**

**Comptes & gestion** (point d'entrée `main.py`)
- 🔐 Authentification (bcrypt, anti-brute-force), rôles **ADMIN / USER**, page profil
- 👥 Inscription avec **validation par l'admin** + notification **e-mail**
- 💳 Trois **formules** (FREE / STANDARD / PREMIUM) avec quotas d'analyses différents
- 💾 **Historique persistant** (résultat + photos réduites) avec export **CSV** et **ZIP de PDF**
- 📊 **Tableau de bord** admin (stats, graphiques, top utilisateurs, purge)
- 🗄️ Base **SQLite** (défaut) ou **PostgreSQL** (Supabase/Neon…)

## 🚀 Lancer l'application

### 1. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 2. Configurer la clé API Anthropic

Obtenez une clé sur <https://console.anthropic.com>, puis **au choix** :

- Variable d'environnement :
  ```bash
  export ANTHROPIC_API_KEY="sk-ant-..."
  ```
- Ou fichier `.streamlit/secrets.toml` :
  ```toml
  ANTHROPIC_API_KEY = "sk-ant-..."
  ```

### 3. Démarrer

```bash
streamlit run plante_sante_app.py
```

## 📱 Utilisation sur smartphone

Streamlit sert une page web responsive. Pour l'utiliser comme une « app » :

1. Lancez l'application (en local ou sur un hébergeur comme
   [Streamlit Community Cloud](https://streamlit.io/cloud)).
2. Ouvrez l'URL dans le navigateur de votre téléphone.
3. **Ajoutez-la à l'écran d'accueil** (menu du navigateur → « Ajouter à
   l'écran d'accueil ») pour la lancer en plein écran comme une application.

L'appareil photo du téléphone est utilisé directement via le champ « 📷
Appareil photo ».

## 🔐 Gestion des utilisateurs (authentification)

L'application peut être protégée par une couche d'authentification complète
(login, rôles ADMIN/USER, administration des comptes).

**Fichiers** : `database.py` (base), `auth.py` (authentification), `admin.py`
(interface admin), `main.py` (point d'entrée protégé).

**Pour activer l'authentification**, lancez `main.py` au lieu de
`plante_sante_app.py` :

```bash
streamlit run main.py
```

> Sur Streamlit Community Cloud : Settings → **Main file path** = `main.py`.

Premier démarrage : si la base est vide, un administrateur est créé à partir de
`ADMIN_EMAIL` / `ADMIN_PASSWORD` (ou un compte par défaut à changer aussitôt).
Connexion/déconnexion, rôles ADMIN/USER, protection des pages via
`require_role()`, mots de passe **bcrypt**, anti-brute-force.

> ⚠️ Avec SQLite, la base est **éphémère** sur Streamlit Cloud (réinitialisée à
> chaque redémarrage). Pour une persistance durable, utilisez **PostgreSQL**
> (Supabase, Neon, Railway…) via `DB_BACKEND=postgres` + `DATABASE_URL`.

## ⚙️ Référence de configuration

Toutes ces clés se définissent en **variables d'environnement** ou dans
`.streamlit/secrets.toml` (sur Streamlit Cloud : **Settings → Secrets**).
Seule `ANTHROPIC_API_KEY` est strictement requise ; tout le reste est optionnel.

### Général & base de données
| Clé | Défaut | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Requis.** Clé API Claude. |
| `DB_BACKEND` | `sqlite` | `sqlite` ou `postgres`. |
| `DATABASE_URL` | — | URL PostgreSQL (requis si `postgres`). Ex. Supabase *Session pooler* + `?sslmode=require`. |
| `SQLITE_PATH` | `users.db` | Chemin du fichier SQLite. |

### Authentification & inscription
| Clé | Défaut | Description |
|---|---|---|
| `ADMIN_EMAIL` | `admin@plantdoctor.local` | E-mail du 1ᵉʳ admin (créé si base vide). |
| `ADMIN_PASSWORD` | `ChangeMe123!` | Mot de passe du 1ᵉʳ admin (**à définir**). |
| `ENABLE_REGISTRATION` | `true` | Active l'inscription publique (validée par l'admin). |

### E-mail (notification d'inscription)
| Clé | Défaut | Description |
|---|---|---|
| `SMTP_HOST` | — | Serveur SMTP (ex. `smtp.gmail.com`). |
| `SMTP_PORT` | `587` | `587` (STARTTLS) ou `465` (SSL). |
| `SMTP_USER` / `SMTP_PASSWORD` | — | Identifiants SMTP (Gmail : **mot de passe d'application**). |
| `SMTP_FROM` | — | Adresse expéditrice. |
| `SMTP_USE_TLS` | `true` | STARTTLS (ignoré si port 465). |
| `ADMIN_NOTIFY_EMAIL` | `ADMIN_EMAIL` | Destinataire des notifications. |

> Si SMTP n'est pas configuré, l'inscription fonctionne quand même (le compte
> apparaît dans « Inscriptions en attente » de l'admin).

### Formules & quotas d'analyses
Quotas par formule (0 = illimité). Priorité : *override utilisateur* > *formule* > *défaut global* > illimité.

| Formule | Jour | Semaine | Mois | An |
|---|---|---|---|---|
| FREE | 3 | 10 | 30 | 200 |
| STANDARD | 20 | 120 | 400 | 3000 |
| PREMIUM | ∞ | ∞ | ∞ | ∞ |

| Clé | Description |
|---|---|
| `PLAN_<FORMULE>_<PÉRIODE>` | Surcharge un quota de formule. Ex. `PLAN_FREE_DAY=5`, `PLAN_STANDARD_MONTH=500`. Périodes : `DAY`, `WEEK`, `MONTH`, `YEAR`. |
| `QUOTA_DAY` / `QUOTA_WEEK` / `QUOTA_MONTH` / `QUOTA_YEAR` | Défaut **global** (fallback si la formule ne fixe rien). |

### Historique : photos & rétention
| Clé | Défaut | Description |
|---|---|---|
| `THUMB_MAX_SIDE` | `600` | Taille max des miniatures stockées (px, borné 200–2000). |
| `THUMB_QUALITY` | `70` | Qualité JPEG des miniatures (borné 30–95). |
| `ANALYSIS_RETENTION_MONTHS` | `0` | Purge auto des analyses plus anciennes (0 = jamais). |

### Exemple complet `.streamlit/secrets.toml`
```toml
ANTHROPIC_API_KEY = "sk-ant-..."

DB_BACKEND   = "postgres"
DATABASE_URL = "postgresql://postgres.xxxx:MDP@aws-0-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=require"

ADMIN_EMAIL    = "vous@exemple.com"
ADMIN_PASSWORD = "un_mot_de_passe_solide"
ENABLE_REGISTRATION = "true"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = "587"
SMTP_USER = "vous@gmail.com"
SMTP_PASSWORD = "mot_de_passe_application"
SMTP_FROM = "vous@gmail.com"

# Optionnel
PLAN_FREE_DAY = "5"
THUMB_MAX_SIDE = "800"
ANALYSIS_RETENTION_MONTHS = "12"
```

## 🗂️ Structure des fichiers
| Fichier | Rôle |
|---|---|
| `plante_sante_app.py` | Application Plant Doctor (analyse, historique, export) |
| `main.py` | Point d'entrée **avec authentification** (à utiliser pour activer les comptes) |
| `auth.py` | Authentification, rôles, inscription |
| `database.py` | Accès base (SQLite/PostgreSQL), schéma, CRUD |
| `admin.py` | Tableau de bord + gestion des utilisateurs |
| `quotas.py` | Formules et quotas d'analyses |
| `mailer.py` | Notifications e-mail (SMTP) |
| `user_profile.py` | Page profil (nom, mot de passe, formule) |
| `app.py` | Générateur Intrastat **indépendant** (sans rapport avec Plant Doctor) |

## 🛠️ Technologie

- [Streamlit](https://streamlit.io) — interface web mobile-friendly
- [Claude](https://www.anthropic.com) (`claude-opus-4-8`) — analyse visuelle

## ⚠️ Avertissement

Le diagnostic est généré par une IA, à titre indicatif. Pour une plante de
valeur ou un doute sérieux, consultez un professionnel (pépiniériste,
jardinerie, service phytosanitaire).
