$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "smoke_test.ps1") @args
& (Join-Path $PSScriptRoot "run_backend_integration_tests.ps1")
