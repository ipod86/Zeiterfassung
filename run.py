import os
import socket
from app import create_app

app = create_app()


def _resolve_port():
    """Port, in dieser Reihenfolge: Umgebungsvariable PORT -> data/.port -> 5050.

    Die Datei data/.port wird vom Installer mit dem gewählten Port geschrieben
    und liegt im (bei Updates geschützten) data-Verzeichnis, sodass jede
    Installation ihren eigenen Port behält.
    """
    env = os.environ.get("PORT", "").strip()
    if env.isdigit():
        return int(env)
    try:
        pf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", ".port")
        with open(pf, encoding="utf-8") as f:
            val = f.read().strip()
        if val.isdigit():
            return int(val)
    except OSError:
        pass
    return 5050


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
    port = _resolve_port()
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
        from app.updater import start_update_checker
        start_update_checker()
    if dev:
        app.run(host=host, port=port, debug=True)
    else:
        from waitress import serve
        serve(app, host=host, port=port, threads=8)
