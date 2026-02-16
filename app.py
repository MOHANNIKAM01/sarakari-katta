import os
import sqlite3
from datetime import datetime
from urllib.parse import urlparse

from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, Response
from werkzeug.security import generate_password_hash, check_password_hash

# Postgres (Neon) support
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

# ✅ Secret key (Render/Prod मध्ये ENV ने set कर)
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE_THIS_TO_A_RANDOM_SECRET_KEY")

# ✅ Branding (इथे नाव/लोगो/टॅगलाइन one-place change)
BRAND = {
    "site_name": "Sarakari Katta",
    "tagline": "तुमच्या प्रगतीचा सोबती",   # ✅ exact as requested (no change)
    "logo_text": "SK",
}

CATEGORIES = [
    ("jobs", "Jobs"),
    ("results", "Results"),
    ("schemes", "Schemes"),
    ("exam_cutoffs", "Exam Cutoffs"),
    ("current_affairs", "Current Affairs"),
]

NAV_ITEMS = [
    ("jobs", "Jobs"),
    ("results", "Results"),
    ("schemes", "Schemes"),
    ("exam_cutoffs", "Exam Cutoffs"),
    ("current_affairs", "Current Affairs"),
]

# =========================
# ✅ ADS SYSTEM (AUTO HIDE until monetize)
# =========================
ADSENSE_CLIENT = os.getenv("ADSENSE_CLIENT", "").strip()  # e.g. ca-pub-xxxxxxxxxxxx
ADS_ENABLED = bool(ADSENSE_CLIENT)

ADS_SLOT_TOP = os.getenv("ADS_SLOT_TOP", "").strip()
ADS_SLOT_SIDE = os.getenv("ADS_SLOT_SIDE", "").strip()
ADS_SLOT_INCONTENT = os.getenv("ADS_SLOT_INCONTENT", "").strip()

app.config["ADS_ENABLED"] = ADS_ENABLED
app.config["ADSENSE_CLIENT"] = ADSENSE_CLIENT
app.config["ADS_SLOT_TOP"] = ADS_SLOT_TOP
app.config["ADS_SLOT_SIDE"] = ADS_SLOT_SIDE
app.config["ADS_SLOT_INCONTENT"] = ADS_SLOT_INCONTENT


# =========================
# ✅ DB SETUP (SQLite local dev fallback, Postgres on Render/Neon)
# =========================
DB_NAME = "database.db"
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()

# Render/Neon कधी कधी postgres:// देतात; psycopg2 ला postgresql:// चालतो, पण postgres:// सुद्धा चालतो.
# तरी normalize ठेवू
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

USE_POSTGRES = DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")


class DBConn:
    """
    sqlite3 आणि psycopg2 दोन्हींसाठी common interface
    - execute().fetchone()/fetchall() काम करेल
    """
    def __init__(self, conn, is_pg: bool):
        self.conn = conn
        self.is_pg = is_pg

    def execute(self, query: str, params=()):
        if self.is_pg:
            cur = self.conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(query, params or ())
            return cur
        else:
            return self.conn.execute(query, params or ())

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def get_db():
    """
    - Local: SQLite
    - Render/Prod: Postgres (Neon)
    """
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        return DBConn(conn, True)

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return DBConn(conn, False)


def init_db():
    db = get_db()

    if USE_POSTGRES:
        # Postgres schema
        db.execute("""
            CREATE TABLE IF NOT EXISTS users(
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS posts(
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                summary TEXT NOT NULL,
                content TEXT NOT NULL,
                official_link TEXT,
                form_link TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # default admin (idempotent)
        default_pass = os.environ.get("ADMIN_PASSWORD", "Admin@12345")
        now = datetime.now().isoformat()

        db.execute(
            """
            INSERT INTO users(username, password_hash, created_at)
            VALUES(%s, %s, %s)
            ON CONFLICT (username) DO NOTHING
            """,
            ("admin", generate_password_hash(default_pass), now),
        )
        db.commit()
        db.close()
        return

    # SQLite schema
    db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS posts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            summary TEXT NOT NULL,
            content TEXT NOT NULL,
            official_link TEXT,
            form_link TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # default admin
    cur = db.execute("SELECT 1 FROM users WHERE username=?", ("admin",))
    if not cur.fetchone():
        default_pass = os.environ.get("ADMIN_PASSWORD", "Admin@12345")
        db.execute(
            "INSERT INTO users(username, password_hash, created_at) VALUES(?,?,?)",
            ("admin", generate_password_hash(default_pass), datetime.now().isoformat()),
        )
        print("✅ Default admin: admin / Admin@12345  (लॉगिन करून लगेच change कर)")

    db.commit()
    db.close()


# ✅ Gunicorn/Render मध्ये पण DB initialize होण्यासाठी
init_db()


@app.context_processor
def inject_globals():
    return dict(
        NAV_ITEMS=NAV_ITEMS,
        BRAND=BRAND,
        current_year=datetime.now().year,
        ADS_ENABLED=app.config["ADS_ENABLED"],
        ADSENSE_CLIENT=app.config["ADSENSE_CLIENT"],
        ADS_SLOT_TOP=app.config["ADS_SLOT_TOP"],
        ADS_SLOT_SIDE=app.config["ADS_SLOT_SIDE"],
        ADS_SLOT_INCONTENT=app.config["ADS_SLOT_INCONTENT"],
    )


def is_logged_in():
    return bool(session.get("user"))


# =========================
# ✅ SEO BASE URL HELPER
# =========================
def get_base_url():
    """
    SEO साठी canonical base URL
    - prod मध्ये ENV SITE_URL दिलं असेल तर ते वापर
    - नाहीतर request.host_url वापर (Render URL / custom domain दोन्ही चालेल)
    """
    site = (os.getenv("SITE_URL") or "").strip()
    if site:
        return site.rstrip("/")
    return request.host_url.rstrip("/")


# =========================
# ✅ SITEMAP + ROBOTS
# =========================
@app.route("/sitemap.xml")
def sitemap():
    base = get_base_url()

    urls = []
    # core pages
    urls.append(f"{base}/")
    for key, _label in CATEGORIES:
        urls.append(f"{base}/category/{key}")

    # posts
    db = get_db()
    if USE_POSTGRES:
        rows = db.execute("SELECT id FROM posts ORDER BY created_at DESC").fetchall()
        for r in rows:
            urls.append(f"{base}/post/{r['id']}")
    else:
        rows = db.execute("SELECT id FROM posts ORDER BY created_at DESC").fetchall()
        for r in rows:
            urls.append(f"{base}/post/{r['id']}")

    db.close()

    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]
    for u in urls:
        xml.append(f"<url><loc>{u}</loc></url>")
    xml.append("</urlset>")

    return Response("\n".join(xml), mimetype="application/xml")


@app.route("/robots.txt")
def robots():
    base = get_base_url()
    body = "\n".join([
        "User-agent: *",
        "Allow: /",
        f"Sitemap: {base}/sitemap.xml"
    ])
    return Response(body, mimetype="text/plain")


@app.route("/")
def index():
    db = get_db()

    if USE_POSTGRES:
        posts = db.execute(
            "SELECT * FROM posts ORDER BY created_at DESC LIMIT 12"
        ).fetchall()

        cat_blocks = {}
        for key, label in CATEGORIES:
            cat_posts = db.execute(
                "SELECT * FROM posts WHERE category=%s ORDER BY created_at DESC LIMIT 4",
                (key,),
            ).fetchall()
            cat_blocks[key] = {"label": label, "posts": cat_posts}

        db.close()
        return render_template("index.html", posts=posts, cat_blocks=cat_blocks)

    posts = db.execute(
        "SELECT * FROM posts ORDER BY created_at DESC LIMIT 12"
    ).fetchall()

    cat_blocks = {}
    for key, label in CATEGORIES:
        cat_posts = db.execute(
            "SELECT * FROM posts WHERE category=? ORDER BY created_at DESC LIMIT 4",
            (key,),
        ).fetchall()
        cat_blocks[key] = {"label": label, "posts": cat_posts}

    db.close()
    return render_template("index.html", posts=posts, cat_blocks=cat_blocks)


@app.route("/category/<cat_key>")
def category(cat_key):
    if cat_key not in [c[0] for c in CATEGORIES]:
        abort(404)

    db = get_db()
    if USE_POSTGRES:
        posts = db.execute(
            "SELECT * FROM posts WHERE category=%s ORDER BY created_at DESC",
            (cat_key,),
        ).fetchall()
    else:
        posts = db.execute(
            "SELECT * FROM posts WHERE category=? ORDER BY created_at DESC",
            (cat_key,),
        ).fetchall()

    db.close()
    label = dict(CATEGORIES).get(cat_key, cat_key)
    return render_template("category.html", posts=posts, cat_key=cat_key, label=label)


@app.route("/post/<int:post_id>")
def post(post_id):
    db = get_db()

    if USE_POSTGRES:
        p = db.execute("SELECT * FROM posts WHERE id=%s", (post_id,)).fetchone()
        if not p:
            db.close()
            abort(404)

        related = db.execute(
            "SELECT * FROM posts WHERE category=%s AND id<>%s ORDER BY created_at DESC LIMIT 6",
            (p["category"], post_id),
        ).fetchall()
        db.close()
        return render_template("post.html", post=p, related=related)

    p = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not p:
        db.close()
        abort(404)

    related = db.execute(
        "SELECT * FROM posts WHERE category=? AND id<>? ORDER BY created_at DESC LIMIT 6",
        (p["category"], post_id),
    ).fetchall()
    db.close()

    return render_template("post.html", post=p, related=related)


@app.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return redirect(url_for("index"))

    db = get_db()
    if USE_POSTGRES:
        posts = db.execute(
            """
            SELECT * FROM posts
            WHERE title ILIKE %s OR summary ILIKE %s OR content ILIKE %s
            ORDER BY created_at DESC
            """,
            (f"%{q}%", f"%{q}%", f"%{q}%"),
        ).fetchall()
        db.close()
        return render_template("category.html", posts=posts, cat_key="search", label=f"Search: {q}")

    posts = db.execute(
        """
        SELECT * FROM posts
        WHERE title LIKE ? OR summary LIKE ? OR content LIKE ?
        ORDER BY created_at DESC
        """,
        (f"%{q}%", f"%{q}%", f"%{q}%"),
    ).fetchall()
    db.close()

    return render_template("category.html", posts=posts, cat_key="search", label=f"Search: {q}")


# ---------- Admin ----------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        db = get_db()
        if USE_POSTGRES:
            user = db.execute("SELECT * FROM users WHERE username=%s", (username,)).fetchone()
        else:
            user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        db.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user"] = username
            flash("✅ Login successful", "success")
            return redirect(url_for("admin"))

        flash("❌ Invalid username/password", "error")

    return render_template("login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    flash("✅ Logged out", "success")
    return redirect(url_for("index"))


@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not is_logged_in():
        return redirect(url_for("admin_login"))

    db = get_db()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "create":
            title = request.form.get("title", "").strip()
            category = request.form.get("category", "").strip()
            summary = request.form.get("summary", "").strip()
            content = request.form.get("content", "").strip()
            official_link = request.form.get("official_link", "").strip()
            form_link = request.form.get("form_link", "").strip()

            if not title or not summary or not content or category not in [c[0] for c in CATEGORIES]:
                flash("❌ Title, Summary, Content आणि Category required", "error")
            else:
                now = datetime.now().isoformat()

                if USE_POSTGRES:
                    db.execute(
                        """
                        INSERT INTO posts(title, category, summary, content, official_link, form_link, created_at, updated_at)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (title, category, summary, content, official_link, form_link, now, now),
                    )
                else:
                    db.execute(
                        """
                        INSERT INTO posts(title, category, summary, content, official_link, form_link, created_at, updated_at)
                        VALUES(?,?,?,?,?,?,?,?)
                        """,
                        (title, category, summary, content, official_link, form_link, now, now),
                    )

                db.commit()
                flash("✅ Post created", "success")

        elif action == "delete":
            pid = request.form.get("post_id")
            if pid:
                if USE_POSTGRES:
                    db.execute("DELETE FROM posts WHERE id=%s", (pid,))
                else:
                    db.execute("DELETE FROM posts WHERE id=?", (pid,))
                db.commit()
                flash("🗑️ Post deleted", "success")

        elif action == "update_password":
            oldp = request.form.get("old_password", "")
            newp = request.form.get("new_password", "")

            if len(newp) < 8:
                flash("❌ New password किमान 8 characters", "error")
            else:
                if USE_POSTGRES:
                    user = db.execute("SELECT * FROM users WHERE username=%s", (session["user"],)).fetchone()
                else:
                    user = db.execute("SELECT * FROM users WHERE username=?", (session["user"],)).fetchone()

                if user and check_password_hash(user["password_hash"], oldp):
                    if USE_POSTGRES:
                        db.execute(
                            "UPDATE users SET password_hash=%s WHERE username=%s",
                            (generate_password_hash(newp), session["user"]),
                        )
                    else:
                        db.execute(
                            "UPDATE users SET password_hash=? WHERE username=?",
                            (generate_password_hash(newp), session["user"]),
                        )
                    db.commit()
                    flash("✅ Password updated", "success")
                else:
                    flash("❌ Old password wrong", "error")

    if USE_POSTGRES:
        posts = db.execute("SELECT * FROM posts ORDER BY created_at DESC").fetchall()
    else:
        posts = db.execute("SELECT * FROM posts ORDER BY created_at DESC").fetchall()

    db.close()
    return render_template("admin.html", posts=posts, categories=CATEGORIES)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)