from flask import Blueprint, request, jsonify, session, render_template, redirect, url_for
from database import get_db_connection
from blueprints.auth import login_required
from blueprints.receptionist import log_audit_action
from werkzeug.security import generate_password_hash
import mysql.connector

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/dashboard')
@login_required(roles=['admin'])
def dashboard():
    """Render Admin Dashboard containing statistics, doctor list, and system audit logs"""
    conn = get_db_connection()
    if not conn:
        return "Database Connection Error", 500

    try:
        cursor = conn.cursor(dictionary=True)

        # 1. Fetch system statistics
        cursor.execute("SELECT COUNT(*) as count FROM patients")
        patients_count = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM doctors")
        doctors_count = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM appointments")
        appointments_count = cursor.fetchone()['count']

        cursor.execute("SELECT IFNULL(SUM(total_amount), 0.00) as sum FROM billing WHERE payment_status = 'paid'")
        total_revenue = cursor.fetchone()['sum']

        # 2. Fetch doctor lists
        cursor.execute("""
            SELECT d.id as doctor_id, u.name, u.email, u.phone, d.specialization, d.qualification, d.experience_years, d.consultation_fee, d.available_days, d.slot_start_time, d.slot_end_time, d.is_active
            FROM doctors d
            JOIN users u ON d.user_id = u.id
            ORDER BY u.name ASC
        """)
        doctors = cursor.fetchall()

        # 3. Fetch audit logs (limited to 50 latest rows)
        cursor.execute("""
            SELECT a.id, u.name as admin_name, u.role, a.action, a.target_type, a.target_id, a.created_at
            FROM audit_logs a
            JOIN users u ON a.admin_id = u.id
            ORDER BY a.created_at DESC
            LIMIT 50
        """)
        audit_logs = cursor.fetchall()

        # Format times
        for d in doctors:
            d['slot_start_time'] = str(d['slot_start_time'])[:5]
            d['slot_end_time'] = str(d['slot_end_time'])[:5]

        cursor.close()
        conn.close()

        return render_template(
            'admin_dashboard.html',
            stats={
                'patients': patients_count,
                'doctors': doctors_count,
                'appointments': appointments_count,
                'revenue': total_revenue
            },
            doctors=doctors,
            logs=audit_logs
        )
    except Exception as e:
        if conn:
            conn.close()
        return f"Error loading admin dashboard: {str(e)}", 500


@admin_bp.route('/doctor/add', methods=['POST'])
@login_required(roles=['admin'])
def add_doctor():
    """Register doctor user and profile in one transaction"""
    admin_user_id = session.get('user_id')
    
    # User inputs
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    phone = request.form.get('phone', '').strip()
    password = request.form.get('password', '')
    
    # Doctor inputs
    specialization = request.form.get('specialization', '').strip()
    qualification = request.form.get('qualification', '').strip()
    experience = int(request.form.get('experience_years', 0))
    fee = float(request.form.get('consultation_fee', 0.00))
    available_days = request.form.get('available_days', '').strip()
    slot_start = request.form.get('slot_start_time')
    slot_end = request.form.get('slot_end_time')

    if not all([name, email, phone, password, specialization, qualification, available_days, slot_start, slot_end]) or experience <= 0 or fee <= 0:
        return jsonify({'success': False, 'message': 'All fields are required and numeric values must be positive.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection error.'}), 500

    try:
        conn.start_transaction()
        cursor = conn.cursor(dictionary=True)

        # Check duplicate email
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Email already registered.'}), 400

        # Insert Doctor User details
        pwd_hash = generate_password_hash(password)
        cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role)
            VALUES (%s, %s, %s, %s, 'doctor')
        """, (name, email, phone, pwd_hash))
        user_id = cursor.lastrowid

        # Insert Doctor profile record
        cursor.execute("""
            INSERT INTO doctors (user_id, specialization, qualification, experience_years, consultation_fee, available_days, slot_start_time, slot_end_time, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
        """, (user_id, specialization, qualification, experience, fee, available_days, slot_start, slot_end))
        doctor_id = cursor.lastrowid

        conn.commit()
        cursor.close()
        conn.close()

        log_audit_action(admin_user_id, f"Added doctor {name}", "doctor", doctor_id)
        return jsonify({'success': True, 'message': 'Doctor profile registered successfully!'})
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500


@admin_bp.route('/doctor/edit/<int:doctor_id>', methods=['POST'])
@login_required(roles=['admin'])
def edit_doctor(doctor_id):
    """Edit doctor profile details"""
    admin_user_id = session.get('user_id')
    data = request.get_json() or {}
    
    specialization = data.get('specialization', '').strip()
    qualification = data.get('qualification', '').strip()
    experience = int(data.get('experience_years', 0))
    fee = float(data.get('consultation_fee', 0.00))
    available_days = data.get('available_days', '').strip()
    slot_start = data.get('slot_start_time')
    slot_end = data.get('slot_end_time')
    is_active = data.get('is_active', True)

    if not all([specialization, qualification, available_days, slot_start, slot_end]) or experience <= 0 or fee <= 0:
        return jsonify({'success': False, 'message': 'All fields are required.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection error.'}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM doctors WHERE id = %s", (doctor_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Doctor not found.'}), 404

        # Update details
        cursor.execute("""
            UPDATE doctors
            SET specialization = %s, qualification = %s, experience_years = %s, consultation_fee = %s, available_days = %s, slot_start_time = %s, slot_end_time = %s, is_active = %s
            WHERE id = %s
        """, (specialization, qualification, experience, fee, available_days, slot_start, slot_end, is_active, doctor_id))
        
        conn.commit()
        cursor.close()
        conn.close()

        log_audit_action(admin_user_id, f"Updated doctor details (ID: {doctor_id})", "doctor", doctor_id)
        return jsonify({'success': True, 'message': 'Doctor profile updated successfully!'})
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500
