# HotDoc Mock — SIT772 Task 9.2D (User Interface and Embedded SQL)

A small **Flask** web application with an HTML form that inserts one record
into the **`Appointment`** table of the HotDoc database designed in Task 7.2C.

- All five mandatory columns (`patient_id`, `practitioner_id`,
  `appointment_type_id`, `time_slot_id`, `status_code`) are chosen from
  dropdowns populated live from the database; `is_first_visit` is a checkbox
  and `cancellation_reason` is optional text.
- Input is **validated on the server before the INSERT is issued** (mandatory
  fields present, ids are positive integers, foreign keys exist, the time slot
  exists and is still available). Invalid input shows a **red** alert and no
  row is added; a valid submit performs a parameterised `INSERT` and shows a
  **green** confirmation with the new `appointment_id`.
- The INSERT uses bound parameters (`%s`), never string concatenation.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Flask application: routes, embedded SQL, validation |
| `templates/index.html` | The appointment form (Bootstrap 5) |
| `requirements.txt` | Python dependencies |
| `Dockerfile` / `.dockerignore` | Container image (listens on port 8000) |
| `env.example` | Template for the git-ignored local `.env` |

## 1. Prepare the database

On the MySQL VM (or local MySQL), run the Task 7.2C scripts as the
`hotdoc_user` schema owner:

```bash
mysql -u root -p < planning/7.2c/init.sql
mysql -u root -p hotdoc_db < planning/7.2c/populate5.sql
mysql -u root -p hotdoc_db < planning/7.2c/tasks.sql   # adds is_first_visit
```

The five seeded time slots are all already booked, so for the **successful**
video demonstration insert one extra available slot first:

```sql
-- A new bookable slot for practitioner 1 (adjust datetimes as desired)
INSERT INTO TimeSlot (practitioner_id, slot_start_time, slot_end_time, is_available)
VALUES (1, '2026-09-20 09:00:00', '2026-09-20 09:15:00', TRUE);
```

## 2. Run locally

```bash
python -m venv .venv
source .venv/Scripts/activate        # Windows Git Bash
pip install -r requirements.txt

cp env.example .env                  # then edit .env with the real DB password
python app.py
```

Open <http://127.0.0.1:8000>.

### Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `DB_HOST` | `127.0.0.1` | MySQL host |
| `DB_PORT` | `3306` | MySQL port |
| `DB_USER` | `hotdoc_user` | DB user |
| `DB_PASSWORD` | _(empty)_ | DB password — **never commit it** |
| `DB_NAME` | `hotdoc_db` | Schema name |
| `APP_PORT` | `8000` | HTTP listen port |

## 3. Run with Docker

```bash
docker build -t hotdoc-app:latest .
docker run --rm -p 8000:8000 --env-file .env hotdoc-app:latest
```

## 4. Video demonstration checklist

1. Show the table first:
   `mysql -u hotdoc_user -p hotdoc_db -e "SELECT * FROM Appointment;"`
2. **Unsuccessful:** load the form, leave a mandatory dropdown on
   "-- please select --" (or pick an already-booked slot), click **Insert**,
   show the red alert, and re-run the SELECT to prove the row count is
   unchanged.
3. **Successful:** select patient / practitioner / type / the new available
   slot / status, click **Insert**, show the green confirmation, and re-run
   the SELECT to show the new row.

## Security notes

- No credentials are stored in source or git. Local secrets live in `.env`
  (git-ignored); in Kubernetes the password will be supplied via a Secret
  created out-of-band (`kubectl create secret generic ...
  --from-literal=db-password=...`).
- `planning/` is git-ignored and was never pushed (it contains unit PDFs and
  infrastructure notes).

## Still to be finalised (infra)

`app-k8s.yaml` (secret-free manifest), `Jenkinsfile`, and the real MySQL VM
IP / image-transfer path between Jenkins (`10.10.10.100`) and the cluster node
(`10.10.10.10`) are added once those details are confirmed.
