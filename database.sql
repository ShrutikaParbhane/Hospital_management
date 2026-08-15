-- =======================================================
-- HOSPITAL APPOINTMENT & PRESCRIPTION SYSTEM - DATABASE SCHEMA
-- =======================================================

DROP DATABASE IF EXISTS hospital_db;
CREATE DATABASE hospital_db;
USE hospital_db;

-- Enable event scheduler (requires appropriate privileges)
SET GLOBAL event_scheduler = ON;

-- =======================================================
-- 1. USERS TABLE (Base login table for all roles)
-- =======================================================
CREATE TABLE IF NOT EXISTS users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    phone VARCHAR(15) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('patient', 'doctor', 'receptionist', 'admin') NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =======================================================
-- 2. DOCTORS TABLE (Extends users)
-- =======================================================
CREATE TABLE IF NOT EXISTS doctors (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    specialization VARCHAR(100) NOT NULL,
    qualification VARCHAR(150) NOT NULL,
    experience_years INT NOT NULL,
    consultation_fee DECIMAL(10,2) NOT NULL,
    available_days VARCHAR(50) NOT NULL, -- e.g., 'Mon,Wed,Fri'
    slot_start_time TIME NOT NULL,
    slot_end_time TIME NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- =======================================================
-- 3. PATIENTS TABLE (Extends users)
-- =======================================================
CREATE TABLE IF NOT EXISTS patients (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    dob DATE NOT NULL,
    gender ENUM('male', 'female', 'other') NOT NULL,
    blood_group VARCHAR(5) NOT NULL,
    address VARCHAR(255) NOT NULL,
    emergency_contact VARCHAR(15) NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- =======================================================
-- 4. RECEPTIONISTS TABLE (Extends users)
-- =======================================================
CREATE TABLE IF NOT EXISTS receptionists (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    employee_code VARCHAR(20) UNIQUE NOT NULL,
    shift ENUM('morning', 'evening', 'night') NOT NULL,
    created_by INT NOT NULL, -- Admin user ID
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
);

-- =======================================================
-- 5. APPOINTMENTS TABLE
-- =======================================================
CREATE TABLE IF NOT EXISTS appointments (
    id INT PRIMARY KEY AUTO_INCREMENT,
    patient_id INT NOT NULL,
    doctor_id INT NOT NULL,
    appointment_date DATE NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    status ENUM('pending', 'confirmed', 'completed', 'cancelled', 'expired') DEFAULT 'pending',
    reason VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE
);

-- =======================================================
-- 6. PRESCRIPTIONS TABLE (1:1 with completed appointments)
-- =======================================================
CREATE TABLE IF NOT EXISTS prescriptions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    appointment_id INT UNIQUE NOT NULL,
    doctor_id INT NOT NULL,
    patient_id INT NOT NULL,
    diagnosis TEXT NOT NULL,
    status ENUM('active', 'completed') DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
    FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE
);

-- =======================================================
-- 7. MEDICINES TABLE
-- =======================================================
CREATE TABLE IF NOT EXISTS medicines (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    manufacturer VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    stock_quantity INT NOT NULL,
    reorder_level INT DEFAULT 10,
    expiry_date DATE NOT NULL
);

-- =======================================================
-- 8. PRESCRIPTION ITEMS TABLE (Junction Table)
-- =======================================================
CREATE TABLE IF NOT EXISTS prescription_items (
    id INT PRIMARY KEY AUTO_INCREMENT,
    prescription_id INT NOT NULL,
    medicine_id INT NOT NULL,
    dosage VARCHAR(50) NOT NULL, -- e.g., '500mg'
    frequency VARCHAR(50) NOT NULL, -- e.g., 'twice daily'
    duration_days INT NOT NULL,
    FOREIGN KEY (prescription_id) REFERENCES prescriptions(id) ON DELETE CASCADE,
    FOREIGN KEY (medicine_id) REFERENCES medicines(id) ON DELETE CASCADE
);

-- =======================================================
-- 9. BILLING TABLE
-- =======================================================
CREATE TABLE IF NOT EXISTS billing (
    id INT PRIMARY KEY AUTO_INCREMENT,
    appointment_id INT UNIQUE NOT NULL,
    patient_id INT NOT NULL,
    consultation_fee DECIMAL(10,2) NOT NULL,
    medicine_charges DECIMAL(10,2) DEFAULT 0.00,
    total_amount DECIMAL(10,2) NOT NULL,
    payment_status ENUM('pending', 'paid', 'failed') DEFAULT 'pending',
    payment_method ENUM('cash', 'card', 'online') NULL,
    billed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE
);

-- =======================================================
-- 10. MEDICINE REQUESTS TABLE
-- =======================================================
CREATE TABLE IF NOT EXISTS medicine_requests (
    id INT PRIMARY KEY AUTO_INCREMENT,
    requested_by INT NOT NULL,                     -- Doctor user_id
    request_type ENUM('new_medicine', 'restock') NOT NULL,
    medicine_id INT NULL,                          -- Null if new_medicine
    medicine_name VARCHAR(100) NULL,               -- Null if restock
    category VARCHAR(50) NULL,
    manufacturer VARCHAR(100) NULL,
    quantity_requested INT NOT NULL,
    reason VARCHAR(255) NULL,
    status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending',
    reviewed_by INT NULL,                          -- Admin user_id
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP NULL,
    FOREIGN KEY (requested_by) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (medicine_id) REFERENCES medicines(id) ON DELETE SET NULL,
    FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL
);

-- =======================================================
-- 11. AUDIT LOGS TABLE
-- =======================================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id INT PRIMARY KEY AUTO_INCREMENT,
    admin_id INT NOT NULL,
    action VARCHAR(255) NOT NULL,
    target_type VARCHAR(50) NOT NULL,
    target_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (admin_id) REFERENCES users(id) ON DELETE CASCADE
);

-- =======================================================
-- TRIGGERS & EVENTS
-- =======================================================

DELIMITER $$

-- 1. Prevent Double-Booking: Insert
CREATE TRIGGER prevent_double_booking_insert
BEFORE INSERT ON appointments
FOR EACH ROW
BEGIN
    DECLARE overlap_count INT;
    
    SELECT COUNT(*) INTO overlap_count
    FROM appointments
    WHERE doctor_id = NEW.doctor_id
      AND appointment_date = NEW.appointment_date
      AND status NOT IN ('cancelled', 'expired')
      AND (
          (NEW.start_time < end_time AND NEW.end_time > start_time)
      );
      
    IF overlap_count > 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'This time slot overlaps with an existing appointment for the selected doctor.';
    END IF;
END$$

-- 2. Prevent Double-Booking: Update
CREATE TRIGGER prevent_double_booking_update
BEFORE UPDATE ON appointments
FOR EACH ROW
BEGIN
    DECLARE overlap_count INT;
    
    IF NEW.status NOT IN ('cancelled', 'expired') THEN
        SELECT COUNT(*) INTO overlap_count
        FROM appointments
        WHERE doctor_id = NEW.doctor_id
          AND appointment_date = NEW.appointment_date
          AND id != NEW.id
          AND status NOT IN ('cancelled', 'expired')
          AND (
              (NEW.start_time < end_time AND NEW.end_time > start_time)
          );
          
        IF overlap_count > 0 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'This time slot overlaps with an existing appointment for the selected doctor.';
        END IF;
    END IF;
END$$

-- 3. Enforce Doctor Availability Window: Insert
CREATE TRIGGER check_doctor_availability_insert
BEFORE INSERT ON appointments
FOR EACH ROW
BEGIN
    DECLARE doc_days VARCHAR(50);
    DECLARE doc_start TIME;
    DECLARE doc_end TIME;
    DECLARE doc_active BOOLEAN;
    DECLARE app_day VARCHAR(10);
    
    SELECT available_days, slot_start_time, slot_end_time, is_active
    INTO doc_days, doc_start, doc_end, doc_active
    FROM doctors
    WHERE id = NEW.doctor_id;
    
    IF doc_active IS NULL OR NOT doc_active THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Selected doctor is currently inactive or does not exist.';
    END IF;
    
    IF NEW.start_time < doc_start OR NEW.end_time > doc_end THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Appointment slot falls outside the doctor availability window.';
    END IF;
    
    SET app_day = SUBSTRING(DAYNAME(NEW.appointment_date), 1, 3);
    IF LOCATE(app_day, doc_days) = 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Doctor is not available on this day of the week.';
    END IF;
END$$

-- 4. Enforce Doctor Availability Window: Update
CREATE TRIGGER check_doctor_availability_update
BEFORE UPDATE ON appointments
FOR EACH ROW
BEGIN
    DECLARE doc_days VARCHAR(50);
    DECLARE doc_start TIME;
    DECLARE doc_end TIME;
    DECLARE doc_active BOOLEAN;
    DECLARE app_day VARCHAR(10);
    
    IF NEW.doctor_id != OLD.doctor_id OR NEW.appointment_date != OLD.appointment_date OR NEW.start_time != OLD.start_time OR NEW.end_time != OLD.end_time THEN
        SELECT available_days, slot_start_time, slot_end_time, is_active
        INTO doc_days, doc_start, doc_end, doc_active
        FROM doctors
        WHERE id = NEW.doctor_id;
        
        IF doc_active IS NULL OR NOT doc_active THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Selected doctor is currently inactive or does not exist.';
        END IF;
        
        IF NEW.start_time < doc_start OR NEW.end_time > doc_end THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Appointment slot falls outside the doctor availability window.';
        END IF;
        
        SET app_day = SUBSTRING(DAYNAME(NEW.appointment_date), 1, 3);
        IF LOCATE(app_day, doc_days) = 0 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Doctor is not available on this day of the week.';
        END IF;
    END IF;
END$$

-- 5. Auto-Billing Generation
CREATE TRIGGER generate_billing_on_completion
AFTER UPDATE ON appointments
FOR EACH ROW
BEGIN
    DECLARE doc_fee DECIMAL(10,2);
    
    IF NEW.status = 'completed' AND OLD.status != 'completed' THEN
        SELECT consultation_fee INTO doc_fee
        FROM doctors
        WHERE id = NEW.doctor_id;
        
        INSERT INTO billing (appointment_id, patient_id, consultation_fee, medicine_charges, total_amount, payment_status)
        VALUES (NEW.id, NEW.patient_id, doc_fee, 0.00, doc_fee, 'pending')
        ON DUPLICATE KEY UPDATE updated_at = CURRENT_TIMESTAMP;
    END IF;
END$$

-- 6. Stock Control: Check Quantity before inserting item
CREATE TRIGGER check_medicine_stock
BEFORE INSERT ON prescription_items
FOR EACH ROW
BEGIN
    DECLARE current_stock INT;
    
    SELECT stock_quantity INTO current_stock
    FROM medicines
    WHERE id = NEW.medicine_id;
    
    IF current_stock < NEW.duration_days THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Insufficient stock quantity for the prescribed medicine.';
    END IF;
END$$

-- 7. Stock Control: Decrement stock and update bill after insert
CREATE TRIGGER decrement_stock_and_bill
AFTER INSERT ON prescription_items
FOR EACH ROW
BEGIN
    DECLARE med_price DECIMAL(10,2);
    DECLARE item_cost DECIMAL(10,2);
    DECLARE app_id INT;
    
    -- Decrement stock quantity
    UPDATE medicines
    SET stock_quantity = stock_quantity - NEW.duration_days
    WHERE id = NEW.medicine_id;
    
    -- Get price
    SELECT unit_price INTO med_price
    FROM medicines
    WHERE id = NEW.medicine_id;
    
    SET item_cost = med_price * NEW.duration_days;
    
    -- Get appointment ID from prescription
    SELECT appointment_id INTO app_id
    FROM prescriptions
    WHERE id = NEW.prescription_id;
    
    -- Update bill
    UPDATE billing
    SET medicine_charges = medicine_charges + item_cost,
        total_amount = total_amount + item_cost
    WHERE appointment_id = app_id;
END$$

-- 8. Trigger to auto-restock a medicine after request approval
CREATE TRIGGER after_restock_approved
AFTER UPDATE ON medicine_requests
FOR EACH ROW
BEGIN
    IF NEW.status = 'approved' AND OLD.status = 'pending' 
       AND NEW.request_type = 'restock' THEN
        UPDATE medicines 
        SET stock_quantity = stock_quantity + NEW.quantity_requested 
        WHERE id = NEW.medicine_id;
    END IF;
END$$

-- 9. Trigger to auto-create a new medicine row after request approval
CREATE TRIGGER after_new_medicine_approved
AFTER UPDATE ON medicine_requests
FOR EACH ROW
BEGIN
    IF NEW.status = 'approved' AND OLD.status = 'pending' 
       AND NEW.request_type = 'new_medicine' THEN
        -- Insert new medicine, setting default unit price to 0.00 and default expiry to 1 year from now
        INSERT INTO medicines (name, category, manufacturer, unit_price, stock_quantity, reorder_level, expiry_date)
        VALUES (NEW.medicine_name, NEW.category, NEW.manufacturer, 0.00, NEW.quantity_requested, 10, DATE_ADD(CURDATE(), INTERVAL 1 YEAR));
    END IF;
END$$

DELIMITER ;

-- =======================================================
-- EVENT: Auto-expire unconfirmed pending appointments
-- =======================================================
CREATE EVENT IF NOT EXISTS expire_appointments
ON SCHEDULE EVERY 15 MINUTE
DO
    UPDATE appointments
    SET status = 'expired'
    WHERE status = 'pending'
      AND (
          appointment_date < CURDATE()
          OR (appointment_date = CURDATE() AND start_time < CURTIME())
      );

-- =======================================================
-- SEED DATA (Password hashes generated via Werkzeug security)
-- =======================================================

-- 1. Insert Admin (password: admin123)
INSERT INTO users (name, email, phone, password_hash, role) VALUES
('Admin User', 'admin@hospital.com', '9999999999', 'scrypt:32768:8:1$6OSY8xNkzIJL3vtD$73c813e15c36c141375490aa6d5ecea13b42cb6ca562f6b95323142db8418cbd304a9e1567045ed7f776f219422bddac643c767583acce0c823b19cbd9b5384b', 'admin');
SET @admin_user_id = LAST_INSERT_ID();

-- 2. Insert Receptionist User (password: receptionist123)
INSERT INTO users (name, email, phone, password_hash, role) VALUES
('Receptionist Rose', 'receptionist@hospital.com', '8888888888', 'scrypt:32768:8:1$KkQbppQyLIGfRt8D$f813d986738c2ad25ce11cc46df323291995e0a709c3dbff511ca7403788c5b5923681ec9db23802b54a17b32764b828994b3b162fde6c31748f4690bee8aae3', 'receptionist');
SET @receptionist_user_id = LAST_INSERT_ID();

-- Insert Receptionist profile
INSERT INTO receptionists (user_id, employee_code, shift, created_by, is_active) VALUES
(@receptionist_user_id, 'EMP-REC01', 'morning', @admin_user_id, TRUE);

-- 3. Insert Doctors
-- Doctor 1: Cardiology (password: doctor123)
INSERT INTO users (name, email, phone, password_hash, role) VALUES
('Dr. Emily Carter', 'emily.carter@hospital.com', '7777777777', 'scrypt:32768:8:1$SIw4AhbHMJIR2b7T$c9aa3f3508f69c9f0c5bb05bba217b1bef8e6f86e4da004706650b999151b81c769428c628d15c26690ff0dd6e4e43faf8d4bc530aee18ce604922d2f0a8f179', 'doctor');
SET @doctor_user_1 = LAST_INSERT_ID();

INSERT INTO doctors (user_id, specialization, qualification, experience_years, consultation_fee, available_days, slot_start_time, slot_end_time, is_active) VALUES
(@doctor_user_1, 'Cardiology', 'MD, DM (Cardiology)', 12, 150.00, 'Mon,Wed,Fri', '09:00:00', '13:00:00', TRUE);

-- Doctor 2: Pediatrics (password: doctor123)
INSERT INTO users (name, email, phone, password_hash, role) VALUES
('Dr. Marcus Vance', 'marcus.vance@hospital.com', '6666666666', 'scrypt:32768:8:1$SIw4AhbHMJIR2b7T$c9aa3f3508f69c9f0c5bb05bba217b1bef8e6f86e4da004706650b999151b81c769428c628d15c26690ff0dd6e4e43faf8d4bc530aee18ce604922d2f0a8f179', 'doctor');
SET @doctor_user_2 = LAST_INSERT_ID();

INSERT INTO doctors (user_id, specialization, qualification, experience_years, consultation_fee, available_days, slot_start_time, slot_end_time, is_active) VALUES
(@doctor_user_2, 'Pediatrics', 'MD (Pediatrics)', 8, 100.00, 'Tue,Thu,Sat', '10:00:00', '16:00:00', TRUE);

-- Doctor 3: General Medicine (password: doctor123)
INSERT INTO users (name, email, phone, password_hash, role) VALUES
('Dr. Sarah Lin', 'sarah.lin@hospital.com', '5555555555', 'scrypt:32768:8:1$SIw4AhbHMJIR2b7T$c9aa3f3508f69c9f0c5bb05bba217b1bef8e6f86e4da004706650b999151b81c769428c628d15c26690ff0dd6e4e43faf8d4bc530aee18ce604922d2f0a8f179', 'doctor');
SET @doctor_user_3 = LAST_INSERT_ID();

INSERT INTO doctors (user_id, specialization, qualification, experience_years, consultation_fee, available_days, slot_start_time, slot_end_time, is_active) VALUES
(@doctor_user_3, 'General Medicine', 'MBBS, MD', 15, 80.00, 'Mon,Tue,Wed,Thu,Fri', '09:00:00', '17:00:00', TRUE);


-- 4. Insert Patients
-- Patient 1 (password: patient123)
INSERT INTO users (name, email, phone, password_hash, role) VALUES
('Alice Green', 'alice@gmail.com', '4444444444', 'scrypt:32768:8:1$ls2Hcm5NaQfSpdNV$48328315118dc1fafdb599a83cc15b3e818ec2e34f342fda6b14ed836202224383e4f88fb46980af541afc4220ea7dd56c501605f195513c302e06614b9d752a', 'patient');
SET @patient_user_1 = LAST_INSERT_ID();

INSERT INTO patients (user_id, dob, gender, blood_group, address, emergency_contact) VALUES
(@patient_user_1, '1995-04-12', 'female', 'A+', '123 Pine St, Cityville', '9876543210');

-- Patient 2 (password: patient123)
INSERT INTO users (name, email, phone, password_hash, role) VALUES
('Bob Carter', 'bob@gmail.com', '3333333333', 'scrypt:32768:8:1$ls2Hcm5NaQfSpdNV$48328315118dc1fafdb599a83cc15b3e818ec2e34f342fda6b14ed836202224383e4f88fb46980af541afc4220ea7dd56c501605f195513c302e06614b9d752a', 'patient');
SET @patient_user_2 = LAST_INSERT_ID();

INSERT INTO patients (user_id, dob, gender, blood_group, address, emergency_contact) VALUES
(@patient_user_2, '1988-11-23', 'male', 'O-', '456 Elm St, Townsville', '9123456789');


-- 5. Insert Medicines (Amoxicillin set below reorder level to trigger low-stock alert)
INSERT INTO medicines (name, manufacturer, category, unit_price, stock_quantity, reorder_level, expiry_date) VALUES
('Amoxicillin 500mg', 'Pfizer', 'Antibiotic', 1.50, 5, 10, '2028-12-31'),
('Ibuprofen 400mg', 'Bayer', 'Analgesic', 0.80, 200, 10, '2027-06-30'),
('Paracetamol 650mg', 'GSK', 'Antipyretic', 0.50, 500, 15, '2029-01-15'),
('Metformin 1000mg', 'Merck', 'Antidiabetic', 1.20, 150, 10, '2028-09-20'),
('Atorvastatin 20mg', 'Viatris', 'Statin', 2.00, 120, 10, '2027-11-10'),
('Cetirizine 10mg', 'McNeil', 'Antihistamine', 0.60, 250, 10, '2028-03-05');
