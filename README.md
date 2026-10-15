# Melon Launcher

A personal Minecraft: Java Edition launcher for Windows, written in Python with PyQt6.

Melon Launcher is a hobby project made for my own use — it is not meant to be a public launcher
someone picks up instead of the official one. It signs in with a Microsoft/Xbox account and launches
the copy of Minecraft: Java Edition that the user already owns. No game content is hosted, bundled or
redistributed: every game file is downloaded from Mojang's official servers through
[`minecraft-launcher-lib`](https://github.com/JakobDev/minecraft-launcher-lib).

## What it does

- Microsoft account sign-in (OAuth 2.0 Authorization Code flow with PKCE) and an offline mode
- Modpack catalog: Modrinth search and a CurseForge home page with featured packs and sections
- Version manifests with SHA-1 verification and a resumable downloader
- Automatic Java Runtime detection/download (Temurin 8/11/17/21) with G1GC tuning
- Per-instance game folders, RAM slider, in-game log console, crash detection
- Encrypted session storage (tokens encrypted at rest)

## Requirements

- Windows
- Python 3.11 or newer (developed against 3.14)
- `pip install -r requirements.txt`

## Running

```bash
python src/main.py
```

Game files, logs and the encrypted session are stored in `~/.melon_launcher` by default (change it
in Settings).

## Microsoft sign-in

Sign-in uses OAuth 2.0 with PKCE and a short-lived local callback server
(`http://localhost:8080/callback`), so no URLs have to be copied by hand.

Minecraft Services only accepts *allowlisted* Azure application IDs. If sign-in fails with
`Invalid app registration`, the configured `microsoft_client_id` has not been approved yet — see
[aka.ms/mce-reviewappid](https://aka.ms/mce-reviewappid). Without an account, **Offline mode** works.

## Tests

Acceptance tests, one file per development stage:

```bash
python test_stage1.py   # application launch, RAM slider limits, UI responsiveness
python test_stage2.py   # manifest schema, SHA-1 checks, download worker signals
python test_stage3.py   # offline auth, session persistence, Microsoft profile structure
python test_stage4.py   # JVM arguments, Java detection, Modrinth API
python test_stage5.py   # launch command, process handling, crash detection
python test_stage6.py   # modpack catalog, filters, CurseForge mapping, covers
```

## Scope

This is a work-in-progress personal project. It is not intended as a general-purpose or public
launcher, and comes with no support or compatibility guarantees. No license is granted for
redistribution or reuse.
