"""
run.py — TokenOps standalone entry point.
This is what PyInstaller bundles into the executable.

When the user double-clicks the .exe / .app:
  1. Creates data directory (~/tokenops-data/)
  2. Starts uvicorn on port 8000
  3. Opens browser to dashboard
  4. Seeds model pricing on first run
"""
import sys
import os
import webbrowser
import threading
import time

# PyInstaller sets sys._MEIPASS when running from bundle
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    BUNDLE_DIR = sys._MEIPASS
    # Store DB in user's home directory so it persists between runs
    DATA_DIR = os.path.join(os.path.expanduser("~"), "tokenops-data")
    os.makedirs(DATA_DIR, exist_ok=True)
    DB_PATH = os.path.join(DATA_DIR, "tokenops.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
    os.environ.setdefault("SECRET_KEY", "tokenops-standalone-secret-key-32chars!!")
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("ALLOWED_ORIGINS", "*")
    # Tell the app where static files are
    os.environ["TOKENOPS_STATIC_DIR"] = os.path.join(BUNDLE_DIR, "static")
else:
    # Running from source
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    os.environ.setdefault("DATABASE_URL", "sqlite:///./tokenops.db")
    os.environ.setdefault("SECRET_KEY", "dev-secret-key-change-in-production!!")
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("ALLOWED_ORIGINS", "*")


def open_browser():
    """Open dashboard in default browser after a short delay."""
    time.sleep(2)
    url = "http://localhost:8000/dashboard"
    print(f"\n  Opening {url} in your browser...\n")
    webbrowser.open(url)


def main():
    print()
    print("  ╔══════════════════════════════════╗")
    print("  ║         TokenOps v1.0            ║")
    print("  ║   LLM Cost Intelligence          ║")
    print("  ╚══════════════════════════════════╝")
    print()
    print(f"  Dashboard:  http://localhost:8000/dashboard")
    print(f"  API Docs:   http://localhost:8000/docs")
    if getattr(sys, 'frozen', False):
        print(f"  Data:       {DATA_DIR}")
    print()
    print("  Press Ctrl+C to stop.")
    print()

    # Open browser in background
    threading.Thread(target=open_browser, daemon=True).start()

    # Start uvicorn
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
