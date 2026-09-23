$ErrorActionPreference = "SilentlyContinue"

function 1Hop([string]$u) {
  $c = ""; $loc = ""
  $h = (& curl.exe -s -o NUL -D - --max-redirs 0 --max-time 25 $u 2>&1 | ForEach-Object { $_ })
  foreach ($l in $h) {
    if (-not $c -and $l -match "^HTTP/.*?\s(\d{3})") { $c = $matches[1] }
    elseif ($l -match "(?i)^location:\s*(.+)$" -and -not $loc) { $loc = $matches[1].Trim() }
  }
  if (-not $c) { $c = (& curl.exe -s -o NUL -w "%{http_code}" --max-redirs 0 --max-time 25 $u 2>&1 | ForEach-Object { $_ } | Select-Object -Last 1) }
  return [pscustomobject]@{ code = $c; loc = $loc }
}

function Final([string]$u) {
  return (& curl.exe -s -o NUL -w "%{http_code}" -L --max-redirs 10 --max-time 45 $u 2>&1 | ForEach-Object { $_ } | Select-Object -Last 1)
}

$out = New-Object System.Collections.Generic.List[string]

$out.Add("=== 1) confirmar/validar o que VOCE confirmou (links que ABREM) ===") | Out-Null
foreach ($p in @("/", "/pt", "/pt/", "/en", "/es", "/pt/register")) {
  $u = "https://garimpador-leads.vercel.app$p"
  $t = 1Hop $u
  $f = Final $u
  $flag = ""
  if ($f -eq "200") { $flag = "FIX_OK" } else { $flag = "?" }
  $out.Add(("  https://garimpador-leads.vercel.app{0,-18} 1hop={1,-3} loc={2,-6} final={3,-5} [{4}]" -f $p, $t.code, $t.loc, $f, $flag)) | Out-Null
}

$out.Add("") | Out-Null
$out.Add("=== 2) INSPECT do alias garimpador-leads.vercel.app (descobrir o deployment real por tras) ===") | Out-Null
$i = (& vercel inspect garimpador-leads.vercel.app 2>&1 | ForEach-Object { $_ }) | Out-String
foreach ($l in ($i -split "`r?`n")) {
  if ($l -match "(?i)(https://frontend-[a-z0-9]+-[a-z0-9-]+\.vercel\.app|ready|created|target|url :|alias|project|"'"'"'name'"'"'|scope)") {
    $out.Add(("  " + $l.Trim())) | Out-Null
  }
}

$out | Out-String