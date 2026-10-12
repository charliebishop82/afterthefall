"""Local operator commands; never run restore while the game server is running."""
import argparse
import getpass
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import time

from database.create_database import connect_database
from game import admin

ROOT = Path(__file__).resolve().parent


def check(c):
    if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or c.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('Database integrity check failed.')
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'accounts', 'auth_sessions', 'settlements', 'admin_actions'} <= tables:
        raise ValueError('Choose an account-game database.')


def backup(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError('Save does not exist.')
    # Exclusive creation prevents accidental replacement of an earlier backup.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb'):
        pass
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as src, closing(connect_database(destination)) as dst:
            check(src)
            src.backup(dst)
            check(dst)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def restore(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or not source.is_file() or not destination.is_file():
        raise ValueError('Choose a backup and a different existing account save.')
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as src:
        check(src)
        # Take a recovery copy first. Operator must stop all servers before restoring.
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        recovery = backup(destination, destination.parent/'backups'/f'{destination.stem}-before-restore-{stamp}.db')
        with closing(connect_database(destination)) as dst:
            src.backup(dst)
            # A restored backup must not resurrect logged-out or suspended sessions.
            with dst:
                dst.execute('DELETE FROM auth_sessions')
            check(dst)
    return recovery


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT/'database/playtest.db')
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create-admin'); create.add_argument('username')
    grant = commands.add_parser('grant-admin'); grant.add_argument('username')
    save = commands.add_parser('backup'); save.add_argument('--output', type=Path)
    load = commands.add_parser('restore'); load.add_argument('source', type=Path); load.add_argument('--server-stopped', action='store_true')
    args = parser.parse_args(argv)
    try:
        if not args.database.is_file():
            raise ValueError('Account save does not exist. Start the account server and create an account first.')
        if args.command == 'create-admin':
            with closing(connect_database(args.database)) as c: check(c)
            password = getpass.getpass('New administrator password (12+ characters): ')
            if password != getpass.getpass('Confirm password: '): raise ValueError('Passwords do not match.')
            accounts_id = admin.create_operator(args.database, args.username, password, int(time.time()))
            print(f'Administrator #{accounts_id} created. Log in to the independent console on port 8768.')
        elif args.command == 'grant-admin':
            with closing(connect_database(args.database)) as c:
                check(c)
            aid = admin.grant(args.database, args.username, int(time.time()))
            print(f'Administrator access granted to account #{aid}. Log in to the independent console on port 8768.')
        elif args.command == 'backup':
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            output = args.output or args.database.parent/'backups'/f'accounts-{stamp}.db'
            print('Backup:', backup(args.database, output))
        else:
            if not args.server_stopped:
                raise ValueError('Stop every game server, then confirm with --server-stopped.')
            print('Restored. Previous save backup:', restore(args.source, args.database))
        return 0
    except (ValueError, OSError, sqlite3.Error) as error:
        print(f'Command failed: {error}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
