param(
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 5003,
    [string]$LogLevel = "info",
    [switch]$Reload,
    [switch]$ForceCPU,
    [switch]$ForceGPU,
    [string]$PythonExe = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $venvPy = Join-Path $repoRoot "venv_ai\Scripts\python.exe"
    if (Test-Path $venvPy) {
        $PythonExe = $venvPy
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $PythonExe = "python"
    } else {
        throw "Python introuvable. Installe Python ou cree .\\venv_ai"
    }
}

$env:PYTHONPATH = $repoRoot

$verifyScript = Join-Path $repoRoot "scripts\verify_gpu_stack.py"
if (-not (Test-Path $verifyScript)) {
    throw "Script manquant: scripts/verify_gpu_stack.py"
}

$probeRaw = & cmd /c """$PythonExe"" ""$verifyScript"" 2>nul"
if (-not $probeRaw) {
    throw "Impossible de lire le diagnostic GPU"
}

$probe = $probeRaw | ConvertFrom-Json
$torchCuda = [bool]($probe.torch.cuda_available)
$ortCuda = [bool]($probe.onnxruntime.has_cuda_provider)
$gpuReady = [bool]($probe.summary.gpu_ready)

if ($ForceCPU -and $ForceGPU) {
    throw "Options incompatibles: -ForceCPU et -ForceGPU"
}

$mode = "cpu"
if ($ForceCPU) {
    $mode = "cpu"
} elseif ($ForceGPU) {
    if (-not $gpuReady) {
        throw "-ForceGPU demande mais GPU stack non pret (torch/onnxruntime CUDA)"
    }
    $mode = "gpu"
} else {
    $mode = if ($gpuReady) { "gpu" } else { "cpu" }
}

if ($mode -eq "gpu") {
    $env:AI_DEVICE = "auto"
    $env:VEHICLE_AI_DEVICE = "auto"
    $env:FACE_ONNX_PROVIDERS = "CUDAExecutionProvider,CPUExecutionProvider"
    $env:VEHICLE_EASYOCR_GPU = "true"
} else {
    $env:AI_DEVICE = "cpu"
    $env:VEHICLE_AI_DEVICE = "cpu"
    $env:FACE_ONNX_PROVIDERS = "CPUExecutionProvider"
    $env:VEHICLE_EASYOCR_GPU = "false"
}

Write-Host ""
Write-Host "Backend auto-start profile"
Write-Host "repoRoot      : $repoRoot"
Write-Host "python        : $PythonExe"
Write-Host "mode          : $mode"
Write-Host "torch_cuda    : $torchCuda"
Write-Host "ort_cuda      : $ortCuda"
Write-Host "AI_DEVICE     : $env:AI_DEVICE"
Write-Host "VEHICLE_AI_DEVICE: $env:VEHICLE_AI_DEVICE"
Write-Host "FACE_ONNX_PROVIDERS: $env:FACE_ONNX_PROVIDERS"
Write-Host "VEHICLE_EASYOCR_GPU: $env:VEHICLE_EASYOCR_GPU"
Write-Host ""
Write-Host "GPU stack report:"
$probe | ConvertTo-Json -Depth 10
Write-Host ""

$args = @("-m", "uvicorn", "vms.backend.main:app", "--host", $BindHost, "--port", "$Port", "--log-level", $LogLevel)
if ($Reload) {
    $args += "--reload"
}

Write-Host "Starting backend: $PythonExe $($args -join ' ')"
& $PythonExe @args


