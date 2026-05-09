# Start Falcon AI Vision backend (PowerShell)
if (Test-Path ".venv\Scripts\Activate.ps1") {
  & .venv\Scripts\Activate.ps1
}
& .venv\Scripts\uvicorn.exe vms.backend.main:app --port 5003 --reload
