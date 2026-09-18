"""Isola os testes do banco de produção (data/leads.db)."""
import os
import tempfile

TEST_DIR = tempfile.mkdtemp(prefix="magicleads_tests_")
os.environ["LEADS_DB_PATH"] = os.path.join(TEST_DIR, "leads.db")
os.environ["SCRAPER_SELF_SCHEDULED"] = "false"