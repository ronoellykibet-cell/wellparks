import sqlite3

conn = sqlite3.connect('wellparks.db')
cursor = conn.cursor()

# Check all pending transactions
cursor.execute("SELECT id, plate_number, payment_status, intasend_invoice_id, created_at FROM transactions WHERE payment_status='PENDING'")
pending = cursor.fetchall()
print('All pending transactions:')
for row in pending:
    print(row)

# Check if they have invoice IDs
cursor.execute("SELECT id, plate_number, intasend_invoice_id FROM transactions WHERE payment_status='PENDING' AND intasend_invoice_id IS NULL")
no_invoice = cursor.fetchall()
print(f'\nPending transactions without invoice IDs: {len(no_invoice)}')
for row in no_invoice:
    print(row)

conn.close()