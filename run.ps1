Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Resolve Python
$pythonCandidates = @(
    'python',
    Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
)

$python = $null
foreach ($cand in $pythonCandidates) {
    try {
        $cmd = Get-Command $cand -ErrorAction Stop
        $python = $cmd.Source
        break
    } catch {}
}

if (-not $python) {
    Write-Host 'Python not found. Install Python 3.12 and re-run this script.' -ForegroundColor Red
    exit 1
}

Write-Host "Using Python: $python" -ForegroundColor Cyan

# Install dependencies
if (Test-Path -LiteralPath 'requirements.txt') {
    & $python -m pip install --disable-pip-version-check -r requirements.txt
}

# Run the Flask app
& $python .venv\livebot.py

