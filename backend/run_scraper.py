import sys

sys.path.insert(0, '.')
import asyncio

from scrapers.socrata_311 import socrata_scraper

asyncio.run(socrata_scraper.run())
