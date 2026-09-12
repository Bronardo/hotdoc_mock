"""
HotDoc mock - Appointment booking form (SIT772 Task 9.2D).

A small Flask web application that demonstrates EMBEDDED SQL: it renders an
HTML form for inserting one record into the `Appointment` table of the HotDoc
database (Task 7.2C), validates all mandatory input on the server BEFORE the
INSERT is issued, and reports a friendly message on both failure and success.

Database credentials are never hard-coded: they are read from environment
variables (DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME). For local
development they can be supplied through a git-ignored `.env` file.
"""

import os

import mysql.connector
from mysql.connector import Error as MySQLError
from dotenv import load_dotenv
from flask import Flask, render_template, request

# Load variables from a local .env file if one exists (no-op in production).
load_dotenv()

app = Flask(__name__)

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "hotdoc_user"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "hotdoc_db"),
}

# ---------------------------------------------------------------------------
# SQL statements
# ---------------------------------------------------------------------------

SQL_PATIENTS = """
    SELECT patient_id, first_name, last_name, date_of_birth
    FROM Patient
    ORDER BY last_name, first_name
"""

SQL_PRACTITIONERS = """
    SELECT practitioner_id, title, first_name, last_name
    FROM Practitioner
    ORDER BY last_name, first_name
"""

SQL_APPT_TYPES = """
    SELECT appointment_type_id, type_name, duration_minutes
    FROM AppointmentType
    ORDER BY type_name
"""

SQL_TIME_SLOTS = """
    SELECT t.time_slot_id,
           t.slot_start_time,
           t.slot_end_time,
           t.is_available,
           p.first_name AS practitioner_first,
           p.last_name  AS practitioner_last
    FROM TimeSlot t
    INNER JOIN Practitioner p ON t.practitioner_id = p.practitioner_id
    ORDER BY t.slot_start_time
"""

SQL_STATUSES = "SELECT status_code FROM tblAppointmentStatus ORDER BY status_code"

# Column list is explicit. appointment_id is AUTO_INCREMENT and booking_timestamp
# has a DEFAULT CURRENT_TIMESTAMP, so neither is supplied by the application.
SQL_INSERT_APPOINTMENT = """
    INSERT INTO Appointment
        (patient_id, practitioner_id, appointment_type_id, time_slot_id,
         status_code, cancellation_reason, is_first_visit)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
"""
# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_connection():
    """Open a MySQL connection using environment-supplied configuration."""
    return mysql.connector.connect(**DB_CONFIG)


def _fmt_dt(value):
    """Format a MySQL DATE/DATETIME value returned by the driver for display."""
    if value is None:
        return ""
    # mysql-connector returns datetime objects; be defensive for mocks.
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def fetch_reference_data():
    """
    Fetch every lookup list needed to render the form.

    Returns (refs, valid_sets, db_error). refs feeds the template; valid_sets
    contains the legal id/value sets used to validate submitted foreign keys.
    """
    refs = {
        "patients": [],
        "practitioners": [],
        "appointment_types": [],
        "time_slots": [],
        "statuses": [],
    }
    valid_sets = {
        "patients": set(),
        "practitioners": set(),
        "appointment_types": set(),
        "available_time_slots": set(),
        "statuses": set(),
    }

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute(SQL_PATIENTS)
        for row in cursor.fetchall():
            pid = row["patient_id"]
            valid_sets["patients"].add(pid)
            refs["patients"].append({
                "id": pid,
                "label": f"{pid} - {row['first_name']} {row['last_name']} "
                         f"(DOB: {_fmt_dt(row['date_of_birth'])[:10]})",
            })

        cursor.execute(SQL_PRACTITIONERS)
        for row in cursor.fetchall():
            prid = row["practitioner_id"]
            valid_sets["practitioners"].add(prid)
            title = f"{row['title']} " if row.get("title") else ""
            refs["practitioners"].append({
                "id": prid,
                "label": f"{prid} - {title}{row['first_name']} {row['last_name']}",
            })

        cursor.execute(SQL_APPT_TYPES)
        for row in cursor.fetchall():
            atid = row["appointment_type_id"]
            valid_sets["appointment_types"].add(atid)
            refs["appointment_types"].append({
                "id": atid,
                "label": f"{atid} - {row['type_name']} "
                         f"({row['duration_minutes']} min)",
            })

        cursor.execute(SQL_TIME_SLOTS)
        for row in cursor.fetchall():
            tsid = row["time_slot_id"]
            available = bool(row["is_available"])
            if available:
                valid_sets["available_time_slots"].add(tsid)
            refs["time_slots"].append({
                "id": tsid,
                "label": (
                    f"{tsid} - {_fmt_dt(row['slot_start_time'])} to "
                    f"{_fmt_dt(row['slot_end_time'])} "
                    f"(Dr. {row['practitioner_last']})"
                ),
                "available": available,
            })

        cursor.execute(SQL_STATUSES)
        for row in cursor.fetchall():
            code = row["status_code"]
            valid_sets["statuses"].add(code)
            refs["statuses"].append(code)

        cursor.close()
    finally:
        conn.close()

    return refs, valid_sets, None
# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "patient_id": "Patient",
    "practitioner_id": "Practitioner",
    "appointment_type_id": "Appointment type",
    "time_slot_id": "Time slot",
    "status_code": "Appointment status",
}

INTEGER_FIELDS = {
    "patient_id": "Patient",
    "practitioner_id": "Practitioner",
    "appointment_type_id": "Appointment type",
    "time_slot_id": "Time slot",
}


def validate_form(form, valid_sets):
    """
    Validate submitted form data BEFORE any INSERT.

    Returns (clean_values, errors). If errors is non-empty NO database
    write may be attempted.
    """
    errors = []
    raw = {}

    # 1) Mandatory-field presence check ------------------------------------
    for field, label in REQUIRED_FIELDS.items():
        value = (form.get(field) or "").strip()
        raw[field] = value
        if value == "":
            errors.append(f"Mandatory field missing: '{label}' must be selected.")

    # 2) Integer foreign-key fields must parse as positive integers
    parsed = {}
    for field, label in INTEGER_FIELDS.items():
        value = raw[field]
        if value == "":
            continue  # already reported as missing above
        try:
            parsed[field] = int(value)
            if parsed[field] <= 0:
                raise ValueError
        except ValueError:
            errors.append(
                f"Invalid format for '{label}': a positive numeric id is "
                f"required, got '{value}'."
            )
    # 3) Submitted values must reference rows that actually exist
    if "patient_id" in parsed and parsed["patient_id"] not in valid_sets["patients"]:
        errors.append(f"Invalid Patient id {parsed['patient_id']}: no such patient exists.")
    if ("practitioner_id" in parsed and
            parsed["practitioner_id"] not in valid_sets["practitioners"]):
        errors.append(f"Invalid Practitioner id {parsed['practitioner_id']}: no such practitioner exists.")
    if ("appointment_type_id" in parsed and
            parsed["appointment_type_id"] not in valid_sets["appointment_types"]):
        errors.append(f"Invalid Appointment Type id {parsed['appointment_type_id']}: no such type exists.")
    if "time_slot_id" in parsed:
        tsid = parsed["time_slot_id"]
        if tsid not in valid_sets["available_time_slots"]:
            # The id either does not exist or is already booked
            # (Appointment.time_slot_id has a UNIQUE constraint).
            errors.append(
                f"Time slot {tsid} is invalid or has already been booked; "
                f"please choose an available slot."
            )
    if raw["status_code"] and raw["status_code"] not in valid_sets["statuses"]:
        errors.append(
            f"Invalid status code '{raw['status_code']}': it is not one of "
            f"the allowed tblAppointmentStatus values."
        )

    # 4) Optional fields
    cancellation_reason = (form.get("cancellation_reason") or "").strip() or None
    is_first_visit = 1 if form.get("is_first_visit") in ("on", "true", "1") else 0

    clean = None
    if not errors:
        clean = (
            parsed["patient_id"],
            parsed["practitioner_id"],
            parsed["appointment_type_id"],
            parsed["time_slot_id"],
            raw["status_code"],
            cancellation_reason,
            is_first_visit,
        )
    return clean, errors


def insert_appointment(clean_values):
    """Run the parameterised INSERT. Returns (new_id, friendly_error)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(SQL_INSERT_APPOINTMENT, clean_values)
            conn.commit()
            return cursor.lastrowid, None
        except MySQLError as exc:
            conn.rollback()
            return None, friendly_db_error(exc)
        finally:
            cursor.close()
    finally:
        conn.close()


def friendly_db_error(exc):
    """Translate a MySQL driver error into a user-appropriate message."""
    msg = str(exc)
    # Error 1062: duplicate key (here: the UNIQUE time_slot_id constraint).
    if getattr(exc, "errno", None) == 1062:
        if "time_slot_id" in msg:
            return ("That time slot has already been booked (duplicate "
                    "time_slot_id); no record was added.")
        return ("This record duplicates an existing unique value; "
                "no record was added.")
    # Error 1452: foreign-key constraint failure.
    if getattr(exc, "errno", None) == 1452:
        return ("The data references a patient, practitioner, appointment "
                "type, time slot or status that does not exist (foreign-key "
                "constraint); no record was added.")
    # Error 1048: NOT NULL violation.
    if getattr(exc, "errno", None) == 1048:
        return ("A mandatory (NOT NULL) column was missing; no record was added.")
    return f"Database rejected the insert ({msg}); no record was added."


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

EMPTY_REFS = {"patients": [], "practitioners": [], "appointment_types": [],
              "time_slots": [], "statuses": []}


@app.route("/", methods=["GET", "POST"])
def index():
    alert = None
    form_data = {}

    try:
        refs, valid_sets, _ = fetch_reference_data()
    except MySQLError as exc:
        return render_template(
            "index.html",
            refs=EMPTY_REFS,
            alert={"type": "danger",
                   "text": (f"Cannot connect to the database: {exc}. "
                            "The form cannot be used until the database "
                            "is reachable.")},
            form_data={},
        )

    if request.method == "POST":
        form_data = request.form.to_dict(flat=True)

        clean_values, errors = validate_form(form_data, valid_sets)
        if errors:
            alert = {"type": "danger",
                     "text": "Insert rejected: " + " ".join(errors)}
        else:
            new_id, db_error = insert_appointment(clean_values)
            if db_error:
                alert = {"type": "danger", "text": "Insert failed: " + db_error}
            else:
                alert = {
                    "type": "success",
                    "text": (f"Success! A new Appointment record "
                             f"(appointment_id = {new_id}) has been inserted."),
                }
                form_data = {}
                # Refresh so the newly-booked slot is displayed correctly.
                refs, valid_sets, _ = fetch_reference_data()

    return render_template("index.html", refs=refs, alert=alert,
                           form_data=form_data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("APP_PORT", "8000")),
            debug=False)

