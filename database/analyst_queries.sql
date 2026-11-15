-- Analyst queries for output/<dataset>/ap_automation.db (SQLite)

-- 1. Work queues: exceptions and value at risk per owning team
SELECT * FROM exception_queue;

-- 2. Invoices ready to pay, by due date
SELECT invoice_id, vendor_id, stated_total, scheduled_payment_date, payment_method
FROM decisions WHERE payment_ready = 'true'
ORDER BY scheduled_payment_date;

-- 3. Vendors causing the most exceptions
SELECT d.vendor_id, v.vendor_name, COUNT(*) AS exceptions
FROM decisions d JOIN vendors v USING (vendor_id)
WHERE d.exceptions <> ''
GROUP BY d.vendor_id ORDER BY exceptions DESC LIMIT 10;

-- 4. Full audit trail for one invoice
SELECT sequence, event_time, from_state, to_state, actor, reason
FROM invoice_events WHERE invoice_id = 'INV-UNI09-2026-000003'
ORDER BY CAST(sequence AS INTEGER);

-- 5. Duplicate pairs detected
SELECT invoice_id, duplicate_of, vendor_invoice_number, stated_total
FROM decisions WHERE duplicate_of <> '';

-- 6. Which receipt lines each invoice line was matched to (N:M bridge)
SELECT * FROM match_allocations WHERE invoice_id = 'INV-UNI09-2026-000003';
