# Mileway Cabs

## Start on Windows

Install Python 3.12 with the python command on PATH, then double-click **Start Mileway.cmd**. The first start installs dependencies in an isolated environment under LocalAppData. Leave the window open and visit http://127.0.0.1:8080. Ctrl+C stops the server and notification worker. Restarting keeps the database and operator credentials.

Open /admin. The generated operator password is in %LOCALAPPDATA%\MilewayPreview\operator-password.txt. Protect this file and the database directory with your operating-system account permissions. To supply your own password, copy .env.example to .env beside run.py and set ADMIN_PASSWORD to a unique password of 16 or more characters.

On Linux or macOS, create a Python virtual environment, install requirements.txt and run python run.py. The default data directory there is ~/.local/share/MilewayPreview.

## Deploy on a native host

1. Use a persistent host and local disk. Configure .env beside run.py. Set DATA_DIR to the durable database directory, and set the business name, contact details and operator password. Environment variables supplied by the host take precedence.
2. Point your domain at the host and terminate TLS with a reverse proxy forwarding to 127.0.0.1:8080. Set HTTPS_ONLY=1. For one trusted proxy that overwrites incoming forwarded headers, set TRUST_LOCAL_PROXY=1. HOST and PORT override the bind address.
3. Use the host service manager to start the virtual environment's Python executable with the absolute path to run.py under a dedicated account. Enable restart on failure. GET /health checks database access. Use one application process per deployment.
4. Open /admin and update the four example vehicles, fuel types, capacities and rates. Disable vehicles outside your fleet. New requests stay pending until approved. Conflicting approvals are blocked per physical vehicle. All trip times are IST.
5. Configure production OSRM-compatible driving and Nominatim-compatible geocoding services covering India. The public defaults support trials and carry no uptime guarantee. Review address matches on the quote map.
6. Configure the notification accounts below and complete a controlled booking through approval, tracking and message receipt.
7. Back up fleet.sqlite using SQLite's online backup API, or stop the service before copying the data directory. Preserve session.key or the separately configured SECRET_KEY. Restrict access to backups containing passenger contact details.

## Notification accounts

ADMIN_EMAIL and ADMIN_PHONE receive new requests. Configure SMTP_HOST, SMTP_PORT, SMTP_FROM, SMTP_USER and SMTP_PASSWORD for STARTTLS email. For WhatsApp Business, supply the versioned Meta phone-number messages endpoint, token, approved template and language. Its seven body parameters are reference, status, pickup, destination, pickup time, vehicle and fare. Use international-format phone numbers. Obtain recipient permissions before activating delivery.

The worker processes configured channels and retains queued messages for others. Restart after configuration changes. Monitor delivery in /admin. Retries use backoff and stop after ten failures. After correcting provider configuration, reset affected failed notices to queued with attempts=0 and next_try=0. A crash after provider acceptance may cause duplicate delivery.

## Verification and release scope

Run python -m unittest discover -s tests from this directory. Tests use isolated storage and a deterministic road-provider fixture.

The first release includes one-way, airport and round-trip requests, route estimates, fare snapshots, vehicle calendars, operator review, tracking, cancellation and notification adapters. Online payments, hourly packages, driver accounts and analytics are later blueprint phases.
