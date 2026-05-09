[CmdletBinding()]
param(
    [ValidateSet("check", "pre-commit")]
    [string]$Mode = "check",
    [switch]$Strict
)

$ErrorActionPreference = "Stop"

function Invoke-GitLines {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $stderrPath = [System.IO.Path]::GetTempFileName()
    try {
        $output = & git -c core.safecrlf=false @Arguments 2>$stderrPath
        if ($LASTEXITCODE -ne 0) {
            return @()
        }

        if ($null -eq $output) {
            return @()
        }

        return @($output | ForEach-Object { [string]$_ })
    }
    finally {
        Remove-Item $stderrPath -ErrorAction SilentlyContinue
    }
}

function Normalize-RepoPath {
    param([string]$Path)

    if ($null -eq $Path) {
        return ""
    }

    return ([string]$Path).Trim() -replace "\\", "/"
}

function Write-Section {
    param([string]$Title)

    Write-Host ""
    Write-Host "== $Title =="
}

$allowRules = @(
    [pscustomobject]@{ Regex = '^\.env\.example$'; Label = '.env example template' }
)

$blockRules = @(
    [pscustomobject]@{ Regex = '^\.vscode/(?!extensions\.json$)'; Label = 'local VS Code workspace files' },
    [pscustomobject]@{ Regex = '^\.idea/'; Label = 'JetBrains workspace files' },
    [pscustomobject]@{ Regex = '(^|/)__pycache__/'; Label = 'Python bytecode cache' },
    [pscustomobject]@{ Regex = '\.(pyc|pyo|pyd)$'; Label = 'Python bytecode artifact' },
    [pscustomobject]@{ Regex = '(^|/)node_modules/'; Label = 'Node dependency directory' },
    [pscustomobject]@{ Regex = '^build/'; Label = 'build output' },
    [pscustomobject]@{ Regex = '^dist/'; Label = 'build output' },
    [pscustomobject]@{ Regex = '^vms/frontend/dist/'; Label = 'frontend build output' },
    [pscustomobject]@{ Regex = '^logs/'; Label = 'log directory' },
    [pscustomobject]@{ Regex = '^reports/'; Label = 'report output' },
    [pscustomobject]@{ Regex = '^runs/'; Label = 'runtime output' },
    [pscustomobject]@{ Regex = '^backups/'; Label = 'backup output' },
    [pscustomobject]@{ Regex = '^recordings/'; Label = 'runtime recordings' },
    [pscustomobject]@{ Regex = '^data/(camera_tamper|datasets|detections|exports|face_detections|known_faces|known_faces_test|recordings|reports|thumbnails|unknown_detections|unknown_faces|vehicle_dataset_benchmark|vehicle_events|vehicle_event_frames|vehicles)/'; Label = 'runtime data output' },
    [pscustomobject]@{ Regex = '^data/(ai_calibration\.json|seed_webcam\.mp4)$'; Label = 'runtime local asset' },
    [pscustomobject]@{ Regex = '^tmp_'; Label = 'temporary scratch file' },
    [pscustomobject]@{ Regex = '\.(log|tmp|temp|bak|orig|rej)$'; Label = 'temporary or log file' },
    [pscustomobject]@{ Regex = '\.(db|sqlite|sqlite3)(-journal|-wal|-shm)?$'; Label = 'local database artifact' },
    [pscustomobject]@{ Regex = '^yolov8.*\.pt$'; Label = 'local model weight' },
    [pscustomobject]@{ Regex = '^vms/frontend/(build_result\.txt|\$null)$'; Label = 'frontend local scratch output' }
)

function Get-BlockReason {
    param([string]$Path)

    $normalized = Normalize-RepoPath $Path
    if (-not $normalized) {
        return $null
    }

    foreach ($rule in $allowRules) {
        if ($normalized -match $rule.Regex) {
            return $null
        }
    }

    foreach ($rule in $blockRules) {
        if ($normalized -match $rule.Regex) {
            return $rule.Label
        }
    }

    return $null
}

function Get-BlockedEntries {
    param([string[]]$Paths)

    $entries = @()
    foreach ($path in @($Paths)) {
        $reason = Get-BlockReason $path
        if ($null -ne $reason) {
            $entries += [pscustomobject]@{
                Path = Normalize-RepoPath $path
                Reason = $reason
            }
        }
    }

    return @($entries)
}

function Show-Entries {
    param(
        [string]$Title,
        [object[]]$Entries,
        [int]$Max = 20
    )

    Write-Section $Title
    if (-not $Entries -or $Entries.Count -eq 0) {
        Write-Host "none"
        return
    }

    $display = @($Entries | Select-Object -First $Max)
    foreach ($entry in $display) {
        Write-Host ("- {0} [{1}]" -f $entry.Path, $entry.Reason)
    }

    if ($Entries.Count -gt $Max) {
        Write-Host ("... and {0} more" -f ($Entries.Count - $Max))
    }
}

$repoRoot = Invoke-GitLines -Arguments @("rev-parse", "--show-toplevel") | Select-Object -First 1
if (-not $repoRoot) {
    Write-Error "Not inside a Git repository."
}

Set-Location $repoRoot

$branch = Invoke-GitLines -Arguments @("branch", "--show-current") | Select-Object -First 1
$status = Invoke-GitLines -Arguments @("status", "--short")
$stagedPaths = Invoke-GitLines -Arguments @("diff", "--cached", "--name-only", "--diff-filter=ACMR")
$unstagedPaths = Invoke-GitLines -Arguments @("diff", "--name-only")
$untrackedPaths = Invoke-GitLines -Arguments @("ls-files", "--others", "--exclude-standard")
$blockedStaged = Get-BlockedEntries -Paths $stagedPaths

if ($Mode -eq "pre-commit") {
    if ($blockedStaged.Count -gt 0) {
        Write-Host "pre-commit blocked staged generated/local files:"
        foreach ($entry in $blockedStaged) {
            Write-Host ("- {0} [{1}]" -f $entry.Path, $entry.Reason)
        }
        Write-Host ""
        Write-Host "Unstage them or move them out of the repository before committing."
        exit 1
    }

    exit 0
}

$trackedPaths = Invoke-GitLines -Arguments @("ls-files")
$blockedTracked = Get-BlockedEntries -Paths $trackedPaths
$blockedUnstaged = Get-BlockedEntries -Paths $unstagedPaths
$blockedUntracked = Get-BlockedEntries -Paths $untrackedPaths
$hooksPath = Invoke-GitLines -Arguments @("config", "--get", "core.hooksPath") | Select-Object -First 1
$normalizedHooksPath = Normalize-RepoPath $hooksPath

Write-Host "Repository : $repoRoot"
Write-Host "Branch     : $branch"
Write-Host "Hooks path : " -NoNewline
if ($normalizedHooksPath) {
    Write-Host $normalizedHooksPath
}
else {
    Write-Host "(not set)"
}

Write-Section "Working Tree"
if (-not $status -or $status.Count -eq 0) {
    Write-Host "clean"
}
else {
    Write-Host ("dirty ({0} change(s))" -f $status.Count)
}

Show-Entries -Title "Staged Generated Files" -Entries $blockedStaged
Show-Entries -Title "Unstaged Generated Files" -Entries $blockedUnstaged
Show-Entries -Title "Untracked Generated Files" -Entries $blockedUntracked

Write-Section "Tracked Generated Files In Repository"
if (-not $blockedTracked -or $blockedTracked.Count -eq 0) {
    Write-Host "none"
}
else {
    Write-Host ("{0} tracked file(s) still match the generated/local rules." -f $blockedTracked.Count)
    $display = @($blockedTracked | Select-Object -First 20)
    foreach ($entry in $display) {
        Write-Host ("- {0} [{1}]" -f $entry.Path, $entry.Reason)
    }
    if ($blockedTracked.Count -gt 20) {
        Write-Host ("... and {0} more" -f ($blockedTracked.Count - 20))
    }
    Write-Host "Use git rm --cached on the files or directories you want to stop tracking."
}

Write-Section "Recommendations"
if (-not $normalizedHooksPath -or $normalizedHooksPath -ne ".githooks") {
    Write-Host "- Enable the repo hook path: git config core.hooksPath .githooks"
}
if ($status.Count -gt 0) {
    Write-Host "- Start the next feature from a clean tree or a dedicated branch/worktree."
}
if ($blockedTracked.Count -gt 0) {
    Write-Host "- Remove already-tracked generated files from Git history or from the current index."
}
if ($blockedUntracked.Count -eq 0 -and $blockedTracked.Count -eq 0 -and $status.Count -eq 0) {
    Write-Host "- Preflight looks clean for the next feature."
}

$hasBlockingIssues = $blockedStaged.Count -gt 0
$hasStrictIssues = $hasBlockingIssues -or $status.Count -gt 0 -or $blockedTracked.Count -gt 0

if ($Strict -and $hasStrictIssues) {
    exit 1
}

if ($hasBlockingIssues) {
    exit 1
}

exit 0
