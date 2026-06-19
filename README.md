# 🌿 Plant Doctor — Analyseur de santé des plantes

Application web **optimisée pour smartphone** : prenez une photo d'une plante
avec l'appareil photo de votre téléphone, l'IA de vision de **Claude** analyse
son état de santé, détecte maladies / parasites / carences, et propose des
**solutions concrètes**.

> ℹ️ Le dépôt contient aussi `app.py`, un générateur Intrastat indépendant.
> L'application décrite ici est `plante_sante_app.py`.

## ✨ Fonctionnalités

- 📷 Prise de **plusieurs photos** (jusqu'à 4, sous différents angles) via l'appareil photo ou la galerie
- 🪴 Identification de la plante (nom commun, nom latin, famille)
- 🩺 Évaluation de l'état de santé avec score sur 100
- 🔬 **Analyse détaillée** : identification, conditions de culture, symptômes & causes
- 🔍 Détection des problèmes (maladies, parasites, carences, stress hydrique…)
- 🖼️ **Illustrations** : schéma dessiné par l'IA + liens vers des photos d'exemples
- 💊 Plan d'action priorisé, 🛡️ prévention et 🗓️ routine d'entretien
- 🇫🇷 Diagnostic entièrement en français

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

## 🛠️ Technologie

- [Streamlit](https://streamlit.io) — interface web mobile-friendly
- [Claude](https://www.anthropic.com) (`claude-opus-4-8`) — analyse visuelle

## ⚠️ Avertissement

Le diagnostic est généré par une IA, à titre indicatif. Pour une plante de
valeur ou un doute sérieux, consultez un professionnel (pépiniériste,
jardinerie, service phytosanitaire).
