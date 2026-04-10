import sqlite3

conn = sqlite3.connect('wellparks.db')
cursor = conn.cursor()

# Mark old pending transactions as FAILED and free spaces
cursor.execute("""
    UPDATE transactions
    SET payment_status='FAILED', gate_status='CLOSED'
    WHERE payment_status='PENDING' AND intasend_invoice_id IS NULL
""")

# Free up the spaces
cursor.execute("""
    UPDATE spaces
    SET is_occupied=0, plate_number=NULL, driver_phone=NULL, driver_email=NULL, entry_time=NULL
    WHERE space_number IN (
        SELECT DISTINCT space_number
        FROM transactions
        WHERE payment_status='FAILED' AND intasend_invoice_id IS NULL
    )
""")

conn.commit()

# Check results
cursor.execute("SELECT COUNT(*) FROM transactions WHERE payment_status='PENDING'")
pending_count = cursor.fetchone()[0]
print(f"Remaining pending transactions: {pending_count}")

cursor.execute("SELECT COUNT(*) FROM spaces WHERE is_occupied=1")
occupied_count = cursor.fetchone()[0]
print(f"Occupied spaces: {occupied_count}")

conn.close()
print("Old pending transactions marked as FAILED and spaces freed.")