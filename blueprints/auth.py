from flask import Blueprint, request, jsonify, session, render_template, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_connection
from functools import wraps

auth_bp = Blueprint('auth', __name__)

# login_required decorator helper
def login_required(roles=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('auth.login_page'))
            if roles and session.get('user_role') not in roles:
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@auth_bp.route('/login-page')
def login_page():
    """Render unified login page"""
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

@auth_bp.route('/register-page')
def register_page():
    """Render patient registration page"""
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('register.html')

@auth_bp.route('/login', methods=['POST'])
def login():
    """Handle unified login credentials check and redirect based on role"""
    data = request.form if request.form else request.get_json()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password are required.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection error.'}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, email, password_hash, role FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if not user or not check_password_hash(user['password_hash'], password):
            return jsonify({'success': False, 'message': 'Invalid email or password.'}), 401

        # Store user info in session
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        session['user_role'] = user['role']
        session['user_email'] = user['email']

        # Query and store role-specific entity ID
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        if user['role'] == 'patient':
            cursor.execute("SELECT id FROM patients WHERE user_id = %s", (user['id'],))
            row = cursor.fetchone()
            if row:
                session['patient_id'] = row['id']
        elif user['role'] == 'doctor':
            cursor.execute("SELECT id FROM doctors WHERE user_id = %s", (user['id'],))
            row = cursor.fetchone()
            if row:
                session['doctor_id'] = row['id']
        cursor.close()
        conn.close()

        # Determine dashboard URL
        redirect_url = url_for(f"{user['role']}.dashboard")
        return jsonify({'success': True, 'message': 'Login successful!', 'redirect': redirect_url})
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@auth_bp.route('/register', methods=['POST'])
def register():
    """Handle patient registration with transactions"""
    data = request.form if request.form else request.get_json()
    
    # User fields
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    phone = data.get('phone', '').strip()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', '')
    
    # Patient fields
    dob = data.get('dob', '')
    gender = data.get('gender', '')
    blood_group = data.get('blood_group', '').strip()
    address = data.get('address', '').strip()
    emergency_contact = data.get('emergency_contact', '').strip()

    # Form Validation
    if not all([name, email, phone, password, confirm_password, dob, gender, blood_group, address, emergency_contact]):
        return jsonify({'success': False, 'message': 'All fields are required.'}), 400

    if password != confirm_password:
        return jsonify({'success': False, 'message': 'Passwords do not match.'}), 400

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

        # Insert User record
        pwd_hash = generate_password_hash(password)
        cursor.execute(
            "INSERT INTO users (name, email, phone, password_hash, role) VALUES (%s, %s, %s, %s, 'patient')",
            (name, email, phone, pwd_hash)
        )
        user_id = cursor.lastrowid

        # Insert Patient record
        cursor.execute(
            "INSERT INTO patients (user_id, dob, gender, blood_group, address, emergency_contact) VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, dob, gender, blood_group, address, emergency_contact)
        )
        patient_id = cursor.lastrowid

        conn.commit()
        cursor.close()
        conn.close()

        # Set session details
        session['user_id'] = user_id
        session['user_name'] = name
        session['user_role'] = 'patient'
        session['user_email'] = email
        session['patient_id'] = patient_id

        return jsonify({'success': True, 'message': 'Registration successful!', 'redirect': url_for('patient.dashboard')})
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@auth_bp.route('/logout')
def logout():
    """Clear session data and redirect to home"""
    session.clear()
    return redirect(url_for('index'))
