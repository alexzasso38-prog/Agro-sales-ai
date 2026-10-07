"""Run the scheduler. It creates reviewable drafts and NEVER sends emails."""
import argparse
import logging
import time
from .config import Settings
from .db import Base, database
from .seed import seed
from .services import run_due

def main():
    parser = argparse.ArgumentParser(description='Worker Agro Sales AI: genera bozze da approvare.')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--interval', type=int, default=30)
    args = parser.parse_args()
    if args.interval < 1:
        parser.error('--interval deve essere almeno 1 secondo')
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    engine, sessions = database(settings.database_url)
    Base.metadata.create_all(engine)
    if settings.demo_mode:
        with sessions() as session:
            seed(session)
    try:
        while True:
            try:
                with sessions() as session:
                    result = run_due(session)
                    if result['processed']:
                        logging.info('Attività elaborate: %s', result)
            except Exception:
                logging.exception('Errore worker; nessun invio automatico eseguito.')
                if args.once:
                    raise
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        engine.dispose()

if __name__ == '__main__':
    main()
