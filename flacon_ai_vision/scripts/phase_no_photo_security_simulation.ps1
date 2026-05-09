param(
    [string]$ApiBase = "http://127.0.0.1:5003",
    [string]$Token = "",
    [string]$Username = "admin",
    [string]$Password = "admin123",
    [int]$CameraId = 1,
    [string]$GateId = "SIM-GATE"
)

$ErrorActionPreference = "Stop"

function Get-PythonExe {
    $candidates = @(
        ".\venv_ai\Scripts\python.exe",
        ".\venv\Scripts\python.exe",
        ".\.venv\Scripts\python.exe",
        "python"
    )
    foreach ($c in $candidates) {
        try {
            if ($c -eq "python") { return $c }
            if (Test-Path $c) { return $c }
        } catch { }
    }
    return "python"
}

function Login-Token {
    param([string]$BaseUrl, [string]$User, [string]$Pass)
    $body = @{ username = $User; password = $Pass } | ConvertTo-Json
    for ($i = 1; $i -le 2; $i++) {
        try {
            $resp = Invoke-RestMethod -Uri "$BaseUrl/api/auth/login" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 30
            return [string]$resp.access_token
        } catch {
            $status = 0
            if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
            if ($status -eq 429 -and $i -lt 2) {
                Start-Sleep -Seconds 65
                continue
            }
            throw
        }
    }
    throw "Login failed"
}

if ([string]::IsNullOrWhiteSpace($Token)) {
    $Token = Login-Token -BaseUrl $ApiBase -User $Username -Pass $Password
}

$headers = @{ Authorization = "Bearer $Token"; "Content-Type" = "application/json" }

Write-Host "== No-Photo Security Simulation =="
Write-Host "API: $ApiBase"

# Scenario 1: camera offline -> tamper alert.
$camPayload = @{
    gate_id = $GateId
    direction = "IN"
    persist = $true
    save_snapshot = $true
} | ConvertTo-Json

$tamperResp = Invoke-RestMethod -Uri "$ApiBase/api/vehicle/recognize/camera/$CameraId" -Method Post -Headers $headers -Body $camPayload -TimeoutSec 30
$tamperPass = ([string]$tamperResp.status -eq "camera_tamper") -and ([string]$tamperResp.decision -eq "denied")

# Scenarios 2/3/4 simulated directly with decision engine and persisted in DB.
$env:SIM_CAMERA_ID = [string]$CameraId
$python = Get-PythonExe
$pyOut = @'
import os
import json
from datetime import datetime

from vms.backend.core.database import SessionLocal, init_db
from vms.backend.models import User, Camera, VehicleRegistry
from vms.backend.services.vehicle_ai.access_control import VehicleAccessController

init_db()
db = SessionLocal()

result = {"success": False}
try:
    admin = db.query(User).filter(User.username == "admin").first() or db.query(User).first()
    if admin is None:
        raise RuntimeError("no_user_available")

    cam = None
    cam_env = os.getenv("SIM_CAMERA_ID", "").strip()
    if cam_env:
        try:
            cam = db.query(Camera).filter(Camera.id == int(cam_env)).first()
        except Exception:
            cam = None
    if cam is None:
        cam = db.query(Camera).first()
    if cam is None:
        cam = Camera(
            name="SIM Camera",
            description="no-photo simulation camera",
            is_active=False,
            connection_status="disconnected",
            owner_id=int(admin.id),
        )
        db.add(cam)
        db.commit()
        db.refresh(cam)

    wh_plate = "SIM1234"
    reg = db.query(VehicleRegistry).filter(VehicleRegistry.matricule == wh_plate).first()
    if reg is None:
        reg = VehicleRegistry(
            matricule=wh_plate,
            marque="Toyota",
            modele="Hilux",
            couleur="white",
            categorie="civil",
            unite=None,
            statut="actif",
            is_flagged=False,
            flag_reason=None,
        )
        db.add(reg)
        db.commit()
        db.refresh(reg)

    ctrl = VehicleAccessController(db)

    def run_case(label, plate, conf, plate_conf, plate_type):
        decision = ctrl.evaluate(
            plate_number=plate,
            plate_type=plate_type,
            confidence=float(conf),
            plate_confidence=float(plate_conf),
            vehicle_type="car",
            vehicle_bbox=None,
            frame_bgr=None,
            classifier_security_tag=None,
            classifier_registry_match=False,
        )
        log_id, alert_ids = ctrl.persist_access_decision(
            decision=decision,
            event_id=None,
            plate_number=plate,
            plate_type=plate_type,
            camera_id=int(cam.id),
            gate_id="SIM-GATE",
            direction="IN",
            timestamp=datetime.utcnow(),
            snapshot_path=None,
            vehicle_detected=True,
            vehicle_type="car",
            plate_confidence=float(plate_conf),
        )
        return {
            "label": label,
            "plate": plate,
            "decision": decision.decision,
            "reason": decision.reason,
            "requires_review": bool(decision.requires_manual_review),
            "alert_type": decision.alert_type,
            "access_log_id": log_id,
            "alert_ids": alert_ids,
        }

    unknown_case = run_case("unknown_plate_denied", "UNK9999", 0.96, 0.95, "civil")
    allowed_case = run_case("whitelist_allowed", wh_plate, 0.97, 0.96, "civil")
    review_case = run_case("low_conf_review", wh_plate, 0.60, 0.58, "civil")

    result = {
        "success": True,
        "camera_id": int(cam.id),
        "unknown_case": unknown_case,
        "allowed_case": allowed_case,
        "review_case": review_case,
    }
finally:
    db.close()

print(json.dumps(result))
'@ | & $python -

$sim = $pyOut | ConvertFrom-Json

$unknownPass = ([string]$sim.unknown_case.decision -eq "denied")
$allowedPass = ([string]$sim.allowed_case.decision -eq "allowed")
$reviewPass = ([string]$sim.review_case.decision -eq "review_required")

# Scenario 5: manual override on review case.
$overrideBody = @{
    access_log_id = [int]$sim.review_case.access_log_id
    forced_decision = "allowed"
    note = "No-photo simulation manual override"
} | ConvertTo-Json

$overrideResp = Invoke-RestMethod -Uri "$ApiBase/api/vehicle/access/manual-override" -Method Post -Headers $headers -Body $overrideBody -TimeoutSec 30
$overridePass = ([string]$overrideResp.override.decision -eq "manual_override")

$alertsResp = Invoke-RestMethod -Uri "$ApiBase/api/vehicle/access/alerts?limit=20" -Method Get -Headers @{ Authorization = "Bearer $Token" } -TimeoutSec 30
$logsResp = Invoke-RestMethod -Uri "$ApiBase/api/vehicle/access/logs?limit=20" -Method Get -Headers @{ Authorization = "Bearer $Token" } -TimeoutSec 30

$report = [pscustomobject]@{
    phase = "no_photo_security_simulation"
    timestamp = (Get-Date).ToString("o")
    api_base = $ApiBase
    scenarios = [pscustomobject]@{
        camera_offline_tamper = [pscustomobject]@{
            pass = $tamperPass
            response = $tamperResp
        }
        unknown_plate_denied = [pscustomobject]@{
            pass = $unknownPass
            result = $sim.unknown_case
        }
        whitelist_allowed = [pscustomobject]@{
            pass = $allowedPass
            result = $sim.allowed_case
        }
        low_confidence_review = [pscustomobject]@{
            pass = $reviewPass
            result = $sim.review_case
        }
        manual_override = [pscustomobject]@{
            pass = $overridePass
            response = $overrideResp
        }
    }
    recent = [pscustomobject]@{
        alerts_count = [int]$alertsResp.count
        logs_count = [int]$logsResp.count
        alerts = $alertsResp.alerts
        logs = $logsResp.logs
    }
}

$null = New-Item -ItemType Directory -Force -Path "logs"
$reportPath = "logs\\phase_no_photo_security_simulation_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss")
$report | ConvertTo-Json -Depth 10 | Set-Content -Path $reportPath -Encoding UTF8

Write-Host ""
Write-Host "Simulation verdict:"
Write-Host ("camera_offline_tamper: " + $tamperPass)
Write-Host ("unknown_plate_denied: " + $unknownPass)
Write-Host ("whitelist_allowed: " + $allowedPass)
Write-Host ("low_confidence_review: " + $reviewPass)
Write-Host ("manual_override: " + $overridePass)
Write-Host ""
Write-Host "Report saved: $reportPath"
