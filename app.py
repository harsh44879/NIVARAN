from flask import (
    Flask,
    render_template,
    request,
    redirect,
    flash,
    session,
    url_for,
    abort,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, timedelta
from functools import wraps
from pathlib import Path
import os
import re
import secrets

from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader

load_dotenv()

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True
)
import re
import secrets


app = Flask(__name__)

# Environment configuration
APP_ENV = os.environ.get("APP_ENV", "development").lower()
IS_PRODUCTION = APP_ENV == "production"

# Secret key: mandatory in production
SECRET_KEY = os.environ.get("SECRET_KEY")

if IS_PRODUCTION and not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be configured in production.")

if not SECRET_KEY:
    SECRET_KEY = "local-development-only-key"

app.config["SECRET_KEY"] = SECRET_KEY

# Database configuration
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace(
            "postgres://", "postgresql+psycopg://", 1
        )
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace(
            "postgresql://", "postgresql+psycopg://", 1
        )

app.config["SQLALCHEMY_DATABASE_URI"] = (
    DATABASE_URL if DATABASE_URL else "sqlite:///user.db"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# File upload limit: 5 MB
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

# Secure session cookies
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION


db = SQLAlchemy(app)

UPLOAD_FOLDER = Path(app.root_path) / "static" / "uploads"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
def get_image_url(image_ref):
    if not image_ref:
        return None

    # New Cloudinary images
    if image_ref.startswith("nivaran/"):
        return cloudinary.utils.cloudinary_url(
            image_ref,
            secure=True
        )[0]

    # Existing local images
    return url_for("static", filename=f"uploads/{image_ref}")


app.jinja_env.globals["image_url"] = get_image_url

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

# Canonical departments and their valid complaint issue categories
ALLOWED_CATEGORIES = {
    "Water Department": [
        "Water Leakage",
        "Dirty Water",
        "Broken Pipeline",
        "No Water Supply",
        "Low Water Pressure",
    ],
    "Electricity Department": [
        "Street Light Not Working",
        "Power Cut",
        "Sparking Wire",
        "Transformer Issue",
        "Electric Pole Damage",
    ],
    "Road Department": [
        "Potholes",
        "Road Cracks",
        "Water Logging On Road",
        "Damaged Footpath",
    ],
}
ALLOWED_DEPARTMENTS = set(ALLOWED_CATEGORIES.keys())
VALID_STATUSES = {"Pending", "In Progress", "Resolved"}
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DEFAULT_DEPARTMENT_SLA_DAYS = {
    "Water Department": 3,
    "Electricity Department": 2,
    "Road Department": 7,
}


# -------------------- DATABASE MODELS --------------------
class User(db.Model):
    sno = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    pincode = db.Column(db.String(6), nullable=True)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)


class cmpl_dets(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    department = db.Column(db.String(100), nullable=False)
    complaint_category = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    area = db.Column(db.String(100), nullable=False)
    landmark = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200), nullable=False)
    pincode = db.Column(db.String(6), nullable=True)
    assigned_emp_id = db.Column(db.Integer, nullable=True)
    assigned_worker_id = db.Column(db.Integer, nullable=True)
    assigned_at = db.Column(db.DateTime, nullable=True)
    worker_started_at = db.Column(db.DateTime, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolution_notes = db.Column(db.Text, nullable=True)
    image = db.Column(db.String(300), nullable=True)
    after_image = db.Column(db.String(300), nullable=True)
    status = db.Column(db.String(50), default="Pending", nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)

    # Phase 2: Deadline Tracking & Escalation Fields
    original_estimated_date = db.Column(db.DateTime, nullable=True)
    current_estimated_date = db.Column(db.DateTime, nullable=True)
    is_escalated = db.Column(db.Boolean, default=False, nullable=False)
    escalation_level = db.Column(db.String(50), nullable=True)


class employee_dets(db.Model):
    emp_id = db.Column(db.Integer, primary_key=True)
    emp_name = db.Column(db.String(100), nullable=False)
    emp_email = db.Column(db.String(100), unique=True, nullable=False)
    emp_password = db.Column(db.String(255), nullable=False)
    emp_dprtmnt = db.Column(db.String(100), nullable=False)
    pincode = db.Column(db.String(6), nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)


class FieldWorker(db.Model):
    __tablename__ = "field_worker"
    worker_id = db.Column(db.Integer, primary_key=True)
    worker_name = db.Column(db.String(100), nullable=False)
    worker_email = db.Column(db.String(100), unique=True, nullable=False)
    worker_password = db.Column(db.String(255), nullable=False)
    worker_dprtmnt = db.Column(db.String(100), nullable=False)
    pincode = db.Column(db.String(6), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)


class ComplaintDelayHistory(db.Model):
    __tablename__ = "complaint_delay_history"
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, nullable=False)
    previous_estimated_date = db.Column(db.DateTime, nullable=True)
    revised_estimated_date = db.Column(db.DateTime, nullable=False)
    delay_reason = db.Column(db.Text, nullable=False)
    officer_id = db.Column(db.Integer, nullable=True)
    officer_name = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PublicNotice(db.Model):
    __tablename__ = "public_notices"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    department = db.Column(db.String(100), nullable=False)
    pincode = db.Column(db.String(6), nullable=False)
    affected_locality = db.Column(db.String(150), nullable=True)
    status = db.Column(db.String(20), default="published", nullable=False)
    scheduled_start = db.Column(db.DateTime, nullable=True)
    scheduled_end = db.Column(db.DateTime, nullable=True)
    created_by_emp_id = db.Column(db.Integer, nullable=True)
    created_by_emp_name = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_effective_status(self):
        if self.status in ("cancelled", "expired", "draft"):
            return self.status
        now = datetime.utcnow()
        if self.scheduled_end and now > self.scheduled_end:
            return "expired"
        if self.scheduled_start and now < self.scheduled_start:
            return "upcoming"
        return "active"


class ComplaintEscalation(db.Model):
    __tablename__ = "complaint_escalations"
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, nullable=False)
    escalated_by_emp_id = db.Column(db.Integer, nullable=True)
    escalated_by_name = db.Column(db.String(100), nullable=True)
    reason = db.Column(db.Text, nullable=False)
    escalation_level = db.Column(db.String(50), default="Supervisor Review", nullable=False)
    review_state = db.Column(db.String(50), default="Under Review", nullable=False)
    action_notes = db.Column(db.Text, nullable=True)
    escalated_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# -------------------- HELPERS & DECORATORS --------------------
def citizen_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id") or session.get("role") != "citizen":
            flash("Please log in as a citizen.")
            return redirect(url_for("login_one"))
        return view(*args, **kwargs)
    return wrapped


def employee_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("emp_id") or session.get("role") != "employee":
            flash("Please log in to the government portal.")
            return redirect(url_for("emp_login"))
        return view(*args, **kwargs)
    return wrapped


def worker_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("worker_id") or session.get("role") != "worker":
            flash("Please log in to the Field Worker Portal.")
            return redirect(url_for("worker_login"))
        return view(*args, **kwargs)
    return wrapped


def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_image(upload, owner_prefix):
    if not upload or not upload.filename:
        return None

    if not allowed_image(upload.filename):
        raise ValueError(
            "Invalid file format. Please upload a PNG, JPG, JPEG, or WEBP image."
        )

    safe_name = secure_filename(upload.filename)

    if not safe_name:
        raise ValueError("The image filename is invalid.")

    unique_name = f"{owner_prefix}_{secrets.token_hex(8)}_{safe_name}"

    try:
        result = cloudinary.uploader.upload(
            upload,
            public_id=f"nivaran/{unique_name.rsplit('.', 1)[0]}",
            resource_type="image",
            overwrite=False
        )

        return result["public_id"]

    except Exception as exc:
        app.logger.exception("Cloudinary image upload failed")
        raise ValueError(
            "Image upload failed. Please try again."
        ) from exc


def is_valid_pincode(pincode):
    return bool(pincode and re.fullmatch(r"^\d{6}$", pincode))


def get_deadline_info(c):
    """
    Computes derived deadline attributes without altering database status.
    Resolved complaints are never marked overdue.
    Complaints with no deadline return 'Not yet estimated'.
    """
    if not c or not getattr(c, "current_estimated_date", None):
        return {
            "has_deadline": False,
            "is_overdue": False,
            "label": "Not yet estimated",
            "badge_class": "bg-secondary",
            "days_diff": 0,
            "formatted_date": "Not estimated",
        }

    target_date = c.current_estimated_date.date()
    today = datetime.utcnow().date()
    diff_days = (target_date - today).days
    formatted_date = c.current_estimated_date.strftime("%d-%m-%Y")

    if c.status == "Resolved":
        return {
            "has_deadline": True,
            "is_overdue": False,
            "label": f"Resolved (Target: {formatted_date})",
            "badge_class": "bg-success",
            "days_diff": diff_days,
            "formatted_date": formatted_date,
        }

    if diff_days < 0:
        overdue_by = abs(diff_days)
        return {
            "has_deadline": True,
            "is_overdue": True,
            "label": f"Overdue by {overdue_by} day{'s' if overdue_by != 1 else ''}",
            "badge_class": "bg-danger",
            "days_diff": diff_days,
            "formatted_date": formatted_date,
        }
    elif diff_days == 0:
        return {
            "has_deadline": True,
            "is_overdue": False,
            "label": "Due today",
            "badge_class": "bg-warning text-dark",
            "days_diff": 0,
            "formatted_date": formatted_date,
        }
    else:
        return {
            "has_deadline": True,
            "is_overdue": False,
            "label": f"{diff_days} day{'s' if diff_days != 1 else ''} remaining",
            "badge_class": "bg-info text-dark",
            "days_diff": diff_days,
            "formatted_date": formatted_date,
        }


@app.context_processor
def inject_globals():
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    return dict(
        get_deadline_info=get_deadline_info,
        today_str=today_str,
    )


# -------------------- CITIZEN ROUTES --------------------
@app.route("/")
def home():
    return render_template("base.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        pincode = request.form.get("pincode", "").strip()

        if not all([name, email, password]):
            flash("Please complete all required fields.")
            return redirect(url_for("signup"))
        if not EMAIL_REGEX.match(email):
            flash("Please enter a valid email address.")
            return redirect(url_for("signup"))
        if len(password) < 8:
            flash("Password must contain at least 8 characters.")
            return redirect(url_for("signup"))
        if pincode and not is_valid_pincode(pincode):
            flash("Please enter a valid 6-digit residential pincode.")
            return redirect(url_for("signup"))
        if User.query.filter_by(email=email).first():
            flash("An account with this email already exists.")
            return redirect(url_for("signup"))

        user = User(
            name=name,
            email=email,
            password=generate_password_hash(password),
            pincode=pincode if pincode else None,
        )
        try:
            db.session.add(user)
            db.session.commit()
            flash("Account created successfully. Please log in.")
            return redirect(url_for("login_one"))
        except Exception:
            db.session.rollback()
            flash("Registration could not be completed. Please try again.")
            return redirect(url_for("signup"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login_one():
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password, password):
            flash("Invalid email or password.")
        else:
            session.clear()
            session["user_id"] = user.sno
            session["email"] = user.email
            session["name"] = user.name
            session["pincode"] = user.pincode or ""
            session["role"] = "citizen"
            flash(f"Welcome back, {user.name}!")
            return redirect(url_for("dashboard"))

    return render_template("login.html", email=email)


@app.route("/dashboard")
@citizen_required
def dashboard():
    return render_template("dashboard.html", name=session.get("name"))


@app.route("/complaint", methods=["GET", "POST"])
@citizen_required
def complaint_one():
    default_pincode = session.get("pincode", "")
    if request.method == "POST":
        department = request.form.get("department", "").strip()
        complaint_category = request.form.get("complaint_category", "").strip()
        description = request.form.get("description", "").strip()
        area = request.form.get("area", "").strip()
        landmark = request.form.get("landmark", "").strip()
        address = request.form.get("address", "").strip()
        pincode = request.form.get("pincode", "").strip()

        # Validate required fields
        if not all([department, complaint_category, description, area, landmark, address, pincode]):
            flash("Please complete all required fields.")
            return redirect(url_for("complaint_one"))

        if department not in ALLOWED_CATEGORIES:
            flash("Please choose a valid department.")
            return redirect(url_for("complaint_one"))

        if complaint_category not in ALLOWED_CATEGORIES[department]:
            flash("The selected complaint category does not match the chosen department.")
            return redirect(url_for("complaint_one"))

        if not is_valid_pincode(pincode):
            flash("Please enter a valid 6-digit complaint location pincode.")
            return redirect(url_for("complaint_one"))

        # Optional citizen image upload
        image_name = None
        file = request.files.get("image")
        if file and file.filename:
            try:
                image_name = save_uploaded_image(file, f"user_{session['user_id']}")
            except ValueError as exc:
                flash(str(exc))
                return redirect(url_for("complaint_one"))

        # Automatic Routing: Look up government employee responsible for this department & pincode
        assigned_officer = employee_dets.query.filter_by(
            emp_dprtmnt=department, pincode=pincode
        ).first()
        assigned_emp_id = assigned_officer.emp_id if assigned_officer else None

        new_complaint = cmpl_dets(
            user_id=session["user_id"],
            department=department,
            complaint_category=complaint_category,
            description=description,
            area=area,
            landmark=landmark,
            address=address,
            pincode=pincode,
            assigned_emp_id=assigned_emp_id,
            image=image_name,
            status="Pending",
        )

        try:
            db.session.add(new_complaint)
            db.session.commit()
            if assigned_officer:
                flash(
                    f"Complaint registered successfully and assigned to Officer {assigned_officer.emp_name} ({department}, Area: {pincode})."
                )
            else:
                flash(
                    f"Complaint registered successfully. Awaiting officer assignment for {department} in area {pincode}."
                )
            return redirect(url_for("track"))
        except Exception:
            db.session.rollback()
            flash("Unable to register complaint due to a database error.")
            return redirect(url_for("complaint_one"))

    return render_template(
        "complaint.html",
        default_pincode=default_pincode,
        categories=ALLOWED_CATEGORIES,
    )


@app.route("/complaint/<int:id>")
@citizen_required
def More_CmplDetails(id):
    user_id = session["user_id"]
    complaint = cmpl_dets.query.filter_by(id=id, user_id=user_id).first()
    if not complaint:
        flash("Unauthorized: You do not have permission to view this complaint.")
        return redirect(url_for("track"))

    assigned_worker = (
        FieldWorker.query.get(complaint.assigned_worker_id)
        if complaint.assigned_worker_id
        else None
    )
    assigned_officer = (
        employee_dets.query.get(complaint.assigned_emp_id)
        if complaint.assigned_emp_id
        else None
    )

    delays = (
        ComplaintDelayHistory.query.filter_by(complaint_id=id)
        .order_by(ComplaintDelayHistory.created_at.desc())
        .all()
    )
    latest_delay = delays[0] if delays else None

    escalations = (
        ComplaintEscalation.query.filter_by(complaint_id=id)
        .order_by(ComplaintEscalation.escalated_at.desc())
        .all()
    )
    latest_escalation = escalations[0] if escalations else None

    return render_template(
        "complaint_details.html",
        complaint=complaint,
        assigned_worker=assigned_worker,
        assigned_officer=assigned_officer,
        delays=delays,
        latest_delay=latest_delay,
        escalations=escalations,
        latest_escalation=latest_escalation,
    )


@app.route("/track")
@citizen_required
def track():
    user_id = session["user_id"]
    complaints = (
        cmpl_dets.query.filter_by(user_id=user_id)
        .order_by(cmpl_dets.date_created.desc())
        .all()
    )
    return render_template("track.html", complaints=complaints)


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("login_one"))


# -------------------- PUBLIC NOTICES & REPORT ROUTES --------------------
@app.route("/notices")
def notices():
    filter_pincode = request.args.get("pincode", "").strip()
    filter_dept = request.args.get("department", "").strip()

    # If citizen logged in and no pincode filter supplied, default to citizen's residential pincode
    if not filter_pincode and session.get("pincode"):
        filter_pincode = session.get("pincode")

    query = PublicNotice.query
    # For non-officer viewers, show only published notices
    if session.get("role") != "employee":
        query = query.filter_by(status="published")

    if filter_pincode:
        query = query.filter_by(pincode=filter_pincode)
    if filter_dept:
        query = query.filter_by(department=filter_dept)

    notices_list = query.order_by(PublicNotice.created_at.desc()).all()

    return render_template(
        "notices.html",
        notices=notices_list,
        current_pincode=filter_pincode,
        current_dept=filter_dept,
    )


@app.route("/complaint/<int:id>/report")
def complaint_report(id):
    complaint = cmpl_dets.query.get(id)
    if not complaint:
        flash("Complaint not found.")
        return redirect(url_for("home"))

    role = session.get("role")
    # Strict role-based authorization check:
    # 1. Citizen must own the complaint
    # 2. Government employee must match complaint's department and pincode
    # 3. Field worker must be assigned to this specific complaint
    is_authorized = False
    if role == "citizen" and session.get("user_id") == complaint.user_id:
        is_authorized = True
    elif role == "employee" and (
        session.get("emp_department") == complaint.department
        and session.get("emp_pincode") == complaint.pincode
    ):
        is_authorized = True
    elif role == "worker" and session.get("worker_id") == complaint.assigned_worker_id:
        is_authorized = True

    if not is_authorized:
        flash("Unauthorized: You do not have permission to view or download this audit report.")
        if role == "employee":
            return redirect(url_for("gov_dashboard"))
        elif role == "worker":
            return redirect(url_for("worker_dashboard"))
        elif role == "citizen":
            return redirect(url_for("track"))
        else:
            return redirect(url_for("login_one"))

    citizen = User.query.get(complaint.user_id)
    assigned_officer = (
        employee_dets.query.get(complaint.assigned_emp_id)
        if complaint.assigned_emp_id
        else None
    )
    assigned_worker = (
        FieldWorker.query.get(complaint.assigned_worker_id)
        if complaint.assigned_worker_id
        else None
    )
    delay_history = (
        ComplaintDelayHistory.query.filter_by(complaint_id=id)
        .order_by(ComplaintDelayHistory.created_at.asc())
        .all()
    )
    escalations = (
        ComplaintEscalation.query.filter_by(complaint_id=id)
        .order_by(ComplaintEscalation.escalated_at.asc())
        .all()
    )
    deadline_info = get_deadline_info(complaint)

    return render_template(
        "complaint_report.html",
        complaint=complaint,
        citizen=citizen,
        assigned_officer=assigned_officer,
        assigned_worker=assigned_worker,
        delays=delay_history,
        delay_history=delay_history,
        escalations=escalations,
        deadline_info=deadline_info,
        generated_at=datetime.utcnow(),
        user_role=role,
    )


# -------------------- GOVERNMENT EMPLOYEE ROUTES --------------------
@app.route("/gov_signup", methods=["GET", "POST"])
def emp_signup():
    if request.method == "POST":
        name = request.form.get("emp_name", "").strip()
        email = request.form.get("emp_email", "").strip().lower()
        password = request.form.get("emp_password", "")
        department = request.form.get("emp_dprtmnt", "").strip()
        pincode = request.form.get("pincode", "").strip()

        if not all([name, email, password, department, pincode]):
            flash("Please complete all required fields.")
            return redirect(url_for("emp_signup"))
        if not EMAIL_REGEX.match(email):
            flash("Please enter a valid official email address.")
            return redirect(url_for("emp_signup"))
        if department not in ALLOWED_DEPARTMENTS:
            flash("Please choose a valid department.")
            return redirect(url_for("emp_signup"))
        if len(password) < 8:
            flash("Password must contain at least 8 characters.")
            return redirect(url_for("emp_signup"))
        if not is_valid_pincode(pincode):
            flash("Please enter a valid 6-digit service area pincode.")
            return redirect(url_for("emp_signup"))
        if employee_dets.query.filter_by(emp_email=email).first():
            flash("An employee account with this email already exists.")
            return redirect(url_for("emp_signup"))

        emp = employee_dets(
            emp_name=name,
            emp_email=email,
            emp_password=generate_password_hash(password),
            emp_dprtmnt=department,
            pincode=pincode,
        )
        try:
            db.session.add(emp)
            db.session.commit()
            flash("Official account created successfully. Please log in.")
            return redirect(url_for("emp_login"))
        except Exception:
            db.session.rollback()
            flash("Registration could not be completed. Please try again.")
            return redirect(url_for("emp_signup"))

    return render_template("gov_signup.html")


@app.route("/gov_login", methods=["GET", "POST"])
def emp_login():
    email = ""
    if request.method == "POST":
        email = request.form.get("emp_email", "").strip().lower()
        password = request.form.get("emp_password", "")
        employee = employee_dets.query.filter_by(emp_email=email).first()

        if not employee or not check_password_hash(employee.emp_password, password):
            flash("Invalid official email or password.")
        else:
            session.clear()
            session["emp_id"] = employee.emp_id
            session["emp_email"] = employee.emp_email
            session["emp_name"] = employee.emp_name
            session["emp_department"] = employee.emp_dprtmnt
            session["emp_pincode"] = str(employee.pincode).zfill(6)
            session["role"] = "employee"
            flash(f"Welcome, Officer {employee.emp_name}!")
            return redirect(url_for("gov_dashboard"))

    return render_template("loginpagegov.html", email=email)


@app.route("/gov-dashboard")
@employee_required
def gov_dashboard():
    department = session["emp_department"]
    pincode = session["emp_pincode"]

    # Filter complaints strictly by employee's department AND service-area pincode
    complaints = cmpl_dets.query.filter_by(
        department=department, pincode=pincode
    ).order_by(cmpl_dets.date_created.desc()).all()

    total = len(complaints)
    pending = sum(1 for c in complaints if c.status == "Pending")
    in_progress = sum(1 for c in complaints if c.status == "In Progress")
    resolved = sum(1 for c in complaints if c.status == "Resolved")

    today = datetime.utcnow().date()
    overdue_count = sum(
        1
        for c in complaints
        if c.status != "Resolved"
        and c.current_estimated_date
        and c.current_estimated_date.date() < today
    )
    escalated_count = sum(1 for c in complaints if c.is_escalated)

    worker_map = {w.worker_id: w.worker_name for w in FieldWorker.query.all()}

    return render_template(
        "dashboardgov.html",
        complaints=complaints,
        total=total,
        pending=pending,
        in_progress=in_progress,
        resolved=resolved,
        overdue_count=overdue_count,
        escalated_count=escalated_count,
        worker_map=worker_map,
    )


@app.route("/gov-complaint/<int:id>")
@employee_required
def gov_complaint_details(id):
    department = session["emp_department"]
    pincode = session["emp_pincode"]

    # Ensure logged-in employee can only access complaints in their department & pincode
    complaint = cmpl_dets.query.filter_by(
        id=id, department=department, pincode=pincode
    ).first()

    if not complaint:
        flash("Unauthorized: This complaint is outside your assigned department or service area.")
        return redirect(url_for("gov_dashboard"))

    assigned_worker = (
        FieldWorker.query.get(complaint.assigned_worker_id)
        if complaint.assigned_worker_id
        else None
    )

    matching_workers = FieldWorker.query.filter_by(
        worker_dprtmnt=department, pincode=pincode, is_active=True
    ).all()

    delay_history = (
        ComplaintDelayHistory.query.filter_by(complaint_id=id)
        .order_by(ComplaintDelayHistory.created_at.desc())
        .all()
    )
    latest_delay = delay_history[0] if delay_history else None

    escalations = (
        ComplaintEscalation.query.filter_by(complaint_id=id)
        .order_by(ComplaintEscalation.escalated_at.desc())
        .all()
    )
    latest_escalation = escalations[0] if escalations else None

    return render_template(
        "gov_complaint_details.html",
        complaint=complaint,
        assigned_worker=assigned_worker,
        matching_workers=matching_workers,
        delay_history=delay_history,
        latest_delay=latest_delay,
        escalations=escalations,
        latest_escalation=latest_escalation,
    )


@app.route("/gov-complaint/<int:id>/set_deadline", methods=["POST"])
@employee_required
def set_complaint_deadline(id):
    department = session["emp_department"]
    pincode = session["emp_pincode"]

    complaint = cmpl_dets.query.filter_by(
        id=id, department=department, pincode=pincode
    ).first()

    if not complaint:
        flash("Unauthorized: You cannot set deadlines for complaints outside your department and pincode.")
        return redirect(url_for("gov_dashboard"))

    date_str = request.form.get("estimated_date", "").strip()
    if not date_str:
        flash("Please provide a valid target resolution date.")
        return redirect(url_for("gov_complaint_details", id=id))

    try:
        target_dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        flash("Invalid date format. Please use the date picker.")
        return redirect(url_for("gov_complaint_details", id=id))

    if target_dt.date() < datetime.utcnow().date():
        flash("Target resolution date cannot be in the past.")
        return redirect(url_for("gov_complaint_details", id=id))

    if not complaint.original_estimated_date:
        complaint.original_estimated_date = target_dt
    complaint.current_estimated_date = target_dt

    try:
        db.session.commit()
        flash(f"Target resolution deadline set to {target_dt.strftime('%d-%m-%Y')} successfully.")
    except Exception:
        db.session.rollback()
        flash("Failed to save estimated resolution date.")

    return redirect(url_for("gov_complaint_details", id=id))


@app.route("/gov-complaint/<int:id>/revise_deadline", methods=["POST"])
@employee_required
def revise_complaint_deadline(id):
    department = session["emp_department"]
    pincode = session["emp_pincode"]

    complaint = cmpl_dets.query.filter_by(
        id=id, department=department, pincode=pincode
    ).first()

    if not complaint:
        flash("Unauthorized: You cannot revise deadlines for complaints outside your department and pincode.")
        return redirect(url_for("gov_dashboard"))

    date_str = request.form.get("revised_date", "").strip()
    delay_reason = request.form.get("delay_reason", "").strip()

    if not date_str:
        flash("Please select a revised target resolution date.")
        return redirect(url_for("gov_complaint_details", id=id))

    if not delay_reason:
        flash("A delay explanation is strictly mandatory when revising the resolution target.")
        return redirect(url_for("gov_complaint_details", id=id))

    try:
        revised_dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        flash("Invalid date format. Please use the date picker.")
        return redirect(url_for("gov_complaint_details", id=id))

    if revised_dt.date() < datetime.utcnow().date():
        flash("Revised completion date cannot be in the past.")
        return redirect(url_for("gov_complaint_details", id=id))

    prev_dt = complaint.current_estimated_date or complaint.original_estimated_date

    delay_record = ComplaintDelayHistory(
        complaint_id=id,
        previous_estimated_date=prev_dt,
        revised_estimated_date=revised_dt,
        delay_reason=delay_reason,
        officer_id=session.get("emp_id"),
        officer_name=session.get("emp_name"),
    )
    db.session.add(delay_record)
    complaint.current_estimated_date = revised_dt

    try:
        db.session.commit()
        flash(f"Resolution target revised to {revised_dt.strftime('%d-%m-%Y')} and delay reason recorded in audit log.")
    except Exception:
        db.session.rollback()
        flash("Failed to record deadline revision due to a database error.")

    return redirect(url_for("gov_complaint_details", id=id))


@app.route("/gov-complaint/<int:id>/escalate", methods=["POST"])
@employee_required
def escalate_complaint(id):
    department = session["emp_department"]
    pincode = session["emp_pincode"]

    complaint = cmpl_dets.query.filter_by(
        id=id, department=department, pincode=pincode
    ).first()

    if not complaint:
        flash("Unauthorized: You cannot escalate complaints outside your department and pincode.")
        return redirect(url_for("gov_dashboard"))

    reason = request.form.get("reason", "").strip()
    level = request.form.get("escalation_level", "Supervisor Review").strip()

    if not reason:
        flash("Please provide a reason for grievance escalation.")
        return redirect(url_for("gov_complaint_details", id=id))

    escalation = ComplaintEscalation(
        complaint_id=id,
        escalated_by_emp_id=session.get("emp_id"),
        escalated_by_name=session.get("emp_name"),
        reason=reason,
        escalation_level=level,
        review_state="Under Review",
    )
    complaint.is_escalated = True
    complaint.escalation_level = level

    db.session.add(escalation)
    try:
        db.session.commit()
        flash(f"Grievance #{id} successfully escalated to {level}.")
    except Exception:
        db.session.rollback()
        flash("Failed to escalate grievance due to a database error.")

    return redirect(url_for("gov_complaint_details", id=id))


@app.route("/gov-complaint/<int:id>/escalation_review", methods=["POST"])
@employee_required
def review_escalation(id):
    department = session["emp_department"]
    pincode = session["emp_pincode"]

    complaint = cmpl_dets.query.filter_by(
        id=id, department=department, pincode=pincode
    ).first()

    if not complaint:
        flash("Unauthorized access.")
        return redirect(url_for("gov_dashboard"))

    review_state = request.form.get("review_state", "Under Review").strip()
    action_notes = request.form.get("action_notes", "").strip()

    latest_esc = (
        ComplaintEscalation.query.filter_by(complaint_id=id)
        .order_by(ComplaintEscalation.escalated_at.desc())
        .first()
    )

    if latest_esc:
        latest_esc.review_state = review_state
        if action_notes:
            latest_esc.action_notes = action_notes
        latest_esc.updated_at = datetime.utcnow()

    if review_state in ("Action Taken", "Dismissed"):
        complaint.is_escalated = False

    try:
        db.session.commit()
        flash(f"Escalation review state updated to {review_state}.")
    except Exception:
        db.session.rollback()
        flash("Failed to update escalation review state.")

    return redirect(url_for("gov_complaint_details", id=id))


@app.route("/gov-complaint/<int:id>/assign", methods=["POST"])
@employee_required
def assign_field_worker(id):
    department = session["emp_department"]
    pincode = session["emp_pincode"]

    complaint = cmpl_dets.query.filter_by(
        id=id, department=department, pincode=pincode
    ).first()

    if not complaint:
        flash("Unauthorized: You cannot assign workers to complaints outside your department and pincode.")
        return redirect(url_for("gov_dashboard"))

    worker_id = request.form.get("worker_id")
        
    if not worker_id:
            flash("Please select a field worker.")
            return redirect(url_for("gov_complaint_details", id=id))
        
    try:
        worker_id = int(worker_id)
    except ValueError:
            flash("Invalid field worker selected.")
            return redirect(url_for("gov_complaint_details", id=id))

    worker = FieldWorker.query.filter_by(
            worker_id=worker_id,
            worker_dprtmnt=department,
            pincode=pincode,
            is_active=True
        ).first()

    if not worker:
        flash("Selected worker does not belong to your department and service area.")
        return redirect(url_for("gov_complaint_details", id=id))

    complaint.assigned_worker_id = worker.worker_id
    complaint.assigned_at = datetime.utcnow()

    try:
        db.session.commit()
        flash(
            f"Complaint #{id} successfully assigned to field worker {worker.worker_name} (ID: #{worker.worker_id})."
        )
    except Exception:
        db.session.rollback()
        flash("Failed to assign worker due to a database error.")

    return redirect(url_for("gov_complaint_details", id=id))


@app.route("/gov-complaint/<int:id>/status", methods=["POST"])
@employee_required
def update_complaint_status(id):
    department = session["emp_department"]
    pincode = session["emp_pincode"]

    complaint = cmpl_dets.query.filter_by(
        id=id, department=department, pincode=pincode
    ).first()

    if not complaint:
        flash("Unauthorized: You cannot update complaints outside your assigned department and pincode.")
        return redirect(url_for("gov_dashboard"))

    new_status = request.form.get("status", "").strip()
    if new_status not in VALID_STATUSES:
        flash("Invalid complaint status selection.")
        return redirect(url_for("gov_complaint_details", id=id))

    complaint.status = new_status
    if new_status == "Resolved" and not complaint.resolved_at:
        complaint.resolved_at = datetime.utcnow()
    if not complaint.assigned_emp_id:
        complaint.assigned_emp_id = session["emp_id"]

    try:
        db.session.commit()
        flash(f"Complaint #{id} status updated to {new_status} successfully.")
    except Exception:
        db.session.rollback()
        flash("Failed to update status due to a database error.")

    return redirect(url_for("gov_complaint_details", id=id))


@app.route("/gov-notices")
@employee_required
def gov_notices():
    department = session["emp_department"]
    pincode = session["emp_pincode"]
    notices = (
        PublicNotice.query.filter_by(department=department, pincode=pincode)
        .order_by(PublicNotice.created_at.desc())
        .all()
    )
    return render_template("gov_notices.html", notices=notices)


@app.route("/gov-notices/create", methods=["GET", "POST"])
@employee_required
def create_notice():
    department = session["emp_department"]
    pincode = session["emp_pincode"]

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        target_pincode = request.form.get("pincode", pincode).strip()
        affected_locality = request.form.get("affected_locality", "").strip()
        status = request.form.get("status", "published").strip()
        start_str = request.form.get("scheduled_start", "").strip()
        end_str = request.form.get("scheduled_end", "").strip()

        if not title or not description:
            flash("Please provide both a notice title and description.")
            return render_template("gov_notice_form.html", notice=None)

        if not is_valid_pincode(target_pincode):
            flash("Please enter a valid 6-digit target pincode.")
            return render_template("gov_notice_form.html", notice=None)

        scheduled_start = None
        scheduled_end = None
        if start_str:
            try:
                scheduled_start = datetime.strptime(start_str, "%Y-%m-%dT%H:%M")
            except ValueError:
                pass
        if end_str:
            try:
                scheduled_end = datetime.strptime(end_str, "%Y-%m-%dT%H:%M")
            except ValueError:
                pass

        notice = PublicNotice(
            title=title,
            description=description,
            department=department,
            pincode=target_pincode,
            affected_locality=affected_locality,
            status=status,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            created_by_emp_id=session.get("emp_id"),
            created_by_emp_name=session.get("emp_name"),
        )
        db.session.add(notice)
        try:
            db.session.commit()
            flash(f"Public notice '{title}' successfully created.")
            return redirect(url_for("gov_notices"))
        except Exception:
            db.session.rollback()
            flash("Failed to create notice due to a database error.")

    return render_template("gov_notice_form.html", notice=None)


@app.route("/gov-notices/<int:id>/edit", methods=["GET", "POST"])
@employee_required
def edit_notice(id):
    department = session["emp_department"]
    pincode = session["emp_pincode"]
    notice = PublicNotice.query.filter_by(
        id=id, department=department, pincode=pincode
    ).first()

    if not notice:
        flash("Notice not found or unauthorized.")
        return redirect(url_for("gov_notices"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        target_pincode = request.form.get("pincode", notice.pincode).strip()
        affected_locality = request.form.get("affected_locality", "").strip()
        status = request.form.get("status", notice.status).strip()
        start_str = request.form.get("scheduled_start", "").strip()
        end_str = request.form.get("scheduled_end", "").strip()

        if not title or not description:
            flash("Please provide both a notice title and description.")
            return render_template("gov_notice_form.html", notice=notice)

        if not is_valid_pincode(target_pincode):
            flash("Please enter a valid 6-digit target pincode.")
            return render_template("gov_notice_form.html", notice=notice)

        scheduled_start = None
        scheduled_end = None
        if start_str:
            try:
                scheduled_start = datetime.strptime(start_str, "%Y-%m-%dT%H:%M")
            except ValueError:
                pass
        if end_str:
            try:
                scheduled_end = datetime.strptime(end_str, "%Y-%m-%dT%H:%M")
            except ValueError:
                pass

        notice.title = title
        notice.description = description
        notice.pincode = target_pincode
        notice.affected_locality = affected_locality
        notice.status = status
        notice.scheduled_start = scheduled_start
        notice.scheduled_end = scheduled_end
        notice.updated_at = datetime.utcnow()

        try:
            db.session.commit()
            flash(f"Public notice #{id} updated successfully.")
            return redirect(url_for("gov_notices"))
        except Exception:
            db.session.rollback()
            flash("Failed to update notice.")

    return render_template("gov_notice_form.html", notice=notice)


@app.route("/gov-notices/<int:id>/status", methods=["POST"])
@employee_required
def update_notice_status(id):
    department = session["emp_department"]
    pincode = session["emp_pincode"]
    notice = PublicNotice.query.filter_by(
        id=id, department=department, pincode=pincode
    ).first()

    if not notice:
        flash("Notice not found or unauthorized.")
        return redirect(url_for("gov_notices"))

    action = request.form.get("action", "expire").strip()
    if action == "expire":
        notice.status = "expired"
    elif action == "cancel":
        notice.status = "cancelled"
    notice.updated_at = datetime.utcnow()

    try:
        db.session.commit()
        flash(f"Notice #{id} marked as {notice.status}.")
    except Exception:
        db.session.rollback()
        flash("Failed to update notice status.")

    return redirect(url_for("gov_notices"))


@app.route("/gov-logout")
def gov_logout():
    session.clear()
    flash("You have been logged out of the Government Portal.")
    return redirect(url_for("emp_login"))


# -------------------- FIELD WORKER ROUTES --------------------
@app.route("/worker_signup", methods=["GET", "POST"])
def worker_signup():
    if request.method == "POST":
        name = request.form.get("worker_name", "").strip()
        email = request.form.get("worker_email", "").strip().lower()
        password = request.form.get("worker_password", "")
        department = request.form.get("worker_dprtmnt", "").strip()
        pincode = request.form.get("pincode", "").strip()

        if not all([name, email, password, department, pincode]):
            flash("Please complete all required fields.")
            return redirect(url_for("worker_signup"))
        if not EMAIL_REGEX.match(email):
            flash("Please provide a valid worker contact email.")
            return redirect(url_for("worker_signup"))
        if department not in ALLOWED_DEPARTMENTS:
            flash("Please choose a valid department.")
            return redirect(url_for("worker_signup"))
        if len(password) < 8:
            flash("Password must contain at least 8 characters.")
            return redirect(url_for("worker_signup"))
        if not is_valid_pincode(pincode):
            flash("Please enter a valid 6-digit service area pincode.")
            return redirect(url_for("worker_signup"))
        if FieldWorker.query.filter_by(worker_email=email).first():
            flash("A field worker with this email already exists.")
            return redirect(url_for("worker_signup"))

        worker = FieldWorker(
            worker_name=name,
            worker_email=email,
            worker_password=generate_password_hash(password),
            worker_dprtmnt=department,
            pincode=pincode,
            is_active=True,
        )
        try:
            db.session.add(worker)
            db.session.commit()
            flash("Field worker registration successful! Please log in.")
            return redirect(url_for("worker_login"))
        except Exception:
            db.session.rollback()
            flash("Worker registration could not be completed. Please try again.")
            return redirect(url_for("worker_signup"))

    return render_template("worker_signup.html")


@app.route("/worker_login", methods=["GET", "POST"])
def worker_login():
    email = ""
    if request.method == "POST":
        email = request.form.get("worker_email", "").strip().lower()
        password = request.form.get("worker_password", "")
        worker = FieldWorker.query.filter_by(worker_email=email, is_active=True).first()

        if not worker or not check_password_hash(worker.worker_password, password):
            flash("Invalid worker email or password.")
        else:
            session.clear()
            session["worker_id"] = worker.worker_id
            session["worker_email"] = worker.worker_email
            session["worker_name"] = worker.worker_name
            session["worker_department"] = worker.worker_dprtmnt
            session["worker_pincode"] = str(worker.pincode).zfill(6)
            session["role"] = "worker"
            flash(f"Welcome, Field Worker {worker.worker_name}!")
            return redirect(url_for("worker_dashboard"))

    return render_template("worker_login.html", email=email)


@app.route("/worker_dashboard")
@worker_required
def worker_dashboard():
    worker_id = session["worker_id"]
    jobs = cmpl_dets.query.filter_by(assigned_worker_id=worker_id).order_by(
        cmpl_dets.date_created.desc()
    ).all()

    total = len(jobs)
    pending = sum(1 for j in jobs if j.status == "Pending")
    in_progress = sum(1 for j in jobs if j.status == "In Progress")
    resolved = sum(1 for j in jobs if j.status == "Resolved")

    return render_template(
        "worker_dashboard.html",
        jobs=jobs,
        total=total,
        pending=pending,
        in_progress=in_progress,
        resolved=resolved,
    )


@app.route("/worker_task/<int:id>")
@worker_required
def worker_task_details(id):
    worker_id = session["worker_id"]
    task = cmpl_dets.query.filter_by(id=id, assigned_worker_id=worker_id).first()

    if not task:
        flash("Unauthorized: You are not assigned to this field task.")
        return redirect(url_for("worker_dashboard"))

    return render_template("worker_task_details.html", task=task)


@app.route("/worker_task/<int:id>/start", methods=["POST"])
@worker_required
def worker_task_start(id):
    worker_id = session["worker_id"]
    task = cmpl_dets.query.filter_by(id=id, assigned_worker_id=worker_id).first()

    if not task:
        flash("Unauthorized: You are not assigned to this field task.")
        return redirect(url_for("worker_dashboard"))

    task.status = "In Progress"
    if not task.worker_started_at:
        task.worker_started_at = datetime.utcnow()

    try:
        db.session.commit()
        flash(f"Task #{id} marked as In Progress. You can now perform the repair.")
    except Exception:
        db.session.rollback()
        flash("Failed to update task status.")

    return redirect(url_for("worker_task_details", id=id))


@app.route("/worker_task/<int:id>/complete", methods=["POST"])
@worker_required
def worker_task_complete(id):
    worker_id = session["worker_id"]
    task = cmpl_dets.query.filter_by(id=id, assigned_worker_id=worker_id).first()

    if not task:
        flash("Unauthorized: You are not assigned to this field task.")
        return redirect(url_for("worker_dashboard"))

    notes = request.form.get("resolution_notes", "").strip()
    if not notes:
        flash("Please provide a completion note describing the repair work performed.")
        return redirect(url_for("worker_task_details", id=id))

    # MANDATORY After-Repair Photo Proof
    file = request.files.get("after_image")
    if not file or not file.filename:
        flash("An after-repair photo is mandatory to resolve this task. Please upload completion proof.")
        return redirect(url_for("worker_task_details", id=id))

    try:
        filename = save_uploaded_image(file, f"worker_{worker_id}")
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("worker_task_details", id=id))

    task.after_image = filename
    task.resolution_notes = notes
    task.status = "Resolved"
    task.resolved_at = datetime.utcnow()

    try:
        db.session.commit()
        flash(f"Task #{id} successfully marked as Resolved with after-repair photo proof!")
    except Exception:
        db.session.rollback()
        flash("Failed to complete task due to a database error.")

    return redirect(url_for("worker_task_details", id=id))


@app.route("/worker_logout")
def worker_logout():
    session.clear()
    flash("You have been logged out of the Field Worker Portal.")
    return redirect(url_for("worker_login"))


# -------------------- ERROR HANDLERS & RUNNER --------------------
@app.errorhandler(413)
def upload_too_large(_error):
    flash("The uploaded file is too large. Please use an image under 5 MB.")
    return redirect(url_for("complaint_one"))


@app.errorhandler(404)
def not_found(_error):
    return render_template("base.html"), 404



if __name__ == "__main__":
    if not IS_PRODUCTION:
        with app.app_context():
            db.create_all()

    debug_mode = (
        not IS_PRODUCTION
        and os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    )

    port = int(os.environ.get("PORT", 7070))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=debug_mode
    )
