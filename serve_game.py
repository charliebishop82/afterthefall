"""Run the Flask playtest with Waitress, optionally behind a local ngrok agent."""
import argparse
from pathlib import Path
import sqlite3

from flask_app import create_app, public_origin, ROOT


def server_options(host, port, public_url=None):
    if not 1 <= port <= 65535:
        raise ValueError('Port must be between 1 and 65535.')
    options={'host':host,'port':port,'threads':4,'max_request_body_size':16384,
             'clear_untrusted_proxy_headers':True,'expose_tracebacks':False}
    if public_url:
        public_origin(public_url)
        if host!='127.0.0.1':
            raise ValueError('Public tunnel mode must bind to 127.0.0.1 so clients cannot bypass the local proxy.')
        options.update(trusted_proxy='127.0.0.1',trusted_proxy_count=1,
                       trusted_proxy_headers={'x-forwarded-proto'})
    return options


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=ROOT/'database/playtest.db')
    parser.add_argument('--log-file',type=Path,default=ROOT/'logs/player-actions.jsonl',help='Rotating timestamped player request log')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8767)
    parser.add_argument('--allow-host',action='append',default=[])
    parser.add_argument('--public-url',default=None)
    args=parser.parse_args(argv)
    try:
        if args.host not in ('127.0.0.1','localhost') and not args.allow_host:
            raise ValueError('LAN hosting requires --allow-host with your LAN address.')
        options=server_options(args.host,args.port,args.public_url)
        app=create_app(args.database,port=args.port,allowed_hosts=args.allow_host,public_url=args.public_url,log_path=args.log_file)
        from waitress import serve
        print(f'Playtest: http://127.0.0.1:{args.port}\nSave: {app.game_database}',flush=True)
        print(f'Player request log: {args.log_file.resolve()}',flush=True)
        if args.public_url:print(f'Configured public origin: {public_origin(args.public_url)} (start ngrok separately)',flush=True)
        print('Waiting for the administrator-controlled shared start. Ctrl+C stops the server.',flush=True)
        serve(app,**options)
    except KeyboardInterrupt:
        pass
    except (ValueError,OSError,sqlite3.Error) as error:
        print(f'Could not start playtest: {error}')
        return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
