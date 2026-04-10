import sqlite3
import httpx
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

INTASEND_SECRET_KEY = os.environ.get("INTASEND_SECRET_KEY", "")
INTASEND_BASE_URL = os.environ.get("INTASEND_BASE_URL", "https://payment.intasend.com")

def get_intasend_key():
    key = INTASEND_SECRET_KEY
    if not key:
        raise ValueError("IntaSend secret key is not configured")
    return key

async def check_remaining_pending():
    conn = sqlite3.connect('wellparks.db')
    conn.row_factory = sqlite3.Row
    pending = conn.execute(
        "SELECT * FROM transactions WHERE payment_status='PENDING' AND intasend_invoice_id IS NOT NULL"
    ).fetchall()
    conn.close()

    print(f"Checking {len(pending)} remaining pending transactions")

    for txn in pending:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{INTASEND_BASE_URL}/api/v1/payment/status/",
                    json={"invoice_id": txn["intasend_invoice_id"]},
                    headers={"Authorization": f"Bearer {get_intasend_key()}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    state = data.get("invoice", {}).get("state", "").upper()
                    print(f"Transaction {txn['id']} - {txn['plate_number']}: {state}")
                else:
                    print(f"Transaction {txn['id']} - {txn['plate_number']}: API Error {resp.status_code}")
        except Exception as e:
            print(f"Transaction {txn['id']} - {txn['plate_number']}: Exception {e}")

asyncio.run(check_remaining_pending())