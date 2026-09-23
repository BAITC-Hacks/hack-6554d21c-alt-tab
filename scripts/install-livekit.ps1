$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$version = '1.13.7'
$assetName = "livekit_${version}_windows_amd64.zip"
$targetDir = Join-Path $repoRoot '.cache/livekit'
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
$baseUrl = "https://github.com/livekit/livekit/releases/download/v$version"
$archivePath = Join-Path $targetDir $assetName
$checksumPath = Join-Path $targetDir 'checksums.txt'
Invoke-WebRequest "$baseUrl/$assetName" -OutFile $archivePath
Invoke-WebRequest "$baseUrl/checksums.txt" -OutFile $checksumPath
$checksumLine = Get-Content -LiteralPath $checksumPath | Where-Object { $_ -match "\s+$([regex]::Escape($assetName))$" }
if (-not $checksumLine) { throw 'No official checksum for the LiveKit archive' }
$expectedHash = ($checksumLine -split '\s+')[0]
$actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
if ($actualHash -ne $expectedHash) { throw 'LiveKit archive checksum mismatch' }
Expand-Archive -LiteralPath $archivePath -DestinationPath $targetDir -Force
Write-Output "LiveKit $version installed and checksum verified in $targetDir"
