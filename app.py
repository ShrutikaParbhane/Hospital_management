from flask import Flask, render_template, session, redirect, url_for
from config import Config
from database import get_db_connection
import os

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

# Context processor to inject user information globally in Jinja2 templates
@app.context_processor
def inject_user():
    return {
        'logged_in': 'user_id' in session,
        'user_name': session.get('user_name'),
        'user_role': session.get('user_role'),
        'user_email': session.get('user_email')
    }

# Root Portal Page
@app.route('/')
def index():
    if 'user_id' in session:
        # Redirect to role-specific dashboard
        role = session.get('user_role')
        return redirect(url_for(f'{role}.dashboard'))
    return render_template('index.html')

# Import and register Blueprints
from blueprints.auth import auth_bp
from blueprints.patient import patient_bp
from blueprints.doctor import doctor_bp
from blueprints.receptionist import receptionist_bp
from blueprints.admin import admin_bp

app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(patient_bp, url_prefix='/patient')
app.register_blueprint(doctor_bp, url_prefix='/doctor')
app.register_blueprint(receptionist_bp, url_prefix='/receptionist')
app.register_blueprint(admin_bp, url_prefix='/admin')

if __name__ == '__main__':
    print("=" * 60)
    print("HOSPITAL APPOINTMENT & PRESCRIPTION SYSTEM")
    print("=" * 60)
    print(f"Server starting at: http://localhost:{Config.PORT}")
    print("=" * 60)
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
