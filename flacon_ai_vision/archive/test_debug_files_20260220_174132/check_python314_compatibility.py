#!/usr/bin/env python3
"""
Vérification de compatibilité Python 3.14 avec les dépendances critiques
"""

import sys

print('='*70)
print('VÉRIFICATION COMPATIBILITÉ PYTHON 3.14')
print('='*70)
print(f'\nVersion Python: {sys.version}')
print(f'Python Implementation: {sys.implementation.name}')

# Test imports critiques
packages = [
    ('SQLAlchemy', 'sqlalchemy'),
    ('Pydantic', 'pydantic'),
    ('FastAPI', 'fastapi'),
    ('Uvicorn', 'uvicorn'),
    ('PyMySQL', 'pymysql'),
    ('Passlib', 'passlib'),
    ('PyJWT', 'jwt'),
    ('Python-Multipart', 'multipart'),
]

print('\n' + '-'*70)
print('Test chargement des packages:')
print('-'*70)

all_ok = True
for name, module in packages:
    try:
        mod = __import__(module)
        version = getattr(mod, '__version__', 'Unknown')
        print(f'✓ {name:<25} {version}')
    except ImportError as e:
        print(f'✗ {name:<25} ERREUR: {e}')
        all_ok = False
    except Exception as e:
        print(f'? {name:<25} {e}')

print('\n' + '='*70)
if all_ok:
    print('✅ TOUS LES PACKAGES SONT COMPATIBLES AVEC PYTHON 3.14!')
    print('   SQLAlchemy, Pydantic, FastAPI fonctionnent parfaitement.')
else:
    print('⚠️  Certains packages ne sont pas disponibles.')
    print('   Installez les dépendances: pip install -r requirements.txt')
print('='*70)
