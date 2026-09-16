from ..utils.logger import logger


class TaxDelinquencyScraper:
    """
    Scraper para dados de Tax Delinquency (débito fiscal imobiliário).
    MVP: placeholder que será conectado a fontes de dados de impostos.
    """

    async def fetch_delinquent(self, city: str = "NYC", hours: int = 48):
        logger.info(f"Tax Delinquency: fetch para {city} (placeholders)")
        return []
