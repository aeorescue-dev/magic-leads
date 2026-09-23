$ErrorActionPreference = "SilentlyContinue"
$OutputEncoding = [System.Text.Encoding]::ASCII

function Probe1Hop([string]$u) {
  $c = $null; $loc = ""
  $h = (& curl.exe -s -o NUL -D - --max-redirs 0 --max-time 25 $u 2>$null | ForEach-Object { $_ })
  foreach ($l in $h) {
    if (-not $c -and $l -match "^HTTP/.*?\s(\d{3})") { $c = $matches[1] }
    elseif ($l -match "(?i)^location:\s*(.+)$" -and -not $loc) { $loc = $matches[1].Trim() }
  }
  if (-not $c) { $c = (& curl.exe -s -o NUL -w "%{http_code}" --max-redirs 0 --max-time 25 $u 2>$null | ForEach-Object { $_ } | Select-Object -Last 1) }
  return [pscustomobject]@{ code = $c; loc = $loc }
}

function FinalCode([string]$u) {
  $f = (& curl.exe -s -o NUL -w "%{http_code}" -L --max-redirs 10 --max-time 45 $u 2>$null | ForEach-Object { $_ } | Select-Object -Last 1)
  return $f
}

$out = New-Object System.Collections.Generic.List[string]

$out.Add("================================================================") | Out-Null
$out.Add(" garimpador-oncode-run: passo final do combinado (fix + alias)") | Out-Null
$out.Add("================================================================") | Out-Null

# ---- 0) contexto ----
$who = (& vercel whoami 2>&1 | ForEach-Object { $_ }) | Select-Object -Last 1
$out.Add("vercel whoami = $who") | Out-Null
$root = "C:\Users\Fabio\Documents\Default Project\garimpador-leads"
$out.Add("repo raiz     = $root") | Out-Null

# ---- 1) catalogar deploys Ready Production do projeto 'frontend' ----
$out.Add("") | Out-Null
$out.Add("[1/4] listando deployments do projeto 'frontend' (production)...") | Out-Null
$raw = (& vercel ls frontend --alpha 2>&1 | ForEach-Object { $_ }) -join "`n"
$cand = @()
foreach ($m in [regex]::Matches($raw, "(?im)^\s*(\.*)\s*(fabio-dev2/frontend|fabio-dev2)\s+(https://(frontend-[a-z0-9]+)\-fabio-dev2\.vercel\.app)\s+●\s+Ready\s+(Production|Preview)")) {
  $cand += $m.Groups[3].Value
}
$cand = @($cand | Select-Object -Unique)

# ---- 2) testar 1-hop /pt em cada candidato; separar FIX_OK (200) de LOOP, usando só curl ----
$out.Add("") | Out-Null
$out.Add("[2/4] testando cada deploy (1-hop em /pt)...") | Out-Null
$fixOk = @()
foreach ($u in $cand) {
  $t = Probe1Hop "$u/pt"
  $tag = ""
  if ($t.code -eq "200") { $tag = "FIX_OK"; $fixOk += $u }
  elseif ($t.code -eq "307" -and $t.loc -eq "/pt") { $tag = "LOOP" }
  else { $tag = "?" }
  $out.Add(("  {0,-48} 1hop={1,-3} loc={2,-8} [{3}]" -f $u, $t.code, $t.loc, $tag)) | Out-Null
}

# ---- 3) escolher o MAIS RECENTE FIX_OK e repontar o alias oficial ----
$out.Add("") | Out-Null
if ($fixOk.Count -eq 0) {
  $out.Add("[3/4] NENHUM deploy FIX_OK encontrado -> alias NAO alterado.") | Out-Null
} else {
  # o primeiro elemento do ls --alpha eh sempre o mais recente; pega o 1o FIX_OK na ordem
  $chosen = $fixOk[0]
  $out.Add(("[3/4] escolhido para o link oficial: {0}" -f $chosen)) | Out-Null
  $out.Add(("      vercel alias set magicleads-oficial.vercel.app {0}" -f $chosen)) | Out-Null
  $aliasOut = (& vercel alias set magicleads-oficial.vercel.app $chosen 2>&1 | ForEach-Object { $_ })
  foreach ($l in ($aliasOut | Out-String) -split "`r?`n") {
    if ($l -match "(?i)success|now points|error|denied|must be") { $out.Add(("      " + $l.Trim())) | Out-Null }
  }
}

# ---- 4) validacao final do link OFICIAL ----
$out.Add("") | Out-Null
$out.Add("[4/4] validacao do link OFICIAL https://magicleads-oficial.vercel.app ...") | Out-Null
foreach ($p in @("/", "/pt", "/pt/", "/en", "/es", "/pt/register")) {
  $u = "https://magicleads-oficial.vercel.app$p"
  $t = Probe1Hop $u
  $fc = FinalCode $u
  $flag = ""
  if ($fc -eq "200" -and ($p -ne "/" -or $t.code -eq "307")) { $flag = "OK" }
  else { $flag = "ATENCAO" }
  $out.Add(("  {0,-50} 1hop={1,-3} loc={2,-10} final={3,-5} [{4}]" -f $u, $t.code, $t.loc, $fc, $flag)) | Out-Null
}

$out | Out-String