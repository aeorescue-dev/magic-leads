$ErrorActionPreference = "SilentlyContinue"
$OutputEncoding = [System.Text.Encoding]::ASCII

$cands = @(
  "frontend-bvzhymk4t-fabio-dev2.vercel.app",
  "frontend-egtac8s6s-fabio-dev2.vercel.app",
  "frontend-sad0xa79j-fabio-dev2.vercel.app",
  "frontend-5avga2c2q-fabio-dev2.vercel.app",
  "frontend-56sbmlr65-fabio-dev2.vercel.app",
  "frontend-m0f19627b-fabio-dev2.vercel.app",
  "frontend-e69ccy3r1-fabio-dev2.vercel.app",
  "frontend-rdwge4ke1-fabio-dev2.vercel.app",
  "frontend-8ufpsvhwm-fabio-dev2.vercel.app",
  "frontend-pq6d0kcck-fabio-dev2.vercel.app",
  "frontend-fis59bq24-fabio-dev2.vercel.app"
)

$out = New-Object System.Collections.Generic.List[string]
$out.Add("=== 1) vercel inspect: pegar timestamp de cada candidata FIX_OK ===") | Out-Null
$rows = [System.Collections.Generic.List[object]]::new()
foreach ($c in $cands) {
  $u = "https://$c"
  $ins = (& vercel inspect $u 2>&1 | ForEach-Object { $_ }) | Out-String
  $created = ""
  foreach ($l in ($ins -split "`r?`n")) {
    if ($l -match "(?i)(created|createdAt)\s*[:=]\s*(.+)") { $created = $matches[2].Trim() }
  }
  $rows.Add([pscustomobject]@{ url = $u; created = $created }) | Out-Null
  $out.Add(("  {0,-52} criado={1}" -f $u, $created)) | Out-Null
}

# ---- 2) escolher a mais NOVA (timestamp maior = mais recente) ----
$out.Add("") | Out-Null
$parsed = @($rows | Where-Object { $_.created } | ForEach-Object {
  $dt = [datetime]::MinValue
  [void][datetime]::TryParse($_.created, [ref]$dt)
  [pscustomobject]@{ url = $_.url; dt = $dt }
} | Sort-Object dt -Descending)
$newest = if ($parsed.Count -gt 0) { $parsed[0].url } else { $null }
$out.Add(("=== 2) mais NOVA FIX_OK => {0}" -f $newest)) | Out-Null

# ---- 3) reapontar alias OFICIAL ----
$out.Add("") | Out-Null
if ($newest) {
  $out.Add(("=== 3) vercel alias set magicleads-oficial.vercel.app {0} ===" -f $newest)) | Out-Null
  $a = (& vercel alias set magicleads-oficial.vercel.app $newest 2>&1 | ForEach-Object { $_ })
  foreach ($l in (($a | Out-String) -split "`r?`n")) {
    if ($l -match "(?i)success|now points|error|denied|must be|already") { $out.Add(("  " + $l.Trim())) | Out-Null }
  }
  $out.Add("") | Out-Null

  # ---- 4) VALIDACAO FINAL do link oficial ----
  $out.Add("=== 4) VALIDACAO do link OFICIAL (1-hop, sem seguir, para detectar loop) ===") | Out-Null
  foreach ($p in @("/", "/pt", "/pt/", "/en", "/es", "/pt/register")) {
    $u = "https://magicleads-oficial.vercel.app$p"
    $code = ""
    $loc = ""
    $h = (& curl.exe -s -o NUL -D - --max-redirs 0 --max-time 25 $u 2>$null | ForEach-Object { $_ })
    foreach ($l in $h) {
      if (-not $code -and $l -match "^HTTP/.*?\s(\d{3})") { $code = $matches[1] }
      elseif ($l -match "(?i)^location:\s*(.+)$" -and -not $loc) { $loc = $matches[1].Trim() }
    }
    $fin = (& curl.exe -s -o NUL -w "%{http_code}" -L --max-redirs 10 --max-time 45 $u 2>$null | ForEach-Object { $_ } | Select-Object -Last 1)
    $flag = ""
    if ($fin -eq "200") { $flag = "OK" } else { $flag = "ATENCAO" }
    $out.Add(("  {0,-48} 1hop={1,-3} loc={2,-8} final={3,-4} [{4}]" -f $u, $code, $loc, $fin, $flag)) | Out-Null
  }
} else {
  $out.Add("Nenhuma candidata com timestamp parsado — alias NAO alterado.") | Out-Null
}

$out | Out-String