#Requires -Version 5.1
param(
  [Parameter(Mandatory = $true)][string]$TokenFile,
  [Parameter(Mandatory = $true)][string]$Dest
)
# Scarica l'ultima release del repo privato ed estrae orchestra/ in Dest.
# Usato da Installa-Orchestra.bat. Errori -> exit 1 con messaggio.
$ErrorActionPreference = 'Stop'

$token = (Get-Content -Raw $TokenFile).Trim().Split()[0]
if (-not $token) { Write-Host '[ERRORE] token.txt vuoto.'; exit 1 }

$headers = @{
  'User-Agent'    = 'orchestra-installer'
  'Accept'        = 'application/vnd.github+json'
  'Authorization' = "Bearer $token"
}
try {
  $rel = Invoke-RestMethod -Uri 'https://api.github.com/repos/advers1ty-it/orchestra/releases/latest' -Headers $headers -TimeoutSec 30
} catch {
  Write-Host '[ERRORE] GitHub non raggiungibile o token non valido.'
  Write-Host $_.Exception.Message
  exit 1
}
if (-not $rel.zipball_url) { Write-Host '[ERRORE] Nessuna release pubblicata.'; exit 1 }

Write-Host ("  release trovata: " + $rel.tag_name)
$zip = Join-Path $env:TEMP 'orchestra-release.zip'
Invoke-WebRequest -Uri $rel.zipball_url -Headers $headers -OutFile $zip -TimeoutSec 300

$tmp = Join-Path $env:TEMP ('orchestra-rel-' + [guid]::NewGuid().ToString('N'))
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$root = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
if (-not $root) { Write-Host '[ERRORE] Zip vuoto.'; exit 1 }

# Copia tutto tranne stato locale (chiavi, dati, backup).
$escludi = @('.env', 'token.txt', 'goals.json', 'budget_global.json', 'storico.db',
             'memoria_indice.db', '__pycache__', '_ goals_fallback', '_dati_test')
Get-ChildItem -Path $root.FullName -Force | ForEach-Object {
  if ($escludi -contains $_.Name) { return }
  $dst = Join-Path $Dest $_.Name
  if ($_.PSIsContainer) {
    if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
    Copy-Item -Recurse -Force $_.FullName $dst
  } else {
    Copy-Item -Force $_.FullName $dst
  }
}
Remove-Item -Recurse -Force $tmp, $zip
Write-Host '  file copiati.'
