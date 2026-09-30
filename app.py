from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import os
import secrets
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "development-secret-key-change-this"
)

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL belum diatur.")

    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        sslmode="require"
    )


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            photo TEXT DEFAULT '',
            active INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            id SERIAL PRIMARY KEY,
            token TEXT UNIQUE NOT NULL,
            used INTEGER DEFAULT 0,
            used_at TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            id SERIAL PRIMARY KEY,
            candidate_id INTEGER NOT NULL REFERENCES candidates(id),
            token_id INTEGER UNIQUE NOT NULL REFERENCES tokens(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute(
        "SELECT id FROM admins WHERE username = %s",
        ("admin",)
    )

    admin = cur.fetchone()

    if not admin:
        cur.execute(
            """
            INSERT INTO admins(username, password_hash)
            VALUES (%s, %s)
            """,
            (
                "admin",
                generate_password_hash("admin123")
            )
        )

    cur.execute(
        "SELECT key FROM settings WHERE key = %s",
        ("voting_open",)
    )

    setting = cur.fetchone()

    if not setting:
        cur.execute(
            """
            INSERT INTO settings(key, value)
            VALUES (%s, %s)
            """,
            ("voting_open", "1")
        )

    conn.commit()
    cur.close()
    conn.close()


def admin_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):

        if not session.get("admin_id"):
            return redirect(url_for("admin_login"))

        return function(*args, **kwargs)

    return wrapper


def voting_open():

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT value FROM settings WHERE key = %s",
        ("voting_open",)
    )

    row = cur.fetchone()

    cur.close()
    conn.close()

    return row and row["value"] == "1"


def make_token(length=8):

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    return "".join(
        secrets.choice(alphabet)
        for _ in range(length)
    )


@app.route("/")
def index():

    return render_template(
        "index.html",
        open=voting_open()
    )


@app.route("/vote", methods=["GET", "POST"])
def vote():

    if not voting_open():
        return render_template("vote_closed.html")

    if request.method == "POST":

        token_value = request.form.get(
            "token",
            ""
        ).strip().upper()

        if not token_value:

            flash(
                "Silakan masukkan token.",
                "error"
            )

            return redirect(url_for("vote"))

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT *
            FROM tokens
            WHERE token = %s
            AND used = 0
            """,
            (token_value,)
        )

        token = cur.fetchone()

        if not token:

            cur.close()
            conn.close()

            flash(
                "Token tidak valid atau sudah digunakan.",
                "error"
            )

            return redirect(url_for("vote"))

        cur.execute(
            """
            SELECT *
            FROM candidates
            WHERE active = 1
            ORDER BY id
            """
        )

        candidates = cur.fetchall()

        cur.close()
        conn.close()

        if not candidates:

            flash(
                "Belum ada peserta/calon.",
                "error"
            )

            return redirect(url_for("vote"))

        session["vote_token_id"] = token["id"]

        return render_template(
            "voting.html",
            candidates=candidates
        )

    return render_template("token.html")


@app.route("/submit-vote", methods=["POST"])
def submit_vote():

    if not voting_open():
        return render_template("vote_closed.html")

    token_id = session.get("vote_token_id")
    candidate_id = request.form.get("candidate_id")

    if not token_id or not candidate_id:

        session.pop("vote_token_id", None)

        flash(
            "Sesi voting tidak valid.",
            "error"
        )

        return redirect(url_for("vote"))

    conn = get_db()

    try:

        conn.autocommit = False

        cur = conn.cursor()

        cur.execute(
            """
            SELECT *
            FROM tokens
            WHERE id = %s
            AND used = 0
            FOR UPDATE
            """,
            (token_id,)
        )

        token = cur.fetchone()

        cur.execute(
            """
            SELECT *
            FROM candidates
            WHERE id = %s
            AND active = 1
            """,
            (candidate_id,)
        )

        candidate = cur.fetchone()

        if not token or not candidate:

            conn.rollback()

            session.pop(
                "vote_token_id",
                None
            )

            flash(
                "Token sudah digunakan atau peserta tidak tersedia.",
                "error"
            )

            return redirect(url_for("vote"))

        cur.execute(
            """
            INSERT INTO votes(candidate_id, token_id)
            VALUES (%s, %s)
            """,
            (
                candidate["id"],
                token["id"]
            )
        )

        cur.execute(
            """
            UPDATE tokens
            SET used = 1,
                used_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (token["id"],)
        )

        conn.commit()

    except Exception:

        conn.rollback()

        flash(
            "Terjadi kesalahan saat menyimpan suara.",
            "error"
        )

        return redirect(url_for("vote"))

    finally:

        conn.close()

    session.pop(
        "vote_token_id",
        None
    )

    return render_template("success.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():

    if session.get("admin_id"):
        return redirect(
            url_for("admin_dashboard")
        )

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT *
            FROM admins
            WHERE username = %s
            """,
            (username,)
        )

        admin = cur.fetchone()

        cur.close()
        conn.close()

        if admin and check_password_hash(
            admin["password_hash"],
            password
        ):

            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]

            return redirect(
                url_for("admin_dashboard")
            )

        flash(
            "Username atau password salah.",
            "error"
        )

    return render_template(
        "admin_login.html"
    )


@app.route("/admin/logout")
def admin_logout():

    session.clear()

    return redirect(
        url_for("index")
    )


@app.route("/admin")
@admin_required
def admin_dashboard():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            c.id,
            c.name,
            c.description,
            c.photo,
            c.active,
            COUNT(v.id) AS votes
        FROM candidates c
        LEFT JOIN votes v
            ON v.candidate_id = c.id
        GROUP BY c.id
        ORDER BY c.id
    """)

    candidates = cur.fetchall()

    cur.execute(
        "SELECT COUNT(*) AS count FROM votes"
    )

    total_votes = cur.fetchone()["count"]

    cur.execute(
        "SELECT COUNT(*) AS count FROM tokens"
    )

    total_tokens = cur.fetchone()["count"]

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM tokens
        WHERE used = 1
        """
    )

    used_tokens = cur.fetchone()["count"]

    cur.execute(
        """
        SELECT value
        FROM settings
        WHERE key = %s
        """,
        ("voting_open",)
    )

    setting = cur.fetchone()

    cur.close()
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

    name = request.form.get(
        "name",
        ""
    ).strip()

    description = request.form.get(
        "description",
        ""
    ).strip()

    photo = request.form.get(
        "photo",
        ""
    ).strip()

    if not name:

        flash(
            "Nama peserta wajib diisi.",
            "error"
        )

        return redirect(
            url_for("admin_dashboard")
        )

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO candidates
        (name, description, photo)
        VALUES (%s, %s, %s)
        """,
        (
            name,
            description,
            photo
        )
    )

    conn.commit()

    cur.close()
    conn.close()

    flash(
        "Peserta berhasil ditambahkan.",
        "success"
    )

    return redirect(
        url_for("admin_dashboard")
    )


@app.route(
    "/admin/candidates/<int:candidate_id>/toggle",
    methods=["POST"]
)
@admin_required
def toggle_candidate(candidate_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE candidates
        SET active =
            CASE
                WHEN active = 1 THEN 0
                ELSE 1
            END
        WHERE id = %s
        """,
        (candidate_id,)
    )

    conn.commit()

    cur.close()
    conn.close()

    return redirect(
        url_for("admin_dashboard")
    )


@app.route(
    "/admin/candidates/<int:candidate_id>/delete",
    methods=["POST"]
)
@admin_required
def delete_candidate(candidate_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM votes
        WHERE candidate_id = %s
        """,
        (candidate_id,)
    )

    votes = cur.fetchone()["count"]

    if votes > 0:

        flash(
            "Peserta yang sudah memiliki suara tidak dapat dihapus.",
            "error"
        )

    else:

        cur.execute(
            """
            DELETE FROM candidates
            WHERE id = %s
            """,
            (candidate_id,)
        )

        conn.commit()

        flash(
            "Peserta berhasil dihapus.",
            "success"
        )

    cur.close()
    conn.close()

    return redirect(
        url_for("admin_dashboard")
    )


@app.route(
    "/admin/tokens/generate",
    methods=["POST"]
)
@admin_required
def generate_tokens():

    try:

        amount = int(
            request.form.get(
                "amount",
                "10"
            )
        )

    except ValueError:

        amount = 10

    amount = max(
        1,
        min(amount, 1000)
    )

    conn = get_db()
    cur = conn.cursor()

    generated = []

    while len(generated) < amount:

        token = make_token()

        try:

            cur.execute(
                """
                INSERT INTO tokens(token)
                VALUES (%s)
                """,
                (token,)
            )

            generated.append(token)

        except psycopg2.IntegrityError:

            conn.rollback()

    conn.commit()

    cur.close()
    conn.close()

    return render_template(
        "tokens_generated.html",
        tokens=generated
    )


@app.route("/admin/tokens")
@admin_required
def tokens():

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM tokens
        ORDER BY id DESC
        """
    )

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "tokens.html",
        tokens=rows
    )


@app.route("/admin/toggle-voting", methods=["POST"])
@admin_required
def toggle_voting():

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT value
        FROM settings
        WHERE key = %s
        """,
        ("voting_open",)
    )

    current = cur.fetchone()["value"]

    new_value = (
        "0"
        if current == "1"
        else "1"
    )

    cur.execute(
        """
        UPDATE settings
        SET value = %s
        WHERE key = %s
        """,
        (
            new_value,
            "voting_open"
        )
    )

    conn.commit()

    cur.close()
    conn.close()

    flash(
        "Status voting diperbarui.",
        "success"
    )

    return redirect(
        url_for("admin_dashboard")
    )


@app.route(
    "/admin/reset-demo",
    methods=["POST"]
)
@admin_required
def reset_demo():

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM votes"
    )

    cur.execute(
        """
        UPDATE tokens
        SET used = 0,
            used_at = NULL
        """
    )

    conn.commit()

    cur.close()
    conn.close()

    flash(
        "Data voting berhasil di-reset.",
        "success"
    )

    return redirect(
        url_for("admin_dashboard")
    )


try:
    init_db()
except Exception as e:
    print("Database belum siap:", e)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )