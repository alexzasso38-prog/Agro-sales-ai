#!/usr/bin/env python3
"""Start the three local demo processes together; Ctrl+C stops all of them."""
import argparse
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-port', type=int, default=8000)
    parser.add_argument('--web-port', type=int, default=5173)
    args = parser.parse_args()
    if args.api_port == args.web_port or any(not 1024 <= p <= 65535 for p in (args.api_port, args.web_port)):
        parser.error('Scegli due porte diverse tra 1024 e 65535.')
    python = ROOT / '.venv/bin/python'
    npm = shutil.which('npm')
    if not python.is_file() or not npm or not (ROOT / 'frontend/node_modules/.bin/vite').exists():
        parser.error('Installa Python 3.11+, Node 20.19+/22.12+ e le dipendenze con make install.')
    for port in (args.api_port, args.web_port):
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
            except OSError:
                parser.error(f'Porta {port} occupata: ferma il precedente servizio dal suo terminale.')
    env = dict(os.environ)
    env.update(DEMO_MODE='true', ALLOW_EXTERNAL_INTEGRATIONS='false',
               DATABASE_URL=f'sqlite:///{ROOT / "backend/data/agro.db"}',
               VITE_API_PROXY=f'http://127.0.0.1:{args.api_port}')
    processes = []
    commands = [
        ([str(python), '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(args.api_port)], ROOT / 'backend'),
        ([npm, 'run', 'dev', '--', '--host', '127.0.0.1', '--port', str(args.web_port), '--strictPort'], ROOT / 'frontend'),
        ([str(python), '-m', 'app.worker', '--interval', '1'], ROOT / 'backend'),
    ]

    def interrupted(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        # The worker starts after API schema initialization, avoiding two first-boot DDL writers.
        for command, cwd in commands[:2]:
            processes.append(subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if any(p.poll() is not None for p in processes):
                raise RuntimeError('Un servizio si è fermato durante l’avvio; controlla il messaggio sopra.')
            try:
                with urlopen(f'http://127.0.0.1:{args.web_port}/health', timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.3)
        else:
            raise RuntimeError('Avvio non completato entro 30 secondi.')
        command, cwd = commands[2]
        processes.append(subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True))
        print(f'\nDEMO pronta sul computer che esegue questo comando: http://127.0.0.1:{args.web_port}', flush=True)
        print('Premi «Entra nella demo» → «Automazioni AI» → «Prova lo scenario demo».', flush=True)
        print('Backend, interfaccia e worker attivi. Nessun invio o chiamata reale. Ctrl+C ferma tutto.\n', flush=True)
        while True:
            for process in processes:
                if process.poll() is not None:
                    raise RuntimeError('Un servizio si è fermato; tutti gli altri vengono arrestati.')
            time.sleep(0.5)
    except KeyboardInterrupt:
        print('\nArresto della demo…', flush=True)
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError) as error:
        print(f'Errore: {error}', file=sys.stderr)
        sys.exit(1)
