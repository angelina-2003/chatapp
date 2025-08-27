from flask import Flask, render_template, request

app = Flask(__name__)


@app.route("/register", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        return f"You entered: {username} / {password}"

    return render_template("register.html")



if __name__ == "__main__":
    app.run(debug=True, port=5060)

