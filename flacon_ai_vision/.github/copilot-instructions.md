<!-- Instructions destinées aux agents IA qui vont coder dans ce dépôt -->
# Copilot / Agent Instructions — Falcon AI Vision (POC)

Résumé rapide
- **Architecture**: POC Python back-end (FastAPI + SQLAlchemy) + simple frontend HTML. Les modules sont répartis en fichiers Python à la racine du workspace (models, schemas, crud, database, app). Le schéma SQL est fourni dans `Untitled-1.sql`.
- **But du guide**: permettre à un agent IA d'être productif immédiatement en expliquant la topologie du code, les points d'intégration et les conventions/problèmes spécifiques à ce dépôt.

Points clés (à lire avant d'éditer)
- **Fichiers clés et rôle**:
  - `from fastapi import FastAPI, Depends, HT.py` — point d'entrée FastAPI (contient `app = FastAPI(...)` et routes).
  - `from pydantic import BaseModel.py` — schémas Pydantic (`UserCreate`, `UserOut`, `CameraCreate`, `EventCreate`, ...).
  - `Untitled-1.py` — SQLAlchemy `Base` et modèles (`User`, `Camera`, `Event`, `Vehicle`).
  - `import os.py` — configuration DB (lit variables d'environnement et expose `engine`, `SessionLocal`, `get_db`).
  - `from passlib.py` — fonctions de hachage, authentification et CRUD helper (ex: `create_user`, `authenticate_user`, `create_camera`, `create_event`).
  - `from backend.app.py` — script d'initialisation DB (appelle `models.Base.metadata.create_all(bind=engine)`).
  - `Untitled-1.sql` — script SQL de création de schéma pour MySQL/MariaDB.
  - `frontend/Untitled-1.html` — simple UI POC consommant l'API (login, grille caméras, ajout caméra).

- **Contrainte majeure**: de nombreux fichiers portent des noms de fichier **malformés** (ex. ils contiennent la première ligne d'import dans le nom). Ces noms empêchent l'utilisation immédiate d'importations relatives/absolues et d'outils standards. Ne renommez ou ne réorganisez pas les fichiers sans validation explicite — demandez avant de normaliser la structure.

Aspects techniques importants
- **Frameworks & libs**: FastAPI, Pydantic, SQLAlchemy, Passlib (bcrypt), driver MySQL via `pymysql` (`mysql+pymysql://...`).
- **DB**: le code attend'une base MySQL/MariaDB. Variables d'environnement utiles: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASS`, `DB_NAME`.
- **Patterns observés**:
  - SQLAlchemy ORM + `declarative_base()` (models en `Untitled-1.py`).
  - Pydantic pour validation d'entrée / sortie (fichiers `from pydantic...`).
  - CRUD et auth cohabitent dans `from passlib.py` (hachage via `CryptContext`). Noms de fonctions réutilisés ailleurs: `authenticate_user`, `create_user`, `list_cameras`, `create_event`.

Conseils pratiques pour agents
- Lorsque vous lisez/modifiez du code, travaillez d'abord sur le contenu des fichiers (edits internes) et évitez les opérations de renommage/moving à grande échelle sans approbation humaine.
- Pour exécuter localement le service, deux approches possibles (à valider avec le mainteneur):
  1. **Réorganisation (recommandée pour exécution)**: déplacer les fichiers dans `backend/app/` avec noms standards (`app.py`, `models.py`, `schemas.py`, `crud.py`, `database.py`, `init_db.py`) et ajouter `__init__.py`. Ensuite lancer:
     - `pip install -r requirements.txt` (si créé)
     - `uvicorn backend.app:app --reload`
  2. **Exécution sans réorg** (fragile): lancer directement les scripts Python en précisant le chemin complet entre guillemets, p.ex. `python "c:\path\to\from backend.app.py"` pour le script d'init. Cette méthode est sujette à erreurs et déconseillée.

Exemples concrets dans le dépôt (pour référence)
- Routes FastAPI: la route `/login` utilise `crud.authenticate_user`; `/users` appelle `crud.create_user`; `/cameras` et `/events` appellent respectivement `create_camera` et `create_event`.
- Initialisation DB: `from backend.app.py` appelle `models.Base.metadata.create_all(bind=engine)`.

Bonnes pratiques spécifiques
- **Modifications d'architecture**: proposez d'abord un plan (liste de fichiers à renommer/déplacer) et attendez confirmation.
- **Tests manuels rapides**: après réorganisation, vérifier que `uvicorn backend.app:app --reload` démarre, puis tester `/health` et `/cameras`.
- **Sécurité**: le POC renvoie un token factice (username) dans `/login`. Si vous implémentez une vraie auth, remplacez par JWT/OAuth2 et ne stockez jamais de mots de passe en clair.

Si tu as besoin que je normalise la structure (création de `backend/app/` et renommage des fichiers), indique "OK, normalise" et je proposerai un patch automatique avec étapes et tests de démarrage.

Questions pour le mainteneur (à valider avant changements invasifs)
- Voulez-vous que j'organise les fichiers en package `backend.app` (oui/non) ?
- Existe-t-il un `requirements.txt` attendu ou un environnement cible (Python version) ?

Merci — propose une action (p.ex. "normalise la structure" ou "crée requirements.txt") pour que j'itère.
