$ErrorActionPreference = "SilentlyContinue"
$out = New-Object System.Collections.Generic.List[string]

function Probe([string]$url) {
  $code = ""
  $loc = ""
  $raw = (& curl.exe -s -o NUL -D - --max-redirs 0 --max-time 20 $url 2>$null | ForEach-Object { $_ })
  foreach ($l in $raw) {
    if ($l -match "^HTTP/.*?\s(\d{3})") { $code = $matches[1] }
    elseif ($l -match "(?i)^location:\s*(.+)$" -and -not $loc) { $loc = $matches[1].Trim() }
  }
  return @{ code = $code; loc = $loc }
}

# 1) lista completa do ls --alpha: URL + idade + estado
$logs = (& vercel ls frontend --alpha 2>&1 | ForEach-Object { $_ }) | Out-String
$out.Add("=== MANCHA COMPLETA (ls --alpha): cada entrada com URL, idade e estado ===") | Out-Null
$all = [System.Collections.ArrayList]::new()
foreach ($ln in ($logs -split "`r?`n")) {
  if ($ln -match "https://(frontend-[a-z0-9]+)-fabio-dev2\.vercel\.app") {
    $url = "https://$($matches[1])-fabio-dev2.vercel.app"
    $age = ""
    if ($ln -match "^\s*([0-9]+[smhd])\s") { $age = $matches[1] }
    $ready = ($ln -match "● Ready")
    $prod  = ($ln -match "(?i)Production")
    [void]$all.Add([pscustomobject]@{ Url=$url; Age=$age; Ready=$ready; Prod=$prod })
  }
}
$ordered = @($all | Sort-Object @{Expression={ ($k = ($_.Age -split ":"))[0] }})
# ordenar por idade numerica: parse smhd -> segundos, menor = mais novo
$ordered = @($all | ForEach-Object {
  $s = 0
  if ($_.Age -match "^([0-9]+)([smhd])$") {
    $n = [int]$matches[1]; $m = @{s=1;m=60;h=3600;d=86400}[$matches[2]]; $s = $n * $m
  } else { $s = [int]::MaxValue }
  [pscustomobject]@{ Url=$_.Url; Age=$_.Age; Ready=$_.Ready; Prod=$_.Prod; Sec=$s }
} | Sort-Object Sec)

$fixOk = [System.Collections.Generic.List[string]]::new()
foreach ($d in $ordered) {
  if (-not $d.Ready) { continue }
  $t = Probe "$($d.Url)/pt"
  $tag = if ($t.code -eq "200") { "FIX_OK" } elseif ($t.code -eq "307" -and $t.loc -eq "/pt") { "LOOP" } else { "?" }
  $row = "  {0,-8} {1,-50} {2,-6} 1hop={3,-3} loc={4,-8} [{5}]" -f $d.Age, $d.Url, $(if($d.Prod){"prod"}else{"prev"}), $t.code, $t.loc, $tag
  $out.Add($row) | Out-Null
  if ($tag -eq "FIX_OK") { $fixOk.Add($d.Url) | Out-Null }
}

# 2) escolher o mais novo FIX_OK (a lista ja vem ordenada por `Sec` crescente = mais novo primeiro)
$out.Add("") | Out-Null
$chosen = $null
if ($fixOk.Count -gt 0) {
  $chosen = $fixOk[0]
  $out.Add(("=== ESCOLHIDO (mais novo FIX_OK): {0} ===" -f $chosen)) | Out-Null
} else {
  $out.Add("=== NENHUM FIX_OK encontrado (nenhum /pt=200). Alias NAO sera alterado. ===") | Out-Null
}

# 3) reapontar alias oficial
if ($chosen) {
  $out.Add("") | Out-Null
  $out.Add("--- vercel alias set magicleads-oficial.vercel.app -> $chosen ---") | Out-Null
  $ao = & vercel alias set magicleads-oficial.vercel.app $chosen 2>&1 | ForEach-Object { $_ }
  $lines = ($ao | Out-String) -split "`r?`n"
  foreach ($l in $lines) {
    if ($l -match "(?i)success|now points|error|denied|must be|scope") { $out.Add("    " + $l.Trim()) | Out-Null }
  }

  # 4) validacao final
  $out.Add("") | Out-Null
  $out.Add("--- VALIDACAO FINAL do link oficial ---") | Out-Null
  Start-Sleep -Seconds 10
  foreach ($p in @("/", "/pt", "/pt/", "/en", "/es", "/pt/register")) {
    $u = "https://magicleads-oficial.vercel.app$p"
    $t = Probe $u
    $c2 = (& curl.exe -s -o NUL -w "%{http_code}" -L --max-redirs 10 --max-time 40 $u 2>$null | ForEach-Object { $_ } | Select-Object -Last 1)
    $flag = if ($c2 -eq "200") { "OK" } else { "ATENCAO($c2)" }
    $out.Add(("  {0,-52} 1hop={1,-3} loc={2,-8} final={3,-5} [{4}]" -f $u, $t.code, $t.loc, $c2, $flag)) | Out-Null
  }
}

$out | Out-String