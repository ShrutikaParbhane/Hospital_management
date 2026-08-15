import mysql.connector
from config import Config

def run_sql_file(filename):
    print("Connecting to MySQL...")
    conn = mysql.connector.connect(
        host=Config.MYSQL_HOST,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD
    )
    cursor = conn.cursor()
    
    print(f"Executing SQL file: {filename}")
    with open(filename, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    current_stmt = []
    delimiter = ';'
    
    for line_num, line in enumerate(lines, 1):
        line_content = line
        if '--' in line:
            line_content = line.split('--')[0]
            
        stripped = line_content.strip()
        if not stripped:
            continue
        if stripped.startswith('--'):
            continue
            
        if stripped.upper().startswith('DELIMITER'):
            parts = stripped.split()
            if len(parts) > 1:
                delimiter = parts[1]
            continue
            
        current_stmt.append(line_content)
        
        if stripped.endswith(delimiter):
            stmt = "".join(current_stmt)
            stmt_stripped = stmt.strip()
            if stmt_stripped.endswith(delimiter):
                stmt_str = stmt_stripped[:-len(delimiter)].strip()
            else:
                stmt_str = stmt_stripped
                
            if stmt_str:
                try:
                    cursor.execute(stmt_str)
                except Exception as e:
                    print(f"Error at line {line_num}: {e}")
                    print(f"Statement: {stmt_str}")
                    raise e
            current_stmt = []
            
    conn.commit()
    cursor.close()
    conn.close()
    print("Database initialized successfully.")

if __name__ == '__main__':
    run_sql_file('database.sql')
