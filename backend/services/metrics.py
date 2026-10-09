"""
Fase 2 — buffer de telemetria em memoria com flush assincrono.

PORQUE ISTO EXISTE
------------------
Uma consulta a Searchbug custa dinheiro. Sem registo, nao ha forma de
responder "quanto pagamos hoje?", "quantas chamadas foram cobradas e
nao devolveram telefone?" ou "esta consulta demorou 4s ou 400ms?". O
incidente do `reveal_timeout` mostrou que essa visibilidade faz falta.

PORQUE UM BUFFER E NAO UM INSERT POR CHAMADA
---------------------------------------------
`get_connection()` abre o SQLite com `busy_timeout=10000`. O scraper, a
API e os webhooks partilham o mesmo ficheiro. Um `INSERT` sincrono por
consulta paga adicionaria latencia ao caminho do utilizador e voltaria a
reproduzir a classe de bug que estamos a eliminar. Aqui:

1. `record()` e sincrono, nao levanta excecao e nao toca na BD.
2. O flush corre numa task de fundo, fora do request.
3. O write usa `busy_timeout` curto e `synchronous=OFF`: telemetria e
   descartavel, nao vale a pena esperar por um lock.

CONTRATO (inviolavel)
---------------------
Perdemos telemetria, nunca o pedido do utilizador. `record()` engole
excepcoes; uma falha no flush devolve o lote ao buffer e segue.

Perdas nao ficam silenciosas: `stats()["dropped"]` e `stats()["flush_errors"]`
sao expostos no painel /admin, para que telemetria perdida apareca como
numero e nao como "zero eventos" enganador.
"""

import asyncio
import logging
import sqlite3
import threading
from collections import deque
from typing import Any, Deque, Dict, List, Optional

import anyio.to_thread

logger = logging.getLogger("magic.metrics")

# Bounded buffers. Um vazamento de telemetria nunca pode consumir a memoria
# do processo, entao o buffer e um deque com teto: em excesso descarta o
# mais ANTIGO e conta o descarte.
_MAX_BUFFER = 5000
_BATCH_SIZE = 200
_FLUSH_INTERVAL_S = 20.0
# Metrics sao descartaveis: 1.5s e suficiente para escrever uma tabela
# pequena e mantem o flush fora do caminho critico mesmo sob contencao.
_METRICS_BUSY_TIMEOUT_MS = 1500

# Colunas por tabela. O timestamp NAO entra: cada tabela define-o com
# `DEFAULT CURRENT_TIMESTAMP` e omite-lo do INSERT e o que faz o default
# aplicar-se (inserir NULL aqui sobrescreveria o default com NULL).
#
# Cada buffer declara o seu proprio esquema. Uma lista global de colunas
# foi o que primeiro deu problema: `push_deliveries` tem `sent_at`,
# `attempts`, `user_id` e `kind`, e nao tem `called_at` nem `billed`.
_SEARCHBUG_COLUMNS = ("outcome", "billed", "latency_ms", "http_status", "city", "error")
_PUSH_COLUMNS = ("outcome", "attempts", "latency_ms", "http_status", "user_id", "kind", "error")

# Coercao por nome de coluna, partilhada pelas tabelas. `record()` e
# chamado com dados de codigo que nao controla (excecoes de bibliotecas),
# por isso normalizar aqui e mais barato do que validar em cada caller.
_INT_COLUMNS = frozenset({"billed", "attempts", "latency_ms", "http_status", "user_id"})
_STR_COLUMNS = frozenset({"outcome", "city", "kind"})
_MAX_ERROR_LEN = 300


class MetricsBuffer:
    """Fila de eventos de telemetria com flush de fundo."""

    def __init__(
        self,
        table: str,
        columns: tuple,
        enabled: bool = True,
        audit_hook=None,
    ):
        self._table = table
        self._columns = tuple(columns)
        self._enabled = enabled
        # `audit_hook` e chamado (conn, row, lastrowid) na MESMA transacao do
        # insert, para o evento de auditoria nunca ficar orfao da sua linha.
        self._audit_hook = audit_hook
        self._buf: Deque[Dict[str, Any]] = deque()
        self._lock = threading.Lock()
        self._task: Optional[asyncio.Task] = None

        self._flushed = 0
        self._dropped = 0
        self._flush_errors = 0

    # ---------------------------------------------------------------- API

    def record(self, **fields: Any) -> None:
        """Enfileira um evento. NUNCA levanta excecao, NUNCA bloqueia.

        Chamado no caminho critico (logo apos uma chamada paga), portanto
        qualquer erro aqui e fatal para a resposta do utilizador.
        """
        if not self._enabled:
            return
        try:
            row = self._normalize(fields)
            with self._lock:
                if len(self._buf) >= _MAX_BUFFER:
                    self._buf.popleft()
                    self._dropped += 1
                self._buf.append(row)
        except Exception:  # pragma: no cover - rede de seguranca
            # Contagem deliberadamente sem lock para nao poder falhar.
            try:
                self._dropped += 1
            except Exception:
                pass
            logger.debug("metrics.record falhou (evento perdido)", exc_info=True)

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "buffered": len(self._buf),
                "flushed": self._flushed,
                "dropped": self._dropped,
                "flush_errors": self._flush_errors,
            }

    # ------------------------------------------------------- ciclo de vida

    async def start(self) -> None:
        if not self._enabled or self._task is not None:
            return
        self._task = asyncio.create_task(self._run())
        logger.info("Buffer de telemetria '%s' iniciado", self._table)

    async def stop(self) -> None:
        """Cancela o loop e tenta um ultimo flush do que sobrou."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        with self._lock:
            pending = len(self._buf)
        if pending:
            logger.info("Flush final de %d evento(s) de '%s'", pending, self._table)
            await self.flush_once()

    # ---------------------------------------------------------------- loop

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(_FLUSH_INTERVAL_S)
                await self.flush_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - o loop nunca pode morrer
            logger.error("Loop de telemetria '%s' morreu", self._table, exc_info=True)

    async def flush_once(self) -> int:
        """Escreve um lote. Devolve o numero de linhas escritas (0 se nada)."""
        with self._lock:
            if not self._buf:
                return 0
            n = min(len(self._buf), _BATCH_SIZE)
            batch = [self._buf.popleft() for _ in range(n)]

        try:
            await anyio.to_thread.run_sync(self._insert, batch)
        except Exception as exc:
            # Falhou: devolve o lote ao inicio do buffer, a nao ser que ja
            # tenha sido truncado por eventos posteriores.
            with self._lock:
                self._flush_errors += 1
                room = max(0, _MAX_BUFFER - len(self._buf))
                if room < len(batch):
                    self._dropped += len(batch) - room
                if room:
                    for row in reversed(batch[:room]):
                        self._buf.appendleft(row)
            logger.warning("Flush de '%s' falhou (%d linhas): %s", self._table, len(batch), exc)
            return 0

        with self._lock:
            self._flushed += len(batch)
        return len(batch)

    # ----------------------------------------------------------------- BD

    def _normalize(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Garante so as colunas conhecidas e tipos aceitos pelo SQLite.

        `error` e truncado: mensagens de provider/exception podem trazer
        payloads inteiros e nao queremos inchar a tabela.
        """
        row: Dict[str, Any] = {c: None for c in self._columns}

        for key, value in fields.items():
            if key not in row:
                continue
            if value is None:
                row[key] = None
            elif key == "billed":
                row[key] = 1 if value else 0
            elif key == "error":
                row[key] = str(value)[:_MAX_ERROR_LEN]
            elif key in _INT_COLUMNS:
                # `bool` e subclasse de `int`: True passaria a 1 sem isto.
                row[key] = int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            elif key in _STR_COLUMNS:
                row[key] = str(value)[:120]
            else:
                row[key] = value
        return row

    def _insert(self, rows: List[Dict[str, Any]]) -> None:
        """Insert em transaccao propria, com conn propria e timeouts curtos.

        Com `audit_hook`, cada linha e inserida individualmente para expor o
        `lastrowid` (call_id) ao hook — a auditoria corre na MESMA transacao:
        se falhar, o lote inteiro volta ao buffer e ninguem fica orfao.
        """
        placeholders = ", ".join(f":{c}" for c in self._columns)
        sql = (
            f"INSERT INTO {self._table} ({', '.join(self._columns)}) "
            f"VALUES ({placeholders})"
        )
        conn = _metrics_connection()
        try:
            conn.execute("BEGIN")
            if self._audit_hook is None:
                conn.executemany(sql, rows)
            else:
                for row in rows:
                    cur = conn.execute(sql, row)
                    self._audit_hook(conn, row, cur.lastrowid)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ----------------------------------------------------------------- API interna

    def _drain_for_test(self) -> List[Dict[str, Any]]:  # pragma: no cover
        with self._lock:
            out = list(self._buf)
            self._buf.clear()
            return out


def _metrics_connection() -> sqlite3.Connection:
    """Conexao dedicada a telemetria: busy_timeout curto, synchronous=OFF.

    `DB_PATH` e importado dentro da funcao, e no topo do modulo, para partir
    o ciclo db -> searchbug -> metrics -> db. Alem disso resolve o path no
    momento da escrita, que e o que os testes manipulam via LEADS_DB_PATH.
    """
    import os

    from backend.services.db import DB_PATH

    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=_METRICS_BUSY_TIMEOUT_MS / 1000.0)
    try:
        conn.execute(f"PRAGMA busy_timeout={_METRICS_BUSY_TIMEOUT_MS};")
        # Telemetria e descartavel: sem fsync por evento. Nao vale esperar
        # por um lock do WAL por causa de uma metrica.
        conn.execute("PRAGMA synchronous=OFF;")
    except sqlite3.OperationalError:
        pass
    return conn


# Instancias por tabela. `record()` e o unico metodo usado no caminho
# critico; o resto e para o lifespan e para o painel.


def _searchbug_cost_audit(conn: sqlite3.Connection, row: Dict[str, Any], call_id: int) -> None:
    """Auditoria de custo da chamada Searchbug, na mesma transacao do insert.

    Somente chamadas `billed=1` (que chegaram ao provider e custaram dinheiro)
    geram evento `searchbug_cost` no credit_ledger, com `user_id=0` (sistema) —
    exatamente o mesmo formato que `backfill_credit_ledger` reconstroi, para
    que as linhas vivas e as backfilled sejam identicas. Idempotente pela
    unique index (user_id, reference_type, reference_id).

    Import lazily (I/O, fora do caminho do request) e, se falhar, derruba a
    transacao para o flush re-tentar o lote — nunca deixa telemetria sem a sua
    auditoria. A import de `db` aqui e segura contra o ciclo db->searchbug->
    metrics->db porque so acontece em runtime, nunca no import do modulo.
    """
    if not row.get("billed"):
        return

    from backend.services.db import _record_credit_event_connection

    _record_credit_event_connection(
        conn,
        user_id=0,
        event_type="searchbug_cost",
        amount=0,
        reference_id=call_id,
        reference_type="searchbug_call",
        metadata={
            "billed": row.get("billed"),
            "outcome": row.get("outcome"),
            "city": row.get("city"),
            "latency_ms": row.get("latency_ms"),
        },
    )


searchbug_metrics = MetricsBuffer(
    "searchbug_calls", _SEARCHBUG_COLUMNS, audit_hook=_searchbug_cost_audit
)
push_metrics = MetricsBuffer("push_deliveries", _PUSH_COLUMNS)
