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
| `app-k8s.yaml` | Kubernetes ConfigMap, Deployment and NodePort Service (no secrets) |
| `Jenkinsfile` | CI/CD pipeline: build, push to Docker Hub, deploy to Kubernetes |

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

## 4. Kubernetes + Jenkins CI/CD

Architecture:

```
local --push--> GitHub --> Jenkins (10.10.10.100)
                              |  docker build
                              |  docker push -> Docker Hub (bronardo/hotdoc-app)
                              v  kubectl (kubeconfig)
                        K8s node (10.10.10.10) -- pull image --> NodePort 30080
                              |
                              v
                        MySQL VM (10.10.10.20:3306, hotdoc_db)
```

### One-time infrastructure setup

1. **MySQL VM (`10.10.10.20`)** — load the Task 7.2C schema and seed data,
   create the application user reachable from the pod network, and make MySQL
   listen on the VNet interface:

   ```sql
   CREATE DATABASE IF NOT EXISTS hotdoc_db;
   CREATE USER 'hotdoc_user'@'%' IDENTIFIED BY '<strong-password>';
   GRANT ALL PRIVILEGES ON hotdoc_db.* TO 'hotdoc_user'@'%';
   FLUSH PRIVILEGES;
   ```

   ```bash
   mysql -u root -p hotdoc_db < planning/7.2c/init.sql
   mysql -u hotdoc_user -p hotdoc_db < planning/7.2c/populate5.sql
   mysql -u hotdoc_user -p hotdoc_db < planning/7.2c/tasks.sql
   # one extra AVAILABLE slot for the successful-insert demonstration:
   mysql -u hotdoc_user -p hotdoc_db -e \
     "INSERT INTO TimeSlot (practitioner_id, slot_start_time, slot_end_time, is_available) \
      VALUES (1, '2026-09-20 09:00:00', '2026-09-20 09:15:00', TRUE);"
   ```

   Ensure `bind-address = 0.0.0.0` in `my.cnf` and that TCP 3306 is open to
   the cluster node / pod subnet.

2. **Jenkins server (`10.10.10.100`)** — copy the cluster kubeconfig so the
   `jenkins` user can run `kubectl` against `10.10.10.10`:

   ```bash
   sudo mkdir -p /var/lib/jenkins/.kube
   # copy admin.conf from 10.10.10.10 to /var/lib/jenkins/.kube/config
   sudo chown -R jenkins:jenkins /var/lib/jenkins/.kube
   sudo -u jenkins kubectl --kubeconfig=/var/lib/jenkins/.kube/config get nodes
   ```

3. **Jenkins credentials** (already configured):
   - `docker-hub-creds` — Docker Hub username (`bronardo`) + password/token;
     used both to push the image and to create the `dockerhub-registry`
     image-pull Secret.
   - `dbuser_hotdoc_user` — MySQL username (`hotdoc_user`) + password; the
     pipeline turns it into the `mysql-vm-secret` Secret
     (`db-username`, `db-password`). No DB password is stored in git.
   - `k8s-node-ip-secret` — **Secret text** holding only the cluster node IP
     (`10.10.10.10`); bound via `credentials()` and used as
     `--server=https://<ip>:6443` on every `kubectl` call, so no node IP is
     hard-coded in the pipeline.

### What the pipeline does (`Jenkinsfile`)

1. Checkout from GitHub.
2. Build `bronardo/hotdoc-app:${BUILD_NUMBER}` and `:latest`.
3. Push both tags to Docker Hub.
4. Create/update `mysql-vm-secret` and `dockerhub-registry` on the cluster
   (`kubectl create secret ... --dry-run=client -o yaml | kubectl apply -f -`).
5. Substitute `__IMAGE_TAG__` in `app-k8s.yaml` with the build number and
   `kubectl apply` (the new immutable image tag triggers the rollout). All
   `kubectl` calls target the node IP from `k8s-node-ip-secret` via
   `--server=https://<ip>:6443`.
6. Wait for `kubectl rollout status` (120 s timeout).

After a successful build the UI is at **http://10.10.10.10:30080**.

### Files

- `app-k8s.yaml` — ConfigMap (host `10.10.10.20`, port, db name), Deployment
  (env from ConfigMap + `mysql-vm-secret`, readiness/liveness probes,
  `imagePullSecrets`), NodePort Service 30080. **Contains no secrets.**
- `Jenkinsfile` — the pipeline above; every secret is accessed through
  Jenkins `withCredentials` and never echoed or written to git.

## 5. Video demonstration checklist

1. Show the table first:
   `mysql -u hotdoc_user -p hotdoc_db -e "SELECT * FROM Appointment;"`
2. **Unsuccessful:** load the form, leave a mandatory dropdown on
   "-- please select --" (or pick an already-booked slot), click **Insert**,
   show the red alert, and re-run the SELECT to prove the row count is
   unchanged.
3. **Successful:** select patient / practitioner / type / the new available
   slot / status, click **Insert**, show the green confirmation, and re-run
   the SELECT to show the new row.

## 6. Security notes

- No credentials are stored in source or git. Local development secrets live
  in `.env` (git-ignored); the Kubernetes password is stored in the
  `mysql-vm-secret` Secret, which the pipeline creates at deploy time from the
  restricted Jenkins credential `dbuser_hotdoc_user` (never printed to logs or
  written to the manifest).
- The Docker Hub credential `docker-hub-creds` is used only inside
  `withCredentials` blocks (push + image-pull Secret creation); the database
  credential `dbuser_hotdoc_user` and the node IP `k8s-node-ip-secret` are
  likewise bound only through Jenkins credentials — none appear in git, and
  secret-bearing commands run without shell xtrace.
- `planning/` is git-ignored and was never pushed (it contains unit PDFs and
  infrastructure notes).
