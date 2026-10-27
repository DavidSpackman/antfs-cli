#!/usr/bin/env python3
#
# Code by Matheus Cansian <dev@drpexe.com>
#
# This helper uses stravalib to send newly downloaded activities to Strava.
#
# You don't need this if Garmin Connect already syncs your activities to
# Strava; using both will create duplicates.
#
# Setup (once):
#
#   1. pip install --user stravalib       # needs Python 3.11 or newer
#   2. Create your own API application at https://www.strava.com/settings/api
#      and set its "Authorization Callback Domain" to: localhost
#   3. ./40-upload_to_strava.py           # enter the app's Client ID and
#                                         # Client Secret, then approve access
#                                         # in the browser
#
# Credentials and tokens are stored in ~/.config/antfs-cli/strava.json.
#
# Then copy this script to ~/.config/antfs-cli/scripts/ and make sure it is
# executable (chmod +x).

import fcntl
import json
import os
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

# Tokens are refreshed below rather than from STRAVA_CLIENT_ID/SECRET in the
# environment, so stravalib's warning about those is just noise.
os.environ.setdefault("SILENCE_TOKEN_WARNINGS", "true")

try:
    from stravalib import Client
    from stravalib.exc import ActivityUploadFailed
except ImportError:
    print(
        "Python package stravalib is not available. "
        "Please install with: pip install --user stravalib"
    )
    sys.exit(1)

FIT_TYPE_ACTIVITY = "4"


def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "antfs-cli")


CONFIG_FILE = os.path.join(config_dir(), "strava.json")


def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(config, f, indent=2)
    os.replace(tmp, CONFIG_FILE)


def store_tokens(config, token_data):
    config["access_token"] = token_data["access_token"]
    config["refresh_token"] = token_data["refresh_token"]
    config["expires_at"] = token_data["expires_at"]
    save_config(config)


def upload(action, filename, fit_type):
    if action != "DOWNLOAD" or fit_type != FIT_TYPE_ACTIVITY:
        return 0

    config = load_config()
    if "refresh_token" not in config:
        print("No Strava login found. Run this script by hand once:")
        print(" ", os.path.abspath(__file__))
        return 1

    # antfs-cli runs this script once per downloaded file, in parallel.
    # Serialise so concurrent runs don't race each other refreshing tokens.
    with open(CONFIG_FILE + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        config = load_config()

        if config["expires_at"] <= time.time() + 60:
            token_data = Client().refresh_access_token(
                client_id=config["client_id"],
                client_secret=config["client_secret"],
                refresh_token=config["refresh_token"],
            )
            store_tokens(config, token_data)

        client = Client(access_token=config["access_token"])
        name = os.path.basename(filename)
        try:
            with open(filename, "rb") as f:
                uploader = client.upload_activity(activity_file=f, data_type="fit")
            uploader.wait(timeout=120)
        except ActivityUploadFailed as e:
            if "duplicate" in str(e).lower():
                print(f"Strava: {name} already uploaded")
                return 0
            print(f"Strava: uploading {name} FAILED: {e}")
            return 1

    print(f"Strava: uploaded {name}")
    return 0


def login():
    config = load_config()
    if "client_id" not in config:
        print("Create an API application at https://www.strava.com/settings/api")
        print('with "Authorization Callback Domain" set to: localhost\n')
        config["client_id"] = int(input("Client ID: "))
        config["client_secret"] = input("Client Secret: ").strip()
        save_config(config)

    state = secrets.token_urlsafe(16)
    result = {}

    class AuthRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            params = parse_qs(urlparse(self.path).query)
            ok = params.get("state") == [state] and "code" in params
            if ok:
                result["code"] = params["code"][0]
            self.send_response(200 if ok else 400)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                (
                    "Strava access granted. You can close this page."
                    if ok
                    else "Strava authorisation failed or was denied."
                ).encode("utf-8")
            )

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), AuthRequestHandler)
    url = Client().authorization_url(
        client_id=config["client_id"],
        redirect_uri=f"http://localhost:{httpd.server_port}",
        scope="activity:write",
        state=state,
    )
    print("\nOpen this page to let antfs-cli upload to your Strava account:\n")
    print(url)
    httpd.handle_request()

    if "code" not in result:
        print("Authorisation failed or was denied.")
        return 1

    token_data = Client().exchange_code_for_token(
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        code=result["code"],
    )
    store_tokens(config, token_data)
    print("Logged in. Tokens saved to", CONFIG_FILE)
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.exit(login())
    sys.exit(upload(sys.argv[1], sys.argv[2], sys.argv[3]))
