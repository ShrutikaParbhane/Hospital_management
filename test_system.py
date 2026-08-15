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
    restock_req_id = None
    new_med_req_id = None
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

        # Test 5a: Exceed Stock (Try prescribing 200 units, when stock is 5)
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

        # Test 5b: Valid Prescription & Bill Recalculation (Prescribe 3 units)
        cursor.execute("""
            INSERT INTO prescription_items (prescription_id, medicine_id, dosage, frequency, duration_days)
            VALUES (%s, 1, '500mg', 'twice daily', 3)
        """, (test_prescription_id,))
        conn.commit()
        print("  [PASS] Prescribed 3 units of Amoxicillin successfully.")

        # Check stock decremented (Trigger: decrement_stock_and_bill)
        cursor.execute("SELECT stock_quantity FROM medicines WHERE id = 1")
        med_final = cursor.fetchone()
        expected_stock = med_init['stock_quantity'] - 3
        if med_final['stock_quantity'] == expected_stock:
            print(f"  [PASS] Stock decremented to {med_final['stock_quantity']}.")
        else:
            print(f"  [FAIL] Stock not decremented. Expected: {expected_stock}, Found: {med_final['stock_quantity']}")

        # Check billing updated (Trigger: decrement_stock_and_bill)
        cursor.execute("SELECT * FROM billing WHERE appointment_id = %s", (test_appointment_id,))
        updated_bill = cursor.fetchone()
        expected_med_charges = float(med_init['unit_price']) * 3 # 1.50 * 3 = 4.50
        expected_total = 150.00 + expected_med_charges # 154.50
        if updated_bill and float(updated_bill['medicine_charges']) == expected_med_charges and float(updated_bill['total_amount']) == expected_total:
            print(f"  [PASS] Bill charges updated dynamically. medicine_charges = ${updated_bill['medicine_charges']}, total_amount = ${updated_bill['total_amount']}.")
        else:
            print(f"  [FAIL] Bill did not recalculate correctly. Expected med charges: {expected_med_charges}, Total: {expected_total}. Found: {updated_bill}")


        # =======================================================
        # 6. RECEPTIONIST LINK PROFILE TESTS
        # =======================================================
        print("\n[Test 6] Verifying Receptionist Table Linking...")
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
        # 7. MEDICINE RESTOCK TRIGGER TESTS
        # =======================================================
        print("\n[Test 7] Verifying Restock Approval Trigger Cascade...")
        # Get initial stock of Ibuprofen (ID: 2)
        cursor.execute("SELECT stock_quantity FROM medicines WHERE id = 2")
        ibu_init = cursor.fetchone()['stock_quantity']
        
        # Insert a pending request for Ibuprofen restock
        cursor.execute("""
            INSERT INTO medicine_requests (requested_by, request_type, medicine_id, quantity_requested, status)
            VALUES (3, 'restock', 2, 50, 'pending')
        """)
        restock_req_id = cursor.lastrowid
        conn.commit()
        
        # Approve request
        cursor.execute("""
            UPDATE medicine_requests 
            SET status = 'approved', reviewed_by = 1, reviewed_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (restock_req_id,))
        conn.commit()
        
        # Check stock incremented
        cursor.execute("SELECT stock_quantity FROM medicines WHERE id = 2")
        ibu_final = cursor.fetchone()['stock_quantity']
        if ibu_final == ibu_init + 50:
            print(f"  [PASS] Restock approved trigger fired. Stock incremented: {ibu_init} -> {ibu_final}.")
        else:
            print(f"  [FAIL] Failed: Stock not incremented. Expected: {ibu_init + 50}, Found: {ibu_final}.")


        # =======================================================
        # 8. NEW MEDICINE INSERTION TRIGGER TESTS
        # =======================================================
        print("\n[Test 8] Verifying New Medicine Approval Trigger Cascade...")
        # Insert a pending request for New Medicine (Aspirin)
        cursor.execute("""
            INSERT INTO medicine_requests (requested_by, request_type, medicine_name, category, manufacturer, quantity_requested, status)
            VALUES (3, 'new_medicine', 'Aspirin 100mg', 'Analgesic', 'Bayer', 100, 'pending')
        """)
        new_med_req_id = cursor.lastrowid
        conn.commit()
        
        # Approve request
        cursor.execute("""
            UPDATE medicine_requests 
            SET status = 'approved', reviewed_by = 1, reviewed_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (new_med_req_id,))
        conn.commit()
        
        # Verify new medicine row exists in medicines catalog
        cursor.execute("SELECT * FROM medicines WHERE name = 'Aspirin 100mg'")
        new_med_row = cursor.fetchone()
        if new_med_row and new_med_row['stock_quantity'] == 100 and float(new_med_row['unit_price']) == 0.00:
            print(f"  [PASS] New medicine approved trigger fired. Medicine '{new_med_row['name']}' automatically created in catalog with stock {new_med_row['stock_quantity']} and default price $0.00.")
        else:
            print("  [FAIL] Failed: New medicine row was not created correctly.")

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
            if restock_req_id:
                cursor.execute("DELETE FROM medicine_requests WHERE id = %s", (restock_req_id,))
            if new_med_req_id:
                cursor.execute("DELETE FROM medicine_requests WHERE id = %s", (new_med_req_id,))
                cursor.execute("DELETE FROM medicines WHERE name = 'Aspirin 100mg'")
            # Reset stock of Amoxicillin
            cursor.execute("UPDATE medicines SET stock_quantity = 5 WHERE id = 1")
            # Reset stock of Ibuprofen
            cursor.execute("UPDATE medicines SET stock_quantity = 200 WHERE id = 2")
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
