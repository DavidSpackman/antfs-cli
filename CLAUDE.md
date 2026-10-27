# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`antfs-cli` downloads FIT files (activities, courses, settings, etc.) from ANT-FS sport watches over an ANT USB stick, and can optionally upload local FIT files back to the device. It is a thin application layer on top of [openant](https://github.com/Tigge/openant) (imported as `ant`), which does all the USB/ANT/ANT-FS protocol work.

## Commands

```sh
pip install -r requirements.txt          # installs openant from git
pip install -e .                         # installs the `antfs-cli` entry point

python3 -m unittest discover tests        # run all tests
python3 -m unittest tests.test_utilities.BasicUtilityTest.test_config_dir   # single test

black .                                  # format (CI runs psf/black and fails on diffs)
```

CI (`.github/workflows/build.yml`) runs `black` as a lint check, then tests via `setup.py test` on Python 3.6–3.9, then `setup.py install` and `antfs-cli --help` as a smoke test. Black is configured in `pyproject.toml` (line length 88, target py37).

Running the program for real requires an ANT USB stick and a watch in range; there are no hardware mocks, so the tests only cover `utilities.py`.

## Architecture

- `antfs_cli/program.py` — everything of substance.
  - `AntFSCLI` subclasses openant's `ant.fs.manager.Application` and implements its callback-driven state machine: `setup_channel` → `on_link` → `on_authentication` → `on_transport`. `main()` builds it and calls `start()`/`stop()`.
  - `on_authentication` reuses a stored passkey (`authfile`) or pairs and writes a new one (`--pair` forces pairing).
  - `on_transport` sets the watch time, diffs the device directory against local files by filename, downloads files that are missing locally *or not yet archived on the watch*, and (with `--upload`) uploads local-only files, then renames them to match the index the device assigned.
  - `_directories` maps local subfolder names to `File.Identifier` FIT sub-types; it drives both which folders are created and which remote files are considered. Adding support for a new FIT type means adding an entry here.
  - Local filenames are `YYYY-MM-DD_HH-MM-SS_<subtype>_<filenumber>.fit` (`get_filename`); the local/remote diff depends on this format staying stable.
  - `Device` owns the per-device folder `<config_dir>/<serial>/` and a `profile_version` file. A mismatch with `Device._PROFILE_VERSION` raises `ProfileVersionException`; bump it only if the on-disk layout changes incompatibly.
- `antfs_cli/scripting.py` — `Runner` executes every file in `<config_dir>/scripts/` (sorted, so the `40-` prefixes set ordering) in a background thread after each download, with args `ACTION FILENAME FIT_TYPE`. Contract is documented in `SCRIPTING.md`. Only `run_download` is currently called.
- `antfs_cli/utilities.py` — XDG config/data dir resolution and `makedirs_if_not_exists`.
- `scripts/` — example user hook scripts (TCX conversion, Garmin Connect / Strava upload). They are not part of the package; users copy them into the scripts dir.

Data and logs live under `$XDG_CONFIG_HOME/antfs-cli/` (default `~/.config/antfs-cli/`); each run writes a timestamped debug log to its `logs/` subfolder, and `--debug` also echoes logging to stderr.
