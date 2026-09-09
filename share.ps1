[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int] $Port = 8000,

    # Useful for automation. Without this switch, ngrok stays attached to the
    # terminal and Ctrl-C closes the public endpoint.
    [switch] $Detached
)

$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
$apiDir = Join-Path $repoRoot "api"
$python = Join-Path $apiDir ".venv\Scripts\python.exe"
$uiIndex = Join-Path $apiDir "screener\static\ui\index.html"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found. Run the project installation first."
}
if (-not (Test-Path -LiteralPath $uiIndex)) {
    throw "The UI is not built. Build web/ before sharing the app."
}
if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
    throw "ngrok is not installed. Install it with: winget install ngrok -s msstore"
}

# This also confirms that an account authtoken is present.
& ngrok config check | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "ngrok is not linked to an account. Run: ngrok config add-authtoken YOUR_TOKEN"
}

if (Get-Process ngrok -ErrorAction SilentlyContinue) {
    throw "ngrok is already running. Stop the existing ngrok process before starting a new share."
}

$randomBytes = New-Object byte[] 18
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $rng.GetBytes($randomBytes)
}
finally {
    $rng.Dispose()
}
$accessPassword = [Convert]::ToBase64String($randomBytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")

# Restart only the expected project server. This ensures every public write is
# protected by the same password used at the ngrok boundary.
$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener) {
    $existing = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    if ($existing.CommandLine -notmatch "uvicorn screener\.api:app") {
        throw "Port $Port belongs to an unexpected process: $($existing.CommandLine)"
    }
    Stop-Process -Id $listener.OwningProcess
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (-not (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)) {
            break
        }
        Start-Sleep -Milliseconds 250
    }
}

$env:SCREENER_TOKEN = $accessPassword
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$apiOut = Join-Path $env:TEMP "graham-api-$stamp.out.log"
$apiErr = Join-Path $env:TEMP "graham-api-$stamp.err.log"
$apiProcess = Start-Process -FilePath $python `
    -ArgumentList @("-m", "uvicorn", "screener.api:app", "--host", "127.0.0.1", "--port", $Port) `
    -WorkingDirectory $apiDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $apiOut `
    -RedirectStandardError $apiErr `
    -PassThru

$apiReady = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    try {
        $config = Invoke-RestMethod "http://127.0.0.1:$Port/config" -TimeoutSec 2
        if ($config.write_protected) {
            $apiReady = $true
            break
        }
    }
    catch {
        # The listener may not be ready yet.
    }
    if ($apiProcess.HasExited) {
        break
    }
    Start-Sleep -Milliseconds 500
}
if (-not $apiReady) {
    throw "The protected API did not start. See $apiErr"
}

$policy = [ordered]@{
    on_http_request = @(
        [ordered]@{
            actions = @(
                [ordered]@{
                    type = "basic-auth"
                    config = [ordered]@{
                        credentials = @("screener:$accessPassword")
                    }
                }
            )
        }
    )
}
$policyPath = Join-Path $env:TEMP "graham-ngrok-$stamp.json"
$policyJson = $policy | ConvertTo-Json -Depth 8
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($policyPath, $policyJson, $utf8WithoutBom)

Write-Host ""
Write-Host "Remote login"
Write-Host "  Username: screener"
Write-Host "  Password: $accessPassword"
Write-Host ""
Write-Host "Use the same password if the app asks for its write-access token."
Write-Host "The endpoint works only while this PC, the API, and ngrok remain running."
Write-Host ""

if (-not $Detached) {
    try {
        & ngrok http $Port --traffic-policy-file $policyPath
    }
    finally {
        Remove-Item -LiteralPath $policyPath -Force -ErrorAction SilentlyContinue
    }
    exit $LASTEXITCODE
}

$ngrokLog = Join-Path $env:TEMP "graham-ngrok-$stamp.log"
$ngrokExe = (Get-Command ngrok).Source
$ngrokProcess = Start-Process -FilePath $ngrokExe `
    -ArgumentList @("http", $Port, "--traffic-policy-file", $policyPath, "--log", $ngrokLog, "--log-format", "json") `
    -WindowStyle Hidden `
    -PassThru

$publicUrl = $null
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
        $tunnels = Invoke-RestMethod "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 2
        $publicUrl = ($tunnels.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1).public_url
        if ($publicUrl) {
            break
        }
    }
    catch {
        # The ngrok inspection API may not be ready yet.
    }
    if ($ngrokProcess.HasExited) {
        break
    }
    Start-Sleep -Milliseconds 500
}

Remove-Item -LiteralPath $policyPath -Force -ErrorAction SilentlyContinue
if (-not $publicUrl) {
    throw "ngrok did not create an endpoint. See $ngrokLog"
}

Write-Host "Remote URL: $publicUrl"
Write-Host "API PID: $($apiProcess.Id)"
Write-Host "ngrok PID: $($ngrokProcess.Id)"
Write-Host "ngrok log: $ngrokLog"
