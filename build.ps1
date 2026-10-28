<#
.SYNOPSIS
    Builds SubTrack for Windows: tests, the .exe, a portable zip and (if Inno Setup is installed) the installer.

.EXAMPLE
    .\build.ps1                 # everything
    .\build.ps1 -SkipTests      # faster rebuild
    .\build.ps1 -NoInstaller    # skip the Inno Setup step
    .\build.ps1 -RequireInstaller   # fail if Inno Setup is missing (used by CI)

    Output goes to dist\:
      dist\SubTrack\SubTrack.exe                 the app folder
      dist\SubTrack-<version>-portable.zip       unzip and run, no install
      dist\SubTrack-<version>-setup.exe          installer
#>
param(
    [switch]$SkipTests,
    [switch]$NoInstaller,
    [switch]$RequireInstaller,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

# Runs a native command and fails on a non-zero exit code. Windows PowerShell 5.1
# would otherwise treat any stderr output (PyInstaller logs everything there) as an error.
function Invoke-Native([string]$What, [scriptblock]$Command) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Command 2>&1 | ForEach-Object { "$_" } } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE) { throw "$What failed (exit code $LASTEXITCODE)" }
}

if (-not $Python) {
    $Python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
}

Step "Installing build dependencies"
Invoke-Native "pip install" { & $Python -m pip install --quiet --disable-pip-version-check -r requirements-build.txt }

$version = (& $Python -c "import sys; sys.path.insert(0, 'src'); import subtrack; print(subtrack.__version__)").Trim()
Write-Host "SubTrack version $version"

if (-not $SkipTests) {
    Step "Running tests"
    Invoke-Native "tests" { & $Python -m pytest -q }
}

Step "Building the .exe with PyInstaller"
Invoke-Native "PyInstaller" { & $Python -m PyInstaller --noconfirm --clean --log-level WARN subtrack.spec }
$exe = "dist\SubTrack\SubTrack.exe"

Step "Smoke-testing the built .exe"
# Start it hidden with a throw-away data folder and check it is still alive after a few seconds.
$smokeData = Join-Path ([IO.Path]::GetTempPath()) "subtrack-smoke-$PID"
New-Item -ItemType Directory -Force $smokeData | Out-Null
$oldAppData = $env:APPDATA
$oldPlatform = $env:QT_QPA_PLATFORM
try {
    $env:APPDATA = $smokeData
    $env:QT_QPA_PLATFORM = "offscreen"
    $process = Start-Process -FilePath $exe -ArgumentList "--minimized" -PassThru
    Start-Sleep -Seconds 6
    $alive = -not $process.HasExited
    if ($alive) { Stop-Process -Id $process.Id -Force }
    if (-not $alive) { throw "SubTrack.exe exited early with code $($process.ExitCode)" }
    if (-not (Test-Path "$smokeData\SubTrack\subtrack.db")) { throw "SubTrack.exe did not create its database" }
    Write-Host "OK: the app started and created its database"

    # Checks that Qt Charts and the native notification library made it into the package.
    $selfTest = Start-Process -FilePath $exe -ArgumentList "--self-test" -PassThru -Wait
    if ($selfTest.ExitCode -ne 0) {
        Get-Content "$smokeData\SubTrack\subtrack.log" -ErrorAction SilentlyContinue | Write-Host
        throw "SubTrack.exe --self-test failed (exit code $($selfTest.ExitCode))"
    }
    Write-Host "OK: self-test passed (charts and Windows notifications load)"
}
finally {
    $env:APPDATA = $oldAppData
    $env:QT_QPA_PLATFORM = $oldPlatform
    Remove-Item -Recurse -Force $smokeData -ErrorAction SilentlyContinue
}

Step "Creating the portable zip"
$zip = "dist\SubTrack-$version-portable.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path "dist\SubTrack" -DestinationPath $zip
Write-Host $zip

if (-not $NoInstaller) {
    $iscc = @(
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($iscc) {
        Step "Building the installer with Inno Setup"
        Invoke-Native "Inno Setup" { & $iscc /Q "/DAppVersion=$version" "installer\subtrack.iss" }
    }
    elseif ($RequireInstaller) {
        throw "Inno Setup 6 not found"
    }
    else {
        Write-Warning "Inno Setup 6 not found, skipping the installer. Install it with: winget install JRSoftware.InnoSetup"
    }
}

Step "Done"
Get-ChildItem dist -File | Format-Table Name, @{ Label = "Size (MB)"; Expression = { [math]::Round($_.Length / 1MB, 1) } }
