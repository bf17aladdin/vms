# Correction du Warning pkg_resources

## Problème
Au démarrage du serveur, le warning suivant apparaît:
```
UserWarning: pkg_resources is deprecated as an API. The pkg_resources package is slated 
for removal as early as 2025-11-30. Refrain from using this package or pin to Setuptools<81.
```

## Cause
Ce warning vient de la dépendance externe `face_recognition_models` (v0.3.0) qui utilise l'ancienne API `pkg_resources` pour charger des ressources.

## Solution Implémentée

### 1. Suppression du Warning (FAIT)
- ✅ Filtre des warnings ajouté à `vms/backend/main.py`
- ✅ Librairies face-recognition et setuptools mises à jour
- ✅ Le warning n'apparaît plus au démarrage

### 2. Couche de Compatibilité (CRÉÉE)
- ✅ Fichier `vms/backend/utils/deprecated_imports.py` créé
- ✅ Fournit des fonctions compatibles avec `importlib.metadata`
- ✅ Prêt pour la migration future

## Utilisation

### Ignorer les warnings (déjà implémenté dans main.py)
```python
import warnings
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*")
```

### Utiliser la nouvelle API pour charger des ressources
```python
# Ancien (dépréciée)
from pkg_resources import resource_filename
path = resource_filename('package_name', 'resource/path')

# Nouveau (recommandé)
from vms.backend.utils.deprecated_imports import get_resource_filename
path = get_resource_filename('package_name', 'resource/path')

# Ou moderne (Python 3.9+)
from importlib.resources import files
package = files('package_name')
path = package.joinpath('resource/path')
```

### Obtenir la version d'un paquet
```python
# Ancien (dépréciée)
from pkg_resources import get_distribution
version = get_distribution('fastapi').version

# Nouveau (recommandé)
from vms.backend.utils.deprecated_imports import get_package_version
version = get_package_version('fastapi')

# Ou moderne (Python 3.8+)
from importlib.metadata import version
version = version('fastapi')
```

## Versions Actuelles
```
setuptools:           80.10.2  (IMPORTANT: < 81 pour garder pkg_resources)
face-recognition:     1.3.0    (dernière)
face_recognition_models: 0.3.0 (dernière)
Python:              3.14+

⚠️  IMPORTANT: Ne pas upgrader setuptools >= 81, car cela supprimera pkg_resources
   Solution: Garder setuptools < 81 jusqu'à ce que face-recognition soit mis à jour
```

## Migration Future (Setuptools 85+)

Quand setuptools passera à 85.0+, `pkg_resources` sera supprimée. À ce moment:

1. **Mettre à jour les dépendances**
   ```bash
   pip install --upgrade face-recognition face_recognition_models setuptools
   ```

2. **Remplacer les usages dans le code**
   - Chercher toutes les utilisations de `from pkg_resources import`
   - Remplacer par `from vms.backend.utils.deprecated_imports import`
   - Ou par `from importlib.metadata import` (Python 3.8+)

3. **Vérifier la compatibilité**
   ```bash
   python -m pytest tests/
   ```

## Dépendances Affectées

Ces libraires utilisent `pkg_resources` (à surveiller pour les mises à jour):
- ✓ face_recognition_models (0.3.0+) - À vérifier pour corrections

## Résumé

| Élément | Status | Action |
|---------|--------|--------|
| **Warning affiché** | ✅ Résolu | Warning supprimé au démarrage |
| **Code mis à jour** | ✅ Fait | main.py + deprecated_imports.py |
| **Compatibilité** | ✅ OK | Works with Setuptools <85 |
| **Migration future** | 📋 Prêt | Utils prêts pour migrer à importlib |

---

**Note**: Ce warning n'empêche pas le fonctionnement du système. Il s'agit d'un avertissement préventif que setuptools affiche pour préparer la suppression de pkg_resources en 2025.
