$ErrorActionPreference = "Stop"
$Repo = "git+https://github.com/hackerboy-223/zerocode.git"

Write-Host "`n[ZeroCode] Installation automatique" -ForegroundColor Cyan
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python 3.10+ est requis. Installe-le depuis https://www.python.org/downloads/ puis relance."
}
$Version = & py -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$Parts = $Version.Split('.')
if ([int]$Parts[0] -lt 3 -or ([int]$Parts[0] -eq 3 -and [int]$Parts[1] -lt 10)) {
    throw "Python 3.10+ est requis (version détectée : $Version)."
}
Write-Host "Python $Version détecté." -ForegroundColor Green

$PipxVersion = & py -m pipx --version 2>$null
if (-not $PipxVersion) {
    Write-Host "Installation de pipx…" -ForegroundColor Cyan
    & py -m pip install --user pipx
    if ($LASTEXITCODE -ne 0) { throw "Échec de l'installation de pipx." }
    & py -m pipx ensurepath
}

Write-Host "Installation de ZeroCode et de toutes ses dépendances…" -ForegroundColor Cyan
& py -m pipx install --force $Repo
if ($LASTEXITCODE -ne 0) { throw "Échec de l'installation de ZeroCode." }

$UserBin = Join-Path $env:USERPROFILE ".local\bin"
if (Test-Path $UserBin) { $env:Path = "$UserBin;$env:Path" }
if (Get-Command zerocode -ErrorAction SilentlyContinue) {
    zerocode --version
    zerocode doctor
} else {
    Write-Host "Installation terminée. Rouvre PowerShell pour actualiser le PATH." -ForegroundColor Yellow
}
Write-Host "`nC'est prêt ! Lance : zerocode" -ForegroundColor Green
Write-Host "Aucune clé API personnelle n'est requise. Le mode auto utilise les routes gratuites anonymes disponibles."
