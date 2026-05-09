import requests
import io
from PIL import Image
import random

def fake_image_bytes():
    # Génère une image JPEG en mémoire
    img = Image.new('RGB', (128, 128), (random.randint(0,255), random.randint(0,255), random.randint(0,255)))
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    buf.seek(0)
    return buf

def test_facial_recognition():
    url = 'http://127.0.0.1:5003/api/ai/facial/recognize'
    files = {'file': ('test.jpg', fake_image_bytes(), 'image/jpeg')}
    data = {'camera_id': 1}
    r = requests.post(url, files=files, data=data)
    print('Facial recognize:', r.status_code, r.json())

def test_vehicle_detection():
    url = 'http://127.0.0.1:5003/api/ai/vehicles/record-detection'
    data = {'license_plate': 'AA-123-BB', 'confidence': 0.95, 'camera_id': 1}
    r = requests.post(url, data=data)
    print('Vehicle detection:', r.status_code, r.json())

def test_zone_creation():
    url = 'http://127.0.0.1:5003/api/ai/zones/create'
    data = [
        ('name', 'ZoneTest'),
        ('camera_id', 1),
        ('polygon_coords', str([[10,10],[100,10],[100,100],[10,100]])),
    ]
    r = requests.post(url, data=data)
    print('Zone creation:', r.status_code, r.json())

if __name__ == '__main__':
    test_facial_recognition()
    test_vehicle_detection()
    test_zone_creation()
