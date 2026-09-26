# Gera Downloads\ita-backend.zip para enviar ao Cloud Shell (sem .env, data/ e caches).
# Uso: clique direito > "Executar com o PowerShell"  ou  powershell -ExecutionPolicy Bypass -File empacotar.ps1
$ErrorActionPreference = "Stop"
$origem = $PSScriptRoot
$destino = Join-Path $env:USERPROFILE "Downloads\ita-backend.zip"
$tmp = Join-Path $env:TEMP "ita-pack"
$pasta = Join-Path $tmp "ita-backend"

if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
New-Item -ItemType Directory -Force $pasta | Out-Null
robocopy $origem $pasta /E /XD __pycache__ .pytest_cache data .venv venv /XF .env *.pyc *.zip /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy falhou ($LASTEXITCODE)" }

if (Test-Path $destino) { Remove-Item -Force $destino }
Compress-Archive -Path $pasta -DestinationPath $destino
Remove-Item -Recurse -Force $tmp
Write-Host "Pronto: $destino"
