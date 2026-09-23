$ErrorActionPreference = "SilentlyContinue"
$root = "C:\Users\Fabio\Documents\Default Project\garimpador-leads"

$lines = New-Object System.Collections.Generic.List[string]

# Deployment confirmado FIX_OK por probe direto + aberto por voce:
# https://garimpador-leads-3e66txz9y-fabio-dev2.vercel.app/pt = 200
$good = "garimpador-leads-3e66txz9y-fabio-dev2.vercel.app"

$lines.Add("=== 1) PROVA antes (o deployment que VOCE abriu ainda responde 200?) ===") | Out-Null
foreach ($p in @("/pt", "/en", "/es")) {
  $u = "https://$good$p"
  $code = (& curl.exe -s -o NUL -w "%{http_code}" -L --max-redirs 10 --max-time 45 $u 2>&1 | ForEach-Object { $_ } | Select-Object -Last 1)
  $tag = if ($code -eq "200") { "FIX_OK" } else { "ATENCAO" }
  $lines.Add(("   {0,-55} final={1,-5} [{2}]" -f $u, $code, $tag)) | Out-Null
}

$lines.Add("") | Out-Null
$lines.Add("=== 2) REAPONTAR o alias OFICIAL magicleads-oficial para ESSE deployment ===") | Out-Null
$args2 = @("alias", "set", "magicleads-oficial.vercel.app", $good)
$raw = (& vercel @args2 2>&1 | ForEach-Object { $_ }) | Out-String
($raw -split "`r?`n") | Where-Object { $_ -match "(?i)success|now points|error|denied|invalid|must" } | ForEach-Object { $lines.Add(("   " + $_.Trim())) | Out-Null }

$lines.Add("") | Out-Null
$lines.Add("=== 3) aguardar 20s e VALIDAR o link OFICIAL ===") | Out-Null
Start-Sleep -Seconds 20
foreach ($p in @("/", "/pt", "/pt/", "/en", "/es", "/pt/register", "/dashboard")) {
  $u = "https://magicleads-oficial.vercel.app$p"
  $code = (& curl.exe -s -o NUL -w "%{http_code}" -L --max-redirs 10 --max-time 45 $u 2>&1 | ForEach-Object { $_ } | Select-Object -Last 1)
  $tag = if ($code -eq "200") { "OK" } else { "ATENCAO" }
  $lines.Add(("   {0,-55} final={1,-5} [{2}]" -f $u, $code, $tag)) | Out-Null
}

$lines | Out-String