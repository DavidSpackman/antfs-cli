"""Workarounds for openant bugs that break syncing.

openant (up to at least 1.3.4) retries an acknowledged or burst send when the
stick reports that it failed, but the check in ``openant.easy.filter`` expects
events shaped ``(channel, 1, [code])`` while the node queues them as
``(channel, code, data)``. A failed send is therefore never noticed: openant
waits ten seconds for a "transfer completed" event that never comes, and by
then the watch has given up on the link. :func:`apply` swaps in a
``wait_for_event`` that spots the failure so openant's own retry runs.

Likewise, when a reply from the watch is lost openant waits 15 seconds and
then either asks again (downloads) or gives up (everything else), but the watch
drops an idle link after about 8. :func:`get_command` resends the request as
soon as the reply is clearly lost:

- in transport, once the watch's beacon is back to idle without the reply
  having arrived, after either being busy or the stick reporting a failed
  incoming transfer (``EVENT_TRANSFER_RX_FAILED``). Asking again while the
  watch is still sending kills the session, so this waits for idle;
- in transport, when the watch acknowledges a request and then ignores it,
  staying idle for a couple of seconds;
- while authenticating, a moment after a failed incoming transfer. The beacon
  says nothing useful there, and the watch may legitimately take a long time
  (pairing waits for a button press), so no other rule applies.

:func:`send_command` remembers the request for this and drops stale replies.
"""

import logging
import queue
import time

import openant.easy.channel
from openant.base.message import Message
from openant.easy.exception import AntException, TransferFailedException
from openant.fs.beacon import Beacon
from openant.fs.manager import Application

_logger = logging.getLogger(__name__)

_FAILURE_CODES = (
    Message.Code.EVENT_TRANSFER_TX_FAILED,
    Message.Code.EVENT_RX_FAIL_GO_TO_SEARCH,
)

# openant retries a failed send forever; stop once the watch is clearly gone.
MAX_CONSECUTIVE_FAILURES = 10

_consecutive_failures = 0

# How long the watch may sit idle after being busy before its reply counts as
# lost. Replies arrive along with the first idle beacon, so this is generous.
IDLE_GRACE = 0.5

# How long the watch may stay idle without ever going busy before the request
# counts as ignored. It normally goes busy within a quarter of a second.
IGNORED_TIMEOUT = 2.0

# How long to wait after a failed incoming transfer while authenticating before
# asking again, so the watch has finished sending.
AUTH_RX_FAILED_GRACE = 1.0

# Resends of a single request before giving up on it.
MAX_RESENDS = 5


def wait_for_event(ok_codes, queue, condition, timeout=10):
    global _consecutive_failures
    with condition:
        for _ in range(timeout):
            for message in queue:
                _, code, _ = message
                if code in ok_codes:
                    queue.remove(message)
                    _consecutive_failures = 0
                    return message
                if code in _FAILURE_CODES:
                    queue.remove(message)
                    _consecutive_failures += 1
                    _logger.warning(
                        "Transfer failed (event %d), attempt %d",
                        code,
                        _consecutive_failures,
                    )
                    if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        _consecutive_failures = 0
                        raise AntException("Transfer failed too many times")
                    raise TransferFailedException()
            condition.wait(1.0)
    raise AntException("Timed out while waiting for message")


def get_command(app, timeout=15.0):
    """Drop-in for ``Application._get_command`` that resends lost requests.

    ``app.beacon_state`` must hold the client device state of the latest
    beacon from the watch, and requests must go through :func:`send_command`.
    """
    events, condition = app._node._events, app._node._event_cond

    def take_rx_failure():
        with condition:
            for message in events:
                if message[1] == Message.Code.EVENT_TRANSFER_RX_FAILED:
                    events.remove(message)
                    return True
        return False

    # Failures from earlier transfers have nothing to do with this reply.
    while take_rx_failure():
        pass

    deadline = time.monotonic() + timeout
    resends = 0
    saw_busy = False
    idle_since = None
    rx_failed_at = None
    while True:
        try:
            command = app._queue.get(True, 0.1)
        except queue.Empty:
            now = time.monotonic()
            state = app.beacon_state
            if take_rx_failure():
                saw_busy = True
                idle_since = None
                rx_failed_at = now
            elif state == Beacon.ClientDeviceState.BUSY:
                saw_busy = True
                idle_since = None
            elif state == Beacon.ClientDeviceState.TRANSPORT and idle_since is None:
                idle_since = now

            if state == Beacon.ClientDeviceState.AUTHENTICATION:
                lost = (
                    rx_failed_at is not None
                    and now - rx_failed_at >= AUTH_RX_FAILED_GRACE
                )
            else:
                # A watch that never went busy ignored the request altogether.
                allowed_idle = IDLE_GRACE if saw_busy else IGNORED_TIMEOUT
                lost = idle_since is not None and now - idle_since >= allowed_idle

            if lost and resends < MAX_RESENDS:
                resends += 1
                _logger.warning("Reply from the watch was lost, asking again")
                send_command(app, app.last_command)
                saw_busy = False
                idle_since = None
                rx_failed_at = None
                deadline = time.monotonic() + timeout
            elif lost or now >= deadline:
                raise
            continue
        app._queue.task_done()
        return command


def send_command(app, command):
    """Drop-in for ``Application._send_command`` that drops stale replies.

    Asking again for a reply that was only late, not lost, gets two replies.
    openant would hand the spare one to the next request, which for a download
    means saving the tail of the previous file as the next file. The request
    is kept in ``app.last_command`` so :func:`get_command` can resend it.
    """
    while True:
        try:
            app._queue.get_nowait()
        except queue.Empty:
            break
        app._queue.task_done()
        _logger.warning("Dropped a stale reply from the watch")
    app.last_command = command
    Application._send_command(app, command)


def apply():
    openant.easy.channel.wait_for_event = wait_for_event
