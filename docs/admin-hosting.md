> For the current Flask playtest, use [the Flask guide](flask-playtest.md).
> This page describes the legacy account server. When following its management
> examples, pass `--database database/accounts.db` before the subcommand.

# Administration and local-network play

The legacy account server uses Python's standard-library HTTP server and SQLite.
The current shared playtest has already migrated to Flask/Waitress; public Internet
deployment remains a separate increment. Seasons are unchanged.

## Give yourself administrator access

Create an ordinary account at http://127.0.0.1:8767, then run this from the project folder:

```powershell
& 'C:/Users/charl/miniconda3/python.exe' manage.py grant-admin YOUR_USERNAME
```

For the current Flask playtest, launch `./start_admin.ps1` and log in at
http://127.0.0.1:8768/. The old account-server instructions below are retained for
legacy saves.
This command is local-only; registration cannot request or grant admin privileges.
No default admin password or automatically promoted first account exists.

The dashboard lists accounts and settlements, suspends/reactivates ordinary accounts,
resets player passwords, publishes season announcements, hides/restores board posts,
and shows the latest 100 audited actions. Every admin change requires a reason.
Board moderation includes the latest 100 posts across seasons. Private mail is not
shown. Suspension blocks login, revokes sessions, and removes the account from new
player interactions. Raids involving suspended accounts are recalled immediately.
The settlement is retained and frozen; reactivation excludes suspended time.
See [Admin operations](admin-operations.md) for season pause/resume and correction tools.
Inactive accounts are skipped
by shared leaderboard refresh, so they cannot block other players. Reactivation does
not restore old sessions. Admin accounts cannot be suspended or reset through the dashboard.

For a reset, set a temporary password of at least 12 characters, give it to the player
privately, and ask them to change it through **Account settings**. The reset revokes
all their sessions and clears login throttling. Passwords are hashed and never stored
in the audit log. Changing your own password requires the current password and logs
out every device. Forced first-login password changes and email recovery are not yet implemented.

## Start on this computer

```powershell
.\start_game.ps1 -Python 'C:/Users/charl/miniconda3/python.exe'
```

The default remains http://127.0.0.1:8767. Saves always use `database/accounts.db`
beside the project, regardless of the terminal's current folder.

## Let people on your local network play

Stop the existing account server with Ctrl+C before starting another on the same port.
Run `ipconfig` and find the IPv4 address of your connected Wi-Fi/Ethernet adapter.
For example, if it is `192.168.1.25`:

```powershell
.\start_game.ps1 -Python 'C:/Users/charl/miniconda3/python.exe' -BindAddress '0.0.0.0' -AllowedHosts '192.168.1.25'
```

Players on the same trusted network visit **http://192.168.1.25:8767**, create accounts,
log in, and create settlements. Use your actual address instead of this example.
Keep the server computer awake and the server running. If Windows Firewall asks,
allow Python on **Private networks**. Do not configure router port forwarding.
If Windows blocks other devices, open PowerShell **as Administrator** and run:

```powershell
New-NetFirewallRule -Name 'SettlementGame-LAN-8767' -DisplayName 'Settlement Game - trusted LAN' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8767 -RemoteAddress LocalSubnet -Profile Private -Program 'C:\Users\charl\miniconda3\python.exe'
```

This rule allows only the game Python executable, Private networks and the local
subnet. This app cannot create it without Windows administrator rights. To remove it,
run `Remove-NetFirewallRule -Name 'SettlementGame-LAN-8767'` as Administrator.
Guest Wi-Fi isolation may also prevent connections.

The equivalent direct command is:

```powershell
& 'C:/Users/charl/miniconda3/python.exe' accounts_app.py --host 0.0.0.0 --allow-host 192.168.1.25 --port 8767
```

Add another `--allow-host` for an explicit LAN hostname. Unexpected Host headers and
cross-origin form submissions are rejected, including inherited building/action forms.
This is HTTP for trusted LAN testing. Use a unique game password. Public hosting
needs HTTPS, an appropriate deployment server, and a separate security review;
do not expose this prototype directly to the Internet.

## Back up and restore

An online consistent SQLite backup (safe while the server runs):

```powershell
& 'C:/Users/charl/miniconda3/python.exe' manage.py backup
```

Backups go under `database/backups/` with UTC timestamps. Existing backup filenames
are never overwritten. `--output PATH` chooses a new destination. Keep a copy outside
the computer too. These commands affect the account game, not `prototype.db`.

To restore, first stop **all** servers using the account save, then run:

```powershell
& 'C:/Users/charl/miniconda3/python.exe' manage.py restore 'database/backups/CHOSEN_BACKUP.db' --server-stopped
```

The flag is your explicit confirmation that servers are stopped, not automatic process
detection. The tool verifies SQLite integrity/foreign keys and account tables, makes
a recovery backup of the current save, restores the selected backup, and invalidates
restored sessions. Restart the server; everyone logs in again. Restoring also restores
the old game state, passwords, account status, and administrator grants.

## Validation

`python run_tests.py` includes admin authorization, session revocation, audit secrecy,
password changes, announcements/moderation, LAN Host/origin boundaries, and backup/restore
checks against temporary databases. Browser checks use a disposable demo save.


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
