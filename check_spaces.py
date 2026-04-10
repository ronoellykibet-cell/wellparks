import sqlite3

conn = sqlite3.connect('wellparks.db')
cursor = conn.cursor()

# Check pending transactions with space info
cursor.execute("""
    SELECT t.id, t.plate_number, t.space_number, t.entry_time, t.exit_time, s.is_occupied, s.plate_number as current_plate
    FROM transactions t
    LEFT JOIN spaces s ON t.space_number = s.space_number
    WHERE t.payment_status='PENDING' AND t.intasend_invoice_id IS NULL
""")
results = cursor.fetchall()

print('Pending transactions without invoice IDs:')
for row in results:
    print(f"ID: {row[0]}, Plate: {row[1]}, Space: {row[2]}, Entry: {row[3]}, Exit: {row[4]}")
    print(f"  Space occupied: {row[5]}, Current plate: {row[6]}")
    print()

conn.close()