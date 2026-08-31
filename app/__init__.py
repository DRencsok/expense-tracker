from flask import Flask
from flask_wtf.csrf import CSRFProtect
from app.database import close_db, init_db

csrf = CSRFProtect()


def create_app():
    app = Flask(__name__, template_folder="../templates",
                static_folder="../static",
                )

    app.config.from_object("config")
    csrf.init_app(app)

    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()

    from app.routes import main
    app.register_blueprint(main)

    return app