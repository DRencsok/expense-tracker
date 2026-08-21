from flask import Flask

app = Flask(__name__)

#Main page
@app.route('/')
def homepage():
    return 'Hello, welcome to the homepage!'
