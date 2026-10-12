param(
    [string]$BindAddress = '127.0.0.1',
    [string[]]$AllowedHosts = @(),
    [int]$Port = 8767,
    [string]$PublicUrl = '',
    [string]$Database = '',
    [string]$Python = (Join-Path $PSScriptRoot '.venv/Scripts/python.exe')
)
$serverArgs = @('-X', 'utf8', (Join-Path $PSScriptRoot 'serve_game.py'), '--host', $BindAddress, '--port', "$Port")
foreach ($allowed in $AllowedHosts) { $serverArgs += @('--allow-host', $allowed) }
if ($PublicUrl) { $serverArgs += @('--public-url', $PublicUrl) }
if ($Database) { $serverArgs += @('--database', $Database) }
& $Python @serverArgs
exit $LASTEXITCODE
