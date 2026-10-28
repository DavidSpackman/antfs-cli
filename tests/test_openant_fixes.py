import collections
import queue
import threading
import time
import types
import unittest

import openant.easy.channel
from openant.base.message import Message
from openant.easy.exception import AntException, TransferFailedException

from openant.fs.beacon import Beacon

from antfs_cli import openant_fixes

COMPLETED = Message.Code.EVENT_TRANSFER_TX_COMPLETED
FAILED = Message.Code.EVENT_TRANSFER_TX_FAILED
RX_FAIL = Message.Code.EVENT_RX_FAIL
RX_TRANSFER_FAILED = Message.Code.EVENT_TRANSFER_RX_FAILED


class WaitForEventTest(unittest.TestCase):
    def setUp(self):
        openant_fixes._consecutive_failures = 0
        self.condition = threading.Condition()

    def wait(self, *events, timeout=1):
        queue = collections.deque((0, code, [code]) for code in events)
        return openant_fixes.wait_for_event(
            [COMPLETED], queue, self.condition, timeout=timeout
        )

    def test_returns_matching_event(self):
        self.assertEqual(self.wait(RX_FAIL, COMPLETED), (0, COMPLETED, [COMPLETED]))

    def test_failed_send_raises_so_openant_retries(self):
        with self.assertRaises(TransferFailedException):
            self.wait(RX_FAIL, FAILED)

    def test_gives_up_after_repeated_failures(self):
        for _ in range(openant_fixes.MAX_CONSECUTIVE_FAILURES - 1):
            with self.assertRaises(TransferFailedException):
                self.wait(FAILED)
        with self.assertRaises(AntException) as cm:
            self.wait(FAILED)
        self.assertNotIsInstance(cm.exception, TransferFailedException)

    def test_success_resets_failure_count(self):
        for _ in range(openant_fixes.MAX_CONSECUTIVE_FAILURES - 1):
            with self.assertRaises(TransferFailedException):
                self.wait(FAILED)
        self.wait(COMPLETED)
        with self.assertRaises(TransferFailedException):
            self.wait(FAILED)

    def test_times_out_without_events(self):
        with self.assertRaises(AntException):
            self.wait(RX_FAIL)

    def test_apply_replaces_channel_wait(self):
        original = openant.easy.channel.wait_for_event
        try:
            openant_fixes.apply()
            self.assertIs(
                openant.easy.channel.wait_for_event, openant_fixes.wait_for_event
            )
        finally:
            openant.easy.channel.wait_for_event = original


class GetCommandTest(unittest.TestCase):
    def setUp(self):
        self.events = collections.deque()
        node = types.SimpleNamespace(
            _events=self.events, _event_cond=threading.Condition()
        )
        self.app = types.SimpleNamespace(
            _node=node,
            _queue=queue.Queue(),
            beacon_state=Beacon.ClientDeviceState.TRANSPORT,
            last_command="request",
        )
        # Resent requests are recorded and, if reply_to_resend, answered.
        self.resent = []
        self.reply_to_resend = True
        original = openant_fixes.Application._send_command
        openant_fixes.Application._send_command = self.fake_send
        self.addCleanup(setattr, openant_fixes.Application, "_send_command", original)

    def fake_send(self, app, command):
        self.resent.append((time.monotonic() - self.start, command))
        if self.reply_to_resend:
            app._queue.put("reply")

    def add_event(self, code):
        self.events.append((0, code, [code]))

    def set_state(self, state):
        self.app.beacon_state = state

    def later(self, delay, function, *args):
        timer = threading.Timer(delay, function, args)
        timer.start()
        self.addCleanup(timer.cancel)

    def get_command(self, timeout=10):
        self.start = time.monotonic()
        return openant_fixes.get_command(self.app, timeout)

    def test_returns_command(self):
        self.app._queue.put("reply")
        self.assertEqual(self.get_command(), "reply")
        self.assertEqual(self.resent, [])

    def test_failed_transfer_resends_once_idle(self):
        self.set_state(Beacon.ClientDeviceState.BUSY)
        self.later(0.1, self.add_event, RX_TRANSFER_FAILED)
        self.later(1.0, self.set_state, Beacon.ClientDeviceState.TRANSPORT)
        self.assertEqual(self.get_command(), "reply")
        [(when, command)] = self.resent
        self.assertEqual(command, "request")
        self.assertGreaterEqual(when, 1.0)
        self.assertEqual(len(self.events), 0)

    def test_ignores_failures_from_earlier_transfers(self):
        self.add_event(RX_TRANSFER_FAILED)
        self.add_event(RX_FAIL)
        self.later(0.3, self.app._queue.put, "reply")
        self.assertEqual(self.get_command(), "reply")
        self.assertEqual(self.resent, [])
        self.assertEqual(list(self.events), [(0, RX_FAIL, [RX_FAIL])])

    def test_watch_idle_after_busy_resends(self):
        self.set_state(Beacon.ClientDeviceState.BUSY)
        self.later(0.2, self.set_state, Beacon.ClientDeviceState.TRANSPORT)
        self.assertEqual(self.get_command(), "reply")
        [(when, _)] = self.resent
        self.assertLess(when, 2)

    def test_reply_after_busy_is_returned(self):
        self.set_state(Beacon.ClientDeviceState.BUSY)
        self.later(0.2, self.set_state, Beacon.ClientDeviceState.TRANSPORT)
        self.later(0.3, self.app._queue.put, "reply")
        self.assertEqual(self.get_command(), "reply")
        self.assertEqual(self.resent, [])

    def test_ignored_request_resends_after_timeout(self):
        self.assertEqual(self.get_command(), "reply")
        [(when, _)] = self.resent
        self.assertGreaterEqual(when, openant_fixes.IGNORED_TIMEOUT)
        self.assertLess(when, openant_fixes.IGNORED_TIMEOUT + 1)

    def test_waits_while_authenticating(self):
        self.set_state(Beacon.ClientDeviceState.AUTHENTICATION)
        self.later(2.5, self.app._queue.put, "reply")
        self.assertEqual(self.get_command(), "reply")
        self.assertEqual(self.resent, [])

    def test_failed_transfer_while_authenticating_resends(self):
        self.set_state(Beacon.ClientDeviceState.AUTHENTICATION)
        self.later(0.2, self.add_event, RX_TRANSFER_FAILED)
        self.assertEqual(self.get_command(), "reply")
        [(when, _)] = self.resent
        self.assertGreaterEqual(when, 0.2 + openant_fixes.AUTH_RX_FAILED_GRACE)

    def test_gives_up_after_too_many_resends(self):
        self.reply_to_resend = False
        original = openant_fixes.IGNORED_TIMEOUT
        openant_fixes.IGNORED_TIMEOUT = 0.2
        self.addCleanup(setattr, openant_fixes, "IGNORED_TIMEOUT", original)
        with self.assertRaises(queue.Empty):
            self.get_command()
        self.assertEqual(len(self.resent), openant_fixes.MAX_RESENDS)

    def test_times_out(self):
        self.set_state(Beacon.ClientDeviceState.AUTHENTICATION)
        with self.assertRaises(queue.Empty):
            self.get_command(0.3)


class SendCommandTest(unittest.TestCase):
    def test_drops_stale_replies_before_sending(self):
        sent = []
        app = types.SimpleNamespace(_queue=queue.Queue())
        app._queue.put("stale")
        app._queue.put("staler")
        original = openant_fixes.Application._send_command
        try:
            openant_fixes.Application._send_command = lambda self, c: sent.append(
                (self._queue.qsize(), c)
            )
            openant_fixes.send_command(app, "request")
        finally:
            openant_fixes.Application._send_command = original
        self.assertEqual(sent, [(0, "request")])
        self.assertEqual(app.last_command, "request")


if __name__ == "__main__":
    unittest.main()
