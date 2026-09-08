import sys
sys.path.insert(0, '.')
from scrapers.socrata_311 import socrata_scraper
import asyncio
asyncio.run(socrata_scraper.run())