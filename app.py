import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# ✅ Secret key (Render/Prod मध्ये ENV ने set कर)
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE_THIS_TO_A_RANDOM_SECRET_KEY")

DB_NAME = "database.db"

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

# Optional: if you create separate ad units in AdSense, store their slot IDs as ENV
ADS_SLOT_TOP = os.getenv("ADS_SLOT_TOP", "").strip()
ADS_SLOT_SIDE = os.getenv("ADS_SLOT_SIDE", "").strip()
ADS_SLOT_INCONTENT = os.getenv("ADS_SLOT_INCONTENT", "").strip()

app.config["ADS_ENABLED"] = ADS_ENABLED
app.config["ADSENSE_CLIENT"] = ADSENSE_CLIENT
app.config["ADS_SLOT_TOP"] = ADS_SLOT_TOP
app.config["ADS_SLOT_SIDE"] = ADS_SLOT_SIDE
app.config["ADS_SLOT_INCONTENT"] = ADS_SLOT_INCONTENT


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
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
    cur.execute("SELECT 1 FROM users WHERE username=?", ("admin",))
    if not cur.fetchone():
        default_pass = os.environ.get("ADMIN_PASSWORD", "Admin@12345")
        cur.execute(
            "INSERT INTO users(username, password_hash, created_at) VALUES(?,?,?)",
            ("admin", generate_password_hash(default_pass), datetime.now().isoformat()),
        )
        print("✅ Default admin: admin / Admin@12345  (लॉगिन करून लगेच change कर)")

    conn.commit()
    conn.close()


# ✅ Gunicorn/Render मध्ये पण DB initialize होण्यासाठी
init_db()


@app.context_processor
def inject_globals():
    return dict(
        NAV_ITEMS=NAV_ITEMS,
        BRAND=BRAND,
        current_year=datetime.now().year,
        # ✅ ads variables available in templates
        ADS_ENABLED=app.config["ADS_ENABLED"],
        ADSENSE_CLIENT=app.config["ADSENSE_CLIENT"],
        ADS_SLOT_TOP=app.config["ADS_SLOT_TOP"],
        ADS_SLOT_SIDE=app.config["ADS_SLOT_SIDE"],
        ADS_SLOT_INCONTENT=app.config["ADS_SLOT_INCONTENT"],
    )


def is_logged_in():
    return bool(session.get("user"))


@app.route("/")
def index():
    conn = get_db()

    posts = conn.execute(
        "SELECT * FROM posts ORDER BY created_at DESC LIMIT 12"
    ).fetchall()

    cat_blocks = {}
    for key, label in CATEGORIES:
        cat_posts = conn.execute(
            "SELECT * FROM posts WHERE category=? ORDER BY created_at DESC LIMIT 4",
            (key,),
        ).fetchall()
        cat_blocks[key] = {"label": label, "posts": cat_posts}

    conn.close()
    return render_template("index.html", posts=posts, cat_blocks=cat_blocks)


@app.route("/category/<cat_key>")
def category(cat_key):
    if cat_key not in [c[0] for c in CATEGORIES]:
        abort(404)

    conn = get_db()
    posts = conn.execute(
        "SELECT * FROM posts WHERE category=? ORDER BY created_at DESC",
        (cat_key,),
    ).fetchall()
    conn.close()

    label = dict(CATEGORIES).get(cat_key, cat_key)
    return render_template("category.html", posts=posts, cat_key=cat_key, label=label)


@app.route("/post/<int:post_id>")
def post(post_id):
    conn = get_db()
    p = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not p:
        conn.close()
        abort(404)

    related = conn.execute(
        "SELECT * FROM posts WHERE category=? AND id<>? ORDER BY created_at DESC LIMIT 6",
        (p["category"], post_id),
    ).fetchall()
    conn.close()

    return render_template("post.html", post=p, related=related)


@app.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return redirect(url_for("index"))

    conn = get_db()
    posts = conn.execute(
        """
        SELECT * FROM posts
        WHERE title LIKE ? OR summary LIKE ? OR content LIKE ?
        ORDER BY created_at DESC
        """,
        (f"%{q}%", f"%{q}%", f"%{q}%"),
    ).fetchall()
    conn.close()

    return render_template("category.html", posts=posts, cat_key="search", label=f"Search: {q}")


# ---------- Admin ----------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()

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

    conn = get_db()

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
                conn.execute(
                    """
                    INSERT INTO posts(title, category, summary, content, official_link, form_link, created_at, updated_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (title, category, summary, content, official_link, form_link, now, now),
                )
                conn.commit()
                flash("✅ Post created", "success")

        elif action == "delete":
            pid = request.form.get("post_id")
            if pid:
                conn.execute("DELETE FROM posts WHERE id=?", (pid,))
                conn.commit()
                flash("🗑️ Post deleted", "success")

        elif action == "update_password":
            oldp = request.form.get("old_password", "")
            newp = request.form.get("new_password", "")

            if len(newp) < 8:
                flash("❌ New password किमान 8 characters", "error")
            else:
                user = conn.execute("SELECT * FROM users WHERE username=?", (session["user"],)).fetchone()
                if user and check_password_hash(user["password_hash"], oldp):
                    conn.execute(
                        "UPDATE users SET password_hash=? WHERE username=?",
                        (generate_password_hash(newp), session["user"]),
                    )
                    conn.commit()
                    flash("✅ Password updated", "success")
                else:
                    flash("❌ Old password wrong", "error")

    posts = conn.execute("SELECT * FROM posts ORDER BY created_at DESC").fetchall()
    conn.close()

    return render_template("admin.html", posts=posts, categories=CATEGORIES)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)