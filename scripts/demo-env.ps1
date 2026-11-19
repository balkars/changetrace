# Dot-source in each demo terminal:  . .\scripts\demo-env.ps1
# Puts the repo's .venv\Scripts first on PATH for this PowerShell session only.
$repo = Split-Path -Parent $PSScriptRoot
$env:PATH = "$repo\.venv\Scripts;" + $env:PATH
$ct = Get-Command ct -ErrorAction SilentlyContinue
if ($ct) { Write-Host "ct: $($ct.Source)" } else { Write-Warning "ct not found under $repo\.venv\Scripts" }
