@echo off
cd /d "C:\Users\Fabio\Documents\Default Project\garimpador-leads\backend"
venv\Scripts\python.exe -c "
import sys
sys.path.insert(0, '.')
from scrapers.socrata_311 import socrata_scraper
import asyncio
asyncio.run(socrata_scraper.run())
"