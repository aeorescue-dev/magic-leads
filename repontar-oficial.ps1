$ErrorActionPreference = "Stop"

function Hop([string]$u) {
  $code = ""; $loc = ""
  $hd = (& curl.exe -s -o NUL -D - --max-redirs 0 --max-time 25 $u 2>&1 | ForEach-Object { $_ })
  foreach ($l in $hd) {
    if (-not $code -and $l -match "^\s*$") { continue }
    if (-not $code -and $l -match "^HTTP/.*?\s(\d{3})") { $code = $matches[1] }
    elseif (-not $loc -and $l -match "(?i)^location:\s*(.+)$") { $loc = $matches[1].Trim() }
  }
  if (-not $code) { $code = (& curl.exe -s -o NUL -w "%{http_code}" --max-redirs 0 --max-time 25 $u 2>&1 | ForEach-Object { $_ } | Select-Object -Last 1) }
  return [pscustomobject]@{ code = $code; loc = $loc }
}
function Fin([string]$u) { return (& curl.exe -s -o NUL -w "%{http_code}" -L --max-redirs 10 --max-time 45 $u 2>&1 | ForEach-Object { $_ } | Select-Object -Last 1) }

$out = New-Object System.Collections.Generic.List[string]
$root = "C:\Users\Fabio\Documents\Default Project\garimpador-leads"

$out.Add("=========== 0) o QUE VOCE CONFIRMOU ABRINDO (prova mais forte) ===========") | Out-Null
foreach ($p in @("/pt", "/en", "/es")) {
  $u = "https://garimpador-leads.vercel.app$p"
  $t = Hop $u
  $f = Fin $u
  $tag = if ($f -eq "200") { "FIX_OK" } else { "ATENCAO" }
  $out.Add(("  {0,-52} 1hop={1,-3} loc={2,-12} final={3,-5} [{4}]" -f $u, $t.code, $t.loc, $f, $tag)) | Out-Null
}

$out.Add("") | Out-Null
$out.Add("=========== 1) inspecao COMPLETA do alias que ABRE, gravada em arquivo ===========") | Out-Null
$insp = (& vercel inspect garimpador-leads.vercel.app 2>&1 | ForEach-Object { $_ }) | Out-String
$insp | Set-Content -Encoding UTF8 "$root\inspect-garimpador.txt"
$out.Add("  inspect gravado em inspect-garimpador.txt (leitura com Grep)") | Out-Null

# buscar a URL de deployment real no conteudo inspecionado (2 padroes)
$depUrl = ""
$lines = ($insp -split "`r?`n")
foreach ($l in $lines) {
  if ($l -match "https://(frontend-[a-z0-9]+)-fabio-dev2\.vercel\.app") { $depUrl = $matches[0]; break }
}
if (-not $depUrl) {
  foreach ($l in $lines) {
    if ($l -match "(?i)deployment|\burl\b|https://([a-z0-9]+)-fabio-dev2") { $out.Add(("   linha suspeita: " + $l.Trim())) | Out-Null }
  }
}
if ($depUrl) {
  $out.Add(("  deployment real por tras do alias confirmado: {0}" -f $depUrl)) | Out-Null

  # validar que ESSE deployment serve /pt=200 antes de qualquer coisa
  $t2 = Hop "$depUrl/pt"
  $f2 = Fin "$depUrl/pt"
  $out.Add(("  pre-probe desse deployment /pt -> 1hop={0} final={1}" -f $t2.code, $f2)) | Out-Null

  if ($f2 -eq "200") {
    $out.Add("") | Out-Null
    $out.Add("=========== 2) REAPONTAR o alias OFICIAL para esse MESMO deployment ===========") | Out-Null
    $aliasOut = (& vercel alias set magicleads-oficial.vercel.app $depUrl 2>&1 | ForEach-Object { $_ })
    foreach ($l in (($aliasOut | Out-String) -split "`r?`n")) {
      if ($l -match "(?i)success|now points|error|denied|must be|cannot") { $out.Add(("   " + $l.Trim())) | Out-Null }
    }

    $out.Add("") | Out-Null
    $out.Add("=========== 3) VALIDACAO FINAL link OFICIAL (deve acabar 200) ===========") | Out-Null
    Start-Sleep -Seconds 15
    foreach ($p2 in @("/", "/pt", "/pt/", "/en", "/es", "/pt/register")) {
      $u2 = "https://magicleads-oficial.vercel.app$p2"
      $h3 = Hop $u2
      $f3 = Fin $u2
      $tag3 = if ($f3 -eq "200") { "OK" } else { "ATENCAO" }
      $out.Add(("   {0,-50} 1hop={1,-3} loc={2,-14} final={3,-5} [{4}]" -f $u2, $h3.code, $h3.loc, $f3, $tag3)) | Out-Null
    }
  } else {
    $out.Add("  ATENCAO: deployment encontrado NAO serve /pt=200; alias NAO alterado.") | Out-Null
  }
} else {
  $out.Add("  ATENCAO: nao achei deployment no inspect. Na busca por linhas: nada acima.") | Out-Null
}

$out | Out-String