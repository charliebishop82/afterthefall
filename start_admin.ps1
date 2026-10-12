param([int]$Port = 8768, [string]$Database = '')
$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$suitePath = Join-Path $PSScriptRoot 'admin_suite.py'
if ($Database) { & $pythonPath $suitePath --port $Port --database $Database }
else { & $pythonPath $suitePath --port $Port }
