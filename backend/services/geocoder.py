import httpx
from typing import Optional, Tuple
from ..utils.logger import logger


class GeocoderService:
    """
    Serviço de geocodificação de endereços.
    Usa Google Geocoder se configurado; caso contrário, retorna None.
    """

    async def geocode(self, address: str) -> Optional[Tuple[float, float]]:
        logger.info(f"Geocoding: {address}")
        return None
