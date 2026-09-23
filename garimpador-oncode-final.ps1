$ErrorActionPreference = "SilentlyContinue"

function Probe1Hop([string]$u) {
  $code = ""; $loc = ""
  $hd = (& curl.exe -s -o NUL -D - --max-redirs 0 --max-time 25 $u 2>&1 | ForEach-Object { $_ })
  foreach ($l in $hd) {
    if (-not $code -and $l -match "^HTTP/.*?\s(\d{3})") { $code = $matches[1] }
    elseif ($l -match "(?i)^location:\s*(.+)$" -and -not $loc) { $loc = $matches[1].Trim() }
  }
  if (-not $code) { $code = (& curl.exe -s -o NUL -w "%{http_code}" --max-redirs 0 --max-time 25 $u 2>&1 | ForEach-Object { $_ } | Select-Object -Last 1) }
  return [pscustomobject]@{ code = $code; loc = $loc }
}
function FinalCode([string]$u) {
  return (& curl.exe -s -o NUL -w "%{http_code}" -L --max-redirs 10 --max-time 45 $u 2>&1 | ForEach-Object { $_ } | Select-Object -Last 1)
}

$out = New-Object System.Collections.Generic.List[string]
$out.Add("================================================================") | Out-Null
$out.Add(" PASSO DETERMINISTICO: usar o alias CONFIRMADO POR VOCE") | Out-Null
$out.Add(" aleatorio/garimpador-leads.vercel.app/pt = 200 (voce abriu)") | Out-Null
$out.Add("================================================================") | Out-Null

# ---- 1) INSPECT do alias que VOCE confirmou -> descobre o DEPLOYMENT REAL por tras ----
$out.Add("") | Out-Null
$out.Add("[1/3] vercel inspect garimpador-leads.vercel.app (revela deployment real)...") | Out-Null
$insp = (& vercel inspect garimpador-leads.vercel.app 2>&1 | ForEach-Object { $_ })
$deployUrl = ""
foreach ($l in ($insp | Out-String) -split "`r?`n") {
  if ($l -match "https://(frontend-[a-z0-9]+-fabio-dev2\.vercel\.app)") { $deployUrl = "https://" + $matches[1]; break }
}
if (-not $deployUrl) {
  # fallback: garimpador-leads pode ser um alias de projektu 'frontend'
  foreach ($l in ($insp | Out-String) -split "`r?`n") {
    if ($l -match "https://(frontend-[a-z0-9]+)-fabio-dev2\.vercel\.app") { $deployUrl = "https://" + $matches[1].Value; break }
  }
}
$out.Add(("  deployment REAL por tras do alias confirmado: {0}" -f $deployUrl)) | Out-Null

# ---- 2) valida que ESSE deployment serve /pt = 200 (fix ok) ----
$out.Add("") | Out-Null
if ($deployUrl) {
  $t = Probe1Hop "$deployUrl/pt"
  $out.Add(("  [2/3] probe {0}/pt  ->  1hop={1} loc={2}  ->  final={3}" -f $deployUrl, $t.code, $t.loc, (FinalCode "$deployUrl/pt"))) | Out-Null
}

# ---- 3) reapontar O ALIAS OFICIAL magicleads-oficial para ESSE MESMO deployment ----
$out.Add("") | Out-Null
if ($deployUrl -and (FinalCode "$deployUrl/pt") -eq "200") {
  $out.Add(("  [3/3] vercel alias set magicleads-oficial.vercel.app {0}" -f $deployUrl)) | Out-Null
  $ao = (& vercel alias set magicleads-oficial.vercel.app $deployUrl 2>&1 | ForEach-Object { $_ })
  foreach ($l in ($ao | Out-String) -split "`r?`n") {
    if ($l -match "(?i)success|now points|error|denied|must be") { $out.Add(("    " + $l.Trim())) | Out-Null }
  }
  $out.Add("") | Out-Null
  $out.Add("--- VALIDACAO FINAL link OFICIAL https://magicleads-oficial.vercel.app ---") | Out-Null
  Start-Sleep -Seconds 12
  foreach ($p in @("/", "/pt", "/pt/", "/en", "/es", "/pt/register")) {
    $u = "https://magicleads-oficial.vercel.app$p"
    $t = Probe1Hop $u
    $fc = FinalCode $u
    $flag = ""
    if ($fc -eq "200" -and ($p -ne "/" -or -not $t.loc)) { $flag = "OK" } else { $flag = "ATENCAO" }
    $out.Add(("  {0,-50} 1hop={1,-3} loc={2,-10} final={3,-5} [{4}]" -f $u, $t.code, $t.loc, $fc, $flag)) | Out-Null
  }
} else {
  $out.Add("  [3/3] SEM deployment valido -> alias NAO alterado (mantem o atual).") | Out-Null
}

$out | Out-String