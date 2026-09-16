"""Phone Lookup Service - Interface e implementações para busca de telefone do dono.

Arquitetura baseada em providers (Strategy Pattern) para permitir:
- MockProvider (dev/test sem credenciais)
- SearchbugProvider (produção quando credenciais chegarem)
- FallbackProvider (futuro provedor secundário)

Quando credenciais Searchbug chegarem: trocar MockPhoneProvider por SearchbugProvider.
"""

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PhoneResult:
    """Resultado padronizado de busca de telefone."""
    success: bool
    phone: Optional[str] = None
    error: Optional[str] = None
    provider: str = "unknown"
    raw_data: Optional[dict] = None


class PhoneLookupProvider(ABC):
    """Interface base para provedores de busca de telefone."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome identificador do provedor (ex: 'searchbug', 'mock', 'fallback')."""
        pass

    @abstractmethod
    async def lookup(self, address: str, city: str, state: str) -> PhoneResult:
        """Busca telefone para endereço.

        Args:
            address: Endereço completo (rua, número)
            city: Cidade
            state: Estado (UF)

        Returns:
            PhoneResult com success=True se encontrou telefone válido
        """
        pass


class MockPhoneProvider(PhoneLookupProvider):
    """Provider mock para desenvolvimento/teste sem credenciais reais.

    Simula taxa de sucesso ~70% para testar fluxo completo.
    Remove quando credenciais Searchbug chegarem.
    """

    name = "mock"

    def __init__(self, success_rate: float = 0.7):
        self.success_rate = success_rate

    async def lookup(self, address: str, city: str, state: str) -> PhoneResult:
        """Simula busca com latência variável e taxa de sucesso configurável."""
        # Simula latência de rede (50-300ms)
        await asyncio.sleep(random.uniform(0.05, 0.3))

        # Determina sucesso/falha
        if random.random() <= self.success_rate:
            # Gera telefone brasileiro válido formato E.164
            ddd = random.choice(["11", "21", "31", "41", "51", "61", "71", "81", "85"])
            numero = f"9{random.randint(1000, 9999)}{random.randint(1000, 9999)}"
            phone = f"+55{ddd}{numero}"

            logger.info(f"MockPhoneProvider: sucesso para {address}, {city} - {phone}")
            return PhoneResult(
                success=True,
                phone=phone,
                provider=self.name,
                raw_data={"address": address, "city": city, "state": state, "mock": True}
            )
        else:
            errors = ["not_found", "rate_limited", "invalid_address", "timeout"]
            error = random.choice(errors)
            logger.warning(f"MockPhoneProvider: falha ({error}) para {address}, {city}")
            return PhoneResult(
                success=False,
                error=error,
                provider=self.name,
                raw_data={"address": address, "city": city, "state": state, "mock": True}
            )


class PhoneLookupService:
    """Serviço orquestrador de busca de telefone com cache, fallback e retry.

    Fluxo:
    1. Verifica cache (endereço normalizado)
    2. Tenta provedores em ordem (primário -> fallbacks)
    3. Retry com backoff exponencial no provedor primário
    4. Armazena resultado no cache
    """

    def __init__(self):
        self._providers: list[PhoneLookupProvider] = []
        self._cache: dict[str, PhoneResult] = {}
        self._cache_ttl_seconds = 30 * 24 * 3600  # 30 dias
        self._max_retries = 2
        self._base_delay = 0.5  # segundos

        # Inicializa com mock provider (substituir por SearchbugProvider quando credenciais chegarem)
        self._providers = [MockPhoneProvider(success_rate=0.7)]
        logger.info(f"PhoneLookupService iniciado com providers: {[p.name for p in self._providers]}")

    def set_providers(self, providers: list[PhoneLookupProvider]) -> None:
        """Substitui lista de provedores (chamado ao configurar Searchbug real)."""
        self._providers = providers
        logger.info(f"PhoneLookupService providers atualizados: {[p.name for p in providers]}")

    def _cache_key(self, address: str, city: str, state: str) -> str:
        """Gera chave de cache normalizada."""
        return f"{address.strip().lower()}|{city.strip().lower()}|{state.strip().upper()}"

    def get_cached(self, address: str, city: str, state: str) -> Optional[PhoneResult]:
        """Retorna resultado cached se válido."""
        key = self._cache_key(address, city, state)
        return self._cache.get(key)

    def _store_cache(self, address: str, city: str, state: str, result: PhoneResult) -> None:
        """Armazena resultado no cache."""
        key = self._cache_key(address, city, state)
        self._cache[key] = result

    async def _try_provider_with_retry(
        self,
        provider: PhoneLookupProvider,
        address: str,
        city: str,
        state: str
    ) -> Optional[PhoneResult]:
        """Tenta provedor com retry exponencial."""
        for attempt in range(self._max_retries + 1):
            try:
                result = await provider.lookup(address, city, state)
                if result.success:
                    return result
                # Se falhou mas não é erro de rate limit, não retry
                if result.error not in ("rate_limited", "timeout"):
                    return result
            except Exception as e:
                logger.warning(f"Provider {provider.name} erro (tentativa {attempt + 1}): {e}")

            if attempt < self._max_retries:
                delay = self._base_delay * (2 ** attempt) + random.uniform(0, 0.1)
                await asyncio.sleep(delay)

        return None

    async def lookup(self, address: str, city: str, state: str) -> PhoneResult:
        """Busca telefone com cache, fallback chain e retry.

        Returns:
            PhoneResult - success=True se encontrou telefone válido
        """
        # 1. Verifica cache
        cached = self.get_cached(address, city, state)
        if cached:
            logger.info(f"PhoneLookup: cache hit para {address}, {city}")
            return cached

        # 2. Tenta provedores em ordem (primário -> fallbacks)
        for provider in self._providers:
            logger.info(f"PhoneLookup: tentando provider {provider.name} para {address}, {city}")
            result = await self._try_provider_with_retry(provider, address, city, state)

            if result and result.success:
                self._store_cache(address, city, state, result)
                logger.info(f"PhoneLookup: sucesso via {provider.name} para {address}")
                return result

            # Se falhou por rate limit, tenta próximo provider
            if result and result.error == "rate_limited":
                logger.warning(f"Provider {provider.name} rate limited, tentando próximo...")
                continue

            # Se falhou por erro não-retryable, não tenta fallbacks (endereço inválido etc)
            if result and result.error in ("invalid_address", "not_found"):
                break

        # 3. Falha total
        error_result = PhoneResult(
            success=False,
            error="all_providers_failed",
            provider="none",
            raw_data={"address": address, "city": city, "state": state}
        )
        self._store_cache(address, city, state, error_result)  # Cache falha também para evitar retry loops
        logger.error(f"PhoneLookup: todos providers falharam para {address}, {city}")
        return error_result

    def clear_cache(self) -> None:
        """Limpa cache (útil para testes)."""
        self._cache.clear()

    def get_stats(self) -> dict:
        """Retorna estatísticas do cache."""
        return {
            "cache_size": len(self._cache),
            "providers": [p.name for p in self._providers],
            "cache_ttl_days": self._cache_ttl_seconds // 86400
        }


# Instância global (singleton)
phone_lookup_service = PhoneLookupService()


# Função de conveniência para uso direto
async def lookup_phone(address: str, city: str, state: str) -> PhoneResult:
    """Função de conveniência para busca direta."""
    return await phone_lookup_service.lookup(address, city, state)
