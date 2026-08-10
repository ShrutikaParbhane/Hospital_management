import mysql.connector
from mysql.connector import Error
from config import Config

def get_db_connection():
    """Create and return a database connection to MySQL server"""
    try:
        connection = mysql.connector.connect(
            host=Config.MYSQL_HOST,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DATABASE
        )
        return connection
    except Error as e:
        print(f"Database connection error: {e}")
        return None

def test_connection():
    """Test if database connection works"""
    connection = get_db_connection()
    if connection:
        connection.close()
        return True
    return False
