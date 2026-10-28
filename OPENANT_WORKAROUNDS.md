# openant workarounds

antfs-cli works around several bugs in [openant](https://github.com/Tigge/openant)
1.x instead of depending on a fork. This file records each one so that, if we
ever decide to send fixes upstream, we know exactly what to propose, and so the
matching workaround can be deleted once a fixed openant is released.

**Status:** nothing has been reported or submitted upstream. The workarounds
live in `antfs_cli/openant_fixes.py` and `antfs_cli/program.py`.

All were found syncing a Garmin Forerunner 310XT over an ANTUSB2 stick, against
openant **1.3.4** (latest release; upstream master was `52c545c` when checked
on 2026-10-28 and still had bugs 1, 2, 3 and 6). Line numbers refer to 1.3.4.

## Clear bugs, small upstream fixes

### 1. Failed sends are never retried

- **Where:** `openant/easy/filter.py:50`, in `wait_for_message`.
- **Bug:** the check for a failed transfer is
  `message[1] == 1 and message[2][0] in [EVENT_TRANSFER_TX_FAILED, EVENT_RX_FAIL_GO_TO_SEARCH]`,
  but `Node._worker_event` queues events as `(channel, event_code, data)`. A
  failed send arrives as `(0, 6, [6])`, never matches, so the retry in
  `Channel.send_acknowledged_data` / `send_burst_transfer` never runs. openant
  waits 10 s for `EVENT_TRANSFER_TX_COMPLETED` and the watch drops the link.
- **Upstream fix:** `elif message[1] in [...]` for the events queue. Also bound
  the retries: the `except TransferFailedException` branches recurse forever.
- **Our workaround:** `openant_fixes.wait_for_event`, patched into
  `openant.easy.channel` by `openant_fixes.apply()` (max 10 failures in a row).
- **Not reported upstream.** The hishizuka/openant fork (built on pre-1.0
  `ant` code) checks the event code correctly in `ant/easy/filter.py`; see its
  commit `d1670d8` for reference.

### 2. `set_time` always crashes

- **Where:** `openant/fs/manager.py:335`.
- **Bug:** the default argument `datetime.now(timezone.utc)` is timezone-aware
  but is subtracted from a naive `datetime(1989, 12, 31)`, raising
  `TypeError: can't subtract offset-naive and offset-aware datetimes`. The
  default is also evaluated once at import, so it would be stale anyway.
- **Upstream fix:** default to `None`, use the current UTC time when `None`,
  and make the epoch timezone-aware (or strip `tzinfo`).
- **Our workaround:** `AntFSCLI.on_transport` passes naive UTC explicitly.
- **Upstream issue:** [Tigge/openant#119](https://github.com/Tigge/openant/issues/119)
  (open, includes a suggested patch). Separately, the 310XT rejects the time
  with response 3, likely the same as
  [#39](https://github.com/Tigge/openant/issues/39); that is not a bug in
  openant and we just log it.

### 3. Downloads are not checked against their CRC

- **Where:** `openant/fs/manager.py:315` (`# TODO: check CRC`).
- **Bug:** a reply for the wrong request (see 5) is accepted, and the result is
  saved as a file. We saw the last 345 bytes of one activity saved as the next.
- **Upstream fix:** check the CRC in `download()`, or at least that the reply's
  offset is the one requested.
- **Our workaround:** `program.is_valid_fit` checks the FIT header and CRC;
  corrupt files aren't saved, so the next sync downloads them again.

## Design issues, bigger upstream changes

These needed tuning against the 310XT, so they'd need discussion upstream.

### 4. Lost replies wait out a 15 s timeout

- **Where:** `Application._get_command` (`openant/fs/manager.py:171`) and its
  callers.
- **Problem:** if the watch's reply is lost, `_get_command` waits 15 s, but the
  watch drops an idle link after about 8 s. Only `download()` retries on
  timeout (line 327); authentication and everything else just fail.
- **Our workaround:** `openant_fixes.get_command` (via
  `AntFSCLI._get_command`) resends the request as soon as the reply is clearly
  lost, judged from the beacon's client state and `EVENT_TRANSFER_RX_FAILED`:
  after the watch goes busy then idle with no reply, after a failed receive
  once the watch is idle again (resending mid-reply kills the session), or
  after 2 s of idle if the watch acknowledged the request but ignored it. While
  authenticating, only a failed receive triggers a resend, so pairing can wait
  for a button press. At most 5 resends per request.

### 5. Stale replies are handed to the next request

- **Where:** `Application._send_command` / `_queue`.
- **Problem:** once a request has been resent, a late original reply leaves a
  spare reply in the queue, which the next request then takes as its answer.
- **Our workaround:** `openant_fixes.send_command` (via
  `AntFSCLI._send_command`) empties the queue before each request.

### 6. A failed sync leaves the watch stuck in its session

- **Where:** `Application._main` (`openant/fs/manager.py:127`).
- **Problem:** on an exception `_main` stops the node without disconnecting,
  so the watch stays in its transport session and ignores the next run's link
  request until it is restarted. `_main` also never handles a watch whose
  first beacon is already in the authentication or transport state.
- **Our workaround:** `AntFSCLI._main` replaces the loop: it ends a session
  left open by an earlier run (the host serial is always 1337, so the watch
  recognises us) and disconnects on any error after linking.

## Removing a workaround

If a fixed openant is released, raise the minimum version in `pyproject.toml`,
delete the matching workaround and its tests, re-run a full sync with
`antfs-cli --debug` against a real watch, and update this file.
