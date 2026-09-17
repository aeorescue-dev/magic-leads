import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('data/leads.db')
c = conn.cursor()

# The issue: SQLite date('now') = 2026-09-16 (UTC), but data is 2026-09-15
# Use the actual data date: 2026-09-15

target_date = '2026-09-15'

print(f"=== RELATÓRIO DETALHADO PARA {target_date} ===\n")

# Total
c.execute("""
    SELECT COUNT(*) FROM leads 
    WHERE date(date_reported) = ?
""", (target_date,))
total = c.fetchone()[0]
print(f"TOTAL DE OPORTUNIDADES: {total}\n")

# Por cidade
c.execute("""
    SELECT city, COUNT(*) as cnt FROM leads 
    WHERE date(date_reported) = ?
    GROUP BY city ORDER BY cnt DESC
""", (target_date,))
print("=== POR CIDADE ===")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]}")
print()

# Por source_type
c.execute("""
    SELECT source_type, COUNT(*) as cnt FROM leads 
    WHERE date(date_reported) = ?
    GROUP BY source_type ORDER BY cnt DESC
""", (target_date,))
print("=== POR FONTE (source_type) ===")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]}")
print()

# Por issue_category
c.execute("""
    SELECT issue_category, COUNT(*) as cnt FROM leads 
    WHERE date(date_reported) = ?
    GROUP BY issue_category ORDER BY cnt DESC
""", (target_date,))
print("=== POR CATEGORIA (issue_category) ===")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]}")
print()

# Por cidade + fonte
c.execute("""
    SELECT city, source_type, COUNT(*) as cnt FROM leads 
    WHERE date(date_reported) = ?
    GROUP BY city, source_type ORDER BY city, cnt DESC
""", (target_date,))
print("=== POR CIDADE + FONTE ===")
current_city = None
for row in c.fetchall():
    if row[0] != current_city:
        current_city = row[0]
        print(f"  {current_city}:")
    print(f"    {row[1]}: {row[2]}")
print()

# Horários (para ver quando rodou)
c.execute("""
    SELECT 
        strftime('%H', date_reported) as hora,
        COUNT(*) as cnt
    FROM leads 
    WHERE date(date_reported) = ?
    GROUP BY hora ORDER BY hora
""", (target_date,))
print("=== DISTRIBUIÇÃO POR HORA (UTC) ===")
for row in c.fetchall():
    print(f"  {row[0]}:00 - {row[1]} leads")
print()

# Verificar se há dados de outras cidades além de Chicago
c.execute("""
    SELECT DISTINCT city FROM leads 
    WHERE date(date_reported) = ?
""", (target_date,))
cities = [row[0] for row in c.fetchall()]
print(f"CIDADES COM DADOS HOJE: {', '.join(cities)}")

# Verificar se NYC, Dallas, Boston, etc. tiveram dados nos últimos dias
print("\n=== CIDADES NOS ÚLTIMOS 3 DIAS ===")
c.execute("""
    SELECT date(date_reported) as dia, city, COUNT(*) as cnt FROM leads 
    WHERE date(date_reported) >= date('now', '-3 days')
    GROUP BY dia, city ORDER BY dia DESC, cnt DESC
""")
current_day = None
for row in c.fetchall():
    if row[0] != current_day:
        current_day = row[0]
        print(f"\n  {current_day}:")
    print(f"    {row[1]}: {row[2]}")

conn.close()