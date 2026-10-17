# Registers csv_sync as a Windows service using NSSM (https://nssm.cc).
# Run from an elevated PowerShell in the repository root:
#   .\csv_sync\install-windows-service.ps1 -ServiceAccount "CORP\svc-csv-sync$"
param(
    [string]$ServiceName = "PharmaOpsCsvSync",
    [string]$Python = (Get-Command python).Source,
    [string]$ServiceAccount = "",          # e.g. a gMSA with read-only access to the share
    [string]$DataDir = "C:\ProgramData\csv_sync"
)
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path

if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    throw "nssm.exe not found on PATH"
}
if (-not (Test-Path "$DataDir\.env")) {
    throw "Create $DataDir\.env first (see csv_sync\.env.example)"
}

# Only Administrators, SYSTEM and the service account may read the .env file (it holds secrets)
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
icacls $DataDir /inheritance:r /grant:r "Administrators:(OI)(CI)F" "SYSTEM:(OI)(CI)F" | Out-Null
if ($ServiceAccount) {
    icacls $DataDir /grant:r "${ServiceAccount}:(OI)(CI)M" | Out-Null
}

nssm install $ServiceName $Python "-m" "csv_sync" "run" "--env-file" "$DataDir\.env"
nssm set $ServiceName AppDirectory $RepoRoot
nssm set $ServiceName AppStdout "$DataDir\csv_sync.log"
nssm set $ServiceName AppStderr "$DataDir\csv_sync.log"
nssm set $ServiceName AppRotateFiles 1
nssm set $ServiceName AppRotateBytes 10485760
nssm set $ServiceName Start SERVICE_AUTO_START
if ($ServiceAccount) {
    nssm set $ServiceName ObjectName $ServiceAccount
}

& $Python -m csv_sync check --env-file "$DataDir\.env"
if ($LASTEXITCODE -ne 0) { throw "Configuration check failed; service not started" }
nssm start $ServiceName
Write-Host "Service $ServiceName installed and started. Log: $DataDir\csv_sync.log"
