@echo off
cd /d "C:\Users\Fabio\Documents\Default Project\garimpador-leads\frontend"
set PATH=C:\Users\Fabio\AppData\Local\Temp\opencode\node-portable;%PATH%
node node_modules\next\dist\bin\next start -p 3005 > next-start.log 2>&1
