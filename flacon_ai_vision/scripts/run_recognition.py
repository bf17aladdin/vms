import base64
import json

import requests

from vms.backend.core.database import SESSION_LOCAL, init_db
from vms.backend.services.face_ai.face_pipeline import FaceRecognitionPipeline


def main() -> None:
    response = requests.get("http://127.0.0.1:5001//api/test/camera/frame", timeout=10)
    if response.status_code != 200:
        print("Failed to get frame:", response.status_code, response.text)
        return

    payload = response.json()
    encoded_frame = payload.get("frame_base64")
    if not encoded_frame:
        print("Missing frame_base64 in payload")
        return

    image_bytes = base64.b64decode(encoded_frame)
    print("Got frame bytes:", len(image_bytes))

    init_db()
    db = SESSION_LOCAL()
    try:
        pipeline = FaceRecognitionPipeline(db)
        result = pipeline.recognize_many_from_bytes(
            image_bytes=image_bytes,
            camera_id=0,
            zone_id=None,
            persist=False,
            top_k=5,
            max_faces=0,
        )
    finally:
        db.close()

    print("Recognition result:", json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
