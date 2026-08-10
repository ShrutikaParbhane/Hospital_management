import mysql.connector
from database import get_db_connection
from werkzeug.security import check_password_hash

def run_tests():
    print("=" * 60)
    print(" RUNNING SYSTEM VERIFICATION SUITE")
    print("=" * 60)

    conn = get_db_connection()
    if not conn:
        print("FAILED: Database connection could not be established.")
        return

    cursor = conn.cursor(dictionary=True)
    test_appointment_id = None
    test_prescription_id = None
    test_patient_id = 1 # Alice Green (PAT-1)
    test_doctor_id = 1  # Dr. Emily Carter (DOC-1, available Mon,Wed,Fri 09:00 - 13:00)

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
        
        # Test 2a: Wrong day of week (Mon,Wed,Fri allowed. Aug 16, 2026 is a Sunday)
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

        # Test 2b: Outside hours bounds (09:00:00 to 13:00:00 allowed. Try 14:00:00 to 15:00:00)
        try:
            cursor.execute("""
                INSERT INTO appointments (patient_id, doctor_id, appointment_date, start_time, end_time, reason, status)
                VALUES (%s, %s, '2026-08-12', '14:00:00', '15:00:00', 'Late visit check', 'pending')
            """, (test_patient_id, test_doctor_id))
            conn.commit()
            print("  [FAIL] Out-of-hours appointment did not trigger error.")
        except mysql.connector.Error as e:
            if e.sqlstate == '45000' and 'availability window' in e.msg:
                print("  [PASS] Out-of-hours slot blocked (Trigger: check_doctor_availability_insert).")
            else:
                print(f"  [FAIL] Unexpected timing block error: {e}")


        # =======================================================
        # 3. DOUBLE-BOOKING PREVENTION TRIGGER TESTS
        # =======================================================
        print("\n[Test 3] Verifying Double-Booking Overlap Triggers...")
        
        # Insert a valid slot (Aug 12, 2026 is a Wednesday, 10:00:00 to 11:00:00)
        cursor.execute("""
            INSERT INTO appointments (patient_id, doctor_id, appointment_date, start_time, end_time, reason, status)
            VALUES (%s, %s, '2026-08-12', '10:00:00', '11:00:00', 'Checkup A', 'pending')
        """, (test_patient_id, test_doctor_id))
        test_appointment_id = cursor.lastrowid
        conn.commit()
        print("  [PASS] Created initial valid appointment slot.")

        # Try to insert overlapping slot (Wednesday, 10:30:00 to 11:30:00)
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
        # 4. AUTO-BILLING CASCADE TESTS
        # =======================================================
        print("\n[Test 4] Verifying Auto-Billing on Completion Cascade...")
        
        # Check initial billing (should not exist for this appointment)
        cursor.execute("SELECT * FROM billing WHERE appointment_id = %s", (test_appointment_id,))
        if cursor.fetchone():
            print("  [FAIL] Billing row exists before completion.")
            
        # Complete appointment
        cursor.execute("UPDATE appointments SET status = 'completed' WHERE id = %s", (test_appointment_id,))
        conn.commit()
        print("  [PASS] Updated appointment status to 'completed'.")

        # Verify billing row created (Trigger: generate_billing_on_completion)
        cursor.execute("SELECT * FROM billing WHERE appointment_id = %s", (test_appointment_id,))
        bill = cursor.fetchone()
        if bill and float(bill['consultation_fee']) == 150.00 and float(bill['total_amount']) == 150.00:
            print(f"  [PASS] Billing row created automatically. consultation_fee = ${bill['consultation_fee']}, total = ${bill['total_amount']}.")
        else:
            print("  [FAIL] Billing row was not created correctly.")


        # =======================================================
        # 5. STOCK LEVEL CONTROL TESTS
        # =======================================================
        print("\n[Test 5] Verifying Inventory Stock Control Triggers...")
        
        # Insert prescription
        cursor.execute("""
            INSERT INTO prescriptions (appointment_id, doctor_id, patient_id, diagnosis, status)
            VALUES (%s, %s, %s, 'Healthy', 'active')
        """, (test_appointment_id, test_doctor_id, test_patient_id))
        test_prescription_id = cursor.lastrowid
        conn.commit()

        # Get initial stock of Amoxicillin (ID: 1)
        cursor.execute("SELECT name, stock_quantity, unit_price FROM medicines WHERE id = 1")
        med_init = cursor.fetchone()
        print(f"  Initial stock of {med_init['name']}: {med_init['stock_quantity']} units.")

        # Test 5a: Exceed Stock (Try prescribing 200 units, when stock is 100)
        try:
            cursor.execute("""
                INSERT INTO prescription_items (prescription_id, medicine_id, dosage, frequency, duration_days)
                VALUES (%s, 1, '500mg', 'three times daily', 200)
            """, (test_prescription_id,))
            conn.commit()
            print("  [FAIL] Allowed prescribing more medicine than available in stock.")
        except mysql.connector.Error as e:
            if e.sqlstate == '45000' and 'Insufficient stock' in e.msg:
                print("  [PASS] Over-limit prescription blocked (Trigger: check_medicine_stock).")
            else:
                print(f"  [FAIL] Unexpected stock check error: {e}")

        # Test 5b: Valid Prescription & Bill Recalculation (Prescribe 10 units)
        cursor.execute("""
            INSERT INTO prescription_items (prescription_id, medicine_id, dosage, frequency, duration_days)
            VALUES (%s, 1, '500mg', 'twice daily', 10)
        """, (test_prescription_id,))
        conn.commit()
        print("  [PASS] Prescribed 10 units of Amoxicillin successfully.")

        # Check stock decremented (Trigger: decrement_stock_and_bill)
        cursor.execute("SELECT stock_quantity FROM medicines WHERE id = 1")
        med_final = cursor.fetchone()
        expected_stock = med_init['stock_quantity'] - 10
        if med_final['stock_quantity'] == expected_stock:
            print(f"  [PASS] Stock decremented to {med_final['stock_quantity']}.")
        else:
            print(f"  [FAIL] Stock not decremented. Expected: {expected_stock}, Found: {med_final['stock_quantity']}")

        # Check billing updated (Trigger: decrement_stock_and_bill)
        cursor.execute("SELECT * FROM billing WHERE appointment_id = %s", (test_appointment_id,))
        updated_bill = cursor.fetchone()
        expected_med_charges = float(med_init['unit_price']) * 10 # 1.50 * 10 = 15.00
        expected_total = 150.00 + expected_med_charges # 165.00
        if updated_bill and float(updated_bill['medicine_charges']) == expected_med_charges and float(updated_bill['total_amount']) == expected_total:
            print(f"  [PASS] Bill charges updated dynamically. medicine_charges = ${updated_bill['medicine_charges']}, total_amount = ${updated_bill['total_amount']}.")
        else:
            print(f"  [FAIL] Bill did not recalculate correctly. Expected med charges: {expected_med_charges}, Total: {expected_total}. Found: {updated_bill}")

    except Exception as ex:
        print(f"TEST SUITE FAILURE: {ex}")
    finally:
        # Clean up test database mutations to keep seed data clean
        print("\nCleaning up test mutations...")
        try:
            if test_prescription_id:
                cursor.execute("DELETE FROM prescription_items WHERE prescription_id = %s", (test_prescription_id,))
                cursor.execute("DELETE FROM prescriptions WHERE id = %s", (test_prescription_id,))
            if test_appointment_id:
                cursor.execute("DELETE FROM billing WHERE appointment_id = %s", (test_appointment_id,))
                cursor.execute("DELETE FROM appointments WHERE id = %s", (test_appointment_id,))
            # Reset stock
            cursor.execute("UPDATE medicines SET stock_quantity = 100 WHERE id = 1")
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
