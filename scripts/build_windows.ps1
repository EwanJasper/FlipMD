#Requires -Version 7.3
param([switch]$PortableOnly)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($env:OS -ne 'Windows_NT') { throw 'Run this script on Windows x64.' }
$env:PYTHONUTF8 = '1'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/'
}

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program exited with code $LASTEXITCODE" }
}

$UvArgs = @('run', '--python', '3.12', '--frozen', '--extra', 'desktop', '--extra', 'dev')
Invoke-Checked uv ($UvArgs + @('pytest', '-q'))
Invoke-Checked uv ($UvArgs + @('--with', 'pyinstaller==6.22.3', 'python', 'scripts/build_desktop.py'))
$VersionOutput = & uv run --python 3.12 --frozen --extra desktop python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])'
if ($LASTEXITCODE -ne 0) { throw 'Could not read application version.' }
$Version = [string]$VersionOutput
$Version = $Version.Trim()
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid application version.' }

$Payload = Join-Path $Root 'dist\windows\FlipMD'
$Output = Join-Path $Root 'dist\installers'
New-Item -ItemType Directory -Force -Path $Output | Out-Null
$Portable = Join-Path $Output "FlipMD-$Version-windows-x64-portable.zip"
Compress-Archive -Path $Payload -DestinationPath $Portable -Force
if ($PortableOnly) { Write-Output $Portable; exit 0 }

$Compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($Compiler) { $Iscc = $Compiler.Source }
else { $Iscc = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe' }
if (-not (Test-Path $Iscc)) { throw 'Install Inno Setup 6.3 or later: https://jrsoftware.org/isdl.php' }

$Prerequisites = Join-Path $Root 'build\windows-prerequisites'
New-Item -ItemType Directory -Force -Path $Prerequisites | Out-Null
$Bootstrapper = Join-Path $Prerequisites 'MicrosoftEdgeWebview2Setup.exe'
Invoke-WebRequest -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $Bootstrapper
$Signature = Get-AuthenticodeSignature -FilePath $Bootstrapper
if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation(?:,|$)') {
    throw 'Microsoft WebView2 bootstrapper signature verification failed.'
}

Invoke-Checked $Iscc @(
    "/DAppVersion=$Version", "/DPayloadDir=$Payload", "/DWebView2Setup=$Bootstrapper",
    "/DInstallerOutput=$Output", (Join-Path $Root 'packaging\windows\flipmd.iss')
)
$Installer = Join-Path $Output "FlipMD-$Version-windows-x64-setup.exe"
if (-not (Test-Path $Installer)) { throw 'The Windows installer was not produced.' }
Get-FileHash $Installer, $Portable -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash.ToLowerInvariant())  $(Split-Path -Leaf $_.Path)" } |
    Set-Content -Encoding ascii (Join-Path $Output "FlipMD-$Version-windows-x64-sha256.txt")
Write-Output $Installer
