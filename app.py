from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3
import secrets
import string
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database.db"

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        photo TEXT DEFAULT '',
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE NOT NULL,
        used INTEGER DEFAULT 0,
        used_at TEXT
    );

    CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id INTEGER NOT NULL,
        token_id INTEGER UNIQUE NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(candidate_id) REFERENCES candidates(id),
        FOREIGN KEY(token_id) REFERENCES tokens(id)
    );
    """)
    if conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO admins(username, password_hash) VALUES (?, ?)",
            (DEFAULT_ADMIN_USERNAME, generate_password_hash(DEFAULT_ADMIN_PASSWORD))
        )
    if conn.execute("SELECT 1 FROM settings WHERE key='voting_open'").fetchone() is None:
        conn.execute("INSERT INTO settings(key,value) VALUES('voting_open','1')")
    conn.commit()
    conn.close()

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper

def voting_open():
    conn = db()
    row = conn.execute("SELECT value FROM settings WHERE key='voting_open'").fetchone()
    conn.close()
    return row and row["value"] == "1"

def make_token(length=8):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))

@app.route("/")
def index():
    return render_template("index.html", open=voting_open())

@app.route("/vote", methods=["GET", "POST"])
def vote():
    if not voting_open():
        return render_template("vote_closed.html")

    if request.method == "POST":
        token_value = request.form.get("token", "").strip().upper()
        if not token_value:
            flash("Silakan masukkan token.", "error")
            return redirect(url_for("vote"))

        conn = db()
        token = conn.execute(
            "SELECT * FROM tokens WHERE token = ? AND used = 0", (token_value,)
        ).fetchone()
        if not token:
            conn.close()
            flash("Token tidak valid atau sudah digunakan.", "error")
            return redirect(url_for("vote"))

        candidates = conn.execute(
            "SELECT * FROM candidates WHERE active=1 ORDER BY id"
        ).fetchall()
        conn.close()

        if not candidates:
            flash("Belum ada peserta/calon yang tersedia.", "error")
            return redirect(url_for("vote"))

        session["vote_token_id"] = token["id"]
        session["vote_token_display"] = token_value
        return render_template("voting.html", candidates=candidates)

    return render_template("token.html")

@app.route("/submit-vote", methods=["POST"])
def submit_vote():
    if not voting_open():
        return render_template("vote_closed.html")

    token_id = session.get("vote_token_id")
    candidate_id = request.form.get("candidate_id")

    if not token_id or not candidate_id:
        flash("Sesi voting tidak valid. Silakan masukkan token kembali.", "error")
        session.pop("vote_token_id", None)
        return redirect(url_for("vote"))

    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        token = conn.execute(
            "SELECT * FROM tokens WHERE id=? AND used=0", (token_id,)
        ).fetchone()

        candidate = conn.execute(
            "SELECT * FROM candidates WHERE id=? AND active=1", (candidate_id,)
        ).fetchone()

        if not token or not candidate:
            conn.rollback()
            flash("Token sudah digunakan atau peserta tidak tersedia.", "error")
            session.pop("vote_token_id", None)
            return redirect(url_for("vote"))

        conn.execute(
            "INSERT INTO votes(candidate_id, token_id) VALUES (?, ?)",
            (candidate["id"], token["id"])
        )
        conn.execute(
            "UPDATE tokens SET used=1, used_at=CURRENT_TIMESTAMP WHERE id=?",
            (token["id"],)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        flash("Token tersebut sudah digunakan.", "error")
        session.pop("vote_token_id", None)
        return redirect(url_for("vote"))
    finally:
        conn.close()

    session.pop("vote_token_id", None)
    session.pop("vote_token_display", None)
    return render_template("success.html")

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = db()
        admin = conn.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
        conn.close()
        if admin and check_password_hash(admin["password_hash"], password):
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            return redirect(url_for("admin_dashboard"))
        flash("Username atau password salah.", "error")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = db()
    candidates = conn.execute("""
        SELECT c.id, c.name, c.description, c.photo, c.active,
               COUNT(v.id) AS votes
        FROM candidates c
        LEFT JOIN votes v ON v.candidate_id=c.id
        GROUP BY c.id
        ORDER BY c.id
    """).fetchall()
    total_votes = conn.execute("SELECT COUNT(*) FROM votes").fetchone()[0]
    total_tokens = conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0]
    used_tokens = conn.execute("SELECT COUNT(*) FROM tokens WHERE used=1").fetchone()[0]
    setting = conn.execute("SELECT value FROM settings WHERE key='voting_open'").fetchone()
    conn.close()
    return render_template(
        "admin.html",
        candidates=candidates,
        total_votes=total_votes,
        total_tokens=total_tokens,
        used_tokens=used_tokens,
        voting_is_open=setting["value"] == "1"
    )

@app.route("/admin/candidates/add", methods=["POST"])
@admin_required
def add_candidate():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    photo = request.form.get("photo", "").strip()
    if not name:
        flash("Nama peserta wajib diisi.", "error")
    else:
        conn = db()
        conn.execute(
            "INSERT INTO candidates(name,description,photo) VALUES(?,?,?)",
            (name, description, photo)
        )
        conn.commit()
        conn.close()
        flash("Peserta berhasil ditambahkan.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/candidates/<int:candidate_id>/toggle", methods=["POST"])
@admin_required
def toggle_candidate(candidate_id):
    conn = db()
    conn.execute("UPDATE candidates SET active = CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?", (candidate_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/candidates/<int:candidate_id>/delete", methods=["POST"])
@admin_required
def delete_candidate(candidate_id):
    conn = db()
    votes = conn.execute("SELECT COUNT(*) FROM votes WHERE candidate_id=?", (candidate_id,)).fetchone()[0]
    if votes > 0:
        flash("Peserta yang sudah memiliki suara tidak dapat dihapus. Nonaktifkan saja.", "error")
    else:
        conn.execute("DELETE FROM candidates WHERE id=?", (candidate_id,))
        conn.commit()
        flash("Peserta berhasil dihapus.", "success")
    conn.close()
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/tokens/generate", methods=["POST"])
@admin_required
def generate_tokens():
    try:
        amount = max(1, min(int(request.form.get("amount", "10")), 1000))
    except ValueError:
        amount = 10

    conn = db()
    generated = []
    while len(generated) < amount:
        token = make_token()
        try:
            conn.execute("INSERT INTO tokens(token) VALUES(?)", (token,))
            generated.append(token)
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()
    return render_template("tokens_generated.html", tokens=generated)

@app.route("/admin/tokens")
@admin_required
def tokens():
    conn = db()
    rows = conn.execute(
        "SELECT * FROM tokens ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return render_template("tokens.html", tokens=rows)

@app.route("/admin/tokens/unused")
@admin_required
def unused_tokens():
    conn = db()
    rows = conn.execute("SELECT token FROM tokens WHERE used=0 ORDER BY id").fetchall()
    conn.close()
    return jsonify([r["token"] for r in rows])

@app.route("/admin/toggle-voting", methods=["POST"])
@admin_required
def toggle_voting():
    conn = db()
    current = conn.execute("SELECT value FROM settings WHERE key='voting_open'").fetchone()["value"]
    new_value = "0" if current == "1" else "1"
    conn.execute("UPDATE settings SET value=? WHERE key='voting_open'", (new_value,))
    conn.commit()
    conn.close()
    flash("Status voting diperbarui.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/reset-demo", methods=["POST"])
@admin_required
def reset_demo():
    conn = db()
    conn.execute("DELETE FROM votes")
    conn.execute("UPDATE tokens SET used=0, used_at=NULL")
    conn.commit()
    conn.close()
    flash("Suara dihapus dan seluruh token dikembalikan menjadi belum digunakan.", "success")
    return redirect(url_for("admin_dashboard"))

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
