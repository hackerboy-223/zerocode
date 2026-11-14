param(
    [string]$Mode = "",
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/hackerboy-223/zerocode.git"
$InstallRef = $env:ZEROCODE_INSTALL_REF
if ([string]::IsNullOrWhiteSpace($InstallRef)) { $InstallRef = "latest" }
$SourceRef = $env:ZEROCODE_SOURCE_REF
if ([string]::IsNullOrWhiteSpace($SourceRef)) { $SourceRef = "feature/zerocode-desktop" }
$script:ReleaseMode = $false
$script:Release = $null
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
function Resolve-InstallRelease {
    if ($InstallRef -eq "latest") {
        try {
            $script:Release = Invoke-RestMethod -Uri "https://api.github.com/repos/hackerboy-223/zerocode/releases/latest" -Headers @{ Accept = "application/vnd.github+json" } -TimeoutSec 20
            $script:InstallRef = [string]$script:Release.tag_name
            if ($script:InstallRef -notmatch '^v?\d+\.\d+\.\d+([.-][A-Za-z0-9.-]+)?
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
    $script:PythonExecutable = (& $script:PythonCommand @script:PythonPrefix -c "import sys; print(sys.executable)").Trim()
    $version = & $script:PythonCommand @script:PythonPrefix -c "import sys; print('%d.%d' % sys.version_info[:2])"
    if ($LASTEXITCODE -ne 0 -or [version]$version -lt [version]"3.10") {
        Stop-Install "Python 3.10+ est requis (version détectée : $version)."
    }
    Write-Ok "Python $version détecté."
}
function Install-Engine {
    Get-PythonCommand
    Resolve-InstallRelease

    if (-not $script:ReleaseMode -and -not (Get-Command git -ErrorAction SilentlyContinue)) {
        Install-WingetPackage "Git.Git"
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

    if ($script:ReleaseMode) {
        $asset = Get-VerifiedReleaseAsset ".whl" "any"
        try {
            Write-Info "Installation du moteur depuis le wheel vérifié…"
            & $script:PythonCommand @script:PythonPrefix -m pipx install --force --python $script:PythonExecutable $asset.Path
            if ($LASTEXITCODE -ne 0) { Stop-Install "L'installation du moteur depuis la release a échoué." }
        } finally {
            Remove-Item -LiteralPath $asset.Directory -Recurse -Force -ErrorAction SilentlyContinue
        }
    } else {
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            Stop-Install "Git n'est pas disponible après son installation. Rouvre PowerShell puis relance."
        }
        Write-Info "Installation du moteur depuis la branche $InstallRef…"
        $gitSpec = "git+$RepoUrl@$InstallRef"
        & $script:PythonCommand @script:PythonPrefix -m pipx install --force --python $script:PythonExecutable $gitSpec
        if ($LASTEXITCODE -ne 0) { Stop-Install "L'installation du moteur ZeroCode a échoué." }
    }

    Refresh-Path
    if (-not (Get-Command zerocode -ErrorAction SilentlyContinue)) {
        Stop-Install "Le moteur est installé, mais zerocode n'est pas dans PATH. Rouvre PowerShell puis relance."
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
    & rustup toolchain install stable --profile minimal
    if ($LASTEXITCODE -ne 0) {
        Stop-Install "Impossible de préparer la toolchain Rust stable."
    }
    $env:RUSTUP_TOOLCHAIN = "stable"

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
    if ($script:ReleaseMode) {
        $asset = Get-VerifiedReleaseAsset ".exe" "x64"
        try {
            Write-Info "Lancement de l'installateur natif ZeroCode Desktop…"
            $process = Start-Process -FilePath $asset.Path -Wait -PassThru
            if ($process.ExitCode -ne 0) {
                Stop-Install "L'installateur Desktop s'est terminé avec le code $($process.ExitCode)."
            }
            Write-Ok "ZeroCode Desktop a été installé."
        } finally {
            Remove-Item -LiteralPath $asset.Directory -Recurse -Force -ErrorAction SilentlyContinue
        }
        return
    }

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
            $process = Start-Process -FilePath $installer.FullName -Wait -PassThru
            if ($process.ExitCode -ne 0) {
                Stop-Install "L'installateur Desktop s'est terminé avec le code $($process.ExitCode)."
            }
            Write-Ok "L'assistant d'installation Desktop s'est terminé."
        } else {
            $downloads = Join-Path $env:USERPROFILE "Downloads"
            New-Item -ItemType Directory -Path $downloads -Force | Out-Null
            $savedInstaller = Join-Path $downloads ("ZeroCode-Desktop-" + (Get-Date -Format "yyyyMMdd-HHmmss") + "-Setup.exe")
            Copy-Item -LiteralPath $installer.FullName -Destination $savedInstaller
            Write-Host "Installateur conservé dans : $savedInstaller" -ForegroundColor Yellow
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
    Write-Info "Version demandée : $InstallRef"
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
) {
                Stop-Install "La dernière release GitHub possède un tag invalide."
            }
            $script:ReleaseMode = $true
            Write-Ok "Release stable sélectionnée : $InstallRef"
        } catch {
            if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) {
                $script:InstallRef = $SourceRef
                $script:ReleaseMode = $false
                Write-Host "Aucune release stable publiée. Installation depuis la branche $SourceRef." -ForegroundColor Yellow
            } else {
                Stop-Install "Impossible de vérifier les releases GitHub : $($_.Exception.Message)"
            }
        }
    } elseif ($InstallRef -match '^v?\d+\.\d+\.\d+([.-][A-Za-z0-9.-]+)?
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
    & rustup toolchain install stable --profile minimal
    if ($LASTEXITCODE -ne 0) {
        Stop-Install "Impossible de préparer la toolchain Rust stable."
    }
    $env:RUSTUP_TOOLCHAIN = "stable"

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
            $process = Start-Process -FilePath $installer.FullName -Wait -PassThru
            if ($process.ExitCode -ne 0) {
                Stop-Install "L'installateur Desktop s'est terminé avec le code $($process.ExitCode)."
            }
            Write-Ok "L'assistant d'installation Desktop s'est terminé."
        } else {
            $downloads = Join-Path $env:USERPROFILE "Downloads"
            New-Item -ItemType Directory -Path $downloads -Force | Out-Null
            $savedInstaller = Join-Path $downloads ("ZeroCode-Desktop-" + (Get-Date -Format "yyyyMMdd-HHmmss") + "-Setup.exe")
            Copy-Item -LiteralPath $installer.FullName -Destination $savedInstaller
            Write-Host "Installateur conservé dans : $savedInstaller" -ForegroundColor Yellow
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
) {
        try {
            $script:Release = Invoke-RestMethod -Uri "https://api.github.com/repos/hackerboy-223/zerocode/releases/tags/$InstallRef" -Headers @{ Accept = "application/vnd.github+json" } -TimeoutSec 20
        } catch {
            Stop-Install "La release $InstallRef est introuvable : $($_.Exception.Message)"
        }
        $script:ReleaseMode = $true
        Write-Ok "Release sélectionnée : $InstallRef"
    } else {
        $script:ReleaseMode = $false
        Write-Info "Installation depuis la branche source : $InstallRef"
    }
}

function Get-ReleaseAsset([string]$Suffix, [string]$Architecture = "x64") {
    if (-not $script:Release -or -not $script:Release.assets) {
        Stop-Install "Les métadonnées de la release sont absentes."
    }
    $assets = @($script:Release.assets | Where-Object {
        $_.name -and $_.name.EndsWith($Suffix, [System.StringComparison]::OrdinalIgnoreCase) -and
        $_.browser_download_url -match '^https://github\.com/hackerboy-223/zerocode/releases/download/'
    })
    if ($Suffix -eq "SHA256SUMS") {
        $assets = @($assets | Where-Object { $_.name -eq "SHA256SUMS" })
    } elseif ($Suffix -eq ".whl") {
        $assets = @($assets | Where-Object { $_.name.StartsWith("zerocode-") })
    }

    $archTokens = if ($Architecture -eq "arm64") { @("arm64", "aarch64") } else { @("x64", "x86_64", "amd64") }
    $ranked = @($assets | Where-Object {
        $name = $_.name.ToLowerInvariant()
        foreach ($token in $archTokens) {
            if ($name.Contains($token)) { return $true }
        }
        return $false
    })
    if ($ranked.Count -gt 0) { $assets = $ranked }
    if ($assets.Count -ne 1) {
        Stop-Install "La release ne contient pas un seul fichier $Suffix compatible avec l'architecture $Architecture."
    }
    return $assets[0]
}

function Get-VerifiedReleaseAsset([string]$Suffix, [string]$Architecture = "x64") {
    $asset = Get-ReleaseAsset $Suffix $Architecture
    $checksum = Get-ReleaseAsset "SHA256SUMS" "any"
    $downloadDir = Join-Path $env:TEMP ("zerocode-release-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $downloadDir | Out-Null
    $destination = Join-Path $downloadDir $asset.name
    $manifestPath = Join-Path $downloadDir "SHA256SUMS"

    Write-Info "Téléchargement de $($asset.name)…"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $destination -UseBasicParsing
    Invoke-WebRequest -Uri $checksum.browser_download_url -OutFile $manifestPath -UseBasicParsing

    $entry = Get-Content -LiteralPath $manifestPath | Where-Object {
        $_ -match '^([a-fA-F0-9]{64})\s+\*?(.+)
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
    & rustup toolchain install stable --profile minimal
    if ($LASTEXITCODE -ne 0) {
        Stop-Install "Impossible de préparer la toolchain Rust stable."
    }
    $env:RUSTUP_TOOLCHAIN = "stable"

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
            $process = Start-Process -FilePath $installer.FullName -Wait -PassThru
            if ($process.ExitCode -ne 0) {
                Stop-Install "L'installateur Desktop s'est terminé avec le code $($process.ExitCode)."
            }
            Write-Ok "L'assistant d'installation Desktop s'est terminé."
        } else {
            $downloads = Join-Path $env:USERPROFILE "Downloads"
            New-Item -ItemType Directory -Path $downloads -Force | Out-Null
            $savedInstaller = Join-Path $downloads ("ZeroCode-Desktop-" + (Get-Date -Format "yyyyMMdd-HHmmss") + "-Setup.exe")
            Copy-Item -LiteralPath $installer.FullName -Destination $savedInstaller
            Write-Host "Installateur conservé dans : $savedInstaller" -ForegroundColor Yellow
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
 -and $Matches[2] -eq $asset.name
    } | Select-Object -First 1
    if (-not $entry -or $entry -notmatch '^([a-fA-F0-9]{64})\s+\*?(.+)
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
    & rustup toolchain install stable --profile minimal
    if ($LASTEXITCODE -ne 0) {
        Stop-Install "Impossible de préparer la toolchain Rust stable."
    }
    $env:RUSTUP_TOOLCHAIN = "stable"

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
            $process = Start-Process -FilePath $installer.FullName -Wait -PassThru
            if ($process.ExitCode -ne 0) {
                Stop-Install "L'installateur Desktop s'est terminé avec le code $($process.ExitCode)."
            }
            Write-Ok "L'assistant d'installation Desktop s'est terminé."
        } else {
            $downloads = Join-Path $env:USERPROFILE "Downloads"
            New-Item -ItemType Directory -Path $downloads -Force | Out-Null
            $savedInstaller = Join-Path $downloads ("ZeroCode-Desktop-" + (Get-Date -Format "yyyyMMdd-HHmmss") + "-Setup.exe")
            Copy-Item -LiteralPath $installer.FullName -Destination $savedInstaller
            Write-Host "Installateur conservé dans : $savedInstaller" -ForegroundColor Yellow
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
) {
        Remove-Item -LiteralPath $downloadDir -Recurse -Force -ErrorAction SilentlyContinue
        Stop-Install "Aucune empreinte SHA-256 publiée pour $($asset.name)."
    }
    $expected = $Matches[1].ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        Remove-Item -LiteralPath $downloadDir -Recurse -Force -ErrorAction SilentlyContinue
        Stop-Install "Le fichier $($asset.name) ne correspond pas à son empreinte SHA-256."
    }

    Write-Ok "Intégrité vérifiée : $($asset.name)"
    return [pscustomobject]@{ Path = $destination; Directory = $downloadDir; Name = $asset.name }
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
    & rustup toolchain install stable --profile minimal
    if ($LASTEXITCODE -ne 0) {
        Stop-Install "Impossible de préparer la toolchain Rust stable."
    }
    $env:RUSTUP_TOOLCHAIN = "stable"

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
            $process = Start-Process -FilePath $installer.FullName -Wait -PassThru
            if ($process.ExitCode -ne 0) {
                Stop-Install "L'installateur Desktop s'est terminé avec le code $($process.ExitCode)."
            }
            Write-Ok "L'assistant d'installation Desktop s'est terminé."
        } else {
            $downloads = Join-Path $env:USERPROFILE "Downloads"
            New-Item -ItemType Directory -Path $downloads -Force | Out-Null
            $savedInstaller = Join-Path $downloads ("ZeroCode-Desktop-" + (Get-Date -Format "yyyyMMdd-HHmmss") + "-Setup.exe")
            Copy-Item -LiteralPath $installer.FullName -Destination $savedInstaller
            Write-Host "Installateur conservé dans : $savedInstaller" -ForegroundColor Yellow
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
