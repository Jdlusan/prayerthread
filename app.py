from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, Response
import csv
import io
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import random
import resend

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")
database_url = os.getenv("DATABASE_URL", "sqlite:///prayers.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=30)

resend.api_key = os.getenv("RESEND_API_KEY", "")

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = ""


def send_email(to, subject, body):
    if not resend.api_key:
        return
    try:
        resend.Emails.send({
            "from": "PrayerThread <hello@prayerthread.app>",
            "to": [to] if isinstance(to, str) else to,
            "subject": subject,
            "text": body,
        })
    except Exception:
        pass


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    requests = db.relationship("PrayerRequest", backref="user", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class PrayerRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    name = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), default="general")
    is_anonymous = db.Column(db.Boolean, default=False)
    is_answered = db.Column(db.Boolean, default=False)
    prayer_count = db.Column(db.Integer, default=0)
    report_count = db.Column(db.Integer, default=0)
    is_hidden = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    comments = db.relationship("Comment", backref="request", lazy=True, cascade="all, delete-orphan")
    updates = db.relationship("PrayerUpdate", backref="request", lazy=True, cascade="all, delete-orphan", order_by="PrayerUpdate.created_at.desc()")


class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("prayer_request.id"), nullable=False)
    ip = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class DigestSubscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PrayerUpdate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("prayer_request.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("prayer_request.id"), nullable=False)
    name = db.Column(db.String(100), nullable=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


with app.app_context():
    db.create_all()


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or not password:
            flash("All fields are required.")
            return render_template("register.html")
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.")
            return render_template("register.html")
        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for("index"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Invalid email or password.")
            return render_template("login.html")
        login_user(user, remember=True)
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


@app.route("/")
def index():
    category = request.args.get("category", "all")
    page = request.args.get("page", 1, type=int)
    query = PrayerRequest.query.filter_by(is_answered=False, is_hidden=False)
    if category != "all":
        query = query.filter_by(category=category)
    pagination = query.order_by(PrayerRequest.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template("index.html", requests=pagination.items, pagination=pagination, category=category)


@app.route("/answered")
def answered():
    answered_list = PrayerRequest.query.filter_by(is_answered=True).order_by(PrayerRequest.created_at.desc()).all()
    return render_template("answered.html", requests=answered_list)


@app.route("/submit", methods=["POST"])
@login_required
def submit():
    content = request.form.get("content", "").strip()
    if not content:
        return redirect(url_for("index"))
    category = request.form.get("category", "general")
    is_anonymous = request.form.get("anonymous") == "on"
    prayer = PrayerRequest(
        user_id=current_user.id,
        name=current_user.name if not is_anonymous else None,
        email=current_user.email,
        content=content,
        category=category,
        is_anonymous=is_anonymous,
    )
    db.session.add(prayer)
    db.session.commit()
    return redirect(url_for("index"))


@app.route("/pray/<int:req_id>", methods=["POST"])
def pray(req_id):
    prayer = PrayerRequest.query.get_or_404(req_id)
    prayer.prayer_count += 1
    db.session.commit()
    if prayer.email:
        send_email(
            to=prayer.email,
            subject="Someone just prayed for you",
            body=(
                f"Hi{' ' + prayer.name if prayer.name else ''},\n\n"
                f"Someone just prayed for your request:\n\n\"{prayer.content}\"\n\n"
                f"You've now been prayed for {prayer.prayer_count} time{'s' if prayer.prayer_count != 1 else ''}.\n\n"
                "Keep trusting God.\n\n— The PrayerThread Team\nprayerthread.app"
            )
        )
    return jsonify({"prayer_count": prayer.prayer_count})


@app.route("/comment/<int:req_id>", methods=["POST"])
def comment(req_id):
    prayer = PrayerRequest.query.get_or_404(req_id)
    content = request.form.get("content", "").strip()
    name = request.form.get("name", "").strip()
    if not name and current_user.is_authenticated:
        name = current_user.name
    if content:
        c = Comment(request_id=req_id, name=name or None, content=content)
        db.session.add(c)
        db.session.commit()
    return redirect(url_for("index") + f"#{req_id}")


@app.route("/answered/<int:req_id>", methods=["POST"])
@login_required
def mark_answered(req_id):
    prayer = PrayerRequest.query.get_or_404(req_id)
    if prayer.user_id != current_user.id:
        return redirect(url_for("index"))
    prayer.is_answered = True
    db.session.commit()
    return redirect(url_for("index"))


@app.route("/delete/<int:req_id>", methods=["POST"])
@login_required
def delete_request(req_id):
    prayer = PrayerRequest.query.get_or_404(req_id)
    if prayer.user_id != current_user.id:
        return redirect(url_for("index"))
    db.session.delete(prayer)
    db.session.commit()
    return redirect(url_for("index"))


@app.route("/update/<int:req_id>", methods=["POST"])
@login_required
def add_update(req_id):
    prayer = PrayerRequest.query.get_or_404(req_id)
    if prayer.user_id != current_user.id:
        return redirect(url_for("index"))
    content = request.form.get("content", "").strip()
    if content:
        u = PrayerUpdate(request_id=req_id, content=content)
        db.session.add(u)
        db.session.commit()
    return redirect(url_for("index") + f"#{req_id}")


@app.route("/report/<int:req_id>", methods=["POST"])
def report(req_id):
    prayer = PrayerRequest.query.get_or_404(req_id)
    ip = request.remote_addr
    already = Report.query.filter_by(request_id=req_id, ip=ip).first()
    if not already:
        db.session.add(Report(request_id=req_id, ip=ip))
        prayer.report_count += 1
        if prayer.report_count >= 3:
            prayer.is_hidden = True
        db.session.commit()
        if prayer.report_count == 1:
            admin_email = os.getenv("MAIL_USERNAME")
            if admin_email:
                send_email(
                    to=admin_email,
                    subject="PrayerThread: A request was flagged",
                    body=f"A prayer request has been reported.\n\nContent: \"{prayer.content}\"\n\nReport count: {prayer.report_count}\n\nReview at prayerthread.app"
                )
    return jsonify({"status": "reported"})


@app.route("/subscribe", methods=["POST"])
def subscribe():
    email = request.form.get("email", "").strip().lower()
    name = request.form.get("name", "").strip()
    if email and not DigestSubscriber.query.filter_by(email=email).first():
        db.session.add(DigestSubscriber(email=email, name=name or None))
        db.session.commit()
        send_email(
            to=email,
            subject="You're on the PrayerThread morning list ✓",
            body=(
                f"Hi{' ' + name if name else ''},\n\n"
                "You're signed up. Every morning you'll receive 3 prayer requests from the PrayerThread community.\n\n"
                "Take a moment to pray for each one. It matters more than you know.\n\n"
                "\"Pray without ceasing.\" — 1 Thessalonians 5:17\n\n"
                "— The PrayerThread Team\n"
                "prayerthread.app\n\n"
                f"To unsubscribe: https://prayerthread.app/unsubscribe?email={email}"
            )
        )
    return jsonify({"status": "ok"})


@app.route("/unsubscribe")
def unsubscribe():
    email = request.args.get("email", "").strip().lower()
    if email:
        sub = DigestSubscriber.query.filter_by(email=email).first()
        if sub:
            db.session.delete(sub)
            db.session.commit()
    return render_template("unsubscribe.html", email=email)


@app.route("/send-digest", methods=["POST"])
def send_digest():
    secret = request.headers.get("X-Digest-Secret", "")
    if secret != os.getenv("DIGEST_SECRET", ""):
        return jsonify({"error": "unauthorized"}), 401

    requests_pool = PrayerRequest.query.filter_by(is_answered=False).all()
    if not requests_pool:
        return jsonify({"status": "no requests"})

    sample = random.sample(requests_pool, min(3, len(requests_pool)))
    subscribers = DigestSubscriber.query.all()

    for sub in subscribers:
        lines = []
        for i, r in enumerate(sample, 1):
            display_name = "Anonymous" if r.is_anonymous or not r.name else r.name
            lines.append(f"{i}. {display_name} ({r.category.title()}):\n   \"{r.content}\"")

        body = (
            f"Good morning{', ' + sub.name if sub.name else ''},\n\n"
            "Here are 3 prayer requests from the PrayerThread community for today:\n\n"
            + "\n\n".join(lines)
            + f"\n\nTake a moment to pray for each one.\n\nVisit prayerthread.app to see more and let someone know you prayed.\n\n— The PrayerThread Team\n\nTo unsubscribe: https://prayerthread.app/unsubscribe?email={sub.email}"
        )
        send_email(
            to=sub.email,
            subject="3 prayers for today — PrayerThread",
            body=body
        )

    return jsonify({"status": "sent", "count": len(subscribers)})


@app.route("/sitemap.xml")
def sitemap():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://prayerthread.app/</loc><priority>1.0</priority></url>
  <url><loc>https://prayerthread.app/answered</loc><priority>0.8</priority></url>
  <url><loc>https://prayerthread.app/register</loc><priority>0.6</priority></url>
  <url><loc>https://prayerthread.app/login</loc><priority>0.5</priority></url>
</urlset>'''
    return Response(xml, mimetype="application/xml")


@app.route("/admin/subscribers")
def admin_subscribers():
    key = request.args.get("key", "")
    if key != os.getenv("ADMIN_SECRET", ""):
        return "Unauthorized", 401
    subscribers = DigestSubscriber.query.order_by(DigestSubscriber.created_at.desc()).all()
    return render_template("admin_subscribers.html", subscribers=subscribers, key=key)


@app.route("/admin/subscribers/export")
def admin_subscribers_export():
    key = request.args.get("key", "")
    if key != os.getenv("ADMIN_SECRET", ""):
        return "Unauthorized", 401
    subscribers = DigestSubscriber.query.order_by(DigestSubscriber.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Email", "Name", "Joined"])
    for s in subscribers:
        writer.writerow([s.email, s.name or "", s.created_at.strftime("%Y-%m-%d")])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=subscribers.csv"}
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
