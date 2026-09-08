"""Limpeza permanente: remove leads de lixo urbano (sanitacao, lixo, pragas,
parking, sinalizacao, trafego, TPW) e mantem apenas oportunidades de reforma
(Telhado, Encanamento, Pintura, Estrutura, Mato Alto).

Faz backup do DB antes de deletar (data/leads.backup.db).
"""
import shutil
import sqlite3
import sys
from pathlib import Path

DB = Path(r"C:\Users\Fabio\Documents\Default Project\garimpador-leads\data\leads.db")
BACKUP = Path(r"C:\Users\Fabio\Documents\Default Project\garimpador-leads\data\leads.backup.db")

JUNK_TERMS = [
    "unsanitary", "dirty condition", "sanitation", "garbage", "trash",
    "litter", "clean sweep", "street spillage", "debris",
    "parking enforcement", "needle", "rodent", "pest ", "pests",
    "bed bug", "mice", "pigeon", "sign repair", "missing sign",
    "traffic signal", "general traffic", "abandoned vehicle",
    "abandoned bicycle", "abandoned bike", "debug test", "test issue",
    "contractors complaint", "fair housing", "squalid", "illegal auto",
    "bike rack", "boston bikes", "work w/out permit",
    "working beyond hours", "recycling", "debris at curb",
]

def junk_where():
    cols = ["issue_description", "descriptor", "case_title",
            "resolution_description", "department"]
    concat = " || ' ' || ".join(f"COALESCE({c}, '')" for c in cols)
    parts = " OR ".join(f"LOWER({concat}) LIKE '%{t}%'" for t in JUNK_TERMS)
    return f"({parts})"

def main():
    shutil.copy2(DB, BACKUP)
    print(f"Backup criado: {BACKUP}")

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    sql = f"SELECT COUNT(*) FROM leads WHERE {junk_where()}"
    n_junk = cur.execute(sql).fetchone()[0]
    n_total = cur.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

    print(f"Total leads: {n_total}")
    print(f"Leads de lixo urbano (a deletar): {n_junk}")
    print(f"Leads de reforma (permanecem): {n_total - n_junk}")

    # Preview por termo
    print("\n--- Ate 'x' por termo ---")
    for t in JUNK_TERMS:
        cols = ["issue_description", "descriptor", "case_title",
                "resolution_description", "department"]
        concat = " || ' ' || ".join(f"COALESCE({c}, '')" for c in cols)
        c = cur.execute(
            f"SELECT COUNT(*) FROM leads WHERE LOWER({concat}) LIKE ?",
            (f"%{t}%",),
        ).fetchone()[0]
        if c:
            print(f"  '{t}': {c}")

    # Preview por cidade/categoria dos leads que serao mantidos
    keep_sql = f"SELECT city, COUNT(*) FROM leads WHERE NOT {junk_where()} GROUP BY city ORDER BY 2 DESC"
    print("\n--- MANTIDOS por cidade ---")
    for row in cur.execute(keep_sql).fetchall():
        print(f"  {row[0]}: {row[1]}")

    keep_cat_sql = f"SELECT issue_category, COUNT(*) FROM leads WHERE NOT {junk_where()} GROUP BY issue_category ORDER BY 2 DESC"
    print("\n--- MANTIDOS por categoria ---")
    for row in cur.execute(keep_cat_sql).fetchall():
        print(f"  {row[0]}: {row[1]}")

    confirm = "--confirm" in sys.argv
    if not confirm:
        answer = input("\nDeletar permanentemente? (sim/Nao): ").strip().lower()
        if answer != "sim":
            print("Cancelado. Nada foi deletado.")
            conn.close()
            return

    cur.execute(f"DELETE FROM leads WHERE {junk_where()}")
    conn.commit()

    after = cur.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    print(f"\nDeletados {cur.rowcount}. Total agora: {after}")
    print("Por cidade apos limpeza:")
    for row in cur.execute("SELECT city, COUNT(*) FROM leads GROUP BY city ORDER BY 2 DESC").fetchall():
        print(f"  {row[0]}: {row[1]}")
    print("Por categoria apos limpeza:")
    for row in cur.execute("SELECT issue_category, COUNT(*) FROM leads GROUP BY issue_category ORDER BY 2 DESC").fetchall():
        print(f"  {row[0]}: {row[1]}")
    print("Com owner_name apos limpeza:")
    print(" ", cur.execute("SELECT COUNT(*) FROM leads WHERE owner_name IS NOT NULL AND owner_name != ''").fetchone()[0])

    conn.close()

if __name__ == "__main__":
    main()