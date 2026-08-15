from flask import Blueprint, request, jsonify, session, render_template, redirect, url_for
from database import get_db_connection
from blueprints.auth import login_required
from werkzeug.security import generate_password_hash
import mysql.connector

receptionist_bp = Blueprint('receptionist', __name__)

def log_audit_action(admin_id, action, target_type, target_id):
    """Helper to log receptionist/admin actions to audit_logs"""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO audit_logs (admin_id, action, target_type, target_id)
            VALUES (%s, %s, %s, %s)
        """, (admin_id, action, target_type, target_id))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Audit log error: {e}")
        if conn:
            conn.close()
        return False


@receptionist_bp.route('/dashboard')
@login_required(roles=['receptionist'])
def dashboard():
    """Render Receptionist Dashboard containing billing lists, walk-in register, pending confirmations, and dispensing console"""
    receptionist_id = session.get('receptionist_id')
    conn = get_db_connection()
    if not conn:
        return "Database Connection Error", 500

    try:
        cursor = conn.cursor(dictionary=True)

        # 0. Fetch Receptionist Profile Info
        cursor.execute("""
            SELECT r.id as receptionist_id, r.employee_code, r.shift, u.name, u.email, u.phone
            FROM receptionists r
            JOIN users u ON r.user_id = u.id
            WHERE r.id = %s
        """, (receptionist_id,))
        receptionist_info = cursor.fetchone()

        # 1. Fetch pending appointments
        cursor.execute("""
            SELECT a.id, pu.name as patient_name, du.name as doctor_name, d.specialization, a.appointment_date, a.start_time, a.end_time, a.status, a.reason
            FROM appointments a
            JOIN patients p ON a.patient_id = p.id
            JOIN users pu ON p.user_id = pu.id
            JOIN doctors d ON a.doctor_id = d.id
            JOIN users du ON d.user_id = du.id
            WHERE a.status = 'pending'
            ORDER BY a.appointment_date ASC, a.start_time ASC
        """)
        pending_appointments = cursor.fetchall()

        # 2a. Fetch Unified Bills
        cursor.execute("""
            SELECT b.id, pu.name as patient_name, du.name as doctor_name, a.appointment_date, b.consultation_fee, b.medicine_charges, b.total_amount, b.payment_status, b.payment_method, b.billed_at
            FROM billing b
            JOIN appointments a ON b.appointment_id = a.id
            JOIN patients p ON a.patient_id = p.id
            JOIN users pu ON p.user_id = pu.id
            JOIN doctors d ON a.doctor_id = d.id
            JOIN users du ON d.user_id = du.id
            ORDER BY b.billed_at DESC
        """)
        bills = cursor.fetchall()

        # 2c. Fetch Prescriptions for dispensing
        cursor.execute("""
            SELECT pr.id as prescription_id, pr.appointment_id, pu.name as patient_name, du.name as doctor_name, pr.diagnosis, pr.created_at,
                   (SELECT COUNT(*) FROM prescription_items WHERE prescription_id = pr.id AND dispensed = FALSE) as undispensed_count
            FROM prescriptions pr
            JOIN appointments a ON pr.appointment_id = a.id
            JOIN patients p ON pr.patient_id = p.id
            JOIN users pu ON p.user_id = pu.id
            JOIN doctors d ON pr.doctor_id = d.id
            JOIN users du ON d.user_id = du.id
            ORDER BY pr.created_at DESC
        """)
        prescriptions = cursor.fetchall()

        # 3. Fetch active doctors list for walk-in appointment scheduling
        cursor.execute("""
            SELECT d.id as doctor_id, u.name as doctor_name, d.specialization
            FROM doctors d
            JOIN users u ON d.user_id = u.id
            WHERE d.is_active = TRUE
        """)
        doctors = cursor.fetchall()

        # Format times
        for app in pending_appointments:
            app['start_time'] = str(app['start_time'])[:5]
            app['end_time'] = str(app['end_time'])[:5]

        cursor.close()
        conn.close()

        return render_template(
            'receptionist_dashboard.html',
            receptionist=receptionist_info,
            pending=pending_appointments,
            bills=bills,
            prescriptions=prescriptions,
            doctors=doctors
        )
    except Exception as e:
        if conn:
            conn.close()
        return f"Error loading receptionist dashboard: {str(e)}", 500


@receptionist_bp.route('/confirm/<int:appointment_id>', methods=['POST'])
@login_required(roles=['receptionist'])
def confirm_appointment(appointment_id):
    """Confirm a pending appointment and log audit action"""
    receptionist_user_id = session.get('user_id')

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection error.'}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        # Fetch current status
        cursor.execute("SELECT status FROM appointments WHERE id = %s", (appointment_id,))
        app = cursor.fetchone()
        
        if not app:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Appointment not found.'}), 404
            
        if app['status'] != 'pending':
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': f'Appointment status is {app["status"]}; cannot confirm.'}), 400

        cursor.execute("UPDATE appointments SET status = 'confirmed' WHERE id = %s", (appointment_id,))
        conn.commit()
        cursor.close()
        conn.close()

        log_audit_action(receptionist_user_id, "Confirmed appointment", "appointment", appointment_id)
        return jsonify({'success': True, 'message': 'Appointment confirmed successfully!'})
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500


@receptionist_bp.route('/bill/pay/<int:bill_id>', methods=['POST'])
@login_required(roles=['receptionist'])
def record_payment(bill_id):
    """Mark a pending bill as paid"""
    receptionist_user_id = session.get('user_id')
    data = request.get_json() or {}
    payment_method = data.get('payment_method', 'cash')

    if payment_method not in ['cash', 'card', 'online']:
        return jsonify({'success': False, 'message': 'Invalid payment method.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection error.'}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT payment_status FROM billing WHERE id = %s", (bill_id,))
        bill = cursor.fetchone()
        if not bill:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Bill not found.'}), 404
        if bill['payment_status'] == 'paid':
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Bill is already paid.'}), 400
            
        cursor.execute("""
            UPDATE billing
            SET payment_status = 'paid', payment_method = %s
            WHERE id = %s
        """, (payment_method, bill_id))
            
        conn.commit()
        cursor.close()
        conn.close()

        log_audit_action(receptionist_user_id, "Settled payment invoice", "billing", bill_id)
        return jsonify({'success': True, 'message': 'Invoice marked as paid successfully!'})
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500


@receptionist_bp.route('/prescription/<int:prescription_id>/items')
@login_required(roles=['receptionist'])
def get_prescription_items(prescription_id):
    """Fetch items for dispensing console"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection error.'}), 500
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT pi.id, m.name as medicine_name, pi.dosage, pi.frequency, pi.duration_days, 
                   m.unit_price, m.stock_quantity, pi.dispensed, m.expiry_date
            FROM prescription_items pi
            JOIN medicines m ON pi.medicine_id = m.id
            WHERE pi.prescription_id = %s
        """, (prescription_id,))
        items = cursor.fetchall()
        
        # Check if medicine is expired
        import datetime
        today = datetime.date.today()
        for item in items:
            item['is_expired'] = (item['expiry_date'] < today)
            item['expiry_date'] = str(item['expiry_date'])
            
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'items': items})
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500


@receptionist_bp.route('/dispense/<int:prescription_id>', methods=['POST'])
@login_required(roles=['receptionist'])
def dispense_prescription(prescription_id):
    """Dispense selected prescription items, link to unified billing, deduct inventory"""
    receptionist_user_id = session.get('user_id')
    data = request.get_json() or {}
    item_ids = data.get('item_ids', [])
    
    if not item_ids:
        return jsonify({'success': False, 'message': 'No items selected for dispensing.'}), 400
        
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection error.'}), 500
        
    try:
        conn.start_transaction()
        cursor = conn.cursor(dictionary=True)
        
        # 1. Fetch prescription information
        cursor.execute("SELECT patient_id, appointment_id FROM prescriptions WHERE id = %s", (prescription_id,))
        prescription = cursor.fetchone()
        if not prescription:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Prescription not found.'}), 404
            
        patient_id = prescription['patient_id']
        appointment_id = prescription['appointment_id']
        
        # 2. Get billing row
        cursor.execute("SELECT id FROM billing WHERE appointment_id = %s", (appointment_id,))
        bill = cursor.fetchone()
        if not bill:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Associated appointment bill not found.'}), 404
            
        billing_id = bill['id']
            
        # 3. Dispense selected items
        for item_id in item_ids:
            cursor.execute("""
                SELECT pi.id, pi.medicine_id, pi.duration_days as quantity, m.unit_price, pi.dispensed
                FROM prescription_items pi
                JOIN medicines m ON pi.medicine_id = m.id
                WHERE pi.id = %s AND pi.prescription_id = %s
            """, (item_id, prescription_id))
            item = cursor.fetchone()
            
            if not item:
                raise Exception(f"Invalid prescription item ID: {item_id}.")
            if item['dispensed']:
                raise Exception("Item has already been dispensed.")
                
            # Insert into billing_items (triggers decrement_stock_on_dispense, check_pharmacy_stock_before_dispense, and after_billing_item_insert)
            cursor.execute("""
                INSERT INTO billing_items (billing_id, prescription_item_id, quantity, unit_price)
                VALUES (%s, %s, %s, %s)
            """, (billing_id, item['id'], item['quantity'], item['unit_price']))
            
            # Update prescription_items status to dispensed
            cursor.execute("UPDATE prescription_items SET dispensed = TRUE WHERE id = %s", (item_id,))
            
        conn.commit()
        cursor.close()
        conn.close()
        
        log_audit_action(receptionist_user_id, "Dispensed prescription items", "prescription", prescription_id)
        return jsonify({'success': True, 'message': 'Medicines dispensed and billed successfully!'})
    except mysql.connector.Error as e:
        if conn:
            conn.rollback()
            conn.close()
        if e.sqlstate == '45000':
            return jsonify({'success': False, 'message': f"Safety Error: {e.msg}"}), 400
        return jsonify({'success': False, 'message': f"Database error: {e.msg}"}), 500
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500


@receptionist_bp.route('/walk-in', methods=['POST'])
@login_required(roles=['receptionist'])
def register_walk_in():
    """Register patient and book appointment in one transaction"""
    receptionist_user_id = session.get('user_id')
    
    # Patient fields
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    phone = request.form.get('phone', '').strip()
    dob = request.form.get('dob', '')
    gender = request.form.get('gender', '')
    blood_group = request.form.get('blood_group', '').strip()
    address = request.form.get('address', '').strip()
    emergency_contact = request.form.get('emergency_contact', '').strip()
    
    # Booking fields
    doctor_id = request.form.get('doctor_id')
    appointment_date = request.form.get('appointment_date')
    start_time = request.form.get('start_time')
    end_time = request.form.get('end_time')
    reason = request.form.get('reason', '').strip()

    if not all([name, email, phone, dob, gender, blood_group, address, emergency_contact, doctor_id, appointment_date, start_time, end_time, reason]):
        return jsonify({'success': False, 'message': 'All fields are required.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection error.'}), 500

    try:
        conn.start_transaction()
        cursor = conn.cursor(dictionary=True)

        # 1. Create Patient User (check duplicate email first)
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Email is already registered.'}), 400

        # Generate a default password for walk-ins
        default_pwd_hash = generate_password_hash('patient123')
        cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role)
            VALUES (%s, %s, %s, %s, 'patient')
        """, (name, email, phone, default_pwd_hash))
        user_id = cursor.lastrowid

        # 2. Insert Patient record
        cursor.execute("""
            INSERT INTO patients (user_id, dob, gender, blood_group, address, emergency_contact)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, dob, gender, blood_group, address, emergency_contact))
        patient_id = cursor.lastrowid

        # 3. Create Appointment (runs BEFORE INSERT triggers on appointments)
        cursor.execute("""
            INSERT INTO appointments (patient_id, doctor_id, appointment_date, start_time, end_time, reason, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'confirmed')
        """, (patient_id, doctor_id, appointment_date, start_time, end_time, reason))
        appointment_id = cursor.lastrowid

        conn.commit()
        cursor.close()
        conn.close()

        # Log audit action
        log_audit_action(receptionist_user_id, "Registered walk-in & booked slot", "patient", patient_id)
        return jsonify({'success': True, 'message': 'Walk-in patient registered and appointment booked successfully!'})
    except mysql.connector.Error as e:
        if conn:
            conn.rollback()
            conn.close()
        # Handle database availability or double-booking trigger rejection
        if e.sqlstate == '45000':
            return jsonify({'success': False, 'message': f"Database Trigger Refusal: {e.msg}"}), 400
        return jsonify({'success': False, 'message': f"Database error: {e.msg}"}), 500
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500
