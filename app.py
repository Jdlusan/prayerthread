from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///prayers.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_USERNAME")

db = SQLAlchemy(app)
mail = Mail(app)


class PrayerRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), default="general")
    is_anonymous = db.Column(db.Boolean, default=False)
    is_answered = db.Column(db.Boolean, default=False)
    prayer_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    comments = db.relationship("Comment", backref="request", lazy=True, cascade="all, delete-orphan")


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("prayer_request.id"), nullable=False)
    name = db.Column(db.String(100), nullable=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


with app.app_context():
    db.create_all()


@app.route("/")
def index():
    category = request.args.get("category", "all")
    if category == "all":
        requests_list = PrayerRequest.query.filter_by(is_answered=False).order_by(PrayerRequest.created_at.desc()).all()
    else:
        requests_list = PrayerRequest.query.filter_by(is_answered=False, category=category).order_by(PrayerRequest.created_at.desc()).all()
    return render_template("index.html", requests=requests_list, category=category)


@app.route("/answered")
def answered():
    answered_list = PrayerRequest.query.filter_by(is_answered=True).order_by(PrayerRequest.created_at.desc()).all()
    return render_template("answered.html", requests=answered_list)


@app.route("/submit", methods=["POST"])
def submit():
    content = request.form.get("content", "").strip()
    if not content:
        return redirect(url_for("index"))

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    category = request.form.get("category", "general")
    is_anonymous = request.form.get("anonymous") == "on"

    prayer = PrayerRequest(
        name=name if not is_anonymous else None,
        email=email if email else None,
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
        try:
            msg = Message(
                subject="Someone just prayed for you",
                recipients=[prayer.email],
                body=f"Hi{' ' + prayer.name if prayer.name else ''},\n\nSomeone just prayed for your request:\n\n\"{prayer.content}\"\n\nYou've now been prayed for {prayer.prayer_count} time{'s' if prayer.prayer_count != 1 else ''}.\n\nKeep trusting God.\n\n— The PrayerThread Team"
            )
            mail.send(msg)
        except Exception:
            pass

    return jsonify({"prayer_count": prayer.prayer_count})


@app.route("/comment/<int:req_id>", methods=["POST"])
def comment(req_id):
    prayer = PrayerRequest.query.get_or_404(req_id)
    content = request.form.get("content", "").strip()
    name = request.form.get("name", "").strip()
    if content:
        c = Comment(request_id=req_id, name=name or None, content=content)
        db.session.add(c)
        db.session.commit()
    return redirect(url_for("index") + f"#{req_id}")


@app.route("/answered/<int:req_id>", methods=["POST"])
def mark_answered(req_id):
    prayer = PrayerRequest.query.get_or_404(req_id)
    prayer.is_answered = True
    db.session.commit()
    return redirect(url_for("index"))


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
