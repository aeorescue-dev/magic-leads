import os
import sqlite3
from datetime import datetime

# Database path
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "leads.db"
)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

try:
    # 1. Total de leads
    total_leads = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]

    # 2. Leads criados/atualizados hoje
    today = datetime.now().strftime("%Y-%m-%d")
    leads_today = conn.execute(
        "SELECT COUNT(*) AS c FROM leads WHERE date(created_at) = ? OR date(updated_at) = ?",
        (today, today)
    ).fetchone()["c"]

    # 3. Leads com owner_name
    with_owner = conn.execute(
        "SELECT COUNT(*) AS c FROM leads WHERE owner_name IS NOT NULL AND owner_name != ''"
    ).fetchone()["c"]

    # 4. Total de usuários
    total_users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]

    # 5. Notificações não lidas (globais)
    unread_global = conn.execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE read = 0"
    ).fetchone()["c"]

    # 6. Notificações totais (globais)
    total_notif_global = conn.execute("SELECT COUNT(*) AS c FROM notifications").fetchone()["c"]

    # 7. Notificações por usuário
    users = conn.execute("SELECT id, email, company_name FROM users").fetchall()

    print(f"[DIAGNOSTICO] Total de Leads no BD: {total_leads}")
    print(f"[DIAGNOSTICO] Leads criados/atualizados hoje: {leads_today}")
    print(f"[DIAGNOSTICO] Leads com owner_name: {with_owner}")
    print(f"[DIAGNOSTICO] Total de usuários: {total_users}")
    print(f"[DIAGNOSTICO] Notificações globais não lidas: {unread_global}")
    print(f"[DIAGNOSTICO] Notificações globais total: {total_notif_global}")
    print()

    for user in users:
        uid = user["id"]
        unread_user = conn.execute(
            "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND read = 0", (uid,)
        ).fetchone()["c"]
        total_user_notif = conn.execute(
            "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ?", (uid,)
        ).fetchone()["c"]
        leads_user = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE reserved_by = ? OR converted_by = ?", (uid, uid)
        ).fetchone()["c"]
        print(f"[DIAGNOSTICO] Usuário {uid} ({user['email']}):")
        print(f"  - Notificações não lidas: {unread_user}")
        print(f"  - Notificações total: {total_user_notif}")
        print(f"  - Leads reservados/convertidos: {leads_user}")

    # 8. Últimos leads inseridos
    print()
    recent = conn.execute(
        "SELECT id, external_id, address, city, date_reported, created_at, owner_name FROM leads ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    print("[DIAGNOSTICO] Últimos 5 leads inseridos:")
    for r in recent:
        print(f"  - ID {r['id']}: {r['address']}, {r['city']} | reported: {r['date_reported']} | created: {r['created_at']} | owner: {r['owner_name'] or 'N/A'}")

    # 9. Últimas notificações
    print()
    recent_notif = conn.execute(
        "SELECT id, user_id, type, title, message, read, created_at FROM notifications ORDER BY created_at DESC LIMIT 10"
    ).fetchall()
    print("[DIAGNOSTICO] Últimas 10 notificações:")
    for r in recent_notif:
        print(f"  - ID {r['id']}: user={r['user_id']} | {r['type']} | {r['title']} | read={r['read']} | {r['created_at']}")

finally:
    conn.close()
