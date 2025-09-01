from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv
import psycopg2
import os

# Load env vars
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-key")

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
                "INSERT INTO users (username, password_hash) VALUES (%s, %s)", (username, hashed)
            )
            conn.commit()
            cur.close()
            conn.close()
            flash("Registered Successfully!")

        except Exception as e:
            flash(f"Error: {e}")


    return redirect(url_for("register_form"), 303)



if __name__ == "__main__":
    app.run(debug=True, port=5000)

