import os
import socket
from app import create_app

app = create_app()


def _local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    host = "0.0.0.0"
    ip = _local_ip()
    print("=" * 56)
    print("  Zeiterfassung läuft")
    print(f"  Dieser Rechner : http://localhost:{port}")
    print(f"  Im Netzwerk    : http://{ip}:{port}")
    print("  Beenden mit Strg+C")
    print("=" * 56)
    dev = bool(os.environ.get("DEV"))
    # start the daily auto-backup scheduler (skip the reloader's parent process)
    if not dev or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        from app.backup import start_scheduler
        start_scheduler()
    if dev:
        app.run(host=host, port=port, debug=True)
    else:
        from waitress import serve
        serve(app, host=host, port=port, threads=8)
