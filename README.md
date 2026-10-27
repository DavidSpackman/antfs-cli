ANT-FS Command Line Interface
=============================

[![Build Status](https://github.com/Tigge/antfs-cli/workflows/Build/badge.svg?branch=master)](https://github.com/Tigge/antfs-cli/actions)
[![Coveralls branch](https://img.shields.io/coveralls/Tigge/antfs-cli/master.svg)](https://coveralls.io/r/Tigge/antfs-cli?branch=master)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

This program (`antfs-cli`) extracts all activity FIT files from a device and
writes them to a folder (see file locations below). The first time it runs it
attempts to sync with the watch. This produces an `authfile` which is written
to the same folder. On startup this program will try to read that file to
avoid having to re-sync.

Requirements
------------

- Python 3.10 or newer
- [openant >= 1.3](https://github.com/Tigge/openant) (installed automatically)

Installation
------------

From a checkout of this repository, run `pipx install .` (or
`pip install --user .`) to install ANT-FS Command Line Interface. This will
install an `antfs-cli` command on your `PATH`.


Linux only needs one extra step so the ANT USB stick can be used without
root: install openant's udev rule
([42-ant-usb-sticks.rules](https://github.com/Tigge/openant/blob/master/resources/42-ant-usb-sticks.rules))
into `/etc/udev/rules.d/`, then run `sudo udevadm control --reload-rules`
and re-plug the stick.

The rule gives access to the `plugdev` group (and to whoever is logged in at
the desktop). Some distributions, such as Fedora, have no `plugdev` group, and
udev then ignores the whole rule. Create it and add yourself, then log out and
back in:

    sudo groupadd -r plugdev
    sudo usermod -aG plugdev $USER

Usage
-----

    usage: antfs-cli [-h] [--upload] [--debug] [--pair] [-a]

    options:
      -h, --help           show this help message and exit
      --upload             enable uploading
      --debug              enable debug
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
every time), and `--debug` to see the full log on the terminal. A log of every
run is always written to the `logs` folder (see file locations below).

Uploading activities to websites
--------------------------------

Uploading is done by hook scripts that `antfs-cli` runs after every download
(see [SCRIPTING.md](SCRIPTING.md)). The scripts in `scripts/` only upload
activities, and treat an activity that is already on the website as a success.

The scripts run with `python3` from your `PATH`, so install their dependencies
for that Python (`pip install --user ...`), not inside a pipx environment.

### Garmin Connect

Uses [python-garminconnect](https://github.com/cyberjunky/python-garminconnect),
which needs Python 3.12 or newer. Garmin has no official API for this, so it
may break if Garmin changes its login again; upgrading `garminconnect` usually
fixes that.

 1. Install the dependency
    ```
    pip install --user garminconnect
    ```
 2. Log in once (asks for your email, password and, if enabled, MFA code)
    ```
    ./scripts/40-upload_to_garmin_connect.py
    ```
    Only login tokens are stored (in `~/.config/antfs-cli/garmin-tokens/`),
    not your password. Run it again if it ever says the login has expired.
 3. Copy `scripts/40-upload_to_garmin_connect.py` into
    `~/.config/antfs-cli/scripts/` and make sure it is still executable.

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
    pip install --user stravalib
    ```
 2. Create your own API application at
    <https://www.strava.com/settings/api> and set its "Authorization Callback
    Domain" to `localhost`.
 3. Log in once: enter the app's Client ID and Client Secret, then open the
    link it prints and approve access
    ```
    ./scripts/40-upload_to_strava.py
    ```
    The app details and tokens are stored in `~/.config/antfs-cli/strava.json`.
 4. Copy `scripts/40-upload_to_strava.py` into
    `~/.config/antfs-cli/scripts/` and make sure it is still executable.

File locations
--------------

### Simple answer (probably correct for most people)

Your files are placed in `~/.config/antfs-cli/`

### Long answer

FIT files and authfiles are stored in an the location specified by the XDG
Base Directory specification. It uses the `$XDG_CONFIG_HOME` with
`$HOME/.config` as backup. In this directory a `antfs-cli` folder is created
in which a folder for each device is created. Both the `.FIT` files and
`authfile` are stored in this device-specific folder. All logs are stored
in a `logs` subfolder of the `antfs-cli` directory.

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

Any compliant ANT-FS device should in theory work, but those specific devices
have been reported as working:

 - Garmin Forerunner 60
 - Garmin Forerunner 405CX
 - Garmin Forerunner 310XT
 - Garmin Forerunner 610
 - Garmin Forerunner 910XT
 - Garmin FR70
 - Garmin Swim

Please let me know if you have any success with devices that are not listed here.
