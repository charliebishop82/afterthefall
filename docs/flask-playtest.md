# Flask playtest and shared start

The current multiplayer entry point is Flask served by Waitress. Game rules,
SQLite persistence and ownership checks remain in the existing game services.
The original `accounts_app.py` and `app.py` remain available for their old saves.
Do not point the fresh playtest at either existing save.

## Local setup

From the project folder in PowerShell, using Python 3.10+ with SQLite 3.37+:

```powershell
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt
& ./.venv/Scripts/python.exe serve_game.py
```

On this computer the project is `C:/Users/charl/OneDrive/Desktop/multiplayer war game`.
The isolated `.venv` is installed there. Open http://127.0.0.1:8767.
Alternatively run `./start_game.ps1` from the project folder.
No Flask debug server is used. Stop Waitress with Ctrl+C before restarting.

The default save is **database/playtest.db**, separate from **database/accounts.db**
and **database/prototype.db**. Existing players create new accounts for this
playtest. Existing saves are preserved, not wiped or imported. An existing save
with players or seasons cannot accidentally be adopted as a fresh playtest.
Restarting the server preserves the lobby or active playtest.

## Register, reserve, then launch together

1. Create the operator account locally; no player settlement is required:

   ```powershell
   & ./.venv/Scripts/python.exe manage.py create-admin admin
   ./start_admin.ps1
   ```

2. Log in at http://127.0.0.1:8768/. For an existing account, use
   `manage.py grant-admin YOUR_USERNAME` instead of creating it again.
   The console contains season pause/resume, player suspension, correction forms,
   password reset, announcements, moderation, diagnostics and audit tools.
   See [Admin operations](admin-operations.md) for frozen-time corrections and limits.
3. Each player registers and reserves a unique settlement name in the lobby.
   They can rename their reservation until launch. No settlement exists and no
   gameplay time passes while waiting.
4. When everyone is ready, the administrator enters a launch reason in the independent operator console
   and presses **Start playtest for all ready players**. All active, enrolled
   players receive their starting settlements in one transaction with the same
   simulation start and protection timestamps. Every previously implemented
   gameplay module, including supply consequences and the Bank, is enabled.
5. The lobby checks for launch every five seconds. Players can also refresh.

Enrollment closes at launch so players in this group begin equally. Suspended
accounts are excluded. A new account created after launch cannot join this run.
The start cannot be repeated; a failed start rolls back the entire group.
The existing season clock still limits the run; complete season endings, awards
and automatic next seasons remain deferred.

Time is processed from elapsed wall-clock time on requests. Keeping the computer
awake and the server running is necessary for friends to connect. Restarting
does not pause an already started run, and idle settlements catch up on access.

## Prepare ngrok for friends

The app is local by default. These steps publish it only when you execute the
ngrok command. Install/sign in to ngrok separately; keep its account token private.
Use the HTTPS domain assigned in your ngrok dashboard, not a made-up example.

1. Copy `ngrok-policy.example.yml` to `ngrok-policy.yml`. Replace the placeholder
   with a long, unique playtest password. Keep that edited file private. This
   browser password gate is separate from each player's game account.
2. Stop the local server. Start it with your exact public origin, for example:

   ```powershell
   & ./.venv/Scripts/python.exe serve_game.py --public-url https://YOUR_DOMAIN.ngrok.app
   ```

3. In another terminal in the same folder, when ready to share:

   ```powershell
   ngrok http http://127.0.0.1:8767 --url https://YOUR_DOMAIN.ngrok.app --traffic-policy-file ngrok-policy.yml --inspect=false
   ```

4. Share the HTTPS URL and tester gate credentials privately with friends.
   Players then register their own game accounts and reserve their settlements.
   Keep yourself in the lobby until the group is ready to start.

The public origin must match the ngrok URL exactly. Keep ngrok's normal Host
header behavior; do not rewrite it to localhost. Waitress trusts only the HTTPS
scheme header from the local proxy and strips other forwarded headers. Tunnel
mode binds only to 127.0.0.1; public sessions use Secure cookies. Using an unknown
Host or a mismatched form Origin is rejected. If your ngrok domain changes,
restart the server with the new origin. Local and public browser sessions are
separate, though they share the same database.

The `--inspect=false` flag disables the agent's local HTTP inspector. Consult
ngrok's account settings separately for cloud traffic capture. The policy and
endpoint must be supported by your ngrok account; a live tunnel has not been
verified as part of local installation. Stop ngrok with Ctrl+C to end access.

Official references: [Flask with Waitress](https://flask.palletsprojects.com/en/stable/deploying/waitress/),
[Waitress proxy settings](https://docs.pylonsproject.org/projects/waitress/en/latest/arguments.html),
[ngrok CLI](https://ngrok.com/docs/gateway/agent/cli),
[ngrok Basic Auth](https://ngrok.com/docs/gateway/traffic-policy/actions/basic-auth).

## Backup and restore

The management commands now default to `database/playtest.db`:

```powershell
& ./.venv/Scripts/python.exe manage.py backup
# Stop every server using this save before restoring:
& ./.venv/Scripts/python.exe manage.py restore database/backups/YOUR_BACKUP.db --server-stopped
```

Restoring creates a recovery backup and invalidates restored login sessions.
To manage the old account save explicitly, put `--database database/accounts.db`
before the subcommand. Do not delete a save to reset a run. For a later fresh
playtest, stop the server and use a new filename:

```powershell
& ./.venv/Scripts/python.exe serve_game.py --database database/playtest-next.db
& ./.venv/Scripts/python.exe manage.py --database database/playtest-next.db grant-admin YOUR_USERNAME
```

## Regression tests

```powershell
& ./.venv/Scripts/python.exe run_tests.py
```

Tests use disposable databases and controlled clocks. The Flask tests cover
atomic launch and rollback, preservation of old saves, enrollment, authorization,
session revocation, ownership, form parsing, gameplay rendering, persisted state,
and actual Waitress proxy behavior. Keep all earlier gameplay tests in the suite.


## Independent operator suite

Run `./start_admin.ps1` separately and open http://127.0.0.1:8768/. The player
application no longer accepts operator actions or starts the shared lobby. Create
an operator with `./.venv/Scripts/python.exe manage.py create-admin admin`, which
prompts privately for a password; an existing account can instead be explicitly
granted the role with `manage.py grant-admin admin`. The console uses the same
save as the player app, with its own login cookie and no settlement requirement.
See [Admin operations](admin-operations.md) for corrections, diagnostics and logs.
Keep the operator console local when publishing the player app. Stop both apps
before restoring a backup.
