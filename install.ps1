param(
    [ValidateSet("tui", "desktop", "both")]
    [string]$Mode = "",
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/hackerboy-223/zerocode.git"
$InstallRef = $env:ZEROCODE_INSTALL_REF
if ([string]::IsNullOrWhiteSpace($InstallRef)) { $InstallRef = "feature/zerocode-desktop" }
if ([string]::IsNullOrWhiteSpace($Mode)) { $Mode = $env:ZEROCODE_INSTALL_MODE }
if ($env:ZEROCODE_INSTALL_YES -eq "1") { $Yes = $true }

function Write-Info([string]$Message) {
    Write-Host ""
    Write-Host "[ZeroCode] $Message" -ForegroundColor Cyan
}
function Write-Ok([string]$Message) {
    Write-Host "[OK] $Message" -ForegroundColor Green
}
function Stop-Install([string]$Message) {
    throw $Message
}
function Confirm-Install([string]$Message) {
    if ($Yes) { return $true }
    $answer = Read-Host "$Message [O/n]"
    return [string]::IsNullOrWhiteSpace($answer) -or $answer -match "^(O|o|Y|y)$"
}
function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath;$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin"
}
function Install-WingetPackage([string]$Id, [string]$Override = "") {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Stop-Install "winget est requis pour installer les dépendances Windows. Mets à jour App Installer depuis le Microsoft Store, puis relance."
    }
    Write-Info "Installation de $Id…"
    $arguments = @(
        "install", "--id", $Id, "--exact",
        "--accept-source-agreements", "--accept-package-agreements"
    )
    if (-not [string]::IsNullOrWhiteSpace($Override)) {
        $arguments += @("--override", $Override)
    }
    & winget @arguments
    if ($LASTEXITCODE -ne 0) {
        Stop-Install "L'installation de $Id a échoué (code $LASTEXITCODE). Installe ce composant manuellement, puis relance."
    }
    Refresh-Path
}
function Select-InstallMode {
    if (-not [string]::IsNullOrWhiteSpace($Mode)) { return }
    Write-Host ""
    Write-Host "  ┌──────────────────────────────────────────┐"
    Write-Host "  │             ZEROCODE INSTALLER            │"
    Write-Host "  ├──────────────────────────────────────────┤"
    Write-Host "  │  1. TUI      Interface dans le terminal  │"
    Write-Host "  │  2. Desktop  Application graphique       │"
    Write-Host "  │  3. Les deux Installer TUI + Desktop     │"
    Write-Host "  └──────────────────────────────────────────┘"
    $choice = Read-Host "Choisis une installation [1-3]"
    switch ($choice) {
        "1" { $script:Mode = "tui" }
        "2" { $script:Mode = "desktop" }
        "3" { $script:Mode = "both" }
        default { Stop-Install "Choix invalide. Relance l'installateur et sélectionne 1, 2 ou 3." }
    }
}
function Get-PythonCommand {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $script:PythonCommand = "py"
        $script:PythonPrefix = @("-3")
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $script:PythonCommand = "python"
        $script:PythonPrefix = @()
    } else {
        Install-WingetPackage "Python.Python.3.12"
        if (Get-Command py -ErrorAction SilentlyContinue) {
            $script:PythonCommand = "py"
            $script:PythonPrefix = @("-3")
        } else {
            Stop-Install "Python vient d'être installé, mais son lanceur n'est pas visible. Ferme puis rouvre PowerShell et relance install.ps1."
        }
    }
    $version = & $script:PythonCommand @script:PythonPrefix -c "import sys; print('%d.%d' % sys.version_info[:2])"
    if ($LASTEXITCODE -ne 0 -or [version]$version -lt [version]"3.10") {
        Stop-Install "Python 3.10+ est requis (version détectée : $version)."
    }
    Write-Ok "Python $version détecté."
}
function Install-Engine {
    Get-PythonCommand
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Install-WingetPackage "Git.Git"
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Stop-Install "Git n'est pas disponible dans ce terminal. Rouvre PowerShell puis relance."
    }

    Write-Info "Préparation de pipx dans un environnement Python isolé…"
    & $script:PythonCommand @script:PythonPrefix -m pip install --user --upgrade pipx
    if ($LASTEXITCODE -ne 0) {
        Stop-Install "Impossible d'installer pipx. Vérifie Python et ta connexion, puis relance."
    }
    & $script:PythonCommand @script:PythonPrefix -m pipx ensurepath
    if ($LASTEXITCODE -ne 0) {
        Stop-Install "pipx n'a pas pu préparer le PATH utilisateur."
    }

    Write-Info "Installation du moteur ZeroCode et de ses dépendances…"
    $gitSpec = "git+$RepoUrl@$InstallRef"
    & $script:PythonCommand @script:PythonPrefix -m pipx install --force $gitSpec
    if ($LASTEXITCODE -ne 0) {
        Stop-Install "L'installation du moteur ZeroCode a échoué."
    }
    Refresh-Path
    if (-not (Get-Command zerocode -ErrorAction SilentlyContinue)) {
        Stop-Install "Le moteur est installé, mais zerocode n'est pas dans PATH. Rouvre PowerShell puis relance zerocode --version."
    }
    & zerocode --version
    if ($LASTEXITCODE -ne 0) { Stop-Install "La commande zerocode n'a pas réussi son contrôle de version." }
    Write-Ok "Moteur ZeroCode installé."
}
function Test-NodeVersion {
    if (-not (Get-Command node -ErrorAction SilentlyContinue) -or -not (Get-Command npm -ErrorAction SilentlyContinue)) {
        return $false
    }
    $raw = (& node --version).Trim().TrimStart("v")
    try { $v = [version]$raw } catch { return $false }
    return ($v.Major -ge 24) -or ($v.Major -eq 22 -and $v.Minor -ge 12) -or ($v.Major -eq 20 -and $v.Minor -ge 19)
}
function Install-DesktopPrerequisites {
    if (-not (Test-NodeVersion)) {
        Install-WingetPackage "OpenJS.NodeJS.LTS"
        if (-not (Test-NodeVersion)) {
            Stop-Install "Node.js 20.19+ ou 22.12+ est nécessaire. La version installée est trop ancienne."
        }
    }
    if (-not (Get-Command rustc -ErrorAction SilentlyContinue) -or -not (Get-Command cargo -ErrorAction SilentlyContinue)) {
        Install-WingetPackage "Rustlang.Rustup"
        Refresh-Path
    }
    if (-not (Get-Command rustc -ErrorAction SilentlyContinue) -or -not (Get-Command cargo -ErrorAction SilentlyContinue)) {
        Stop-Install "Rust n'est pas disponible. Ferme puis rouvre PowerShell, vérifie Rustup, puis relance l'installation."
    }

    $programFiles = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $vsPath = Join-Path $programFiles "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vsPath)) {
        Install-WingetPackage "Microsoft.VisualStudio.2022.BuildTools" "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
    }
    if (-not (Test-Path $vsPath)) {
        Stop-Install "Visual Studio C++ Build Tools n'a pas été détecté après installation."
    }

    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $webViewPath = Join-Path $programFilesX86 "Microsoft\EdgeWebView\Application"
    if (-not (Test-Path $webViewPath)) {
        Install-WingetPackage "Microsoft.EdgeWebView2Runtime"
    }
    if (-not (Get-Command makensis -ErrorAction SilentlyContinue)) {
        Install-WingetPackage "NSIS.NSIS"
    }
    Refresh-Path
    Write-Ok "Node.js, Rust, Visual Studio C++ Build Tools et NSIS sont prêts."
}
function Install-Desktop {
    Install-DesktopPrerequisites
    $tempRoot = Join-Path $env:TEMP ("zerocode-installer-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    try {
        Write-Info "Récupération du code source de ZeroCode…"
        & git clone --depth 1 --branch $InstallRef $RepoUrl (Join-Path $tempRoot "source")
        if ($LASTEXITCODE -ne 0) { Stop-Install "Impossible de récupérer la branche $InstallRef." }

        $desktopPath = Join-Path $tempRoot "source\desktop"
        if (-not (Test-Path (Join-Path $desktopPath "package-lock.json"))) {
            Stop-Install "Le projet Desktop est absent de la branche $InstallRef."
        }

        Push-Location $desktopPath
        try {
            Write-Info "Installation des dépendances frontend (npm ci)…"
            & npm ci
            if ($LASTEXITCODE -ne 0) { Stop-Install "L'installation des dépendances npm a échoué." }

            Write-Info "Compilation de ZeroCode Desktop…"
            & npm run app:build -- --bundles nsis
            if ($LASTEXITCODE -ne 0) { Stop-Install "La compilation Tauri a échoué. Les messages Cargo/NSIS ci-dessus indiquent le composant manquant." }
        } finally {
            Pop-Location
        }

        $bundlePath = Join-Path $desktopPath "src-tauri\target\release\bundle\nsis"
        $installer = Get-ChildItem -Path $bundlePath -Filter "*.exe" -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $installer) { Stop-Install "L'installateur NSIS n'a pas été généré." }

        Write-Ok "Installateur natif généré : $($installer.FullName)"
        if (Confirm-Install "Lancer maintenant l'installateur graphique de ZeroCode Desktop ?") {
            Start-Process -FilePath $installer.FullName -Wait
            Write-Ok "L'assistant d'installation Desktop s'est terminé."
        } else {
            Write-Host "Installateur conservé dans : $($installer.FullName)" -ForegroundColor Yellow
        }
    } finally {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

try {
    if ([string]::IsNullOrWhiteSpace($Mode) -and -not [Environment]::UserInteractive) {
        Stop-Install "Mode requis en non-interactif : utilise -Mode tui, -Mode desktop ou -Mode both."
    }
    Select-InstallMode
    if ($Mode -notin @("tui", "desktop", "both")) {
        Stop-Install "Mode inconnu : $Mode (attendu : tui, desktop ou both)."
    }

    Write-Info "Système : Windows $([Environment]::OSVersion.Version)"
    Write-Info "Installation sélectionnée : $Mode"
    Write-Info "Branche source : $InstallRef"
    if (-not (Confirm-Install "Continuer ? Les composants manquants seront installés et Desktop sera compilé localement.")) {
        Stop-Install "Installation annulée."
    }

    Install-Engine
    if ($Mode -in @("desktop", "both")) { Install-Desktop }

    Write-Host ""
    Write-Ok "Installation terminée."
    if ($Mode -in @("tui", "both")) { Write-Host "  TUI : zerocode" }
    if ($Mode -in @("desktop", "both")) { Write-Host "  Desktop : menu Démarrer > ZeroCode Desktop" }
    Write-Host "Vérification du moteur : zerocode doctor"
    Write-Host "Aucune clé API personnelle n'est requise pour commencer avec le mode auto."
} catch {
    Write-Host ""
    Write-Host "[Échec] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Corrige le prérequis indiqué puis relance le même installateur." -ForegroundColor Yellow
    exit 1
}
