from __future__ import annotations

import json

from hermes_tescmd_plugin import audit


def test_safe_arg_summary_redacts_location_search_and_unknown_strings() -> None:
    summary = audit._safe_arg_summary(  # noqa: SLF001
        {
            "profile": "default",
            "region": "na",
            "confirm": True,
            "destination": "123 Main St, Anytown, CA",
            "query": "coffee near home",
            "email": "driver@example.com",
            "nickname": "Home Garage",
            "raw_payload": {"formatted_address": "123 Main St", "location": {"lat": 37.1, "lon": -122.2}},
            "place_candidates": ["place-id-1", "place-id-2"],
            "percent": 80,
        }
    )

    assert summary["profile"] == "default"
    assert summary["region"] == "na"
    assert summary["confirm"] is True
    assert summary["percent"] == 80
    assert summary["destination"] == "[REDACTED]"
    assert summary["query"] == "[REDACTED]"
    assert summary["email"] == "[REDACTED]"
    assert summary["nickname"] == {"redacted": True, "type": "str", "length": 11, "hash": audit._hash_value("Home Garage")}  # noqa: SLF001
    assert summary["raw_payload"]["redacted"] is True
    assert summary["raw_payload"]["type"] == "dict"
    assert summary["raw_payload"]["count"] == 2
    assert summary["place_candidates"]["redacted"] is True
    assert summary["place_candidates"]["type"] == "list"
    assert summary["place_candidates"]["count"] == 2

    serialized = json.dumps(summary, sort_keys=True)
    assert "123 Main" not in serialized
    assert "coffee near home" not in serialized
    assert "driver@example.com" not in serialized
    assert "Home Garage" not in serialized
    assert "place-id" not in serialized


def test_append_command_event_does_not_write_unknown_arg_values(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    audit.append_command_event(
        tool_name="tescmd_navigation_send",
        operation="vehicle_command",
        command_name="navigation_request",
        stage="attempt",
        ok=None,
        args={
            "profile": "default",
            "region": "na",
            "vin": "5YJ3E1EA7JF000001",
            "confirm": True,
            "destination": "123 Main St, Anytown, CA",
            "nickname": "Home Garage",
            "nested": {"address": "456 Secret Ave", "location": {"lat": 37.1, "lon": -122.2}},
        },
    )

    raw = audit.audit_log_path().read_text(encoding="utf-8")
    event = json.loads(raw)

    assert event["confirm"] is True
    assert event["args"]["destination"] == "[REDACTED]"
    assert event["args"]["vin"] == "[REDACTED]"
    assert event["args"]["nickname"]["redacted"] is True
    assert event["args"]["nested"]["redacted"] is True
    assert event["target"]["suffix"] == "0001"
    assert "5YJ3E1EA7JF000001" not in raw
    assert "123 Main" not in raw
    assert "Home Garage" not in raw
    assert "456 Secret" not in raw
    assert "37.1" not in raw
