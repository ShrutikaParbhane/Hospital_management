/**
 * Client-Side validation utility functions
 */

function validateEmail(email) {
    const re = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
    return re.test(String(email).toLowerCase());
}

function validatePhone(phone) {
    const re = /^[0-9]{10}$/;
    return re.test(String(phone));
}

function validateName(name) {
    const re = /^[A-Za-z\s]{2,50}$/;
    return re.test(String(name));
}

function isDateInPast(dateString) {
    const inputDate = new Date(dateString);
    const today = new Date();
    today.setHours(0,0,0,0);
    return inputDate < today;
}
