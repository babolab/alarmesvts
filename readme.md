# Alarmes Collision – Rapport Streamlit

Application Streamlit pour importer un fichier CSV d’alarmes VTS/anticollision, filtrer les événements **COLLISION**, sélectionner un ou plusieurs navires + une plage de dates, puis générer :
- un rapport affiché dans la page,
- un export **CSV**,
- un export **PDF** (mode paysage) avec logo.

## Fonctionnalités

- Import d’un CSV d’alarmes.
- Filtre sur `event_type == "COLLISION"`.
- Extraction de la liste unique des navires à partir de :
  - `ship_name`
  - `target_1_ship_name`
- Sélection multi-navires.
- Sélection d’une période (dates min/max par défaut selon le fichier).
- Rapport **par navire sélectionné** (sections séparées).
- Colonnes du rapport :
  - Navire, Navire cible
  - CPA (m) : `dcpam` (mise en rouge si < 150 m)
  - TCPA (min) : conversion depuis `tcpamsec` (supposé en millisecondes)
  - Date, Heure (`event_dt_local`)
  - Position du navire (conversion WKT `POINT(lon lat)` -> DMS)
  - Commentaire (concaténation de `ack_comment`)
- Déduplication / regroupement :
  - Couple **non ordonné** (A/B = B/A)
  - Fenêtre **15 minutes** : si plusieurs lignes d’un même couple dans la fenêtre, on retient l’alarme au **CPA minimal**
  - Commentaires concaténés avec séparateur ` | ` (et `-` si aucun commentaire)

## Structure attendue du CSV

Le code suppose que le CSV contient au minimum les colonnes suivantes :

- `ship_name`
- `target_1_ship_name`
- `event_type`
- `event_dt_local`
- `event_pos_wkt` (ex: `POINT(-2.78 50.04)`)
- `dcpam` (CPA en mètres)
- `tcpamsec` (TCPA — **interprété comme millisecondes**)
- `ack_comment` (optionnel, peut être vide)

Si ton export n’a pas exactement les mêmes noms de colonnes, il faudra adapter la fonction `load_and_clean()`.

## Installation

### Prérequis
- Python 3.10+ (testé avec Python 3.12)
- pip

### Installer les dépendances

```bash
pip install -r requirements.txt
```

Exemple de `requirements.txt` :

```txt
streamlit
pandas
fpdf2
```


## Lancer l’application

```bash
streamlit run app.py
```

Puis ouvre : http://localhost:8501

## Ajouter un logo

Place un fichier `logo.png` à la racine, au même niveau que `app.py` :

```
.
├─ app.py
├─ logo.png
├─ requirements.txt
└─ README.md
```

- Dans Streamlit : affiché en haut à gauche.
- Dans le PDF : affiché en petit en haut à droite.


## Sorties

### Export CSV

- Encodage : UTF-8 with BOM (`utf-8-sig`)
- Séparateur : `;`


### Export PDF

- Généré avec `fpdf2`
- Orientation : paysage
- Mise en évidence CPA < 150 m (rouge)
- En-tête indiquant : alarmes groupées par couple de navires et par intervalle de 15 minutes


## Notes / Paramètres importants

- TCPA : le champ `tcpamsec` est traité comme **millisecondes** et converti en minutes via :
    - `tcpa_min = tcpamsec / 1000 / 60`
- Filtre TCPA appliqué :
    - `0 ≤ TCPA ≤ 7 minutes`
- Les lignes avec CPA/TCPA manquants sont exclues (conformément aux règles).
- Les navires sans nom (vide/NaN) sont exclus avant construction des couples.
- Pour éviter des erreurs de tri / groupby sur des tuples, on recommande d’utiliser une clé de couple en chaîne (`"A||B"`), ou de bien nettoyer les NaN.


## Dépannage

### Erreur “< not supported between instances of 'float' and 'str'”

Cause typique : `ship_name` ou `target_1_ship_name` contient un NaN (float) au lieu d’une chaîne.

Correctifs recommandés dans `load_and_clean()` :

- `fillna("")` puis `.str.strip()` sur les colonnes de noms
- Exclure les lignes dont l’un des deux noms est vide
- Construire `couple_key` en **chaîne** plutôt qu’en tuple, par ex. `"||".join(sorted([...]))`


### PDF : caractères non supportés (Unicode)

Les polices de base (Helvetica) ne supportent pas certains caractères Unicode (ex: `→`).

- Remplacer `→` par `->`
- Ou charger une police Unicode (TTF) si nécessaire


## Déploiement sur Streamlit Community Cloud

### Prérequis

- Un compte GitHub
- Un compte Streamlit Community Cloud : https://streamlit.io/cloud (gratuit)


### Structure du repo GitHub

```
.
├── app.py
├── logo.png
├── requirements.txt
└── README.md
```

> Si tu utilises `fpdf2`, **aucun package système** n’est nécessaire.

#### Option alternative (si un jour tu bascules vers weasyprint)

Sur Streamlit Cloud (Linux), `weasyprint` peut fonctionner si tu ajoutes un fichier `packages.txt` :

`requirements.txt` (exemple) :

```txt
streamlit
pandas
weasyprint
```

`packages.txt` :

```txt
libpango-1.0-0
libpangocairo-1.0-0
libcairo2
libgdk-pixbuf2.0-0
libffi-dev
shared-mime-info
```


### Étapes de déploiement

1. **Pousser le code sur GitHub** :

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/TON_USER/TON_REPO.git
git push -u origin main
```

2. Aller sur https://share.streamlit.io et se connecter.
3. Cliquer sur **New app**.
4. Renseigner :
    - Repository : `TON_USER/TON_REPO`
    - Branch : `main`
    - Main file path : `app.py`
5. Cliquer sur **Deploy**.

### Mises à jour

À chaque `git push` sur la branche `main`, Streamlit Community Cloud redéploie automatiquement l’application.

