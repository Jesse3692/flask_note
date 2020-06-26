from flask import Flask
from flask import redirect
from flask import render_template

app = Flask(__name__)

@app.route('/')
def index():
    return "Hello Flask"

@app.route('/rdt')
def rdt():
    return redirect("/")

@app.route('/home')
def home():
    return render_template("home.html")

if __name__ == "__main__":
    app.run(debug=True)