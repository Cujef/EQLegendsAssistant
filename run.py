"""EQ Legends Assistant launcher.

Usage: python run.py [--port N] [--no-browser]
"""
import io
import sys
import threading
import webbrowser

# Windows consoles default to cp1252; mob/item names contain characters outside it
# and a print() must never crash the app (parser run.py pattern).
if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def main():
    from app.config import CONFIG
    port = CONFIG['port']
    if '--port' in sys.argv:
        port = int(sys.argv[sys.argv.index('--port') + 1])

    import uvicorn
    from app.server import app  # noqa: F401 - imported for uvicorn; also triggers startup wiring

    from app import __version__
    url = f'http://127.0.0.1:{port}'
    print(f'EQ Legends Assistant v{__version__} -> {url}')
    if '--no-browser' not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')


if __name__ == '__main__':
    main()
