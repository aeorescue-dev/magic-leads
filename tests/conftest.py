"""Configuração de testes.

Isola o SQLite de teste ANTES de qualquer import do backend, para que os testes
de despacho NUNCA toquem o banco de desenvolvimento/produção (data/leads.db).
"""

import os
import tempfile

_TMP_DB = os.path.join(tempfile.gettempdir(), "magicleads_test_leads.db")
for _suffix in ("", "-wal", "-shm"):
    try:
        os.remove(_TMP_DB + _suffix)
    except OSError:
        pass

os.environ["LEADS_DB_PATH"] = _TMP_DB
os.environ.pop("LEADS_RESET_ON_BOOT", None)
os.environ.pop("LEADS_SEED_FILE", None)
os.environ.pop("DATA_DIR", None)
