"""
Serverless entrypoint para Vercel.

O Vercel detecta `app` neste módulo como handler ASGI e serve o FastAPI completo.
O caminho padrão do runtime é a raiz do repo, então `backend.main` é importável.
"""
import sys
import os

# Garante que a raiz do projeto esteja no path (runtime serverless Vercel)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.main import app  # noqa: E402  (app ASGI/FastAPI)
from backend.services.db import init_db  # noqa: E402

# Garante que o banco SQLite exista no boot
init_db()

# Handler padrão exigido pela Vercel
handler = app
