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

        cursor.execute("""
            SELECT 
                (SELECT IFNULL(SUM(consultation_fee), 0.00) FROM consultation_bills WHERE payment_status = 'paid') + 
                (SELECT IFNULL(SUM(total_amount), 0.00) FROM pharmacy_bills WHERE payment_status = 'paid') as sum
        """)
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

        # 4. Fetch receptionist lists
        cursor.execute("""
            SELECT r.id as receptionist_id, u.name, u.email, u.phone, r.employee_code, r.shift, r.is_active
            FROM receptionists r
            JOIN users u ON r.user_id = u.id
            ORDER BY u.name ASC
        """)
        receptionists = cursor.fetchall()

        # 5. Fetch low-stock medicines
        cursor.execute("""
            SELECT id, name, category, manufacturer, unit_price, stock_quantity, reorder_level, expiry_date
            FROM medicines
            WHERE stock_quantity <= reorder_level
            ORDER BY stock_quantity ASC
        """)
        low_stock = cursor.fetchall()

        # 6. Fetch doctor medicine requests
        cursor.execute("""
            SELECT mr.id, mr.request_type, mr.medicine_id, mr.medicine_name, mr.category, mr.manufacturer, mr.quantity_requested, mr.reason, mr.status, mr.requested_at,
                   u.name as doctor_name, m.name as existing_med_name
            FROM medicine_requests mr
            JOIN users u ON mr.requested_by = u.id
            LEFT JOIN medicines m ON mr.medicine_id = m.id
            ORDER BY mr.status = 'pending' DESC, mr.requested_at DESC
        """)
        requests = cursor.fetchall()

        # 7. Fetch all medicines in catalog
        cursor.execute("SELECT id, name, category, manufacturer, unit_price, stock_quantity, reorder_level, expiry_date FROM medicines ORDER BY name")
        all_medicines = cursor.fetchall()

        # 8. Fetch expiring medicines alerts (View)
        cursor.execute("SELECT id, name, category, manufacturer, stock_quantity, expiry_date, days_to_expiry FROM expiring_medicines_alert ORDER BY days_to_expiry ASC")
        expiring_medicines = cursor.fetchall()

        # 9. Fetch stock adjustments history
        cursor.execute("""
            SELECT sa.id, sa.adjustment_type, sa.quantity_removed, sa.reason, sa.created_at, m.name as medicine_name, u.name as admin_name
            FROM stock_adjustments sa
            JOIN medicines m ON sa.medicine_id = m.id
            JOIN users u ON sa.admin_id = u.id
            ORDER BY sa.created_at DESC
            LIMIT 20
        """)
        stock_adjustments = cursor.fetchall()

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
            receptionists=receptionists,
            low_stock=low_stock,
            expiring_medicines=expiring_medicines,
            stock_adjustments=stock_adjustments,
            requests=requests,
            medicines=all_medicines,
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


@admin_bp.route('/receptionist/add', methods=['POST'])
@login_required(roles=['admin'])
def add_receptionist():
    """Register receptionist user and profile in one transaction"""
    admin_user_id = session.get('user_id')
    
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    phone = request.form.get('phone', '').strip()
    password = request.form.get('password', '')
    employee_code = request.form.get('employee_code', '').strip()
    shift = request.form.get('shift', '')

    if not all([name, email, phone, password, employee_code, shift]):
        return jsonify({'success': False, 'message': 'All fields are required.'}), 400

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

        # Check duplicate employee code
        cursor.execute("SELECT id FROM receptionists WHERE employee_code = %s", (employee_code,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Employee code already exists.'}), 400

        # Insert user
        pwd_hash = generate_password_hash(password)
        cursor.execute("""
            INSERT INTO users (name, email, phone, password_hash, role)
            VALUES (%s, %s, %s, %s, 'receptionist')
        """, (name, email, phone, pwd_hash))
        user_id = cursor.lastrowid

        # Insert receptionist profile
        cursor.execute("""
            INSERT INTO receptionists (user_id, employee_code, shift, created_by, is_active)
            VALUES (%s, %s, %s, %s, TRUE)
        """, (user_id, employee_code, shift, admin_user_id))
        receptionist_id = cursor.lastrowid

        conn.commit()
        cursor.close()
        conn.close()

        log_audit_action(admin_user_id, f"Added receptionist {name}", "receptionist", receptionist_id)
        return jsonify({'success': True, 'message': 'Receptionist registered successfully!'})
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500


@admin_bp.route('/request/review/<int:request_id>', methods=['POST'])
@login_required(roles=['admin'])
def review_medicine_request(request_id):
    """Approve or reject a doctor's medicine request (fires database triggers)"""
    admin_user_id = session.get('user_id')
    data = request.get_json() or {}
    action = data.get('action') # 'approved' or 'rejected'

    if action not in ['approved', 'rejected']:
        return jsonify({'success': False, 'message': 'Invalid action. Must be approved or rejected.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection error.'}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT status FROM medicine_requests WHERE id = %s", (request_id,))
        req = cursor.fetchone()

        if not req:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Medicine request not found.'}), 404

        if req['status'] != 'pending':
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'This request has already been reviewed.'}), 400

        # Update status - this will fire after_restock_approved or after_new_medicine_approved triggers!
        cursor.execute("""
            UPDATE medicine_requests
            SET status = %s, reviewed_by = %s, reviewed_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (action, admin_user_id, request_id))

        conn.commit()
        cursor.close()
        conn.close()

        log_audit_action(admin_user_id, f"Reviewed medicine request ID {request_id} to status: {action}", "medicine_request", request_id)
        return jsonify({'success': True, 'message': f'Request successfully {action}!'})
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500


@admin_bp.route('/medicine/edit/<int:med_id>', methods=['POST'])
@login_required(roles=['admin'])
def edit_medicine_price(med_id):
    """Edit medicine price or reorder level"""
    admin_user_id = session.get('user_id')
    data = request.get_json() or {}
    unit_price = float(data.get('unit_price', 0.00))
    reorder_level = int(data.get('reorder_level', 10))

    if unit_price < 0 or reorder_level < 0:
        return jsonify({'success': False, 'message': 'Invalid numeric values.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection error.'}), 500

    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE medicines
            SET unit_price = %s, reorder_level = %s
            WHERE id = %s
        """, (unit_price, reorder_level, med_id))
        conn.commit()
        cursor.close()
        conn.close()

        log_audit_action(admin_user_id, f"Updated medicine price/reorder for ID {med_id}", "medicine", med_id)
        return jsonify({'success': True, 'message': 'Medicine details updated successfully!'})
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500


@admin_bp.route('/inventory/adjust', methods=['POST'])
@login_required(roles=['admin'])
def adjust_inventory():
    """Manual adjustment / removal of expired or damaged stock by administrator"""
    admin_user_id = session.get('user_id')
    data = request.form if request.form else request.get_json()
    
    medicine_id = data.get('medicine_id')
    adjustment_type = data.get('adjustment_type')
    quantity_removed = data.get('quantity_removed')
    reason = data.get('reason', '').strip()

    if not all([medicine_id, adjustment_type, quantity_removed]):
        return jsonify({'success': False, 'message': 'Missing required fields.'}), 400

    try:
        medicine_id = int(medicine_id)
        quantity_removed = int(quantity_removed)
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid numeric inputs.'}), 400

    if quantity_removed <= 0:
        return jsonify({'success': False, 'message': 'Quantity must be greater than zero.'}), 400

    if adjustment_type not in ['expired_removal', 'damaged', 'correction']:
        return jsonify({'success': False, 'message': 'Invalid adjustment type.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection error.'}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        
        # Verify current stock level to prevent adjusting more than available
        cursor.execute("SELECT stock_quantity, name FROM medicines WHERE id = %s", (medicine_id,))
        med = cursor.fetchone()
        if not med:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Medicine not found.'}), 404
            
        if med['stock_quantity'] < quantity_removed:
            cursor.close()
            conn.close()
            return jsonify({
                'success': False, 
                'message': f"Cannot adjust/remove {quantity_removed} units. Current catalog stock of '{med['name']}' is only {med['stock_quantity']} units."
            }), 400

        # Log adjustment (this runs after_stock_adjustment_deduct trigger to update inventory)
        cursor.execute("""
            INSERT INTO stock_adjustments (medicine_id, admin_id, adjustment_type, quantity_removed, reason)
            VALUES (%s, %s, %s, %s, %s)
        """, (medicine_id, admin_user_id, adjustment_type, quantity_removed, reason))
        adjustment_id = cursor.lastrowid
        
        conn.commit()
        cursor.close()
        conn.close()
        
        log_audit_action(admin_user_id, f"Recorded manual stock adjustment (removed {quantity_removed} units of {med['name']})", "stock_adjustment", adjustment_id)
        return jsonify({'success': True, 'message': 'Inventory adjustment logged and catalog updated successfully!'})
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500
