#!/usr/bin/env python3
"""Poll the app database for ``accepted`` RL train jobs and run SB3 training (separate from API)."""

from __future__ import annotations

import argparse
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Claim rl_train_jobs rows (accepted → running) and execute Stable-Baselines3 training.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one job if available, then exit (exit 0 when idle or done).",
    )
    args = parser.parse_args()

    from app.config import get_settings
    from app.db import get_session_local, init_db
    from app.rl.train_jobs import claim_next_accepted_train_job, execute_rl_train_work

    settings = get_settings()
    if not settings.enable_rl_engine:
        logging.error("ENABLE_RL_ENGINE is false; nothing to do.")
        return 1

    init_db(settings.database_url)
    SessionLocal = get_session_local()
    poll = max(0.2, float(settings.rl_train_worker_poll_sec))

    while True:
        db = SessionLocal()
        try:
            jid = claim_next_accepted_train_job(db)
        finally:
            db.close()

        if jid:
            logging.info("Claimed RL train job %s", jid)
            execute_rl_train_work(jid)
            if args.once:
                return 0
        else:
            if args.once:
                return 0
            time.sleep(poll)


if __name__ == "__main__":
    sys.exit(main())
