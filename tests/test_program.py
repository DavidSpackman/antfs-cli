import array
import datetime
import os
import tempfile
import unittest

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
