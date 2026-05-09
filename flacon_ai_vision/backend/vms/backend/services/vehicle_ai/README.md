## Vehicle AI Modular Engine

This package is organized as a modular ANPR pipeline with one responsibility per module:

- `vehicle_detection_module.py`
  - Vehicle detection stage
  - Plate-only fallback trigger
  - Selectable tracking backend (`iou` or `sort`) with per-camera `track_id`
- `plate_scanner_module.py`
  - Plate OCR scan from ROI
  - Candidate ranking / merge fallback
  - Plate text plausibility checks + normalization bridge
- `ocr_stabilizer_module.py`
  - Weighted multi-frame OCR voting
  - Camera+track keyed stabilization
  - Stability ratio + margin gating before applying OCR correction
- `vehicle_attributes_module.py`
  - Plate type classification orchestration
  - Plate identity formatting (civil/military display)
  - Vehicle profile enrichment (light classifier + registry enrichment for color/type/marque)
- `vehicle_profile_classifier.py`
  - Lightweight dedicated classifier for vehicle profile
  - Dominant color estimation from ROI
  - Type/body/model/make hints from geometry + detector class
- `tiny_onnx_brand_classifier.py`
  - Optional tiny ONNX brand classifier (feature-flag)
  - Activated only when model is configured and backend is available
  - Falls back silently to light profile classifier
- `vehicle_consistency_module.py`
  - Weighted consistency score (0-1) with explainable reasons and flags
  - Multi-frame smoothing keyed by camera/track (or plate fallback)
  - Confidence level output (`high|medium|low`) for future anomaly/alert engines
- `vehicle_anomaly_module.py`
  - Rule-based anomaly engine (no ML)
  - Uses only consistency score + flags
  - Outputs explicit `level/reason/rules_triggered`
- `vehicle_alert_engine_module.py`
  - Rule-based alert emission layer (no ML)
  - Cooldown + anti-spam + frequency escalation
  - Produces explicit suppression reason and triggered rules
- `vehicle_taxonomy.py`
  - Canonical taxonomy for vehicle colors/brands/categories
  - Alias normalization (EN/FR variants) before API output
  - Stable brand key generation for frontend logo mapping
- `vehicle_live_monitoring_module.py`
  - DB-backed live monitoring snapshot builder for polling UI
  - Aggregates event/alert counters, recent alerts, and lightweight timeline buckets
  - No websocket dependency (REST polling friendly)
- `vehicle_pipeline.py`
  - Main orchestrator (`VehicleRecognitionPipeline`)
  - Stage timings, cache, OCR aggregation, persistence, API response

### Scaling notes

- Tracking and OCR aggregation are keyed by camera (and track where available) to reduce cross-vehicle text mixing.
- Shared heavy components (detector/OCR/normalizer) are initialized once and reused.
- Runtime behavior is configurable via `.env`:
  - `VEHICLE_TRACK_*` + `VEHICLE_TRACKER_MODE=iou|sort`
  - `VEHICLE_SORT_MATCH_IOU`, `VEHICLE_SORT_MATCH_DISTANCE_RATIO`
  - `VEHICLE_TINY_BRAND_ONNX_*` (optional brand classifier)
  - `VEHICLE_CONSISTENCY_W_*`, `VEHICLE_CONSISTENCY_*`
  - `VEHICLE_ANOMALY_*`
  - `VEHICLE_ALERT_*`
  - `VEHICLE_RUNTIME_*`
  - `VEHICLE_ANPR_PLATE_ONLY_FALLBACK`
  - `OCR_BACKEND`, `VEHICLE_OCR_*`

### Robustness benchmark (dataset)

- Batch benchmark script: `vms/backend/scripts/benchmark_vehicle_dataset.py`
- Example:
  - `python vms/backend/scripts/benchmark_vehicle_dataset.py --dataset-root dataset --recursive --camera-id 1 --use-modular-engine true --plate-only-fallback true --output-json data/vehicle_dataset_benchmark/report.json --output-csv data/vehicle_dataset_benchmark/report.csv`
- Optional ground truth CSV columns:
  - `filename,plate_number,plate_type,color,brand,model`
