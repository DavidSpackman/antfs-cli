# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`antfs-cli` downloads FIT files (activities, courses, settings, etc.) from ANT-FS sport watches over an ANT USB stick, and can optionally upload local FIT files back to the device. It is a thin application layer on top of [openant](https://github.com/Tigge/openant) (imported as `openant`; versions before 1.0 used `ant`), which does all the USB/ANT/ANT-FS protocol work.

## Commands

```sh
python3 -m pip install -e .              # installs openant and the `antfs-cli` entry point

python3 -m unittest discover tests        # run all tests
python3 -m unittest tests.test_utilities.BasicUtilityTest.test_config_dir   # single test

black .                                  # format (CI runs psf/black and fails on diffs)
```

All packaging metadata lives in `pyproject.toml` (there is no `setup.py`); Python 3.10+ is required. CI (`.github/workflows/build.yml`) runs `black` as a lint check, then on Python 3.10–3.14 installs the package, runs `antfs-cli --help` as a smoke test, runs the tests under coverage (uploaded to Coveralls) and builds the sdist/wheel. Black is configured in `pyproject.toml` (line length 88, target py310).

Running the program for real requires an ANT USB stick and a watch in range; there is no hardware mock. Tests cover the parts that don't touch the radio: `plan_sync`/`get_filename` (using a `FakeFile` stand-in for openant's `File`), `Device` folder and passkey handling, `is_valid_fit`, the session handling in `AntFSCLI._main` (fake beacons), the `openant_fixes` timing rules (fake event queues and beacon states), and the script `Runner`. Keep new sync logic in pure functions like `plan_sync` so it stays testable.

## Architecture

- `antfs_cli/program.py` — everything of substance.
  - `AntFSCLI` subclasses openant's `openant.fs.manager.Application` and implements its callback-driven state machine: `setup_channel` → `on_link` → `on_authentication` → `on_transport`. `main()` builds it and calls `start()`/`stop()`.
  - `on_authentication` reuses a stored passkey (`authfile`) or pairs and writes a new one (`--pair` forces pairing).
  - `on_transport` sets the watch time, uses the module-level `plan_sync` to diff the device directory against local files by filename, downloads files that are missing locally *or not yet archived on the watch*, and (with `--upload`) uploads local-only files, then renames them to match the index the device assigned.
  - `_directories` maps local subfolder names to `File.Identifier` FIT sub-types; it drives both which folders are created and which remote files are considered. Adding support for a new FIT type means adding an entry here.
  - Local filenames are `YYYY-MM-DD_HH-MM-SS_<subtype>_<filenumber>.fit` (`get_filename`); the local/remote diff depends on this format staying stable.
  - `Device` owns the per-device folder `<config_dir>/<serial>/` and a `profile_version` file. A mismatch with `Device._PROFILE_VERSION` raises `ProfileVersionException`; bump it only if the on-disk layout changes incompatibly.
- `antfs_cli/openant_fixes.py` — workarounds for openant 1.x bugs that made syncing a real watch (Forerunner 310XT) fail: failed sends never retried, lost or ignored replies waited out a 15 s timeout while the watch drops an idle link after ~8 s, and stale replies were saved as the next file. `AntFSCLI` routes `_get_command`/`_send_command` through it and `main()` calls `apply()`. `AntFSCLI._main` replaces openant's loop so a session left open by a crashed run is ended (the host serial is always 1337, so the watch recognises us) and the watch is disconnected on errors; `is_valid_fit` rejects corrupt downloads so the next sync retries them. Tune timings only against real hardware logs (`--debug`). `OPENANT_WORKAROUNDS.md` lists each openant bug, its upstream location and fix, and what to delete once openant is fixed; keep it in step with these workarounds.
- `antfs_cli/scripting.py` — `Runner` executes every file in `<config_dir>/scripts/` (sorted, so the `40-` prefixes set ordering) in a background thread after each download, with args `ACTION FILENAME FIT_TYPE`. Contract is documented in `SCRIPTING.md`. Only `run_download` is currently called.
- `antfs_cli/utilities.py` — XDG config/data dir resolution.
- `scripts/` — user hook scripts (TCX conversion, Garmin Connect / Strava upload). They are not part of the package; users copy them into the scripts dir, and they run under whatever `python3` is on `PATH`, not antfs-cli's environment. All only act on `DOWNLOAD` of FIT type `4` (activity). The two upload scripts are standalone: run with no arguments for an interactive one-off login that stores tokens under the config dir (never the password), or by `Runner` to upload; they `flock` their token store because `Runner` starts them concurrently. CI doesn't install or test them.
  - Garmin Connect upload is the main reason this fork is maintained. It uses `garminconnect` (python-garminconnect); `garmin-uploader` and `garth` are dead or deprecated after Garmin auth changes, so don't switch back to them. Use `upload_activity` (treated as a device sync, so Garmin forwards to Strava), not `import_activity`.
  - `--upload` on the CLI means uploading local FIT files *to the watch*; it is unrelated to these scripts.

Data and logs live under `$XDG_CONFIG_HOME/antfs-cli/` (default `~/.config/antfs-cli/`), and README's "File locations" section lists what goes where; each run writes a timestamped debug log to its `logs/` subfolder, and `--debug` also echoes logging to stderr.
