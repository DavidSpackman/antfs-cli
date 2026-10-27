ANT-FS Command Line Interface
=============================

[![Build Status](https://github.com/DavidSpackman/antfs-cli/actions/workflows/build.yml/badge.svg?branch=master)](https://github.com/DavidSpackman/antfs-cli/actions/workflows/build.yml)
[![Coverage Status](https://coveralls.io/repos/github/DavidSpackman/antfs-cli/badge.svg?branch=master)](https://coveralls.io/github/DavidSpackman/antfs-cli?branch=master)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

This program (`antfs-cli`) downloads the FIT files (activities, courses,
settings, totals and so on) from an ANT-FS sports watch, such as an older
Garmin Forerunner, using an ANT USB stick, and stores them in a folder (see
file locations below). After each download it can run your own scripts, for
example to upload new activities to Garmin Connect.

The first time it runs it pairs with the watch and saves the result in an
`authfile` next to the downloaded files, so later runs don't need to pair
again.

This is a fork of [Tigge/antfs-cli](https://github.com/Tigge/antfs-cli).

Requirements
------------

- Python 3.10 or newer (3.12 or newer for the Garmin Connect upload script)
- An ANT USB stick (see supported devices below)
- [openant >= 1.3](https://github.com/Tigge/openant) (installed automatically)

Installation
------------

From a checkout of this repository:

    python3 -m pip install --user ".[upload]"

This installs the `antfs-cli` command (in `~/.local/bin`) together with the
dependency of the Garmin Connect upload script, for the same `python3` that the
upload scripts run with. Leave out `[upload]` if you won't upload to Garmin
Connect. If `python3 -m pip` is missing, install pip first (on Fedora:
`sudo dnf install python3-pip`).

`pipx install .` also works for `antfs-cli` itself, but the upload scripts
can't see packages installed inside the pipx environment.

### USB permissions (Linux)

To use the ANT USB stick without root, install openant's udev rule
([42-ant-usb-sticks.rules](https://github.com/Tigge/openant/blob/master/resources/42-ant-usb-sticks.rules)):

    sudo curl -o /etc/udev/rules.d/42-ant-usb-sticks.rules \
        https://raw.githubusercontent.com/Tigge/openant/master/resources/42-ant-usb-sticks.rules
    sudo udevadm control --reload-rules

then re-plug the stick.

The rule gives access to the `plugdev` group, and to whoever is logged in at
the desktop. Some distributions, such as Fedora, have no `plugdev` group, and
udev then ignores the whole rule. Create the group and add yourself, then log
out and back in:

    sudo groupadd -r plugdev
    sudo usermod -aG plugdev $USER

Usage
-----

    usage: antfs-cli [-h] [--upload] [--debug] [--pair] [-a]

    options:
      -h, --help           show this help message and exit
      --upload             also copy FIT files that are only stored locally to the
                           watch
      --debug              also print the debug log to the terminal
      --pair               force pairing even if already paired
      -a, --skip-archived  don't download files marked as 'archived' on the watch

Run `antfs-cli` with the ANT USB stick plugged in and the watch nearby (on
most watches, in its sync/pairing mode). On the first run, confirm the pairing
request on the watch.

On each run, `antfs-cli`:

 - sets the watch's clock,
 - downloads every FIT file it doesn't have yet. Files the watch has not yet
   marked as archived are downloaded again each time, since they may still
   change. Use `--skip-archived` to download only files that have never been
   archived on the watch.
 - with `--upload`, copies FIT files that exist locally but not on the watch
   (for example a course or workout you put in the device's `courses` or
   `workouts` folder) **to the watch**. This has nothing to do with uploading
   to websites; see below for that.

Use `--pair` if the watch has forgotten the pairing (authentication fails
every time). A log of every run is written to the `logs` folder (see file
locations below), whether or not you use `--debug`.

Uploading activities to websites
--------------------------------

Uploading is done by hook scripts that `antfs-cli` runs after every download
(see [SCRIPTING.md](SCRIPTING.md)). The scripts in `scripts/` only upload
activities, and treat an activity that is already on the website as a success.

The scripts run with `python3` from your `PATH`, so install their dependencies
for that Python (`python3 -m pip install --user ...`), not inside a pipx
environment.

### Garmin Connect

Uses [python-garminconnect](https://github.com/cyberjunky/python-garminconnect),
which needs Python 3.12 or newer. Garmin has no official API for this, so it
may break if Garmin changes its login again; upgrading `garminconnect` usually
fixes that.

 1. Install the dependency (already done if you installed with `[upload]`)
    ```
    python3 -m pip install --user garminconnect
    ```
 2. Copy the script into place
    ```
    mkdir -p ~/.config/antfs-cli/scripts
    cp scripts/40-upload_to_garmin_connect.py ~/.config/antfs-cli/scripts/
    ```
 3. Log in once. It asks for your Garmin Connect email, password and, if
    two-step verification is on, the code Garmin sends you
    ```
    ~/.config/antfs-cli/scripts/40-upload_to_garmin_connect.py
    ```
    Only login tokens are stored (in `~/.config/antfs-cli/garmin-tokens/`),
    not your password. They renew themselves; run the script by hand again
    only if it says the login has expired.

Activities uploaded this way are treated like ones synced from the watch, so
if Garmin Connect is linked to Strava (or other services) they are passed on
as usual.

### Strava

You don't need this if Garmin Connect already forwards your activities to
Strava; using both creates duplicates. It uses
[stravalib](https://github.com/stravalib/stravalib), which needs Python 3.11
or newer.

 1. Install the dependency
    ```
    python3 -m pip install --user stravalib
    ```
 2. Create your own API application at
    <https://www.strava.com/settings/api> and set its "Authorization Callback
    Domain" to `localhost`.
 3. Copy the script into place
    ```
    mkdir -p ~/.config/antfs-cli/scripts
    cp scripts/40-upload_to_strava.py ~/.config/antfs-cli/scripts/
    ```
 4. Log in once: enter the app's Client ID and Client Secret, then open the
    link it prints and approve access
    ```
    ~/.config/antfs-cli/scripts/40-upload_to_strava.py
    ```
    The app details and tokens are stored in `~/.config/antfs-cli/strava.json`.

File locations
--------------

Everything is stored in `~/.config/antfs-cli/` (more precisely
`$XDG_CONFIG_HOME/antfs-cli/`, with `~/.config` used when `$XDG_CONFIG_HOME`
is not set):

| Path                   | Contents                                                       |
|------------------------|----------------------------------------------------------------|
| `<serial>/`            | One folder per watch, named after its serial number            |
| `<serial>/authfile`    | Pairing key for that watch                                     |
| `<serial>/activities/` | Downloaded activities; `courses/`, `settings/`, `totals/` and so on hold the other FIT file types |
| `scripts/`             | Hook scripts run after each download (see [SCRIPTING.md](SCRIPTING.md)) |
| `logs/`                | A log of every run                                             |
| `garmin-tokens/`       | Garmin Connect login tokens (upload script)                    |
| `strava.json`          | Strava app details and tokens (upload script)                  |

The token files give access to your accounts, so they are only readable by
you. Deleting them logs the upload scripts out.

Supported devices
-----------------

Any device supported by [openant](https://github.com/Tigge/openant) should work.

ANT-FS was mainly used by Garmin watches from around 2008 to 2013. Most newer
watches sync over USB, Wi-Fi or Bluetooth instead and won't be found by
`antfs-cli`; for those, copy the FIT files off the watch over USB.

### ANT USB Sticks

 - [ANTUSB2 Stick](http://www.thisisant.com/developer/components/antusb2/)
 (0fcf:1008: Dynastream Innovations, Inc.)
 - [ANTUSB-m Stick](http://www.thisisant.com/developer/components/antusb-m/)
 (0fcf:1009: Dynastream Innovations, Inc.)

### ANT-FS Devices

Any compliant ANT-FS device should in theory work, but these specific devices
have been reported as working:

 - Garmin Forerunner 60
 - Garmin Forerunner 405CX
 - Garmin Forerunner 310XT
 - Garmin Forerunner 610
 - Garmin Forerunner 910XT
 - Garmin FR70
 - Garmin Swim

Please open an issue if you have success with a device that is not listed here.
