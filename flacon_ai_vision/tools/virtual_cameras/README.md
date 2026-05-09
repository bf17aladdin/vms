# Virtual Cameras

This folder provides a complete virtual RTSP camera environment for Falcon AI Vision. It turns local videos such as `cam01` to `cam04` from `Downloads` into stable RTSP feeds, making local validation possible without physical cameras or NVR hardware.

## Included scripts

- `start_video_virtual_cameras.ps1`: starts MediaMTX if needed, launches 4 looping RTSP publishers, and writes runtime metadata
- `stop_video_virtual_cameras.ps1`: stops the virtual camera FFmpeg publishers and the owned MediaMTX instance
- `smoke_test_virtual_cameras.ps1`: validates all RTSP endpoints with `ffprobe` and checks FFmpeg process health
- `register_virtual_cameras.ps1`: creates or updates the virtual cameras in Falcon AI Vision
- `prepare_local_ai_test.ps1`: validates the streams, captures comparison snapshots, scores face/vehicle suitability, tags cameras in SQLite, and can hit Falcon face/vehicle endpoints

## Start the RTSP streams

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\virtual_cameras\start_video_virtual_cameras.ps1
```

This creates:

- `rtsp://127.0.0.1:8554/cam01`
- `rtsp://127.0.0.1:8554/cam02`
- `rtsp://127.0.0.1:8554/cam03`
- `rtsp://127.0.0.1:8554/cam04`

Default streaming profile:

- codec: H.264 via `libx264`
- preset: `veryfast`
- tune: `zerolatency`
- resolution: `1280x720`
- fps: `25`
- bitrate: `1000k`

## Smoke test all RTSP streams

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\virtual_cameras\smoke_test_virtual_cameras.ps1
```

Expected style of output:

```text
cam01 OK
cam02 OK
cam03 OK
cam04 OK
```

The smoke test validates:

- RTSP endpoint reachability
- detected video codec
- normalized output resolution
- frame rate visibility through `ffprobe`
- active FFmpeg publisher process per virtual camera

## Register them in Falcon AI

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\virtual_cameras\register_virtual_cameras.ps1 -Username YOUR_USER -Password YOUR_PASSWORD -EnableAi
```

Default backend target: `http://127.0.0.1:5003`

## Prepare Falcon for local AI testing

The backend now defaults to local SQLite at `./data/falcon.db` when `DATABASE_URL` is not set.

Run the end-to-end local prep workflow with:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\virtual_cameras\prepare_local_ai_test.ps1
```

This workflow:

- validates RTSP reachability for `cam01` to `cam04`
- confirms codec, resolution, and frame rate via `ffprobe`
- captures temporary snapshots under `.\data\camera_selection\...`
- scores brightness, blur, face visibility, and vehicle suitability
- assigns database roles: `best_for_faces`, `best_for_vehicles`, `mixed_detection`
- registers or updates the virtual cameras in Falcon SQLite
- optionally validates `/api/facial/detect-faces/{camera_id}` and `/api/vehicle/recognize/camera/{camera_id}` if the backend is already running

## Stop the streams

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\virtual_cameras\stop_video_virtual_cameras.ps1
```

## Validation Notes

Validated locally with:

- `ffprobe` successfully reading `cam01` to `cam04`
- H.264 detected on all four streams
- output resolution confirmed as `1280x720`
- frame rate confirmed as `25 fps`
- FFmpeg publisher processes confirmed running for each stream

Known note:

- `cam02` may emit a minor decoder warning such as `Missing reference picture`, while still remaining readable and passing the smoke test

## Result

This setup provides a stable, reproducible multi-camera RTSP lab for Falcon AI Vision. It is intended for plug-and-play ingestion, stream validation, and detection pipeline testing without requiring any physical camera hardware.
