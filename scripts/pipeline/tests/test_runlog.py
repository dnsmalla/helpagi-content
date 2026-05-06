"""Tests for lib.runlog.RunLog."""
from __future__ import annotations

import json
import re
from pathlib import Path

from lib.runlog import RunLog


def test_records_events_in_order() -> None:
    log = RunLog(run_id="20260506T000000Z")
    log.record("start", phase="discover")
    log.record("channel_probed", handle="@mreflow", raw=4, kept=2)
    log.record("end")
    events = [e["event"] for e in log.entries]
    assert events == ["start", "channel_probed", "end"]
    probed = log.entries[1]
    assert probed["handle"] == "@mreflow"
    assert probed["raw"] == 4
    assert probed["kept"] == 2


def test_each_entry_has_timestamp() -> None:
    log = RunLog()
    log.record("x")
    iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")
    assert iso_re.match(log.entries[0]["ts"])


def test_write_emits_valid_json(tmp_path: Path) -> None:
    log = RunLog(run_id="20260506T000000Z")
    log.record("foo", n=1)
    out = log.write(tmp_path)
    assert out.name == "runlog-20260506T000000Z.json"
    payload = json.loads(out.read_text())
    assert payload["run_id"] == "20260506T000000Z"
    assert payload["entries"][0]["event"] == "foo"
    assert payload["entries"][0]["n"] == 1
    assert "started_at" in payload
    assert "ended_at" in payload


def test_run_id_default_format() -> None:
    log = RunLog()
    assert re.match(r"^\d{8}T\d{6}Z$", log.run_id)
