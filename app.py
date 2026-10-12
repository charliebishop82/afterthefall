"""Run the local settlement prototype: python app.py (standard library only)."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import sqlite3
import sys
import time
import json
from urllib.parse import parse_qs, urlsplit

from game.settlement import create_settlement, prepare_database, read_settlement
from game.views import render_page
from game.simulation import advance_settlement, apply_action, resource_rates
from game.buildings import change_building
from game.building_views import live_payload
from game.scavenging import assign as assign_scavenger

ROOT = Path(__file__).resolve().parent
DEFAULT_SAVE = ROOT / 'database' / 'prototype.db'


class PrototypeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, database, clock=time.time):
        self.database = Path(database).resolve()
        self.clock = clock
        self.form_token = secrets.token_urlsafe(32)
        super().__init__(address, PrototypeHandler)


class PrototypeHandler(BaseHTTPRequestHandler):
    @property
    def form_token(self):return self.server.form_token

    def reply(self, status, body=b'', content_type='text/html; charset=utf-8', location=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        if location:
            self.send_header('Location', location)
        self.end_headers()
        self.wfile.write(body)

    def valid_origin(self):
        port = self.server.server_address[1]
        return self.headers.get("Origin") in (None, f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def local_request(self):
        port = self.server.server_address[1]
        if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            self.reply(403, b'Use the localhost address printed by the app.', 'text/plain; charset=utf-8')
            return False
        return True

    def do_GET(self):
        if not self.local_request():
            return
        path = urlsplit(self.path).path
        if path == '/static/style.css':
            self.reply(200, (ROOT / 'static' / 'style.css').read_bytes(), 'text/css; charset=utf-8')
        elif path == '/static/resources.css':
            self.reply(200, (ROOT / 'static' / 'resources.css').read_bytes(), 'text/css; charset=utf-8')
        elif path == '/static/resources.js':
            self.reply(200, (ROOT / 'static' / 'resources.js').read_bytes(), 'text/javascript; charset=utf-8')
        elif path == '/static/buildings.css':
            self.reply(200, (ROOT / 'static' / 'buildings.css').read_bytes(), 'text/css; charset=utf-8')
        elif path == '/static/buildings.js':
            self.reply(200, (ROOT / 'static' / 'buildings.js').read_bytes(), 'text/javascript; charset=utf-8')
        elif path == '/favicon.ico':
            self.reply(204)
        elif path in ('/', '/api/resources'):
            try:
                state = advance_settlement(self.server.database, now=int(self.server.clock()))
                if path == '/api/resources':
                    if state is None:
                        self.reply(404, b'{}', 'application/json')
                    else:
                        payload = {'status': state['season']['status'],
                                   'food': state['resources']['food'], 'water': state['resources']['water'],
                                   'rates': resource_rates(state)}
                        payload.update(live_payload(state))
                        payload['materials']={r:state['resources'][r] for r in ('scrap','metal','electronics')}
                        self.reply(200, json.dumps(payload).encode('utf-8'), 'application/json')
                else:
                    self.reply(200, render_page(state, self.form_token))
            except (ValueError, sqlite3.Error):
                self.reply(500, b'Unable to read this save. No data was reset. Check the selected database.', 'text/plain; charset=utf-8')
        else:
            self.reply(404, b'Not found.', 'text/plain; charset=utf-8')

    def do_POST(self):
        if not self.local_request():
            return
        if self.path not in ('/settlement', '/clock', '/administrator', '/buildings', '/scavenging','/needs','/manufacturing'):
            self.reply(404, b'Not found.', 'text/plain; charset=utf-8')
            return
        port = self.server.server_address[1]
        if not self.valid_origin():
            self.reply(403, b'Request origin rejected.', 'text/plain; charset=utf-8')
            return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/x-www-form-urlencoded':
            self.reply(415, b'Expected a form submission.', 'text/plain; charset=utf-8')
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                self.reply(413, b'Invalid form size.', 'text/plain; charset=utf-8')
                return
            form = parse_qs(self.rfile.read(length).decode('utf-8'), max_num_fields=8, keep_blank_values=True)
            if any(len(values)!=1 for values in form.values()):
                raise ValueError('Duplicate form fields.')
        except (ValueError, UnicodeError):
            self.reply(400, b'Invalid form.', 'text/plain; charset=utf-8')
            return
        if not secrets.compare_digest(form.get('token', [''])[0].encode('utf-8'),
                                      self.form_token.encode('ascii')):
            self.reply(403, b'Reload the page before changing your settlement.', 'text/plain; charset=utf-8')
            return
        name = form.get('name', [''])[0]
        try:
            now = int(self.server.clock())
            if self.path == '/settlement':
                create_settlement(self.server.database, name, now=now)
            elif self.path == '/needs':
                from game.needs import command
                command(self.server.database,form.get('action',[''])[0],now,food=form.get('food',['full'])[0],water=form.get('water',['full'])[0])
            elif self.path == '/manufacturing':
                from game.manufacturing import command
                args={key:int(form[key][0]) for key in ('building_id','quantity','job_id') if key in form}
                command(self.server.database,form.get('action',[''])[0],now,unit_type=form.get('unit_type',[''])[0],repeat=form.get('repeat',['0'])[0]=='1',**args)
            elif self.path == '/clock':
                action = form.get('action', [''])[0]
                if action not in ('resume', 'pause'):
                    raise ValueError('Choose Start time or Pause time.')
                apply_action(self.server.database, action, now=now)
            elif self.path == '/scavenging':
                try:
                    derelict_id=int(form.get('derelict_id',[''])[0]);citizen_id=int(form.get('citizen_id',[''])[0])
                except ValueError:
                    raise ValueError('Choose a derelict and citizen from the lists.') from None
                assign_scavenger(self.server.database,form.get('action',[''])[0],derelict_id,citizen_id,now=now,exposed=form.get('exposed',[''])[0]=='1')
            elif self.path == '/buildings':
                args = {}
                for key in ('building_id', 'citizen_id', 'x', 'y', 'rotation', 'expected_level', 'unit_id'):
                    if key in form:
                        try:
                            args[key] = int(form[key][0])
                        except ValueError:
                            raise ValueError('Use whole numbers for coordinates and choose entries from the lists.') from None
                if 'building_type' in form:
                    args['building_type'] = form['building_type'][0]
                args['exposed']=form.get('exposed',[''])[0]=='1'
                change_building(self.server.database, form.get('action', [''])[0], now=now, **args)
            else:
                try:
                    citizen_id = int(form.get('citizen_id', [''])[0])
                except ValueError:
                    raise ValueError('Choose a citizen from the list.') from None
                apply_action(self.server.database, 'assign', citizen_id=citizen_id, now=now)
        except ValueError as error:
            self.reply(400, render_page(read_settlement(self.server.database), self.form_token, str(error), name))
            return
        except sqlite3.Error:
            self.reply(500, b'Could not save the settlement. The transaction was rolled back.', 'text/plain; charset=utf-8')
            return
        self.reply(303, location='/')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=DEFAULT_SAVE)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error('Port must be between 0 and 65535.')
    try:
        prepare_database(args.database)
        with PrototypeServer(('127.0.0.1', args.port), args.database) as server:
            print(f'Open http://127.0.0.1:{server.server_address[1]}', flush=True)
            print(f'Save: {server.database}\nPress Ctrl+C to stop. Your settlement stays saved.', flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped. Saved progress retained.')
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f'Could not start prototype: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
