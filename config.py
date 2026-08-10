import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

class Config:
    """Base configuration class loading environment variables"""
    MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_USER = os.getenv('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', 'Guddu1609')
    MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'hospital_db')
    SECRET_KEY = os.getenv('SECRET_KEY', 'hospital_appointment_prescription_system_secret_key_2026')
    DEBUG = True
    PORT = 5000
    HOST = '0.0.0.0'
