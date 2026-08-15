from flask import Blueprint, request, jsonify, session, render_template, redirect, url_for
from database import get_db_connection
from blueprints.auth import login_required
import mysql.connector

doctor_bp = Blueprint('doctor', __name__)

@doctor_bp.route('/dashboard')
@login_required(roles=['doctor'])
def dashboard():
    """Render Doctor Dashboard with profile, upcoming schedule, and past history"""
    doctor_id = session.get('doctor_id')
    user_id = session.get('user_id')
    
    conn = get_db_connection()
    if not conn:
        return "Database Connection Error", 500
        
    try:
        cursor = conn.cursor(dictionary=True)
        
        # 1. Fetch Doctor Profile info
        cursor.execute("""
            SELECT d.id as doctor_id, u.name, u.email, u.phone, d.specialization, d.qualification, d.experience_years, d.consultation_fee, d.available_days, d.slot_start_time, d.slot_end_time
            FROM doctors d
            JOIN users u ON d.user_id = u.id
            WHERE d.id = %s
        """, (doctor_id,))
        doctor_info = cursor.fetchone()
        
        # 2. Fetch Scheduled Appointments (pending/confirmed/cancelled/completed)
        cursor.execute("""
            SELECT a.id, u.name as patient_name, p.dob, p.gender, p.blood_group, a.appointment_date, a.start_time, a.end_time, a.status, a.reason, a.patient_id
            FROM appointments a
            JOIN patients p ON a.patient_id = p.id
            JOIN users u ON p.user_id = u.id
            WHERE a.doctor_id = %s
            ORDER BY a.appointment_date DESC, a.start_time DESC
        """, (doctor_id,))
        appointments = cursor.fetchall()
        
        # 3. Fetch medicines list for the prescription dropdown
        cursor.execute("SELECT id, name, category, unit_price, stock_quantity FROM medicines ORDER BY name")
        medicines = cursor.fetchall()

        # 4. Fetch medicine requests submitted by this doctor
        cursor.execute("""
            SELECT mr.id, mr.request_type, mr.medicine_id, mr.medicine_name, mr.category, mr.manufacturer, mr.quantity_requested, mr.reason, mr.status, mr.requested_at,
                   m.name as existing_med_name
            FROM medicine_requests mr
            LEFT JOIN medicines m ON mr.medicine_id = m.id
            WHERE mr.requested_by = %s
            ORDER BY mr.requested_at DESC
        """, (user_id,))
        requests_history = cursor.fetchall()

        # Format times
        for app in appointments:
            app['start_time'] = str(app['start_time'])[:5]
            app['end_time'] = str(app['end_time'])[:5]
            
        doctor_info['slot_start_time'] = str(doctor_info['slot_start_time'])[:5]
        doctor_info['slot_end_time'] = str(doctor_info['slot_end_time'])[:5]
        
        cursor.close()
        conn.close()
        
        return render_template(
            'doctor_dashboard.html', 
            doctor=doctor_info, 
            appointments=appointments,
            medicines=medicines,
            requests=requests_history
        )
    except Exception as e:
        if conn:
            conn.close()
        return f"Error loading doctor dashboard: {str(e)}", 500


@doctor_bp.route('/diagnose', methods=['POST'])
@login_required(roles=['doctor'])
def diagnose_and_prescribe():
    """Handle appointment completion and prescription generation within a SQL transaction"""
    doctor_id = session.get('doctor_id')
    data = request.get_json() or {}
    
    appointment_id = data.get('appointment_id')
    diagnosis = data.get('diagnosis', '').strip()
    meds = data.get('medicines', []) # Array of dicts: {medicine_id, dosage, frequency, duration_days}

    if not appointment_id or not diagnosis:
        return jsonify({'success': False, 'message': 'Appointment ID and Diagnosis are required.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection error.'}), 500

    try:
        conn.start_transaction()
        cursor = conn.cursor(dictionary=True)
        
        # 1. Verify doctor ownership of appointment and fetch patient_id
        cursor.execute("""
            SELECT id, patient_id, status 
            FROM appointments 
            WHERE id = %s AND doctor_id = %s
        """, (appointment_id, doctor_id))
        app = cursor.fetchone()
        
        if not app:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Appointment not found or unauthorized.'}), 404
            
        if app['status'] == 'completed':
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'This consultation has already been completed.'}), 400

        patient_id = app['patient_id']

        # 2. Insert Prescription record
        cursor.execute("""
            INSERT INTO prescriptions (appointment_id, doctor_id, patient_id, diagnosis, status)
            VALUES (%s, %s, %s, %s, 'active')
        """, (appointment_id, doctor_id, patient_id, diagnosis))
        prescription_id = cursor.lastrowid

        # 3. Insert Prescription Items (this will fire BEFORE INSERT triggers to check stock level)
        for med in meds:
            medicine_id = med.get('medicine_id')
            dosage = med.get('dosage', '').strip()
            frequency = med.get('frequency', '').strip()
            duration_days = int(med.get('duration_days', 0))
            
            if not medicine_id or not dosage or not frequency or duration_days <= 0:
                conn.rollback()
                cursor.close()
                conn.close()
                return jsonify({'success': False, 'message': 'Invalid medicine details. Duration must be greater than 0.'}), 400

            # Execute insert to run check_medicine_stock database trigger
            cursor.execute("""
                INSERT INTO prescription_items (prescription_id, medicine_id, dosage, frequency, duration_days)
                VALUES (%s, %s, %s, %s, %s)
            """, (prescription_id, medicine_id, dosage, frequency, duration_days))

        # 4. Mark Appointment as completed (this will fire generate_billing_on_completion trigger)
        cursor.execute("""
            UPDATE appointments
            SET status = 'completed'
            WHERE id = %s
        """, (appointment_id,))

        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'message': 'Consultation marked completed. Billing & Prescriptions processed successfully!'})
        
    except mysql.connector.Error as e:
        if conn:
            conn.rollback()
            conn.close()
        # Handle database trigger violations (e.g. stock quantities out-of-bounds)
        if e.sqlstate == '45000':
            return jsonify({'success': False, 'message': f"Database Trigger Refusal: {e.msg}"}), 400
        return jsonify({'success': False, 'message': f"Database error: {e.msg}"}), 500
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500


@doctor_bp.route('/request/add', methods=['POST'])
@login_required(roles=['doctor'])
def submit_medicine_request():
    """Submit restock or new medicine request"""
    user_id = session.get('user_id')
    
    # Determine parameters based on request type
    request_type = request.form.get('request_type') # 'restock' or 'new_medicine'
    quantity = request.form.get('quantity_requested')
    reason = request.form.get('reason', '').strip()
    
    if not request_type or not quantity or int(quantity) <= 0:
        return jsonify({'success': False, 'message': 'Request type and valid positive quantity are required.'}), 400
        
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection error.'}), 500
        
    try:
        cursor = conn.cursor()
        
        if request_type == 'restock':
            medicine_id = request.form.get('medicine_id')
            if not medicine_id:
                cursor.close()
                conn.close()
                return jsonify({'success': False, 'message': 'Medicine selection is required for restock.'}), 400
                
            cursor.execute("""
                INSERT INTO medicine_requests (requested_by, request_type, medicine_id, quantity_requested, reason, status)
                VALUES (%s, 'restock', %s, %s, %s, 'pending')
            """, (user_id, medicine_id, quantity, reason))
            
        elif request_type == 'new_medicine':
            med_name = request.form.get('medicine_name', '').strip()
            category = request.form.get('category', '').strip()
            manufacturer = request.form.get('manufacturer', '').strip()
            
            if not med_name or not category or not manufacturer:
                cursor.close()
                conn.close()
                return jsonify({'success': False, 'message': 'New medicine name, category, and manufacturer are required.'}), 400
                
            cursor.execute("""
                INSERT INTO medicine_requests (requested_by, request_type, medicine_name, category, manufacturer, quantity_requested, reason, status)
                VALUES (%s, 'new_medicine', %s, %s, %s, %s, %s, 'pending')
            """, (user_id, med_name, category, manufacturer, quantity, reason))
            
        else:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Invalid request type.'}), 400
            
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'message': 'Medicine request submitted to administrator successfully!'})
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500
