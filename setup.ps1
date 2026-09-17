<#!
.SYNOPSIS
Creates the project's Python virtual environment and installs dependencies.

.DESCRIPTION
Run this once after installing Python 3.10 or newer. It creates .venv in this
folder; that folder is local-only and should not be committed to Git.
#>

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSCommandPath
$Python = Get-Command py -ErrorAction SilentlyContinue

if ($null -eq $Python) {
    $Python = Get-Command python -ErrorAction SilentlyContinue
}

if ($null -eq $Python) {
    throw 'Python 3.10 or newer is required. Install it, reopen PowerShell, then run .\setup.ps1 again.'
}

& $Python.Source -m venv (Join-Path $ProjectRoot '.venv')
& (Join-Path $ProjectRoot '.venv\Scripts\python.exe') -m pip install --upgrade pip
& (Join-Path $ProjectRoot '.venv\Scripts\python.exe') -m pip install -r (Join-Path $ProjectRoot 'requirements.txt')

Write-Host 'Environment is ready. Activate it with: .\.venv\Scripts\Activate.ps1'
