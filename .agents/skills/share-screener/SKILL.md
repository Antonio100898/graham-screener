---
name: share-screener
description: Securely expose the Graham Screener running on this Windows PC through ngrok. Use when the user asks to share, start, restart, stop, or check the remote screener, mentions ngrok, or wants to connect to the local app from anywhere.
---

# Share Screener

Operate the repository's secure ngrok workflow through `share.ps1` at the
repository root. Port 8000 is the packaged application: FastAPI serves both the
API and the built React UI. Do not expose Vite's development port 5173.

## Preserve access boundaries

- Treat a request to start, share, restart, or stop the tunnel as authorization
  for that operation. A status question authorizes read-only checks only.
- Never start a plain `ngrok http 8000` endpoint. Read endpoints include local
  portfolio information, so the entire ngrok boundary must require
  authentication.
- Never put an ngrok authtoken, access password, or API token in a tracked file.
  Do not ask the user to paste an ngrok authtoken into chat.
- `share.ps1` generates a new access password for each launch, uses it for both
  ngrok Basic Auth and `SCREENER_TOKEN`, and removes its temporary traffic-policy
  file after ngrok starts. Do not replace that with a fixed credential.

## Start or share

1. Work from the repository root and inspect `share.ps1` before changing it.
2. Run `ngrok config check`. If the agent is not linked, ask the user to run
   `ngrok config add-authtoken "YOUR_PRIVATE_AUTHTOKEN"` directly on the PC and
   wait for confirmation.
3. Check for an existing ngrok process and query
   `http://127.0.0.1:4040/api/tunnels`. If a healthy protected endpoint already
   exists and the user did not request a restart, report it rather than replacing
   it. A generated password cannot be recovered later; restart only when the
   user requests it or says the credential was lost.
4. For an agent-run background launch, execute:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\share.ps1 -Detached
   ```

   For a user-controlled foreground launch, omit `-Detached`; Ctrl-C then stops
   ngrok. The script validates the venv and built UI, restarts only the expected
   project Uvicorn process with write protection, and launches ngrok hidden when
   detached.

## Verify a new endpoint

Use the URL and generated credential printed by the launch:

- Request `/health` without authorization and with the
  `ngrok-skip-browser-warning: 1` header. It must return HTTP 401.
- Request `/health` with Basic Auth. It must return HTTP 200.
- Request `/config` with Basic Auth and confirm `write_protected` is `true`.
- Request `/` with Basic Auth and confirm HTTP 200 with HTML content.
- Do not download `dashboard.json` merely as a smoke test; it is large.

If any security check fails, stop the newly launched ngrok process and report
the failure instead of handing out the URL.

## Handoff

Give the user the HTTPS URL, username `screener`, and generated password. Explain
that the same password is the in-app write-access token and that the computer,
API, and ngrok process must remain running and awake. Do not store the current
credential in this skill.

## Stop or restart

Resolve the exact ngrok PID and confirm it belongs to the ngrok executable before
using `Stop-Process`. Stop the protected Uvicorn process only when the user also
asks to stop the local app. For a restart, stop the verified ngrok process and
then use `share.ps1`; report the newly generated password because the previous
one no longer applies.
