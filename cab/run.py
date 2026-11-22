"""Start the native web server and notification worker."""
import logging
import os
import secrets
import threading
from pathlib import Path

from dotenv import load_dotenv


def main():
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env", interpolate=False)
    home = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local/share") / "MilewayPreview"
    directory = Path(os.getenv("DATA_DIR") or home).expanduser()
    if not directory.is_absolute():
        directory = root / directory
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.environ["DATA_DIR"] = str(directory)
    if not os.getenv("ADMIN_PASSWORD"):
        password = directory / "operator-password.txt"
        try:
            with os.fdopen(os.open(password, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as f:
                f.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass
        os.environ["ADMIN_PASSWORD"] = password.read_text().strip()
        logging.info("Operator password file: %s", password)
    if len(os.environ["ADMIN_PASSWORD"]) < 16:
        raise SystemExit("ADMIN_PASSWORD needs at least 16 characters.")

    from waitress import create_server
    from app import app
    from notify import run_worker

    host = os.getenv("HOST") or "127.0.0.1"
    port = int(os.getenv("PORT") or 8080)
    server = create_server(app, host=host, port=port)
    stop = threading.Event()
    worker = threading.Thread(target=run_worker, args=(stop,), daemon=True, name="notifications")
    worker.start()
    logging.info("Booking site listening at http://%s:%s", host, port)
    try:
        server.run()
    finally:
        stop.set()
        server.close()
        worker.join(timeout=5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
