import mysql.connector
from database import get_db_connection
from werkzeug.security import check_password_hash

def run_tests():
    print("=" * 60)
    print(" RUNNING UNIFIED SINGLE-BILL VERIFICATION SUITE")
    print("=" * 60)

    conn = get_db_connection()
    if not conn:
        print("FAILED: Database connection could not be established.")
        return

    cursor = conn.cursor(dictionary=True)
    test_appointment_id = None
    test_prescription_id = None
    test_prescription_item_id = None
    test_billing_id = None
    test_billing_item_id = None
    restock_req_id = None
    new_med_req_id = None
    test_adjustment_id = None
    expired_med_id = None
    test_expired_adj_id = None
    
    test_patient_id = 1 # Alice Green (PAT-1)
    test_doctor_id = 1  # Dr. Emily Carter (DOC-1)

    try:
        # =======================================================
        # 1. VERIFY SEED USERS LOGIN
        # =======================================================
        print("\n[Test 1] Verifying Seed User Credentials...")
        cursor.execute("SELECT email, password_hash, role FROM users WHERE email = 'admin@hospital.com'")
        admin_user = cursor.fetchone()
        if admin_user and check_password_hash(admin_user['password_hash'], 'admin123'):
            print("  [PASS] Admin credentials match.")
        else:
            print("  [FAIL] Failed: Admin credentials do not match.")

        cursor.execute("SELECT email, password_hash, role FROM users WHERE email = 'alice@gmail.com'")
        patient_user = cursor.fetchone()
        if patient_user and check_password_hash(patient_user['password_hash'], 'patient123'):
            print("  [PASS] Patient credentials match.")
        else:
            print("  [FAIL] Failed: Patient credentials do not match.")


        # =======================================================
        # 2. DOCTOR AVAILABILITY TRIGGER TESTS
        # =======================================================
        print("\n[Test 2] Verifying Doctor Availability Triggers...")
        try:
            cursor.execute("""
                INSERT INTO appointments (patient_id, doctor_id, appointment_date, start_time, end_time, reason, status)
                VALUES (%s, %s, '2026-08-16', '10:00:00', '11:00:00', 'Sunday visit check', 'pending')
            """, (test_patient_id, test_doctor_id))
            conn.commit()
            print("  [FAIL] Wrong weekday appointment did not trigger error.")
        except mysql.connector.Error as e:
            if e.sqlstate == '45000' and 'day of the week' in e.msg:
                print("  [PASS] Wrong weekday blocked (Trigger: check_doctor_availability_insert).")
            else:
                print(f"  [FAIL] Unexpected weekday block error: {e}")


        # =======================================================
        # 3. DOUBLE-BOOKING PREVENTION TRIGGER TESTS
        # =======================================================
        print("\n[Test 3] Verifying Double-Booking Overlap Triggers...")
        cursor.execute("""
            INSERT INTO appointments (patient_id, doctor_id, appointment_date, start_time, end_time, reason, status)
            VALUES (%s, %s, '2026-08-12', '10:00:00', '11:00:00', 'Checkup A', 'pending')
        """, (test_patient_id, test_doctor_id))
        test_appointment_id = cursor.lastrowid
        conn.commit()
        print("  [PASS] Created initial valid appointment slot.")

        try:
            cursor.execute("""
                INSERT INTO appointments (patient_id, doctor_id, appointment_date, start_time, end_time, reason, status)
                VALUES (%s, %s, '2026-08-12', '10:30:00', '11:30:00', 'Checkup B', 'pending')
            """, (test_patient_id, test_doctor_id))
            conn.commit()
            print("  [FAIL] Overlapping appointment did not trigger error.")
        except mysql.connector.Error as e:
            if e.sqlstate == '45000' and 'overlaps' in e.msg:
                print("  [PASS] Overlapping appointment blocked (Trigger: prevent_double_booking_insert).")
            else:
                print(f"  [FAIL] Unexpected overlap error: {e}")


        # =======================================================
        # 4. UNIFIED AUTO-BILLING: BILL CREATION ON COMPLETION
        # =======================================================
        print("\n[Test 4] Verifying Billing Record Creation on Completion...")
        cursor.execute("SELECT * FROM billing WHERE appointment_id = %s", (test_appointment_id,))
        if cursor.fetchone():
            print("  [FAIL] Billing record exists before completion.")
            
        cursor.execute("UPDATE appointments SET status = 'completed' WHERE id = %s", (test_appointment_id,))
        conn.commit()
        print("  [PASS] Updated appointment status to 'completed'.")

        cursor.execute("SELECT * FROM billing WHERE appointment_id = %s", (test_appointment_id,))
        b = cursor.fetchone()
        if b and float(b['consultation_fee']) == 150.00 and float(b['medicine_charges']) == 0.00 and b['payment_status'] == 'pending':
            print(f"  [PASS] billing row created automatically. fee = ${b['consultation_fee']}, medicines = ${b['medicine_charges']}, status = {b['payment_status']}.")
            test_billing_id = b['id']
        else:
            print("  [FAIL] Billing row was not created correctly.")


        # =======================================================
        # 5. SAFETY LOCKS: EXPIRED MEDICINE PREVENTING
        # =======================================================
        print("\n[Test 5] Verifying Expired Medicine safety block...")
        cursor.execute("""
            INSERT INTO prescriptions (appointment_id, doctor_id, patient_id, diagnosis, status)
            VALUES (%s, %s, %s, 'Healthy Check', 'active')
        """, (test_appointment_id, test_doctor_id, test_patient_id))
        test_prescription_id = cursor.lastrowid
        conn.commit()

        # Try prescribing expired medicine (Aspirin ID: 7)
        try:
            cursor.execute("""
                INSERT INTO prescription_items (prescription_id, medicine_id, dosage, frequency, duration_days)
                VALUES (%s, 7, '500mg', 'once daily', 5)
            """, (test_prescription_id,))
            conn.commit()
            print("  [FAIL] Safety check failed. Expired medicine prescription allowed.")
        except mysql.connector.Error as e:
            if e.sqlstate == '45000' and 'expired' in e.msg:
                print("  [PASS] Expired medicine prescription blocked (Trigger: before_prescribe_check_expiry).")
            else:
                print(f"  [FAIL] Unexpected error: {e}")


        # =======================================================
        # 6. UNIFIED PHARMACY BILLING & STOCK CONTROL TRIGGERS
        # =======================================================
        print("\n[Test 6] Verifying Pharmacy Dispensing & Stock Controls...")
        # Get current stock of Amoxicillin (ID: 1)
        cursor.execute("SELECT stock_quantity, unit_price FROM medicines WHERE id = 1")
        med_init = cursor.fetchone()
        
        # Prescribe valid medicine (Amoxicillin ID: 1, 3 units)
        cursor.execute("""
            INSERT INTO prescription_items (prescription_id, medicine_id, dosage, frequency, duration_days)
            VALUES (%s, 1, '500mg', 'twice daily', 3)
        """, (test_prescription_id,))
        test_prescription_item_id = cursor.lastrowid
        conn.commit()
        
        # Verify stock is NOT decremented yet (since prescribing is not dispensing!)
        cursor.execute("SELECT stock_quantity FROM medicines WHERE id = 1")
        stock_after_prescribe = cursor.fetchone()['stock_quantity']
        if stock_after_prescribe == med_init['stock_quantity']:
            print("  [PASS] Stock is not modified on prescription creation.")
        else:
            print("  [FAIL] Stock was modified on prescription write.")

        # Test 6a: Try dispensing quantity exceeding stock
        try:
            cursor.execute("""
                INSERT INTO billing_items (billing_id, prescription_item_id, quantity, unit_price)
                VALUES (%s, %s, 999, 1.50)
            """, (test_billing_id, test_prescription_item_id))
            conn.commit()
            print("  [FAIL] Insufficient stock check did not block dispensing.")
        except mysql.connector.Error as e:
            if e.sqlstate == '45000' and 'Insufficient stock' in e.msg:
                print("  [PASS] Insufficient stock block trigger fired (Trigger: check_pharmacy_stock_before_dispense).")
            else:
                print(f"  [FAIL] Unexpected error: {e}")

        # Test 6b: Dispense valid item
        cursor.execute("""
            INSERT INTO billing_items (billing_id, prescription_item_id, quantity, unit_price)
            VALUES (%s, %s, 3, %s)
        """, (test_billing_id, test_prescription_item_id, med_init['unit_price']))
        test_billing_item_id = cursor.lastrowid
        conn.commit()
        print("  [PASS] Dispensed 3 units of Amoxicillin successfully.")

        # Verify stock decremented
        cursor.execute("SELECT stock_quantity FROM medicines WHERE id = 1")
        med_final = cursor.fetchone()
        if med_final['stock_quantity'] == med_init['stock_quantity'] - 3:
            print(f"  [PASS] Stock decremented to {med_final['stock_quantity']}.")
        else:
            print(f"  [FAIL] Stock not decremented. Expected: {med_init['stock_quantity'] - 3}, Found: {med_final['stock_quantity']}")

        # Verify unified bill updated
        cursor.execute("SELECT medicine_charges, total_amount FROM billing WHERE id = %s", (test_billing_id,))
        updated_b = cursor.fetchone()
        expected_med = float(med_init['unit_price']) * 3 # 1.50 * 3 = 4.50
        expected_total = 150.00 + expected_med
        if updated_b and float(updated_b['medicine_charges']) == expected_med and float(updated_b['total_amount']) == expected_total:
            print(f"  [PASS] Unified bill charges recalculated. medicine_charges = ${updated_b['medicine_charges']}, total_amount = ${updated_b['total_amount']}.")
        else:
            print(f"  [FAIL] Total amount not updated correctly. Expected: med={expected_med}, tot={expected_total}, Found: {updated_b}")


        # =======================================================
        # 7. RECEPTIONIST LINK PROFILE
        # =======================================================
        print("\n[Test 7] Verifying Receptionist Table Linking...")
        cursor.execute("""
            SELECT r.employee_code, r.shift, u.name 
            FROM receptionists r 
            JOIN users u ON r.user_id = u.id 
            WHERE u.email = 'receptionist@hospital.com'
        """)
        rec_profile = cursor.fetchone()
        if rec_profile and rec_profile['employee_code'] == 'EMP-REC01' and rec_profile['shift'] == 'morning':
            print(f"  [PASS] Receptionist profile linked. Employee: {rec_profile['name']}, Code: {rec_profile['employee_code']}, Shift: {rec_profile['shift']}.")
        else:
            print("  [FAIL] Failed: Receptionist profile linked lookup error.")


        # =======================================================
        # 8. MEDICINE RESTOCK & CATALOG TRIGGER TESTS
        # =======================================================
        print("\n[Test 8] Verifying Request Restock and Catalog triggers...")
        cursor.execute("""
            INSERT INTO medicine_requests (requested_by, request_type, medicine_id, quantity_requested, status)
            VALUES (3, 'restock', 2, 25, 'pending')
        """)
        restock_req_id = cursor.lastrowid
        conn.commit()
        
        cursor.execute("SELECT stock_quantity FROM medicines WHERE id = 2")
        ibu_init = cursor.fetchone()['stock_quantity']
        
        cursor.execute("UPDATE medicine_requests SET status = 'approved', reviewed_by = 1, reviewed_at = CURRENT_TIMESTAMP WHERE id = %s", (restock_req_id,))
        conn.commit()
        
        cursor.execute("SELECT stock_quantity FROM medicines WHERE id = 2")
        ibu_final = cursor.fetchone()['stock_quantity']
        if ibu_final == ibu_init + 25:
            print(f"  [PASS] Restock approved trigger fired. Stock: {ibu_init} -> {ibu_final}.")
        else:
            print(f"  [FAIL] Failed: Stock not incremented.")


        # =======================================================
        # 9. MANUAL STOCK ADJUSTMENTS CASCADE
        # =======================================================
        print("\n[Test 9] Verifying Manual Stock Adjustment Logs & Triggers...")
        cursor.execute("SELECT stock_quantity FROM medicines WHERE id = 3")
        para_init = cursor.fetchone()['stock_quantity']

        # Insert manual stock adjustment
        cursor.execute("""
            INSERT INTO stock_adjustments (medicine_id, admin_id, adjustment_type, quantity_removed, reason)
            VALUES (3, 1, 'damaged', 10, 'Broken container glass')
        """)
        test_adjustment_id = cursor.lastrowid
        conn.commit()
        print("  [PASS] Logged manual stock adjustment of removing 10 units.")

        # Check stock decremented (Trigger: after_stock_adjustment_deduct)
        cursor.execute("SELECT stock_quantity FROM medicines WHERE id = 3")
        para_final = cursor.fetchone()['stock_quantity']
        if para_final == para_init - 10:
            print(f"  [PASS] Manual stock adjustment trigger fired. Stock: {para_init} -> {para_final}.")
        else:
            print(f"  [FAIL] Failed: Stock not decremented on manual adjustment.")

        # =======================================================
        # 10. AUTO-REMOVE EXPIRED STOCK EVENT LOGIC
        # =======================================================
        print("\n[Test 10] Verifying Expired Stock Auto-Removal Event logic...")
        # Create an expired medicine temporarily
        cursor.execute("""
            INSERT INTO medicines (name, manufacturer, category, unit_price, stock_quantity, reorder_level, expiry_date)
            VALUES ('Test Expired Pill', 'TestLab', 'Analgesic', 1.00, 50, 5, '2020-01-01')
        """)
        expired_med_id = cursor.lastrowid
        conn.commit()
        print(f"  [PASS] Inserted temporary expired medicine with stock = 50.")
        
        # Run the EVENT statements simulating cursor fire
        cursor.execute("SELECT id, stock_quantity, expiry_date FROM medicines WHERE id = %s", (expired_med_id,))
        med_row = cursor.fetchone()
        
        cursor.execute("""
            INSERT INTO stock_adjustments (medicine_id, admin_id, adjustment_type, quantity_removed, reason)
            VALUES (%s, NULL, 'expired_removal', %s, CONCAT('Auto-removed: expired on ', %s))
        """, (med_row['id'], med_row['stock_quantity'], med_row['expiry_date']))
        conn.commit()
        print("  [PASS] Simulated auto_remove_expired_medicine event execution using cursor-equivalent sequence.")

        # Verify stock was zeroed out via trigger
        cursor.execute("SELECT stock_quantity FROM medicines WHERE id = %s", (expired_med_id,))
        p_stock = cursor.fetchone()['stock_quantity']
        if p_stock == 0:
            print("  [PASS] Medicine stock successfully zeroed out.")
        else:
            print(f"  [FAIL] Failed: Stock is not zero. Found: {p_stock}")
            
        # Verify the adjustment log is created with admin_id as NULL
        cursor.execute("SELECT * FROM stock_adjustments WHERE medicine_id = %s", (expired_med_id,))
        adj_log = cursor.fetchone()
        if adj_log and adj_log['admin_id'] is None and adj_log['adjustment_type'] == 'expired_removal':
            print("  [PASS] Correct system adjustment log created with admin_id = NULL.")
            test_expired_adj_id = adj_log['id']
        else:
            print(f"  [FAIL] Failed: Adjustment log check. Found: {adj_log}")

    except Exception as ex:
        print(f"TEST SUITE FAILURE: {ex}")
    finally:
        print("\nCleaning up test mutations...")
        try:
            if test_billing_item_id:
                cursor.execute("DELETE FROM billing_items WHERE id = %s", (test_billing_item_id,))
            if test_billing_id:
                cursor.execute("DELETE FROM billing WHERE id = %s", (test_billing_id,))
            if test_prescription_item_id:
                cursor.execute("DELETE FROM prescription_items WHERE id = %s", (test_prescription_item_id,))
            if test_prescription_id:
                cursor.execute("DELETE FROM prescriptions WHERE id = %s", (test_prescription_id,))
            if test_appointment_id:
                cursor.execute("DELETE FROM billing WHERE appointment_id = %s", (test_appointment_id,))
                cursor.execute("DELETE FROM appointments WHERE id = %s", (test_appointment_id,))
            if restock_req_id:
                cursor.execute("DELETE FROM medicine_requests WHERE id = %s", (restock_req_id,))
            if new_med_req_id:
                cursor.execute("DELETE FROM medicine_requests WHERE id = %s", (new_med_req_id,))
            if test_adjustment_id:
                cursor.execute("DELETE FROM stock_adjustments WHERE id = %s", (test_adjustment_id,))
            if test_expired_adj_id:
                cursor.execute("DELETE FROM stock_adjustments WHERE id = %s", (test_expired_adj_id,))
            if expired_med_id:
                cursor.execute("DELETE FROM medicines WHERE id = %s", (expired_med_id,))
            # Reset stock quantities
            cursor.execute("UPDATE medicines SET stock_quantity = 5 WHERE id = 1")
            cursor.execute("UPDATE medicines SET stock_quantity = 200 WHERE id = 2")
            cursor.execute("UPDATE medicines SET stock_quantity = 500 WHERE id = 3")
            conn.commit()
            print("Clean up completed.")
        except Exception as clean_ex:
            print(f"Clean up failed: {clean_ex}")
        
        cursor.close()
        conn.close()
        print("\n" + "=" * 60)
        print(" VERIFICATION SUITE FINISHED")
        print("=" * 60)

if __name__ == '__main__':
    run_tests()
