from flask import Blueprint, request, jsonify, session, render_template, redirect, url_for
from database import get_db_connection
from blueprints.auth import login_required
import mysql.connector

patient_bp = Blueprint('patient', __name__)

@patient_bp.route('/dashboard')
@login_required(roles=['patient'])
def dashboard():
    """Render Patient Dashboard with appointments, bills, prescriptions"""
    patient_id = session.get('patient_id')
    user_id = session.get('user_id')
    
    conn = get_db_connection()
    if not conn:
        return "Database Connection Error", 500
        
    try:
        cursor = conn.cursor(dictionary=True)
        
        # 1. Fetch Patient Info
        cursor.execute("""
            SELECT p.id as patient_id, u.name, u.email, u.phone, p.dob, p.gender, p.blood_group, p.address, p.emergency_contact
            FROM patients p
            JOIN users u ON p.user_id = u.id
            WHERE p.id = %s
        """, (patient_id,))
        patient_info = cursor.fetchone()
        
        # 2. Fetch Booked Appointments
        cursor.execute("""
            SELECT a.id, u.name as doctor_name, d.specialization, a.appointment_date, a.start_time, a.end_time, a.status, a.reason
            FROM appointments a
            JOIN doctors d ON a.doctor_id = d.id
            JOIN users u ON d.user_id = u.id
            WHERE a.patient_id = %s
            ORDER BY a.appointment_date DESC, a.start_time DESC
        """, (patient_id,))
        appointments = cursor.fetchall()
        
        # 3. Fetch Billing history
        cursor.execute("""
            SELECT b.id, b.appointment_id, b.consultation_fee, b.medicine_charges, b.total_amount, b.payment_status, b.payment_method, b.billed_at,
                   u.name as doctor_name, a.appointment_date
            FROM billing b
            JOIN appointments a ON b.appointment_id = a.id
            JOIN doctors d ON a.doctor_id = d.id
            JOIN users u ON d.user_id = u.id
            WHERE b.patient_id = %s
            ORDER BY b.billed_at DESC
        """, (patient_id,))
        bills = cursor.fetchall()

        # 4. Fetch Prescriptions
        cursor.execute("""
            SELECT pr.id as prescription_id, pr.appointment_id, pr.diagnosis, pr.status, pr.created_at,
                   u.name as doctor_name, a.appointment_date
            FROM prescriptions pr
            JOIN appointments a ON pr.appointment_id = a.id
            JOIN doctors d ON a.doctor_id = d.id
            JOIN users u ON d.user_id = u.id
            WHERE pr.patient_id = %s
            ORDER BY pr.created_at DESC
        """, (patient_id,))
        prescriptions = cursor.fetchall()
        
        # 5. Fetch Active Doctors list for the booking modal dropdown
        cursor.execute("""
            SELECT d.id as doctor_id, u.name as doctor_name, d.specialization, d.consultation_fee, d.available_days, d.slot_start_time, d.slot_end_time
            FROM doctors d
            JOIN users u ON d.user_id = u.id
            WHERE d.is_active = TRUE
        """)
        doctors = cursor.fetchall()

        # Format times for display in templates
        for app in appointments:
            app['start_time'] = str(app['start_time'])[:5]
            app['end_time'] = str(app['end_time'])[:5]

        for d in doctors:
            d['slot_start_time'] = str(d['slot_start_time'])[:5]
            d['slot_end_time'] = str(d['slot_end_time'])[:5]

        cursor.close()
        conn.close()
        
        return render_template(
            'patient_dashboard.html', 
            patient=patient_info, 
            appointments=appointments, 
            bills=bills, 
            prescriptions=prescriptions,
            doctors=doctors
        )
    except Exception as e:
        if conn:
            conn.close()
        return f"Error loading patient dashboard: {str(e)}", 500


@patient_bp.route('/check-availability', methods=['POST'])
@login_required(roles=['patient'])
def check_availability():
    """Async endpoint to check if doctor is free and available"""
    data = request.get_json() or {}
    doctor_id = data.get('doctor_id')
    date = data.get('appointment_date')
    start_time = data.get('start_time')
    end_time = data.get('end_time')

    if not all([doctor_id, date, start_time, end_time]):
        return jsonify({'success': False, 'message': 'Missing required fields.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection error.'}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        
        # 1. Check doctor's working schedule
        cursor.execute("""
            SELECT available_days, slot_start_time, slot_end_time, is_active
            FROM doctors
            WHERE id = %s
        """, (doctor_id,))
        doc = cursor.fetchone()
        
        if not doc or not doc['is_active']:
            return jsonify({'success': False, 'message': 'Doctor is currently unavailable or inactive.'})

        # Check start/end bounds
        import datetime
        t_start = datetime.datetime.strptime(start_time, "%H:%M").time()
        t_end = datetime.datetime.strptime(end_time, "%H:%M").time()
        
        # Convert DB times
        db_start = (datetime.datetime.min + doc['slot_start_time']).time()
        db_end = (datetime.datetime.min + doc['slot_end_time']).time()

        if t_start < db_start or t_end > db_end:
            return jsonify({
                'success': False, 
                'message': f"Selected slot lies outside doctor availability: {str(doc['slot_start_time'])[:5]} to {str(doc['slot_end_time'])[:5]}"
            })

        # Check weekday availability (DayName)
        app_date_obj = datetime.datetime.strptime(date, "%Y-%m-%d")
        day_str = app_date_obj.strftime("%A")[:3] # e.g. 'Mon'
        if day_str not in doc['available_days']:
            return jsonify({
                'success': False, 
                'message': f"Doctor only practices on: {doc['available_days']}. Chosen date is a {day_str}."
            })

        # 2. Check overlap with existing appointments
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM appointments
            WHERE doctor_id = %s
              AND appointment_date = %s
              AND status NOT IN ('cancelled', 'expired')
              AND (%s < end_time AND %s > start_time)
        """, (doctor_id, date, start_time, end_time))
        overlap = cursor.fetchone()
        cursor.close()
        conn.close()

        if overlap['count'] > 0:
            return jsonify({'success': False, 'message': 'This slot is already booked. Please choose a different time.'})

        return jsonify({'success': True, 'message': 'Slot is available for booking!'})
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500


@patient_bp.route('/book', methods=['POST'])
@login_required(roles=['patient'])
def book_appointment():
    """Create appointment utilizing Database overlapping/availability triggers"""
    patient_id = session.get('patient_id')
    
    data = request.form if request.form else request.get_json()
    doctor_id = data.get('doctor_id')
    appointment_date = data.get('appointment_date')
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    reason = data.get('reason', '').strip()

    if not all([doctor_id, appointment_date, start_time, end_time, reason]):
        return jsonify({'success': False, 'message': 'All fields are required.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection error.'}), 500

    try:
        cursor = conn.cursor()
        # Enforce execution of BEFORE INSERT triggers in database
        cursor.execute("""
            INSERT INTO appointments (patient_id, doctor_id, appointment_date, start_time, end_time, reason, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending')
        """, (patient_id, doctor_id, appointment_date, start_time, end_time, reason))
        
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'message': 'Appointment booked successfully!'})
    except mysql.connector.Error as e:
        if conn:
            conn.rollback()
            conn.close()
        # Check custom trigger error (SQLSTATE 45000)
        if e.sqlstate == '45000':
            return jsonify({'success': False, 'message': e.msg}), 400
        return jsonify({'success': False, 'message': f"Database Trigger Refusal: {e.msg}"}), 500
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500


@patient_bp.route('/prescription/<int:prescription_id>')
@login_required(roles=['patient'])
def view_prescription(prescription_id):
    """View details of a specific prescription, including its medicines"""
    patient_id = session.get('patient_id')
    
    conn = get_db_connection()
    if not conn:
        return "Database Connection Error", 500
        
    try:
        cursor = conn.cursor(dictionary=True)
        # Fetch diagnosis details
        cursor.execute("""
            SELECT pr.id, pr.diagnosis, pr.created_at, u.name as doctor_name, d.specialization
            FROM prescriptions pr
            JOIN doctors d ON pr.doctor_id = d.id
            JOIN users u ON d.user_id = u.id
            WHERE pr.id = %s AND pr.patient_id = %s
        """, (prescription_id, patient_id))
        prescription = cursor.fetchone()
        
        if not prescription:
            cursor.close()
            conn.close()
            return "Prescription not found or access denied.", 404
            
        # Fetch medicines list
        cursor.execute("""
            SELECT m.name as medicine_name, pi.dosage, pi.frequency, pi.duration_days, m.category
            FROM prescription_items pi
            JOIN medicines m ON pi.medicine_id = m.id
            WHERE pi.prescription_id = %s
        """, (prescription_id,))
        items = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'prescription': prescription, 'items': items})
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500


@patient_bp.route('/pay/<int:bill_id>', methods=['POST'])
@login_required(roles=['patient'])
def pay_bill(bill_id):
    """Mock billing payment portal update"""
    patient_id = session.get('patient_id')
    data = request.get_json() or {}
    payment_method = data.get('payment_method', 'card')

    if payment_method not in ['cash', 'card', 'online']:
        return jsonify({'success': False, 'message': 'Invalid payment method.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection error.'}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        # Verify ownership of bill
        cursor.execute("SELECT id, total_amount FROM billing WHERE id = %s AND patient_id = %s", (bill_id, patient_id))
        bill = cursor.fetchone()
        
        if not bill:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Bill not found or unauthorized.'}), 404

        # Update payment status
        cursor.execute("""
            UPDATE billing
            SET payment_status = 'paid', payment_method = %s
            WHERE id = %s
        """, (payment_method, bill_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': f"Payment of ${bill['total_amount']} processed successfully!"})
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500
