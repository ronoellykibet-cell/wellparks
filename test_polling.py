import asyncio
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

INTASEND_SECRET_KEY = os.environ.get("INTASEND_SECRET_KEY", "")
INTASEND_BASE_URL = os.environ.get("INTASEND_BASE_URL", "https://payment.intasend.com")

def get_intasend_key():
    key = INTASEND_SECRET_KEY
    if not key:
        raise ValueError("IntaSend secret key is not configured")
    if key.startswith("ISPubKey_"):
        raise ValueError("Invalid IntaSend key: publishable key detected. Use INTASEND_SECRET_KEY with a secret key.")
    return key

async def test_polling():
    # Simulate one polling cycle
    import sqlite3
    conn = sqlite3.connect('wellparks.db')
    conn.row_factory = sqlite3.Row
    pending = conn.execute(
        "SELECT * FROM transactions WHERE payment_status='PENDING' AND intasend_invoice_id IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchall()
    conn.close()

    print(f"Found {len(pending)} pending transactions")

    for txn in pending:
        print(f"Checking transaction {txn['id']}: {txn['plate_number']} - Invoice: {txn['intasend_invoice_id']}")
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
                    print(f"Status: {state}")
                    if state == "COMPLETE":
                        print("Payment completed! Would update database...")
                else:
                    print(f"Error: {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"Exception: {e}")

asyncio.run(test_polling())