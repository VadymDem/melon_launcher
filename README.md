# Melon Launcher

A lightweight, open-source Minecraft: Java Edition launcher for Windows, built with Python and PyQt6.

Melon Launcher lets players sign in with their own Microsoft/Xbox account and launch the copy of
Minecraft: Java Edition they already own. It does not distribute or provide access to any game
content — all game files come from Mojang's official servers via
[`minecraft-launcher-lib`](https://github.com/JakobDev/minecraft-launcher-lib).

## Features

- Microsoft account sign-in (OAuth 2.0 Authorization Code flow with PKCE, via a local callback server — no copy/paste of URLs)
- Offline mode for launching without an account
- Modrinth and CurseForge project search
- Version manifests with SHA-1 file verification and a resumable downloader
- Automatic Java Runtime detection and download (Temurin 8/11/17/21) with G1GC tuning
- RAM allocation from a slider bounded by physical memory
- In-app game log console with colour-coded output
- Crash detection with automatic crash-log reporting
- Encrypted session storage (tokens encrypted at rest with Fernet)

## Requirements

- Python 3.11 or newer
- Windows (the launcher is developed and tested on Windows; the code is platform-agnostic where possible)

## Installation

```bash
git clone https://github.com/VadymDem/melon_launcher.git
cd melon_launcher
pip install -r requirements.txt
```

## Running

```bash
python src/main.py
```

Game data, logs and the encrypted session file are stored in `~/.melon_launcher` by default
(configurable in Settings).

## Microsoft sign-in

Sign-in uses a standard OAuth 2.0 Authorization Code flow with PKCE:

1. The launcher opens the Microsoft login page in your browser.
2. You sign in and approve the request.
3. The browser is redirected back to a short-lived local HTTP server (`http://localhost:8080/callback`),
   which completes the token exchange and returns you to the launcher. No manual URL copying is needed.

> **Note:** Minecraft Services only accepts *allowlisted* Azure application IDs. If sign-in fails with
> `Invalid app registration`, your `client_id` has not been approved yet — see
> [aka.ms/mce-reviewappid](https://aka.ms/mce-reviewappid) to submit it for review.
> The active client ID is configured via the `microsoft_client_id` setting in `config.json`.

If you do not own Minecraft: Java Edition, use **Offline mode** — it works without any Microsoft account.

## Project structure

```
src/
  main.py             Entry point
  core/               Business logic
    auth.py           Microsoft OAuth + offline auth, encrypted session
    manifest.py       Manifest schema, parsing and validation
    manifest_manager.py
    file_checker.py   SHA-1 verification of installed files
    download_worker.py
    java_manager.py   Java detection / Temurin download
    jvm_config.py     JVM argument builder (RAM, G1GC)
    launch_manager.py Command building, game process, crash handling
    modrinth_api.py   Modrinth + CurseForge clients
    builtin_manifests.py  Vanilla / Fabric / Forge profiles
    icon_manager.py
  ui/                 PyQt6 widgets (main window, settings, profile, build info)
  utils/              Config and token encryption
  assets/             Stylesheet and icons
```

## Tests

The project ships with acceptance tests, one file per development stage:

```bash
python test_stage1.py   # application launch, RAM slider limits, UI responsiveness
python test_stage2.py   # manifest schema, SHA-1 checks, download worker signals
python test_stage3.py   # offline auth, session persistence, Microsoft profile structure
python test_stage4.py   # JVM arguments, Java detection, Modrinth API
python test_stage5.py   # launch command, process handling, crash detection
```

## License

Open source. See the repository for details.