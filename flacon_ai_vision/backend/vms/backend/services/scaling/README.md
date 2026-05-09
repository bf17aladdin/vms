# Scaling Modules (Parallel Path)

These modules are intentionally isolated from the current production routes/UI.

Goals:
- Keep existing workflow untouched.
- Build a parallel scalable architecture for 20+ cameras.
- Validate each block independently before integration.

Modules:
- `frame_task_queue.py`: bounded queues + backpressure + dedupe by camera.
- `multi_camera_ingestion_service.py`: continuous multi-camera ingestion with sampling.
- `vehicle_inference_service.py`: inference runner using existing `VehicleRecognitionPipeline`.
- `vehicle_inference_worker.py`: async inference worker(s).
- `vehicle_event_persistence_service.py`: async DB persistence adapter.
- `vehicle_event_writer_worker.py`: async event writer with retries.

Recommended execution model:
1. Ingestion service pushes `FrameTask` into queue A.
2. Inference workers consume queue A and push `InferenceResultTask` into queue B.
3. Event writer workers consume queue B and persist to DB.
