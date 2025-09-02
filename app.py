from flask import Flask, flash, session, request, redirect, url_for, render_template, jsonify
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from functools import wraps         # For login
import psycopg2
import os

# Load env vars
load_dotenv()

app = Flask(__name__)
secret_key = os.getenv("SECRET_KEY", "keykey")
app.config["SECRET_KEY"] = secret_key 



# ---------- Database helper ----------
def get_connection():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
    )

# -------------------- Routes --------------------


@app.get("/")
def index():
    return redirect(url_for("register_form"), code=302)

@app.route("/register", methods=["GET"])
def register_form():
    return render_template("register.html")


@app.route("/register", methods=["POST"])
def register_submit() -> None:
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        
        if not username or not password:
            flash("Username and password required.")
            return redirect(url_for("register_form"), 303)

        hashed = generate_password_hash(password)

        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO users (username, password_hash)
                VALUES (%s, %s)
                ON CONFLICT (username) DO NOTHING
                """,
                (username, hashed)   
            )
            if cur.rowcount == 1:
                conn.commit()
                flash("✅ Registered Successfully!", "success")
            else:
                conn.rollback()
                flash("Username already exists. Please choose another.", "error")

        except Exception as e:
            flash(f"Error: {e}")

    return redirect(url_for("register_form"), 303)



@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if not username or not password:
            flash("Username and password required.", "error")
            return redirect(url_for("login"), 303)

        conn = cur = None
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT id, username, password_hash FROM users WHERE username = %s",
                (username,),
            )
            row = cur.fetchone()

            if not row:
                flash("No such user.", "error")
                return redirect(url_for("login"), 303)

            user_id, db_username, db_hash = row
            if not check_password_hash(db_hash, password):
                flash("Incorrect password.", "error")
                return redirect(url_for("login"), 303)

            session["user_id"] = user_id
            session["username"] = db_username
            flash("Logged in successfully!", "success")
            return redirect(url_for("home"), 303)

        except Exception as e:
            flash(f"Error: {e}", "error")
            return redirect(url_for("login"), 303)
        finally:
            if cur: cur.close()
            if conn: conn.close()

    # IMPORTANT: for GET, always return the template
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"), 303)



def login_required(view_func):
    @wraps(view_func)  # keeps original function name
    def wrapper(*args, **kwargs):
        # Check if user is logged in
        if "user_id" not in session:
            flash("Please log in first.", "error")
            return redirect(url_for("login"), 303)
        # If logged in, call the original function
        return view_func(*args, **kwargs)
    return wrapper



# ----------------- HOME PAGE -----------------
@app.route("/home", methods=["GET"])
@login_required
def home():
    conn = cur = None
    chats = []
    try:
        conn = get_connection()
        cur = conn.cursor()
        # Only chats the current user is in; newest activity first
        cur.execute("""
            SELECT c.id, u.username
            FROM chats c
            JOIN chat_members cm_self ON cm_self.chat_id = c.id AND cm_self.user_id = %s
            JOIN chat_members cm_other ON cm_other.chat_id = c.id AND cm_other.user_id <> %s
            JOIN users u ON u.id = cm_other.user_id
            WHERE (SELECT COUNT(*) FROM chat_members WHERE chat_id = c.id) = 2
            ORDER BY COALESCE(c.updated_at, c.created_at) DESC, c.id DESC
        """, (session["user_id"], session["user_id"]))
        rows = cur.fetchall()  # [(chat_id, other_username), ...]
        chats = [{"id": r[0], "username": r[1]} for r in rows]
    except Exception as e:
        flash(f"Error loading chats: {e}", "error")
    finally:
        if cur: cur.close()
        if conn: conn.close()

    return render_template(
        "home.html",
        username=session.get("username"),
        chats=chats
    )



@app.route("/search_users", methods=["GET"])
@login_required
def search_users():
    q = (request.args.get("q") or "").strip()
    me = session["user_id"]
    if not q:
        return jsonify([])
    conn = cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, username
            FROM users
            WHERE username ILIKE %s AND id <> %s
            ORDER BY username ASC
            LIMIT 10
        """, (f"%{q}%", me))
        rows = cur.fetchall()
        return jsonify([{"id": r[0], "username": r[1]} for r in rows])
    finally:
        if cur: cur.close()
        if conn: conn.close()


def find_or_create_dm(conn, current_user_id: int, target_user_id: int) -> int:
    cur = conn.cursor()
    try:
        # Try to find a dm between the two user
        cur.execute("""
            SELECT c.id
            FROM chats c
            JOIN chat_members cm1 ON cm1.chat_id = c.id AND cm1.user_id = %s
            JOIN chat_members cm2 ON cm2.chat_id = c.id AND cm2.user_id = %s
            WHERE (SELECT COUNT(*) FROM chat_members WHERE chat_id = c.id) = 2
            LIMIT 1
        """, (current_user_id, target_user_id))

        # If found one, reuse it
        row = cur.fetchone()
        if row:
            return row[0]

        # Otherwise create a new dm
        cur.execute("INSERT INTO chats (title) VALUES (%s) RETURNING id", ("Chat",))
        chat_id = cur.fetchone()[0]

        # Also add the chat into chats and members into chat_members
        cur.execute("INSERT INTO chat_members (chat_id, user_id) VALUES (%s, %s)", (chat_id, current_user_id))
        cur.execute("INSERT INTO chat_members (chat_id, user_id) VALUES (%s, %s)", (chat_id, target_user_id))
        conn.commit()
        return chat_id
    
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


@app.route("/start_dm", methods=["POST"])
@login_required
def start_dm():
    target_username = (request.form.get("username") or "").strip()
    if not target_username:
        flash("No username provided.", "error")
        return redirect(url_for("home"), 303)

    conn = cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username = %s", (target_username,))
        row = cur.fetchone()
        if not row:
            flash("User not found.", "error")
            return redirect(url_for("home"), 303)

        target_user_id = row[0]
        chat_id = find_or_create_dm(conn, session["user_id"], target_user_id)

        # optional: bump to top on /home immediately
        with conn.cursor() as c2:
            c2.execute("UPDATE chats SET updated_at = NOW() WHERE id = %s", (chat_id,))
            conn.commit()

        return redirect(url_for("chat", chat_id=chat_id), 303)
    except Exception:
        if conn: conn.rollback()
        flash("Could not start chat.", "error")
        return redirect(url_for("home"), 303)
    finally:
        if cur: cur.close()
        if conn: conn.close()



"""
When user visits any chat -> GET 
When user sends a text -> POST
"""
@app.route("/chat/<int:chat_id>", methods=["GET", "POST"])
@login_required
def chat(chat_id):
    if request.method == "POST":
        body = (request.form.get("body") or "").strip()
        if not body:
            flash("Message cannot be empty.", "error")
            return redirect(url_for("chat", chat_id=chat_id), 303)
        conn = cur = None
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO messages (chat_id, user_id, body) VALUES (%s, %s, %s)",
                (chat_id, session["user_id"], body)
            )
            cur.execute("UPDATE chats SET updated_at = NOW() WHERE id = %s", (chat_id,))
            conn.commit()
        except Exception as e:
            if conn: conn.rollback()
            flash(f"Could not send message: {e}", "error")
        finally:
            if cur: cur.close()
            if conn: conn.close()
        return redirect(url_for("chat", chat_id=chat_id), 303)

    # GET request: load messages
    conn = cur = None
    messages = []
    chat_title = f"Chat {chat_id}"
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT m.id, u.username, m.body, m.created_at
            FROM messages m
            JOIN users u ON u.id = m.user_id
            WHERE m.chat_id = %s
            ORDER BY m.created_at ASC, m.id ASC
            """,
            (chat_id,)
        )
        messages = cur.fetchall()
        flash(f"Loaded {len(messages)} message(s)", "info")

        cur.execute(
            """
            SELECT u.username
            FROM chat_members cm
            JOIN users u ON u.id = cm.user_id
            WHERE cm.chat_id = %s AND cm.user_id <> %s
            LIMIT 1
            """,
            (chat_id, session["user_id"])
        )
        row = cur.fetchone()
        if row:
            chat_title = row[0]
    except Exception as e:
        flash(f"Error loading messages: {e}", "error")
    finally:
        if cur: cur.close()
        if conn: conn.close()

    return render_template(
        "chat.html",
        chat_id=chat_id,
        chat_title=chat_title,
        messages=messages
    )

if __name__ == "__main__":
    app.run(debug=True, port=5000)
