import array
import datetime
import os
import queue
import tempfile
import unittest

from openant.fs.beacon import Beacon
from openant.fs.file import File

from antfs_cli import program

ACTIVITY = File.Identifier.ACTIVITY
COURSE = File.Identifier.COURSE


class FakeFile:
    """Stand-in for openant.fs.file.File with only what antfs-cli reads."""

    def __init__(
        self,
        number,
        sub_type=ACTIVITY,
        archived=False,
        readable=True,
        date=datetime.datetime(2020, 5, 17, 8, 30, 0),
    ):
        self._number = number
        self._sub_type = sub_type
        self._archived = archived
        self._readable = readable
        self._date = date

    def get_date(self):
        return self._date

    def get_fit_sub_type(self):
        return self._sub_type

    def get_fit_file_number(self):
        return self._number

    def is_archived(self):
        return self._archived

    def is_readable(self):
        return self._readable


class GetFilenameTest(unittest.TestCase):
    def test_format(self):
        fil = FakeFile(12, sub_type=ACTIVITY)
        self.assertEqual(program.get_filename(fil), "2020-05-17_08-30-00_4_12.fit")


class PlanSyncTest(unittest.TestCase):
    def local(self, fil):
        return (program.get_filename(fil), fil.get_fit_sub_type())

    def test_new_remote_file_is_downloaded(self):
        fil = FakeFile(1, archived=True)
        downloading, uploading = program.plan_sync([], [fil])
        self.assertEqual(downloading, [fil])
        self.assertEqual(uploading, [])

    def test_archived_file_present_locally_is_skipped(self):
        fil = FakeFile(1, archived=True)
        downloading, _ = program.plan_sync([self.local(fil)], [fil])
        self.assertEqual(downloading, [])

    def test_unarchived_file_present_locally_is_downloaded_again(self):
        fil = FakeFile(1, archived=False)
        downloading, _ = program.plan_sync([self.local(fil)], [fil])
        self.assertEqual(downloading, [fil])

    def test_skip_archived_drops_archived_files_missing_locally(self):
        archived = FakeFile(1, archived=True)
        fresh = FakeFile(2, archived=False)
        downloading, _ = program.plan_sync([], [archived, fresh], skip_archived=True)
        self.assertEqual(downloading, [fresh])

    def test_unreadable_and_unknown_type_files_are_ignored(self):
        unreadable = FakeFile(1, readable=False)
        unknown = FakeFile(2, sub_type=0xFF)
        downloading, uploading = program.plan_sync([], [unreadable, unknown])
        self.assertEqual(downloading, [])
        self.assertEqual(uploading, [])

    def test_local_only_files_are_uploaded(self):
        on_device = FakeFile(1, archived=True)
        local_only = FakeFile(2, sub_type=COURSE)
        _, uploading = program.plan_sync(
            [self.local(on_device), self.local(local_only)], [on_device]
        )
        self.assertEqual(uploading, [self.local(local_only)])


class DeviceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.basedir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_folders_and_profile_version(self):
        device = program.Device(self.basedir, 1234, "Forerunner")
        self.assertEqual(device.get_path(), os.path.join(self.basedir, "1234"))
        for folder in ("activities", "courses", "settings"):
            self.assertTrue(os.path.isdir(os.path.join(device.get_path(), folder)))
        self.assertEqual(device.get_profile_version(), program.Device._PROFILE_VERSION)

    def test_reopening_existing_device_works(self):
        program.Device(self.basedir, 1234, "Forerunner")
        program.Device(self.basedir, 1234, "Forerunner")

    def test_passkey_round_trip(self):
        device = program.Device(self.basedir, 1234, "Forerunner")
        self.assertIsNone(device.read_passkey())
        passkey = array.array("B", [1, 2, 3, 4, 5, 6, 7, 8])
        device.write_passkey(passkey)
        self.assertEqual(device.read_passkey(), passkey)

    def write_profile_version(self, version):
        path = os.path.join(self.basedir, "1234")
        os.makedirs(path)
        with open(os.path.join(path, program.Device._PROFILE_VERSION_FILE), "w") as f:
            f.write(str(version))

    def test_newer_profile_version_is_rejected(self):
        self.write_profile_version(program.Device._PROFILE_VERSION + 1)
        with self.assertRaises(program.Device.ProfileVersionException):
            program.Device(self.basedir, 1234, "Forerunner")

    def test_existing_folder_without_profile_version_is_rejected(self):
        os.makedirs(os.path.join(self.basedir, "1234"))
        with self.assertRaises(program.Device.ProfileVersionException):
            program.Device(self.basedir, 1234, "Forerunner")


def make_fit(records=b"\x40\x00\x00\x00\x00\x00"):
    header = bytes([12, 0x10, 0x83, 0x00]) + len(records).to_bytes(4, "little")
    body = header + b".FIT" + records
    return body + program._fit_crc(body).to_bytes(2, "little")


class IsValidFitTest(unittest.TestCase):
    def test_valid_file(self):
        self.assertTrue(program.is_valid_fit(make_fit()))

    def test_crc_of_known_data(self):
        # Reference value from the FIT SDK's CRC routine.
        self.assertEqual(program._fit_crc(b"123456789"), 0xBB3D)

    def test_bad_checksum(self):
        data = bytearray(make_fit())
        data[13] ^= 0xFF
        self.assertFalse(program.is_valid_fit(bytes(data)))

    def test_truncated(self):
        self.assertFalse(program.is_valid_fit(make_fit()[:-3]))

    def test_tail_of_another_file(self):
        self.assertFalse(program.is_valid_fit(make_fit()[5:]))

    def test_empty(self):
        self.assertFalse(program.is_valid_fit(b""))


LINK = Beacon.ClientDeviceState.LINK
AUTH = Beacon.ClientDeviceState.AUTHENTICATION
TRANSPORT = Beacon.ClientDeviceState.TRANSPORT


class FakeBeacon:
    def __init__(self, state):
        self.state = state

    def get_client_device_state(self):
        return self.state


class SessionTest(unittest.TestCase):
    """AntFSCLI._main never leaves the watch stuck in a session."""

    def make_cli(self, *states):
        cli = object.__new__(program.AntFSCLI)
        cli._beacons = queue.Queue()
        for state in states:
            cli._beacons.put(FakeBeacon(state))
        cli.calls = []
        cli.disconnect = lambda: cli.calls.append("disconnect")
        cli.stop = lambda: cli.calls.append("stop")
        cli.on_link = lambda beacon: cli.calls.append("link") or True
        cli.on_authentication = lambda beacon: cli.calls.append("auth") or True
        cli.on_transport = lambda beacon: cli.calls.append("transport")
        return cli

    def test_normal_sync(self):
        cli = self.make_cli(LINK, AUTH, TRANSPORT)
        cli._main()
        self.assertEqual(cli.calls, ["link", "auth", "transport", "disconnect", "stop"])

    def test_ends_session_left_open_by_earlier_run(self):
        cli = self.make_cli(TRANSPORT, TRANSPORT, LINK, AUTH, TRANSPORT)
        cli._main()
        self.assertEqual(
            cli.calls,
            ["disconnect", "link", "auth", "transport", "disconnect", "stop"],
        )

    def test_disconnects_when_sync_fails(self):
        cli = self.make_cli(LINK, AUTH, TRANSPORT)

        def fail(beacon):
            raise RuntimeError("radio trouble")

        cli.on_transport = fail
        with self.assertRaises(RuntimeError):
            cli._main()
        self.assertEqual(cli.calls, ["link", "auth", "disconnect", "stop"])

    def test_failed_disconnect_does_not_hide_error(self):
        cli = self.make_cli(LINK, AUTH)

        def fail(*args):
            raise RuntimeError("radio trouble")

        cli.on_authentication = fail
        cli.disconnect = fail
        with (
            self.assertLogs(level="WARNING"),
            self.assertRaisesRegex(RuntimeError, "radio trouble"),
        ):
            cli._main()
