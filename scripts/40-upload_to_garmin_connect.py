#!/usr/bin/env python3
#
# Code by Tony Bussieres <t.bussieres@gmail.com>
# Updated by Bastien Abadie <bastien@nextcairn.com>
# inspired by 40-convert_to_tcx.py by Gustav Tiger <gustav@tiger.name>
#
# This helper uses python-garminconnect to send newly downloaded activities
# to Garmin Connect.
#
# Setup (once):
#
#   pip install --user garminconnect     # needs Python 3.12 or newer
#   ./40-upload_to_garmin_connect.py     # log in, answer the MFA prompt
#
# Logging in stores tokens (not your password) in
# ~/.config/antfs-cli/garmin-tokens/. They refresh themselves; run the script
# by hand again if Garmin ever asks you to log in again.
#
# Then copy this script to ~/.config/antfs-cli/scripts/ and make sure it is
# executable (chmod +x).

import fcntl
import getpass
import os
import sys

try:
    from garminconnect import (
        Garmin,
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
    )
except ImportError:
    print(
        "Python package garminconnect is not available. "
        "Please install with: pip install --user garminconnect"
    )
    sys.exit(1)

FIT_TYPE_ACTIVITY = "4"


def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "antfs-cli")


TOKENSTORE = os.path.join(config_dir(), "garmin-tokens")


def upload(action, filename, fit_type):
    if action != "DOWNLOAD" or fit_type != FIT_TYPE_ACTIVITY:
        return 0

    if not os.path.isdir(TOKENSTORE):
        print("No Garmin Connect login found. Run this script by hand once:")
        print(" ", os.path.abspath(__file__))
        return 1

    # antfs-cli runs this script once per downloaded file, in parallel.
    # Serialise so concurrent runs don't race each other refreshing tokens.
    with open(os.path.join(TOKENSTORE, ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)

        garmin = Garmin()
        try:
            garmin.login(TOKENSTORE)
        except GarminConnectAuthenticationError as e:
            print("Garmin Connect login expired or invalid:", e)
            print("Run this script by hand to log in again:")
            print(" ", os.path.abspath(__file__))
            return 1
        # Keep any refreshed tokens for the next run.
        garmin.client.dump(TOKENSTORE)

        name = os.path.basename(filename)
        try:
            garmin.upload_activity(filename)
        except GarminConnectConnectionError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 409:
                print(f"Garmin Connect: {name} already uploaded")
                return 0
            print(f"Garmin Connect: uploading {name} FAILED: {e}")
            return 1

    print(f"Garmin Connect: uploaded {name}")
    return 0


def login():
    email = input("Garmin Connect email: ")
    password = getpass.getpass("Garmin Connect password: ")
    garmin = Garmin(
        email, password, prompt_mfa=lambda: input("Garmin Connect MFA code: ")
    )
    garmin.login()
    garmin.client.dump(TOKENSTORE)
    print("Logged in. Tokens saved to", TOKENSTORE)
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.exit(login())
    sys.exit(upload(sys.argv[1], sys.argv[2], sys.argv[3]))
