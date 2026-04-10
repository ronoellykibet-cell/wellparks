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

async def fix_pending_transactions():
    conn = sqlite3.connect('wellparks.db')
    conn.row_factory = sqlite3.Row
    pending = conn.execute(
        "SELECT * FROM transactions WHERE payment_status='PENDING' AND intasend_invoice_id IS NOT NULL"
    ).fetchall()

    print(f"Found {len(pending)} pending transactions to check")

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
                    if state == "COMPLETE":
                        mpesa_ref = data.get("invoice", {}).get("mpesa_reference", txn["transaction_ref"])
                        # Update transaction
                        conn.execute(
                            "UPDATE transactions SET payment_status='COMPLETED', gate_status='OPEN', transaction_ref=? WHERE id=?",
                            (mpesa_ref, txn["id"]),
                        )
                        # Free up the space
                        conn.execute(
                            "UPDATE spaces SET is_occupied=0, plate_number=NULL, driver_phone=NULL, driver_email=NULL, entry_time=NULL WHERE space_number=?",
                            (txn["space_number"],),
                        )
                        print(f"Fixed transaction {txn['id']} - {txn['plate_number']}: COMPLETED")
                    else:
                        print(f"Transaction {txn['id']} still {state}")
        except Exception as e:
            print(f"Error checking transaction {txn['id']}: {e}")

    conn.commit()
    conn.close()
    print("Database updated")

asyncio.run(fix_pending_transactions())