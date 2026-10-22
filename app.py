import os
import secrets
from datetime import datetime, timezone
from functools import wraps

import requests
from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from supabase import create_client

load_dotenv()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY", ""),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
    MAX_CONTENT_LENGTH=int(os.getenv("MAX_UPLOAD_MB", "4")) * 1024 * 1024,
)

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "item-photos")

if not app.config["SECRET_KEY"]:
    # Works for local testing, but set a fixed random value in .env / Render for stable sessions.
    app.config["SECRET_KEY"] = secrets.token_hex(32)

supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else None


@app.before_request
def protect_post_forms():
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not sent or not expected or not secrets.compare_digest(sent, expected):
            abort(400, description="Invalid form security token. Refresh the page and try again.")


def make_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def configured():
    return bool(SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY and SUPABASE_SERVICE_ROLE_KEY and supabase_admin)


def db():
    if not configured():
        raise RuntimeError("Supabase is not configured yet. Follow the README setup steps.")
    return supabase_admin


def current_profile():
    uid = session.get("user_id")
    if not uid or not configured():
        return None
    try:
        result = db().table("profiles").select("id, full_name, email, role, created_at").eq("id", uid).maybe_single().execute()
        return result.data
    except Exception:
        return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in first.", "info")
            return redirect(url_for("login"))
        profile = current_profile()
        if not profile:
            session.clear()
            flash("Your profile could not be loaded. Please sign in again.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in with an administrator account.", "info")
            return redirect(url_for("login"))
        profile = current_profile()
        if not profile or profile.get("role") != "admin":
            flash("Admin access only.", "error")
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped


def auth_request(path, payload):
    if not SUPABASE_URL or not SUPABASE_PUBLISHABLE_KEY:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY in your .env file first.")
    response = requests.post(
        f"{SUPABASE_URL}/auth/v1/{path}",
        headers={"apikey": SUPABASE_PUBLISHABLE_KEY, "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        message = body.get("msg") or body.get("message") or body.get("error_description") or body.get("error") or "Authentication failed."
        raise ValueError(message)
    return body


def upload_photo(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    allowed = {"jpg", "jpeg", "png", "webp"}
    filename = file_storage.filename.rsplit(".", 1)
    if len(filename) != 2 or filename[1].lower() not in allowed:
        raise ValueError("Upload a JPG, PNG, or WEBP image only.")
    ext = filename[1].lower()
    object_path = f"{session['user_id']}/{secrets.token_hex(12)}.{ext}"
    content_type = file_storage.mimetype or "application/octet-stream"
    response = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{object_path}",
        headers={
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": content_type,
            "x-upsert": "false",
        },
        data=file_storage.read(),
        timeout=30,
    )
    if not response.ok:
        raise ValueError("Photo upload failed. Check that the Supabase Storage bucket exists.")
    # This project uses a public bucket for listing photos. Do not upload IDs or private information.
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{object_path}"


@app.context_processor
def inject_globals():
    return {"profile": current_profile(), "supabase_ready": configured(), "current_year": datetime.now().year, "csrf_token": make_csrf_token}


@app.route("/")
def index():
    try:
        rows = db().table("items").select("id,title,description,category,item_type,campus,found_location,photo_url,status,created_at,reporter_id").in_("status", ["approved", "turned_over", "claimed", "resolved"]).order("created_at", desc=True).limit(100).execute().data or [] if configured() else []
    except Exception:
        rows = []
    return render_template("index.html", items=rows, db_ready=configured())


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not full_name or not email or len(password) < 8:
            flash("Enter your name, a valid email, and a password with at least 8 characters.", "error")
            return render_template("register.html")
        try:
            auth_request("signup", {"email": email, "password": password, "data": {"full_name": full_name}})
            flash("Account created. If email confirmation is enabled, verify your email before signing in.", "success")
            return redirect(url_for("login"))
        except Exception as exc:
            flash(str(exc), "error")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        try:
            auth = auth_request("token?grant_type=password", {"email": email, "password": password})
            auth_user = auth.get("user") or {}
            user_id = auth_user.get("id")
            if not user_id:
                raise ValueError("Sign-in succeeded but no user ID was returned. Check email verification settings.")
            session.clear()
            session["user_id"] = user_id
            profile = current_profile()
            if not profile:
                full_name = (auth_user.get("user_metadata") or {}).get("full_name") or email.split("@")[0]
                db().table("profiles").upsert({"id": user_id, "full_name": full_name, "email": email, "role": "student"}).execute()
                profile = current_profile()
            flash("Welcome back!", "success")
            return redirect(url_for("admin_dashboard" if profile and profile.get("role") == "admin" else "index"))
        except Exception as exc:
            flash(str(exc), "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("index"))


@app.route("/report", methods=["GET", "POST"])
@login_required
def report_item():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        item_type = request.form.get("item_type", "lost")
        category = request.form.get("category", "Other")
        campus = request.form.get("campus", "").strip()
        location = request.form.get("found_location", "").strip()
        if not title or not description or not campus or not location or item_type not in {"lost", "found"}:
            flash("Complete all required fields.", "error")
            return render_template("report.html")
        try:
            photo_url = upload_photo(request.files.get("photo"))
            payload = {
                "reporter_id": session["user_id"], "title": title, "description": description,
                "item_type": item_type, "category": category, "campus": campus,
                "found_location": location, "photo_url": photo_url, "status": "pending_review",
            }
            inserted = db().table("items").insert(payload).execute().data or []
            if inserted:
                db().table("activity_logs").insert({"actor_id": session["user_id"], "action": "item_report_submitted", "entity_type": "item", "entity_id": inserted[0]["id"], "details": {"item_type": item_type, "status": "pending_review"}}).execute()
            flash("Report submitted for staff review.", "success")
            return redirect(url_for("my_reports"))
        except Exception as exc:
            flash(str(exc), "error")
    return render_template("report.html")


@app.route("/my-reports")
@login_required
def my_reports():
    try:
        rows = db().table("items").select("*").eq("reporter_id", session["user_id"]).order("created_at", desc=True).execute().data or []
    except Exception:
        rows = []
    return render_template("my_reports.html", items=rows)


@app.route("/claims/<item_id>", methods=["POST"])
@login_required
def claim_item(item_id):
    details = request.form.get("proof_details", "").strip()
    if len(details) < 12:
        flash("Please provide enough non-sensitive details for staff to verify ownership.", "error")
        return redirect(url_for("index"))
    try:
        item = db().table("items").select("id,status,reporter_id").eq("id", item_id).maybe_single().execute().data
        if not item or item.get("status") not in {"approved", "turned_over"}:
            flash("This item is not available for a claim request.", "error")
        elif item.get("reporter_id") == session["user_id"]:
            flash("You cannot claim an item you submitted.", "error")
        else:
            created_claim = db().table("claims").insert({"item_id": item_id, "claimant_id": session["user_id"], "proof_details": details, "status": "pending"}).execute().data or []
            if created_claim:
                db().table("activity_logs").insert({"actor_id": session["user_id"], "action": "claim_request_submitted", "entity_type": "claim", "entity_id": created_claim[0]["id"], "details": {"item_id": item_id}}).execute()
            flash("Claim request sent to staff for verification.", "success")
    except Exception as exc:
        flash(str(exc), "error")
    return redirect(url_for("index"))


@app.route("/my-claims")
@login_required
def my_claims():
    try:
        claims = db().table("claims").select("id,item_id,proof_details,status,created_at").eq("claimant_id", session["user_id"]).order("created_at", desc=True).execute().data or []
        for claim in claims:
            item = db().table("items").select("title,campus").eq("id", claim["item_id"]).maybe_single().execute().data
            claim["item"] = item or {"title": "Item unavailable", "campus": ""}
    except Exception:
        claims = []
    return render_template("my_claims.html", claims=claims)


@app.route("/admin")
@admin_required
def admin_dashboard():
    client = db()
    items = client.table("items").select("*").order("created_at", desc=True).limit(250).execute().data or []
    claims = client.table("claims").select("*").order("created_at", desc=True).limit(250).execute().data or []
    profiles = client.table("profiles").select("id,full_name,email,role,created_at").order("created_at", desc=True).limit(250).execute().data or []
    activity = client.table("activity_logs").select("id,actor_id,action,entity_type,entity_id,details,created_at").order("created_at", desc=True).limit(50).execute().data or []
    for log in activity:
        actor = client.table("profiles").select("full_name,email").eq("id", log["actor_id"]).maybe_single().execute().data if log.get("actor_id") else None
        log["actor"] = actor or {"full_name": "System / deleted user", "email": ""}
    for claim in claims:
        claim["item"] = client.table("items").select("title,campus").eq("id", claim["item_id"]).maybe_single().execute().data or {"title": "Unknown item", "campus": ""}
        claimant = client.table("profiles").select("full_name,email").eq("id", claim["claimant_id"]).maybe_single().execute().data
        claim["claimant"] = claimant or {"full_name": "Unknown user", "email": ""}
    return render_template("admin.html", items=items, claims=claims, users=profiles, activity=activity,
                           pending_items=sum(x.get("status") == "pending_review" for x in items),
                           pending_claims=sum(x.get("status") == "pending" for x in claims))


@app.route("/admin/items/<item_id>/status", methods=["POST"])
@admin_required
def admin_item_status(item_id):
    status = request.form.get("status", "")
    allowed = {"pending_review", "approved", "rejected", "turned_over", "claimed", "resolved", "archived"}
    if status not in allowed:
        flash("Invalid item status.", "error")
    else:
        try:
            db().table("items").update({"status": status, "reviewed_by": session["user_id"], "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", item_id).execute()
            db().table("activity_logs").insert({"actor_id": session["user_id"], "action": "item_status_updated", "entity_type": "item", "entity_id": item_id, "details": {"status": status}}).execute()
            flash("Item status updated.", "success")
        except Exception as exc:
            flash(str(exc), "error")
    return redirect(url_for("admin_dashboard") + "#items")


@app.route("/admin/claims/<claim_id>/status", methods=["POST"])
@admin_required
def admin_claim_status(claim_id):
    status = request.form.get("status", "")
    if status not in {"approved", "rejected"}:
        flash("Invalid claim decision.", "error")
    else:
        try:
            claim = db().table("claims").select("id,item_id,claimant_id").eq("id", claim_id).maybe_single().execute().data
            if not claim:
                flash("Claim request not found.", "error")
            else:
                db().table("claims").update({"status": status, "reviewed_by": session["user_id"], "reviewed_at": datetime.now(timezone.utc).isoformat()}).eq("id", claim_id).execute()
                if status == "approved":
                    db().table("items").update({"status": "claimed", "reviewed_by": session["user_id"], "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", claim["item_id"]).execute()
                db().table("activity_logs").insert({"actor_id": session["user_id"], "action": "claim_" + status, "entity_type": "claim", "entity_id": claim_id, "details": {"item_id": claim["item_id"]}}).execute()
                flash("Claim decision saved.", "success")
        except Exception as exc:
            flash(str(exc), "error")
    return redirect(url_for("admin_dashboard") + "#claims")


@app.route("/health")
def health():
    return {"status": "ok", "supabase_configured": configured()}


@app.errorhandler(413)
def too_large(_error):
    flash(f"Photo is too large. Maximum upload size is {app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)} MB.", "error")
    return redirect(request.referrer or url_for("report_item"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
