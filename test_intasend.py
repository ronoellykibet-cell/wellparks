import os
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

INTASEND_SECRET_KEY = os.environ.get("INTASEND_SECRET_KEY", "")
INTASEND_BASE_URL = os.environ.get("INTASEND_BASE_URL", "https://payment.intasend.com")

async def test_intasend_status(invoice_id):
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{INTASEND_BASE_URL}/api/v1/payment/status/",
                params={"invoice_id": invoice_id},
                headers={"Authorization": f"Bearer {INTASEND_SECRET_KEY}"},
                timeout=10,
            )
            print(f"Status code: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                print(f"Response: {data}")
                state = data.get("invoice", {}).get("state", "").upper()
                print(f"Payment state: {state}")
            else:
                print(f"Error response: {resp.text}")
    except Exception as e:
        print(f"Exception: {e}")

# Test with one of the pending invoice IDs
asyncio.run(test_intasend_status("KO63BWG"))