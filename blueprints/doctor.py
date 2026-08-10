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
            medicines=medicines
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
