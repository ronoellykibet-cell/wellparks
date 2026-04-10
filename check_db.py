import sqlite3

conn = sqlite3.connect('wellparks.db')
cursor = conn.cursor()

# Check total transactions
cursor.execute('SELECT COUNT(*) FROM transactions')
total = cursor.fetchone()[0]
print(f'Total transactions: {total}')

# Check pending transactions
cursor.execute("SELECT COUNT(*) FROM transactions WHERE payment_status='PENDING'")
pending = cursor.fetchone()[0]
print(f'Pending transactions: {pending}')

# Show recent transactions
cursor.execute("SELECT id, plate_number, payment_status, intasend_invoice_id, created_at FROM transactions ORDER BY created_at DESC LIMIT 3")
recent = cursor.fetchall()
print('Recent transactions:')
for row in recent:
    print(row)

conn.close()