$ErrorActionPreference="SilentlyContinue"
$root = "C:\Users\Fabio\Documents\Default Project\garimpador-leads"
$dep = "garimpador-leads-3e66txz9y-fabio-dev2.vercel.app"
$out = (& vercel alias set magicleads-oficial.vercel.app $dep 2>&1 | ForEach-Object { $_ }) | Out-String
$out | Set-Content -Encoding UTF8 "$root\alias-oficial-pos-fix.txt"
# e tambem via cmd cru (parse de encoding do vercel 100% trava)
cmd /c ("vercel alias set magicleads-oficial.vercel.app " + $dep + " > `"" + $root + "\alias-oficial-cru.txt`" 2>&1")
