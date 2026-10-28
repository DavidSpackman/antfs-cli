#!/usr/bin/env python
#
# Ant
#
# Copyright (c) 2012, Gustav Tiger <gustav@tiger.name>
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import array
import logging
import datetime
import time
from argparse import ArgumentParser
import os
import sys
import traceback

from openant.fs.manager import (
    Application,
    AntFSAuthenticationException,
    AntFSTimeException,
    AntFSDownloadException,
)
from openant.fs.manager import AntFSUploadException
from openant.fs.file import File

from . import utilities
from . import scripting

_logger = logging.getLogger()

_directories = {
    ".": File.Identifier.DEVICE,
    "activities": File.Identifier.ACTIVITY,
    "courses": File.Identifier.COURSE,
    "waypoints": File.Identifier.WAYPOINTS,
    "monitoring_b": File.Identifier.MONITORING_B,
    # "profile":     File.Identifier.?
    # "goals?":      File.Identifier.GOALS,
    # "bloodprs":    File.Identifier.BLOOD_PRESSURE,
    # "summaries":   File.Identifier.ACTIVITY_SUMMARY,
    "settings": File.Identifier.SETTING,
    "sports": File.Identifier.SPORT,
    "totals": File.Identifier.TOTALS,
    "weight": File.Identifier.WEIGHT,
    "workouts": File.Identifier.WORKOUT,
}

_filetypes = dict((v, k) for (k, v) in _directories.items())


class Device:
    class ProfileVersionException(Exception):
        pass

    _PROFILE_VERSION = 1
    _PROFILE_VERSION_FILE = "profile_version"

    def __init__(self, basedir, serial, name):
        self._path = os.path.join(basedir, str(serial))
        self._serial = serial
        self._name = name

        # Check profile version, if not a new device
        if os.path.isdir(self._path):
            if self.get_profile_version() < self._PROFILE_VERSION:
                raise Device.ProfileVersionException(
                    "Profile version mismatch, too old"
                )
            elif self.get_profile_version() > self._PROFILE_VERSION:
                raise Device.ProfileVersionException(
                    "Profile version mismatch, too new"
                )

        # Create directories
        for directory in _directories:
            os.makedirs(os.path.join(self._path, directory), exist_ok=True)

        # Write profile version (If none)
        path = os.path.join(self._path, self._PROFILE_VERSION_FILE)
        if not os.path.exists(path):
            with open(path, "w") as f:
                f.write(str(self._PROFILE_VERSION))

    def get_path(self):
        return self._path

    def get_serial(self):
        return self._serial

    def get_name(self):
        return self._name

    def get_profile_version(self):
        path = os.path.join(self._path, self._PROFILE_VERSION_FILE)
        try:
            with open(path, "rb") as f:
                return int(f.read())
        except FileNotFoundError:
            return 0

    def read_passkey(self):
        try:
            with open(os.path.join(self._path, "authfile"), "rb") as f:
                d = array.array("B", f.read())
                _logger.debug("loaded authfile: %r", d)
                return d
        except FileNotFoundError:
            return None

    def write_passkey(self, passkey):
        with open(os.path.join(self._path, "authfile"), "wb") as f:
            passkey.tofile(f)
            _logger.debug("wrote authfile: %r, %r", self._serial, passkey)


class AntFSCLI(Application):
    PRODUCT_NAME = "antfs-cli"

    def __init__(self, config_dir, args):
        Application.__init__(self)

        self.config_dir = config_dir

        # Set up scripting
        scripts_dir = os.path.join(self.config_dir, "scripts")
        os.makedirs(scripts_dir, exist_ok=True)
        self.scriptr = scripting.Runner(scripts_dir)

        self._device = None
        self._uploading = args.upload
        self._pair = args.pair
        self._skip_archived = args.skip_archived

    def setup_channel(self, channel):
        channel.set_period(4096)
        channel.set_search_timeout(255)
        channel.set_rf_freq(50)
        channel.set_search_waveform([0x53, 0x00])
        channel.set_id(0, 0x01, 0)

        channel.open()
        # channel.request_message(Message.ID.RESPONSE_CHANNEL_STATUS)
        print("Searching...")

    def on_link(self, beacon):
        _logger.debug("on link, %r, %r", beacon.get_serial(), beacon.get_descriptor())
        self.link()
        return True

    def on_authentication(self, beacon):
        _logger.debug("on authentication")
        serial, name = self.authentication_serial()
        self._device = Device(self.config_dir, serial, name)

        passkey = self._device.read_passkey()
        print(f"Authenticating with {name} ({serial})")
        _logger.debug("serial %s, %r, %r", name, serial, passkey)

        if passkey is not None and not self._pair:
            try:
                print(" - Passkey:", end=" ")
                sys.stdout.flush()
                self.authentication_passkey(passkey)
                print("OK")
                return True
            except AntFSAuthenticationException:
                print("FAILED")
                return False
        else:
            try:
                print(" - Pairing:", end=" ")
                sys.stdout.flush()
                passkey = self.authentication_pair(self.PRODUCT_NAME)
                self._device.write_passkey(passkey)
                print("OK")
                return True
            except AntFSAuthenticationException:
                print("FAILED")
                return False

    def on_transport(self, beacon):

        # Adjust time
        print(" - Set time:", end=" ")
        try:
            # openant's default is timezone-aware (and fixed at import time),
            # but it subtracts a naive epoch, so pass naive UTC explicitly.
            now = datetime.datetime.now(datetime.timezone.utc)
            self.set_time(now.replace(tzinfo=None))
        except (AntFSTimeException, AntFSDownloadException, AntFSUploadException):
            print("FAILED")
            _logger.exception("Could not set time")
        else:
            print("OK")

        directory = self.download_directory()
        # directory.print_list()

        # Map local filenames to FIT file types
        local_files = []
        for folder, filetype in _directories.items():
            path = os.path.join(self._device.get_path(), folder)
            for filename in os.listdir(path):
                if os.path.splitext(filename)[1].lower() == ".fit":
                    local_files.append((filename, filetype))

        downloading, uploading = plan_sync(
            local_files, directory.get_files(), self._skip_archived
        )

        print("Downloading", len(downloading), "file(s)")
        if self._uploading:
            print(" and uploading", len(uploading), "file(s)")

        # Download missing files:
        for fileobject in downloading:
            self.download_file(fileobject)

        # Upload missing files:
        if uploading and self._uploading:
            # Upload
            results = {}
            for filename, typ in uploading:
                index = self.upload_file(typ, filename)
                results[index] = (filename, typ)

            # Rename uploaded files locally
            directory = self.download_directory()
            for index, (filename, typ) in results.items():
                try:
                    file_object = next(
                        f for f in directory.get_files() if f.get_index() == index
                    )
                    src = os.path.join(
                        self._device.get_path(), _filetypes[typ], filename
                    )
                    dst = self.get_filepath(file_object)
                    print(" - Renamed", src, "to", dst)
                    os.rename(src, dst)
                except Exception as e:
                    print(" - Failed", index, filename, e)

    def get_filepath(self, fil):
        return os.path.join(
            self._device.get_path(),
            _filetypes[fil.get_fit_sub_type()],
            get_filename(fil),
        )

    def download_file(self, fil):
        sys.stdout.write(f"Downloading {get_filename(fil)}: ")
        sys.stdout.flush()
        data = self.download(fil.get_index(), AntFSCLI._get_progress_callback())
        with open(self.get_filepath(fil), "wb") as fd:
            data.tofile(fd)
        sys.stdout.write("\n")
        sys.stdout.flush()

        self.scriptr.run_download(self.get_filepath(fil), fil.get_fit_sub_type())

    def upload_file(self, typ, filename):
        sys.stdout.write(f"Uploading {filename}: ")
        sys.stdout.flush()
        with open(
            os.path.join(self._device.get_path(), _filetypes[typ], filename), "rb"
        ) as fd:
            data = array.array("B", fd.read())
        index = self.create(typ, data, AntFSCLI._get_progress_callback())
        sys.stdout.write("\n")
        sys.stdout.flush()
        return index

    @staticmethod
    def _get_progress_callback():
        start_time = time.time()

        def callback(new_progress):
            s = "[{0:<30}]".format("." * int(new_progress * 30))
            if new_progress == 0:
                s += " started"
            else:
                delta = time.time() - start_time
                eta = datetime.timedelta(seconds=int(delta / new_progress - delta))
                s += f" ETA: {eta}"
            sys.stdout.write(s)
            sys.stdout.flush()
            sys.stdout.write("\b" * len(s))

        return callback


def get_filename(fil):
    """Local filename for a remote FIT file.

    The download/upload diff in plan_sync matches local and remote files by
    this name, so changing the format makes every file look new."""
    date = fil.get_date().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{date}_{fil.get_fit_sub_type()}_{fil.get_fit_file_number()}.fit"


def plan_sync(local_files, remote_files, skip_archived=False):
    """Work out which files to download and which to upload.

    local_files is a list of (filename, fit_type) for FIT files on disk and
    remote_files is the device's directory listing. Returns the remote file
    objects to download and the (filename, fit_type) pairs to upload.

    A remote file is downloaded if it is missing locally, or if the device
    has not marked it as archived yet (it may still be changing). With
    skip_archived, archived files are never downloaded."""
    remote = [
        (get_filename(fil), fil)
        for fil in remote_files
        if fil.get_fit_sub_type() in _filetypes and fil.is_readable()
    ]
    local_names = {name for name, _ in local_files}
    remote_names = {name for name, _ in remote}

    downloading = [
        fil for name, fil in remote if name not in local_names or not fil.is_archived()
    ]
    if skip_archived:
        downloading = [fil for fil in downloading if not fil.is_archived()]

    uploading = [
        (name, fit_type) for name, fit_type in local_files if name not in remote_names
    ]
    return downloading, uploading


def main():
    parser = ArgumentParser(
        description="Extracts FIT files from ANT-FS based sport watches."
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="also copy FIT files that are only stored locally to the watch",
    )
    parser.add_argument(
        "--debug", action="store_true", help="also print the debug log to the terminal"
    )
    parser.add_argument(
        "--pair", action="store_true", help="force pairing even if already paired"
    )
    parser.add_argument(
        "-a",
        "--skip-archived",
        action="store_true",
        help="don't download files marked as 'archived' on the watch",
    )
    args = parser.parse_args()

    # Set up config dir
    config_dir = utilities.XDG(AntFSCLI.PRODUCT_NAME).get_config_dir()
    logs_dir = os.path.join(config_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    # Set up logging
    _logger.setLevel(logging.DEBUG)

    # If you add new module/logger name longer than the 22 characters
    # just increase the value after %(name).
    # The longest module/logger name now is "openant.easy.exception".
    formatter = logging.Formatter(
        fmt="%(threadName)-10s %(asctime)s  %(name)-22s"
        "  %(levelname)-8s  %(message)s (%(filename)s:%(lineno)d)"
    )

    log_filename = os.path.join(
        logs_dir,
        f"{time.strftime('%Y%m%d-%H%M%S')}-{AntFSCLI.PRODUCT_NAME}.log",
    )
    handler = logging.FileHandler(log_filename, "w")
    handler.setFormatter(formatter)
    _logger.addHandler(handler)

    if args.debug:
        _logger.addHandler(logging.StreamHandler())

    try:
        g = AntFSCLI(config_dir, args)
        try:
            g.start()
        finally:
            g.stop()
    except Device.ProfileVersionException as e:
        print(
            "\nError: %s\n\nThis means that %s found that your data directory "
            "structure was too old or too new. The best option is "
            "probably to let %s recreate your "
            "folder by deleting your data folder, after backing it up, "
            "and let all your files be redownloaded from your sports "
            "watch." % (e, AntFSCLI.PRODUCT_NAME, AntFSCLI.PRODUCT_NAME)
        )
        return 1
    except (Exception, KeyboardInterrupt) as e:
        traceback.print_exc()
        _logger.exception("Interrupted")
        print("Interrupted:", str(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
