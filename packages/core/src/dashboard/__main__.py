"""Run one loopback dashboard coordinator."""
from .app import app
from .constants import HOST, PORT

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False)