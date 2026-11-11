# Deploy do cache TTS shared + env da rampa.
# Agendado para rodar fora do horario de pico (20:00 ET).
# Nao contem segredos: apenas flags publicas e o pool de DIDs.

$ErrorActionPreference = "Stop"
$repo = "C:\Users\Fabio\Documents\Default Project\garimpador-leads"
$log = Join-Path $repo "deploy_voice_tts_cache.log"
$project = "7b6bbb01-0fd5-462c-b723-3b3597b60d79"
$service = "magic-leads"
$environment = "production"
$base = "https://magic-leads-production.up.railway.app"

$env:Path = "C:\Users\Fabio\AppData\Roaming\npm;$env:Path"

function Log([string]$message) {
    $line = "$(Get-Date -Format o) $message"
    Add-Content -Path $log -Value $line
    Write-Output $line
}

Set-Location $repo
Log "=== deploy voice tts cache: start ==="

$vars = [ordered]@{
    "VOICE_TTS_CACHE_ENABLED" = "1"
    "VOICE_TTS_CACHE_MODE" = "shared"
    "VOICE_TTS_SHARED_NAME" = "there"
    "VOICE_MAX_CALLS_PER_DAY" = "300"
    "VOICE_TTS_CACHE_TTL_DAYS" = "14"
    "VOICE_FREEZE" = "0"
    "VOICE_DID_POOL_BY_CITY" = '{"new york":["+19292562550","+19294480511","+19293571376","+19293571378","+19295567262","+19296280134","+15189429910"]}'
}

foreach ($key in $vars.Keys) {
    Log "setting $key"
    & railway variable set "$key=$($vars[$key])" --service $service --environment $environment -p $project --skip-deploys 2>&1 | ForEach-Object { Log $_ }
}

Log "pushing master (triggers deploy with new code + env)"
& git push origin master 2>&1 | ForEach-Object { Log $_ }

$deployed = $false
for ($i = 0; $i -lt 80; $i++) {
    Start-Sleep -Seconds 15
    try {
        $openapi = Invoke-RestMethod -Uri "$base/openapi.json" -TimeoutSec 10
        $paths = $openapi.paths.PSObject.Properties.Name
        if ($paths -contains "/api/voice/tts/{audio_hash}.mp3") {
            Log "new code detected in openapi after $($i * 15)s"
            $deployed = $true
            break
        }
        Log "waiting for deploy ($($i * 15)s)"
    } catch {
        Log "waiting for deploy ($($i * 15)s): $($_.Exception.Message)"
    }
}

if (-not $deployed) {
    Log "ERROR: new code not detected after 20 minutes"
    exit 1
}

Start-Sleep -Seconds 10
try {
    $health = Invoke-WebRequest -Uri "$base/health" -TimeoutSec 10 -UseBasicParsing
    Log "health status $($health.StatusCode)"
} catch {
    Log "health error: $($_.Exception.Message)"
}

$probe = "$base/api/voice/tts/0000000000000000000000000000000000000000000000000000000000000000.mp3"
try {
    $resp = Invoke-WebRequest -Uri $probe -TimeoutSec 10 -UseBasicParsing
    Log "tts probe status $($resp.StatusCode)"
} catch {
    $status = $_.Exception.Response.StatusCode.value__
    $body = ""
    try {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $body = $reader.ReadToEnd()
    } catch { }
    Log "tts probe status $status body=$body"
}

$cacheTest = @'
import json
from backend.services import voice_audio_cache as c
c.init()
r = c.get_or_create("Deploy probe. This is an automated test.")
print("CACHE_PROBE", json.dumps({k: r.get(k) for k in ("ok","hash","url","chars","bytes","hit","reason")}, ensure_ascii=True))
'@
Log "running cache synthesis probe"
$cacheTest | & railway ssh --service $service --environment $environment -p $project python 2>&1 | ForEach-Object { Log $_ }

Log "=== deploy voice tts cache: end ==="
