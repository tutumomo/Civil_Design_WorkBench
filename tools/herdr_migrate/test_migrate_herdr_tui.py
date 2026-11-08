#!/usr/bin/env python3
"""Self-test for migrate_herdr_tui.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import migrate_herdr_tui as m  # noqa: E402


failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name} {detail}")
        failures.append(name)


def app_commands() -> set[str]:
    out = subprocess.run(
        ["herdr-app", "commands"], capture_output=True, text=True, check=True
    ).stdout
    return {c["name"] for c in json.loads(out)}


def test_chord_conversion() -> None:
    check("prefix becomes ctrl-shift", m._legacy_chord("prefix+c") == "ctrl-shift-c")
    check(
        "prefix+shift stays single shift",
        m._legacy_chord("prefix+shift+n") == "ctrl-shift-n",
    )
    check("named minus becomes a character", m._legacy_chord("prefix+minus") == "ctrl-shift--")
    check("named question becomes a character", m._legacy_chord("prefix+?") == "ctrl-shift-?")
    check("direct chord keeps its modifiers", m._legacy_chord("cmd+alt+d") == "cmd-alt-d")
    check("modifier order is normalised", m._legacy_chord("shift+cmd+d") == "cmd-shift-d")
    check("arrows are kept", m._legacy_chord("prefix+left") == "ctrl-shift-left")


def test_program_chords_are_protected() -> None:
    # A chord written out in full is a stated intent: it is honoured, but the
    # cost to running programs is reported.
    cfg = {"keys": {"close_pane": "ctrl+c"}}
    keys, report = m.convert_keys(cfg)
    chords = keys.get("global", {})
    check("an explicit ctrl+c is honoured", chords.get("ctrl-c") == "pane.close")
    check(
        "the cost to programs is reported",
        any("belongs to the program" in r for r in report),
    )
    # A prefix binding never lands on a program chord: the prefix becomes
    # ctrl-shift, so the program keeps its ctrl+letter.
    cfg = {"keys": {"close_pane": "prefix+w"}}
    keys, _ = m.convert_keys(cfg)
    check("a prefix binding avoids program chords", "ctrl-shift-w" in keys["global"])


def test_defaults_are_left_alone() -> None:
    cfg = {"keys": {"new_tab": "prefix+c"}}
    keys, report = m.convert_keys(cfg)
    check("a default binding is not written", keys.get("global") == {})
    check("the skipped default is reported", any("defaults" in r for r in report))


def test_custom_bindings_are_converted() -> None:
    cfg = {"keys": {"new_tab": "prefix+t", "next_tab": "ctrl+alt+right"}}
    keys, _ = m.convert_keys(cfg)
    check("a custom prefix binding converts", keys["global"].get("ctrl-shift-t") == "tab.new")
    check("a custom direct chord converts", keys["global"].get("ctrl-alt-right") == "tab.next")


def test_settings_conversion() -> None:
    cfg = {
        "theme": {"name": "atom-one-dark", "custom": {"accent": "#ff0000", "panel_bg": "#00ff00"}},
        "ui": {"pane_scrollbars": False},
        "sound": {"enabled": True, "done_path": "a.mp3", "request_path": "b.mp3"},
    }
    settings, _ = m.convert_settings(cfg)
    check("a known theme carries over", settings.get("theme") == "atom-one-dark")
    check("accent carries over", settings["colors"].get("accent") == "#ff0000")
    check("panel_bg maps to surface", settings["colors"].get("surface") == "#00ff00")
    check("pane_scrollbars carries over", settings.get("pane_scrollbars") is False)
    check("sound enabled carries over", settings["sounds"]["enabled"] is True)
    check("done sound carries over", settings["sounds"]["done"] == "a.mp3")
    check("request sound maps to blocked", settings["sounds"]["blocked"] == "b.mp3")


def test_unknown_theme_is_reported() -> None:
    settings, report = m.convert_settings({"theme": {"name": "catppuccin"}})
    check("an unknown theme is not set", "theme" not in settings)
    check("an unknown theme is reported", any("catppuccin" in r for r in report))


def test_every_mapped_action_is_a_real_command() -> None:
    commands = app_commands()
    bad = [
        (name, cmd)
        for name, (cmd, _) in m.ACTION_MAP.items()
        if cmd.split(":")[0] not in commands
    ]
    check("every mapped action is a real app command", not bad, str(bad))


def test_end_to_end_write() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        legacy = tmp_path / "config.toml"
        legacy.write_text(
            '[keys]\nprefix = "ctrl+b"\nnew_tab = "prefix+t"\n', encoding="utf-8"
        )
        app_home = tmp_path / "app"
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "migrate_herdr_tui.py"),
                str(legacy),
                "--app-home",
                str(app_home),
                "--apply",
            ],
            capture_output=True,
            text=True,
        )
        check("the run succeeds", result.returncode == 0, result.stderr)
        keys = json.loads((app_home / "keys.json").read_text(encoding="utf-8"))
        check("keys.json was written", keys["global"].get("ctrl-shift-t") == "tab.new")
        check("settings.json was written", (app_home / "settings.json").is_file())


def main() -> int:
    test_chord_conversion()
    test_program_chords_are_protected()
    test_defaults_are_left_alone()
    test_custom_bindings_are_converted()
    test_settings_conversion()
    test_unknown_theme_is_reported()
    test_every_mapped_action_is_a_real_command()
    test_end_to_end_write()
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
