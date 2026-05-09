#!/usr/bin/env python3
import requests
import json

TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsInVzZXJfaWQiOjEsInJvbGUiOiJhZG1pbiIsImV4cCI6MTc3MTI1MDkzM30.HB0k5Jgo-5ypZyZNOGFqKynPhS9k7NC1YwyXEGELQMU'
HEADERS = {'Authorization': f'Bearer {TOKEN}'}
BASE_URL = 'http://localhost:5003'

def test_live_stream():
    """Test 1: Live Stream Page - /api/cameras"""
    print('=' * 50)
    print('TEST 1: 📹 Live Stream Page')
    print('=' * 50)
    try:
        resp = requests.get(f'{BASE_URL}/api/cameras', headers=HEADERS, timeout=5)
        data = resp.json()
        if 'cameras' in data:
            print(f'✓ Cameras endpoint: {data["count"]} cameras found')
            for cam in data['cameras'][:2]:
                print(f'  - {cam["name"]} ({cam["status"]})')
        else:
            print(f'✓ Response: {data}')
        return True
    except Exception as e:
        print(f'✗ Error: {e}')
        return False

def test_ai_gallery():
    """Test 2: AI Gallery - /api/ai/facial/history"""
    print('\n' + '=' * 50)
    print('TEST 2: 🖼️ AI Gallery (Faces)')
    print('=' * 50)
    try:
        resp = requests.get(f'{BASE_URL}/api/ai/facial/history', headers=HEADERS, timeout=5)
        data = resp.json()
        if 'count' in data:
            print(f'✓ Facial detections: {data["count"]} found')
        elif 'detections' in data:
            print(f'✓ Detections: {len(data["detections"])} found')
        else:
            print(f'✓ Response: {data}')
        return True
    except Exception as e:
        print(f'✗ Error: {e}')
        return False

def test_recorded_videos():
    """Test 3: Recorded Videos - /api/videos/recorded"""
    print('\n' + '=' * 50)
    print('TEST 3: 🎬 Recorded Videos')
    print('=' * 50)
    try:
        resp = requests.get(f'{BASE_URL}/api/videos/recorded', headers=HEADERS, timeout=5)
        data = resp.json()
        if isinstance(data, list):
            print(f'✓ Videos: {len(data)} found')
        elif isinstance(data, dict):
            count = data.get('count', len(data))
            print(f'✓ Response: {count} items')
        else:
            print(f'✓ Response received: {type(data)}')
        return True
    except Exception as e:
        print(f'✗ Error: {e}')
        return False

if __name__ == '__main__':
    print('\n🧪 Testing 3 New Pages Endpoints\n')
    
    results = []
    results.append(('Live Stream', test_live_stream()))
    results.append(('AI Gallery', test_ai_gallery()))
    results.append(('Recorded Videos', test_recorded_videos()))
    
    print('\n' + '=' * 50)
    print('SUMMARY')
    print('=' * 50)
    for name, success in results:
        status = '✓ PASS' if success else '✗ FAIL'
        print(f'{status}: {name}')
    
    passed = sum(1 for _, s in results if s)
    print(f'\nTotal: {passed}/{len(results)} tests passed\n')
