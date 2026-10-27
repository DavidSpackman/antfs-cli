import os
import stat
import sys
import tempfile
import unittest

from antfs_cli import scripting


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.scripts_dir = os.path.join(self._tmp.name, "scripts")
        self.output = os.path.join(self._tmp.name, "output")
        os.makedirs(self.scripts_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def add_script(self, name):
        path = os.path.join(self.scripts_dir, name)
        with open(path, "w") as f:
            f.write(
                f"#!{sys.executable}\n"
                "import sys\n"
                f"with open({self.output!r}, 'a') as f:\n"
                f"    f.write({name!r} + ' ' + ' '.join(sys.argv[1:]) + '\\n')\n"
            )
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)

    def test_scripts_are_sorted(self):
        self.add_script("50-second")
        self.add_script("10-first")
        runner = scripting.Runner(self.scripts_dir)
        self.assertEqual(runner.get_scripts(), ["10-first", "50-second"])

    def test_scripts_run_in_order_with_arguments(self):
        self.add_script("50-second")
        self.add_script("10-first")
        runner = scripting.Runner(self.scripts_dir)
        runner._run_action("DOWNLOAD", "/data/file.fit", 4)
        with open(self.output) as f:
            self.assertEqual(
                f.read().splitlines(),
                [
                    "10-first DOWNLOAD /data/file.fit 4",
                    "50-second DOWNLOAD /data/file.fit 4",
                ],
            )
