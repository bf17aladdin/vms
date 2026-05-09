#!/usr/bin/env python3
"""
Test rapide des APIs SOC Dashboard
"""

import requests
import json

def test_soc_apis():
    base_url = 'http://127.0.0.1:5003'

    print('🧪 Test des APIs SOC Dashboard')
    print('=' * 50)

    # Test métriques SOC
    try:
        response = requests.get(f'{base_url}/api/soc/metrics', timeout=5)
        if response.status_code == 200:
            data = response.json()
            print('✅ GET /api/soc/metrics - OK')
            print(f'   Caméras: {data.get("cameras_active", 0)}/{data.get("cameras_total", 0)} actives')
        else:
            print(f'❌ GET /api/soc/metrics - Status {response.status_code}')
    except Exception as e:
        print(f'❌ GET /api/soc/metrics - Erreur: {e}')

    # Test alertes
    try:
        response = requests.get(f'{base_url}/api/soc/alerts', timeout=5)
        if response.status_code == 200:
            data = response.json()
            print('✅ GET /api/soc/alerts - OK')
            print(f'   Alertes trouvées: {len(data)}')
        else:
            print(f'❌ GET /api/soc/alerts - Status {response.status_code}')
    except Exception as e:
        print(f'❌ GET /api/soc/alerts - Erreur: {e}')

    print('')
    print('📋 APIs SOC disponibles:')
    print('   • GET  /api/soc/metrics - Métriques opérationnelles')
    print('   • GET  /api/soc/alerts - Alertes récentes')
    print('   • WS   /api/soc/ws - WebSocket temps réel')
    print('   • GET  /api/soc/export/* - Exports PDF/Excel')

if __name__ == '__main__':
    test_soc_apis()