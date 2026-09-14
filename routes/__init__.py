"""Every blueprint, registered in one fixed order. app.py calls
register_all(app) after its own hooks are in place."""
from flask import Flask


def register_all(app: Flask) -> None:
    from routes import auth, integration, setup, stream, admin_library, admin_misc, spa
    for mod in (auth, integration, setup, stream, admin_library, admin_misc, spa):
        app.register_blueprint(mod.bp)
