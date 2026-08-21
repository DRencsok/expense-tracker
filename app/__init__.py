from flask import Flask
from app.database import close_db


def create_app():
    app = Flask(__name__, template_folder="../templates")

    app.config.from_object("config")

    app.teardown_appcontext(close_db)

    from app.routes import main
    app.register_blueprint(main)

    return app