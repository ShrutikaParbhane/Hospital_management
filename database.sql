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
    reorder_level INT DEFAULT 10
);

-- =======================================================
-- 7b. MEDICINE BATCHES TABLE
-- =======================================================
CREATE TABLE IF NOT EXISTS medicine_batches (
    id INT PRIMARY KEY AUTO_INCREMENT,
    medicine_id INT NOT NULL,
    batch_number VARCHAR(50) NOT NULL,
    quantity_received INT NOT NULL,
    quantity_remaining INT NOT NULL,
    expiry_date DATE NOT NULL,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (medicine_id) REFERENCES medicines(id) ON DELETE CASCADE
);

-- =======================================================
-- 8. PRESCRIPTION ITEMS TABLE
-- =======================================================
CREATE TABLE IF NOT EXISTS prescription_items (
    id INT PRIMARY KEY AUTO_INCREMENT,
    prescription_id INT NOT NULL,
    medicine_id INT NOT NULL,
    dosage VARCHAR(50) NOT NULL, -- e.g., '500mg'
    frequency VARCHAR(50) NOT NULL, -- e.g., 'twice daily'
    duration_days INT NOT NULL,
    quantity INT NOT NULL DEFAULT 1,
    dispensed ENUM('pending', 'dispensed', 'declined') DEFAULT 'pending',
    FOREIGN KEY (prescription_id) REFERENCES prescriptions(id) ON DELETE CASCADE,
    FOREIGN KEY (medicine_id) REFERENCES medicines(id) ON DELETE CASCADE
);

-- =======================================================
-- =======================================================
-- 9. BILLING TABLE
-- =======================================================
CREATE TABLE IF NOT EXISTS billing (
    id INT PRIMARY KEY AUTO_INCREMENT,
    appointment_id INT UNIQUE NOT NULL,
    patient_id INT NOT NULL,
    consultation_fee DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    medicine_charges DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    total_amount DECIMAL(10,2) GENERATED ALWAYS AS (consultation_fee + medicine_charges) STORED,
    payment_status ENUM('pending', 'paid', 'failed') DEFAULT 'pending',
    payment_method ENUM('cash', 'card', 'online') NULL,
    billed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE
);

-- =======================================================
-- 10. BILLING ITEMS TABLE
-- =======================================================
CREATE TABLE IF NOT EXISTS billing_items (
    id INT PRIMARY KEY AUTO_INCREMENT,
    billing_id INT NOT NULL,
    prescription_item_id INT NOT NULL,
    quantity INT NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    subtotal DECIMAL(10,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    FOREIGN KEY (billing_id) REFERENCES billing(id) ON DELETE CASCADE,
    FOREIGN KEY (prescription_item_id) REFERENCES prescription_items(id) ON DELETE CASCADE
);

-- =======================================================
-- 12. MEDICINE REQUESTS TABLE
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
    unit_price DECIMAL(10,2) NULL,
    expiry_date DATE NULL,
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
-- 13. STOCK ADJUSTMENTS LOG TABLE
-- =======================================================
CREATE TABLE IF NOT EXISTS stock_adjustments (
    id INT PRIMARY KEY AUTO_INCREMENT,
    medicine_id INT NOT NULL,
    admin_id INT NULL,
    adjustment_type ENUM('expired_removal', 'damaged', 'correction') NOT NULL,
    quantity_removed INT NOT NULL,
    reason VARCHAR(255) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (medicine_id) REFERENCES medicines(id) ON DELETE CASCADE,
    FOREIGN KEY (admin_id) REFERENCES users(id) ON DELETE SET NULL
);

-- =======================================================
-- 14. AUDIT LOGS TABLE
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
-- VIEWS
-- =======================================================

-- 1a. Medicine Stock Summary View (COALESCE handles 0 stock)
CREATE VIEW medicine_stock_summary AS
SELECT m.id AS medicine_id,
       COALESCE(SUM(b.quantity_remaining), 0) AS total_stock,
       MIN(b.expiry_date) AS nearest_expiry
FROM medicines m
LEFT JOIN medicine_batches b ON m.id = b.medicine_id AND b.quantity_remaining > 0 AND b.expiry_date >= CURDATE()
GROUP BY m.id;

-- 1b. Expiring Medicines view
CREATE VIEW expiring_medicines_alert AS
SELECT m.id, m.name, m.category, m.manufacturer, b.quantity_remaining AS stock_quantity, b.expiry_date,
       DATEDIFF(b.expiry_date, CURDATE()) AS days_to_expiry, b.batch_number
FROM medicines m
JOIN medicine_batches b ON m.id = b.medicine_id
WHERE b.expiry_date <= DATE_ADD(CURDATE(), INTERVAL 30 DAY)
  AND b.expiry_date >= CURDATE()
  AND b.quantity_remaining > 0;

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
    
    IF NEW.appointment_date < CURDATE() THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Appointment date cannot be in the past.';
    END IF;
    
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
        IF NEW.appointment_date < CURDATE() THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Appointment date cannot be in the past.';
        END IF;
        
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

-- 5. Auto-Billing Consultation fee on completion
CREATE TRIGGER generate_billing_on_completion
AFTER UPDATE ON appointments
FOR EACH ROW
BEGIN
    DECLARE doc_fee DECIMAL(10,2);
    
    IF NEW.status = 'completed' AND OLD.status != 'completed' THEN
        SELECT consultation_fee INTO doc_fee
        FROM doctors
        WHERE id = NEW.doctor_id;
        
        INSERT INTO billing (appointment_id, patient_id, consultation_fee, medicine_charges, payment_status)
        VALUES (NEW.id, NEW.patient_id, doc_fee, 0.00, 'pending')
        ON DUPLICATE KEY UPDATE updated_at = CURRENT_TIMESTAMP;
    END IF;
END$$

-- 6. Safety Control: Block prescribing expired medicines
CREATE TRIGGER before_prescribe_check_expiry
BEFORE INSERT ON prescription_items
FOR EACH ROW
BEGIN
    DECLARE nearest_exp DATE;
    
    SELECT nearest_expiry INTO nearest_exp 
    FROM medicine_stock_summary 
    WHERE medicine_id = NEW.medicine_id;
    
    IF nearest_exp IS NULL OR nearest_exp < CURDATE() THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Safety Lockout: Cannot prescribe an expired or unavailable medicine.';
    END IF;
END$$

-- 6b. Live Bill Auto-Update: Add medicine cost to bill upon prescription item insertion
CREATE TRIGGER after_prescription_item_insert
AFTER INSERT ON prescription_items
FOR EACH ROW
BEGIN
    DECLARE v_billing_id INT;
    DECLARE v_price DECIMAL(10,2);

    SELECT b.id INTO v_billing_id
    FROM billing b
    JOIN prescriptions p ON p.appointment_id = b.appointment_id
    WHERE p.id = NEW.prescription_id;

    SELECT unit_price INTO v_price FROM medicines WHERE id = NEW.medicine_id;

    IF v_billing_id IS NOT NULL THEN
        UPDATE billing
        SET medicine_charges = medicine_charges + (v_price * NEW.quantity)
        WHERE id = v_billing_id;
    END IF;
END$$

-- 7. Dispense Stock Control: Check stock quantity across batches before pharmacy item dispense
CREATE TRIGGER check_pharmacy_stock_before_dispense
BEFORE INSERT ON billing_items
FOR EACH ROW
BEGIN
    DECLARE current_stock INT;
    DECLARE med_id INT;
    
    SELECT medicine_id INTO med_id
    FROM prescription_items
    WHERE id = NEW.prescription_item_id;
    
    SELECT total_stock INTO current_stock
    FROM medicine_stock_summary
    WHERE medicine_id = med_id;
    
    IF current_stock IS NULL OR current_stock < NEW.quantity THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Safety Refusal: Insufficient stock quantity for the dispensed medicine.';
    END IF;
END$$

-- 7b. FEFO Stock Deduction Procedure
CREATE PROCEDURE deduct_stock_fefo(IN p_medicine_id INT, IN p_qty INT)
BEGIN
    DECLARE v_batch_id INT;
    DECLARE v_remaining INT;
    DECLARE v_take INT;
    DECLARE v_qty_left INT DEFAULT p_qty;
    DECLARE done INT DEFAULT FALSE;
    
    DECLARE batch_cursor CURSOR FOR
        SELECT id, quantity_remaining 
        FROM medicine_batches
        WHERE medicine_id = p_medicine_id 
          AND quantity_remaining > 0 
          AND expiry_date >= CURDATE()
        ORDER BY expiry_date ASC;
        
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = TRUE;

    OPEN batch_cursor;
    read_loop: LOOP
        FETCH batch_cursor INTO v_batch_id, v_remaining;
        IF done OR v_qty_left <= 0 THEN 
            LEAVE read_loop; 
        END IF;
        
        SET v_take = LEAST(v_remaining, v_qty_left);
        UPDATE medicine_batches 
        SET quantity_remaining = quantity_remaining - v_take 
        WHERE id = v_batch_id;
        
        SET v_qty_left = v_qty_left - v_take;
    END LOOP;
    CLOSE batch_cursor;

    IF v_qty_left > 0 THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Insufficient stock across all valid batches.';
    END IF;
END$$

-- 8. Dispense Stock Control: Decrement stock using FEFO batch selection
CREATE TRIGGER decrement_stock_on_dispense
AFTER INSERT ON billing_items
FOR EACH ROW
BEGIN
    DECLARE med_id INT;
    
    -- Get medicine ID from prescription_items
    SELECT medicine_id INTO med_id
    FROM prescription_items
    WHERE id = NEW.prescription_item_id;
    
    CALL deduct_stock_fefo(med_id, NEW.quantity);
END$$

-- 9. Recalculate medicine charges on bill: Insert
CREATE TRIGGER after_billing_item_insert
AFTER INSERT ON billing_items
FOR EACH ROW
BEGIN
    UPDATE billing
    SET medicine_charges = (
        SELECT COALESCE(SUM(subtotal), 0.00) FROM billing_items WHERE billing_id = NEW.billing_id
    )
    WHERE id = NEW.billing_id;
END$$

-- 10. Recalculate medicine charges on bill: Update
CREATE TRIGGER after_billing_item_update
AFTER UPDATE ON billing_items
FOR EACH ROW
BEGIN
    UPDATE billing
    SET medicine_charges = (
        SELECT COALESCE(SUM(subtotal), 0.00) FROM billing_items WHERE billing_id = NEW.billing_id
    )
    WHERE id = NEW.billing_id;
END$$

-- 11. Recalculate medicine charges on bill: Delete
CREATE TRIGGER after_billing_item_delete
AFTER DELETE ON billing_items
FOR EACH ROW
BEGIN
    UPDATE billing
    SET medicine_charges = (
        SELECT COALESCE(SUM(subtotal), 0.00) FROM billing_items WHERE billing_id = OLD.billing_id
    )
    WHERE id = OLD.billing_id;
END$$

-- 12. Trigger to auto-restock a medicine: Creates new batch
CREATE TRIGGER after_restock_approved
AFTER UPDATE ON medicine_requests
FOR EACH ROW
BEGIN
    IF NEW.status = 'approved' AND OLD.status = 'pending' 
       AND NEW.request_type = 'restock' THEN
        INSERT INTO medicine_batches (medicine_id, batch_number, quantity_received, quantity_remaining, expiry_date)
        VALUES (
            NEW.medicine_id, 
            CONCAT('BAT-REQ', NEW.id), 
            NEW.quantity_requested, 
            NEW.quantity_requested, 
            COALESCE(NEW.expiry_date, DATE_ADD(CURDATE(), INTERVAL 1 YEAR))
        );
    END IF;
END$$

-- 13. Trigger to auto-create a new medicine and insert its batch
CREATE TRIGGER after_new_medicine_approved
AFTER UPDATE ON medicine_requests
FOR EACH ROW
BEGIN
    DECLARE new_med_id INT;
    IF NEW.status = 'approved' AND OLD.status = 'pending' 
       AND NEW.request_type = 'new_medicine' THEN
        INSERT INTO medicines (name, category, manufacturer, unit_price, reorder_level)
        VALUES (NEW.medicine_name, NEW.category, NEW.manufacturer, COALESCE(NEW.unit_price, 0.00), 10);
        
        SET new_med_id = LAST_INSERT_ID();
        
        INSERT INTO medicine_batches (medicine_id, batch_number, quantity_received, quantity_remaining, expiry_date)
        VALUES (
            new_med_id, 
            CONCAT('BAT-NEW', NEW.id), 
            NEW.quantity_requested, 
            NEW.quantity_requested, 
            COALESCE(NEW.expiry_date, DATE_ADD(CURDATE(), INTERVAL 1 YEAR))
        );
    END IF;
END$$

-- 14. Trigger to deduct stock on manual adjustments using FEFO
CREATE TRIGGER after_stock_adjustment_deduct
AFTER INSERT ON stock_adjustments
FOR EACH ROW
BEGIN
    IF NEW.adjustment_type != 'expired_removal' THEN
        CALL deduct_stock_fefo(NEW.medicine_id, NEW.quantity_removed);
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
-- EVENT: Auto-remove expired stock once daily
-- =======================================================
DELIMITER $$
CREATE EVENT IF NOT EXISTS auto_remove_expired_batches
ON SCHEDULE EVERY 1 DAY
STARTS CURRENT_DATE + INTERVAL 1 DAY
DO
BEGIN
    -- Log what's being removed, before removing it
    INSERT INTO stock_adjustments (medicine_id, admin_id, adjustment_type, quantity_removed, reason)
    SELECT medicine_id, NULL, 'expired_removal', quantity_remaining,
           CONCAT('Auto-removed expired batch: ', batch_number, ', exp ', expiry_date)
    FROM medicine_batches
    WHERE expiry_date < CURDATE() AND quantity_remaining > 0;

    -- Zero out remaining quantity of expired batches
    UPDATE medicine_batches
    SET quantity_remaining = 0
    WHERE expiry_date < CURDATE() AND quantity_remaining > 0;
END$$
DELIMITER ;

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


-- 5. Insert Medicines Catalog
INSERT INTO medicines (id, name, manufacturer, category, unit_price, reorder_level) VALUES
(1, 'Amoxicillin 500mg', 'Pfizer', 'Antibiotic', 1.50, 10),
(2, 'Ibuprofen 400mg', 'Bayer', 'Analgesic', 0.80, 10),
(3, 'Paracetamol 650mg', 'GSK', 'Antipyretic', 0.50, 15),
(4, 'Metformin 1000mg', 'Merck', 'Antidiabetic', 1.20, 10),
(5, 'Atorvastatin 20mg', 'Viatris', 'Statin', 2.00, 10),
(6, 'Cetirizine 10mg', 'McNeil', 'Antihistamine', 0.60, 10),
(7, 'Aspirin 500mg', 'Bayer', 'Analgesic', 0.75, 10), -- Expired
(8, 'Vitamin C 500mg', 'GSK', 'Vitamin', 0.50, 10); -- Near Expiry

-- 6. Insert Medicine Batches
INSERT INTO medicine_batches (medicine_id, batch_number, quantity_received, quantity_remaining, expiry_date) VALUES
(1, 'BAT-AMX01', 5, 5, '2028-12-31'),
(2, 'BAT-IBU01', 200, 200, '2027-06-30'),
(3, 'BAT-PAR01', 500, 500, '2029-01-15'),
(4, 'BAT-MET01', 150, 150, '2028-09-20'),
(5, 'BAT-ATO01', 120, 120, '2027-11-10'),
(6, 'BAT-CET01', 250, 250, '2028-03-05'),
(7, 'BAT-ASP01', 100, 100, '2025-01-01'), -- Expired
(8, 'BAT-VIT01', 80, 80, DATE_ADD(CURDATE(), INTERVAL 15 DAY));
