#!/usr/bin/env python3
"""Migrate a legacy Herdr TUI config.toml into Herdr App's JSON config.

The legacy terminal app (herdrdev/herdr) read ~/.config/herdr/config.toml.
Herdr App (herdrdev/herdr-app) reads ~/.config/herdr-app/{keys.json,settings.json}.
This script reads the old TOML and writes the new JSON files.

Usage:
    python3 tools/herdr_migrate/migrate_herdr_tui.py <legacy-config.toml> [--apply]

Without --apply it prints the proposed keys.json / settings.json plus a report
of what could not be mapped, and writes nothing.

Two rules drive the conversion:

* The legacy app used a prefix (Ctrl-B by default). Herdr App has no prefix
  mode, so "prefix+X" becomes a direct chord that keeps the same letter.
* Plain Ctrl+letter chords belong to the running program, not to Herdr. The
  legacy prefix meant a chord was unambiguous; without a prefix it is not.
  Those bindings move to Ctrl+Shift instead of stealing the program's keys.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any


def _legacy_chord(action: str) -> str | None:
    """Turn one legacy binding into a direct chord, or None if unmappable.

    "prefix+X" becomes "ctrl-shift-X": the prefix is Ctrl-B, and Ctrl-B
    alone is a program key, so the chord needs a second modifier to stay
    unambiguous.
    """
    action = action.strip()
    if not action:
        return None
    if action.startswith("prefix+"):
        rest = action[len("prefix+") :]
        if rest.startswith("shift+"):
            rest = rest[len("shift+") :]
            key = LEGACY_KEY_NAMES.get(rest, rest)
            return f"ctrl-shift-{key}"
        key = LEGACY_KEY_NAMES.get(rest, rest)
        return f"ctrl-shift-{key}"
    if "+" in action:
        parts = action.split("+")
        mods = parts[:-1]
        key = parts[-1]
        ordered = [m for m in ("cmd", "ctrl", "alt", "shift") if m in mods]
        key = LEGACY_KEY_NAMES.get(key, key)
        return "-".join([*ordered, key]) if ordered else key
    return LEGACY_KEY_NAMES.get(action, action)


# The legacy app named punctuation ("prefix+minus"); Herdr App writes the
# character itself ("ctrl-shift--"), the way its own default keys do.
LEGACY_KEY_NAMES = {
    "minus": "-",
    "plus": "+",
    "comma": ",",
    "period": ".",
    "equal": "=",
    "dot": ".",
    "question": "?",
    "slash": "/",
    "backslash": "\\",
    "semicolon": ";",
    "quote": "'",
    "backtick": "`",
    "space": "space",
}


# Chords a running program owns. Binding these in the global section would
# take them away from whatever is running in the focused terminal.
PROGRAM_CHORDS = {
    "ctrl-a",
    "ctrl-c",
    "ctrl-d",
    "ctrl-e",
    "ctrl-k",
    "ctrl-l",
    "ctrl-r",
    "ctrl-u",
    "ctrl-w",
    "ctrl-z",
}


# The legacy app's own defaults. A binding still at its default is not a
# personal choice, so it is left to Herdr App's defaults instead of being
# written out.
LEGACY_DEFAULTS = {
    "help": "prefix+?",
    "settings": "prefix+s",
    "new_workspace": "prefix+shift+n",
    "new_worktree": "prefix+shift+g",
    "rename_workspace": "prefix+shift+w",
    "close_workspace": "prefix+shift+d",
    "workspace_picker": "prefix+w",
    "goto": "prefix+g",
    "navigate_workspace_up": "up",
    "navigate_workspace_down": "down",
    "navigate_pane_left": "h",
    "navigate_pane_down": "j",
    "navigate_pane_up": "k",
    "navigate_pane_right": "l",
    "detach": "prefix+q",
    "reload_config": "prefix+shift+r",
    "open_notification_target": "prefix+o",
    "new_tab": "prefix+c",
    "rename_tab": "prefix+shift+t",
    "previous_tab": "prefix+p",
    "next_tab": "prefix+n",
    "switch_tab": "prefix+1..9",
    "close_tab": "prefix+shift+x",
    "rename_pane": "prefix+shift+p",
    "edit_scrollback": "prefix+e",
    "copy_mode": "prefix+[",
    "focus_pane_left": "prefix+h",
    "focus_pane_down": "prefix+j",
    "focus_pane_up": "prefix+k",
    "focus_pane_right": "prefix+l",
    "swap_pane_left": "prefix+shift+h",
    "swap_pane_down": "prefix+shift+j",
    "swap_pane_up": "prefix+shift+k",
    "swap_pane_right": "prefix+shift+l",
    "cycle_pane_next": "prefix+tab",
    "cycle_pane_previous": "prefix+shift+tab",
    "split_vertical": "prefix+v",
    "split_horizontal": "prefix+minus",
    "close_pane": "prefix+x",
    "zoom": "prefix+z",
    "resize_mode": "prefix+r",
    "toggle_sidebar": "prefix+b",
}


# Legacy action name -> (Herdr App command, section).
# "global" is the app window; "terminal" applies while a terminal has focus.
ACTION_MAP: dict[str, tuple[str, str]] = {
    # workspaces <-> spaces
    "new_workspace": ("space.new", "global"),
    "rename_workspace": ("space.rename", "global"),
    "close_workspace": ("space.close", "global"),
    "previous_workspace": ("space.prev", "global"),
    "next_workspace": ("space.next", "global"),
    # tabs
    "new_tab": ("tab.new", "global"),
    "rename_tab": ("tab.rename", "global"),
    "close_tab": ("tab.close", "global"),
    "previous_tab": ("tab.prev", "global"),
    "next_tab": ("tab.next", "global"),
    # panes
    "split_vertical": ("pane.split:right", "global"),
    "split_horizontal": ("pane.split:down", "global"),
    "close_pane": ("pane.close", "global"),
    "zoom": ("pane.zoom", "global"),
    "focus_pane_left": ("pane.go:left", "global"),
    "focus_pane_right": ("pane.go:right", "global"),
    "focus_pane_up": ("pane.go:up", "global"),
    "focus_pane_down": ("pane.go:down", "global"),
    "swap_pane_left": ("pane.swap:left", "global"),
    "swap_pane_right": ("pane.swap:right", "global"),
    "swap_pane_up": ("pane.swap:up", "global"),
    "swap_pane_down": ("pane.swap:down", "global"),
    # agents / notifications
    "previous_agent": ("agent.prev", "global"),
    "next_agent": ("agent.next", "global"),
    # misc
    "help": ("app.help", "global"),
    "settings": ("app.settings", "global"),
}


# Legacy actions with no Herdr App equivalent.
UNSUPPORTED_ACTIONS = {
    "workspace_picker": "Herdr App uses the command palette (app.palette) instead.",
    "goto": "Herdr App uses the command palette (app.palette) instead.",
    "reload_config": "Herdr App reads its JSON config live; there is nothing to reload.",
    "detach": "Herdr App has no detach; closing the window keeps terminals alive.",
    "new_worktree": "Herdr App has a worktree mod; bind it as a mod action.",
    "open_worktree": "Herdr App has a worktree mod; bind it as a mod action.",
    "remove_worktree": "Herdr App has a worktree mod; bind it as a mod action.",
    "edit_scrollback": "No Herdr App command opens scrollback in $EDITOR.",
    "clear_pane": "No Herdr App command clears a pane's scrollback.",
    "copy_mode": "Herdr App copies with the mouse or Cmd-C; there is no copy mode.",
    "last_pane": "No Herdr App command focuses the last pane across spaces.",
    "focus_agent": "Needs a terminal id; Herdr App has no index-based agent jump.",
    "switch_tab": "Indexed jump; bind the number keys individually.",
    "switch_workspace": "Indexed jump; bind the number keys individually.",
    "resize_mode": "Herdr App has no resize mode.",
    "resize_pane_left": "No Herdr App command resizes a pane.",
    "resize_pane_right": "No Herdr App command resizes a pane.",
    "resize_pane_up": "No Herdr App command resizes a pane.",
    "resize_pane_down": "No Herdr App command resizes a pane.",
    "toggle_sidebar": "Herdr App toggles the sidebar with the layout toggle.",
    "cycle_pane_next": "Herdr App moves between panes with pane.go.",
    "cycle_pane_previous": "Herdr App moves between panes with pane.go.",
    "rename_pane": "No Herdr App command renames a pane.",
    "open_notification_target": "Notifications live in the agent list.",
    "remote_image_paste": "The terminal section handles clipboard images.",
}


# Legacy [ui] setting -> Herdr App settings.json key.
# Only settings that exist in the App's Person struct are listed; the rest are
# reported as having no equivalent.
SETTINGS_MAP: dict[str, str] = {
    "ui.pane_scrollbars": "pane_scrollbars",
}


# The App's built-in theme names, and the legacy names that map onto them.
APP_THEME_NAMES = {"graphite", "ink", "moss", "paper", "atom-one-dark", "win98"}
LEGACY_THEME_ALIASES = {
    "catppuccin": None,
    "catppuccin-latte": None,
    "dracula": None,
    "nord": None,
    "gruvbox": None,
    "gruvbox-light": None,
    "one-dark": "atom-one-dark",
    "one-light": None,
    "solarized": None,
    "solarized-light": None,
    "kanagawa": None,
    "kanagawa-lotus": None,
    "rose-pine": None,
    "rose-pine-dawn": None,
    "vesper": None,
    "tokyo-night": None,
    "tokyo-night-day": None,
    "terminal": None,
}


# Legacy [theme.custom] token -> Herdr App theme token. The App's token names
# are its own (see `theme()` in herdr.d.ts); these are the ones that carry over.
COLOR_MAP: dict[str, str] = {
    "accent": "accent",
    "panel_bg": "surface",
    "sidebar_bg": "chrome",
    "active_row_bg": "selected",
    "selection_bg": "selection",
    "text": "foreground",
    "subtext0": "muted",
}


def _dig(data: dict[str, Any], dotted: str) -> Any:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def convert_keys(cfg: dict[str, Any]) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Build Herdr App keys.json from the legacy [keys] table."""
    legacy_keys = cfg.get("keys")
    if not isinstance(legacy_keys, dict):
        return {}, ["No [keys] table in the legacy config; the App's defaults stay as they are."]

    sections: dict[str, dict[str, str]] = {"global": {}}
    report: list[str] = []
    defaults_used = 0
    taken = _existing_bindings()

    for action, raw in legacy_keys.items():
        if action in {"prefix", "indexed", "command"}:
            continue
        bindings = _as_list(raw)
        if not bindings:
            continue

        # A binding the user never changed is not a personal preference; leave
        # it to Herdr App's defaults so the App keeps its own (better) map.
        if LEGACY_DEFAULTS.get(action) in bindings:
            defaults_used += 1
            continue

        target = ACTION_MAP.get(action)
        if target is None:
            note = UNSUPPORTED_ACTIONS.get(action, "no Herdr App equivalent.")
            report.append(f"skipped {action}: {note}")
            continue
        command, section = target
        for binding in bindings:
            chord = _legacy_chord(binding)
            if chord is None:
                continue
            if not chord.startswith(("cmd-", "ctrl-", "alt-", "shift-")):
                report.append(
                    f"skipped {action} = {binding!r}: a bare key would intercept typing."
                )
                continue
            if chord in PROGRAM_CHORDS:
                # The person wrote this chord out in full, so it is a stated
                # intent, not a leftover from the prefix. It is honoured, but
                # it costs every program in every terminal its Ctrl-<letter>,
                # so say so plainly.
                report.append(
                    f"warning: {action} = {binding!r} was bound anyway, but "
                    f"{chord} belongs to the program running in the terminal. "
                    "Programs lose it while this binding exists; remove the line "
                    "from keys.json if that was not meant."
                )
            chord = _free_chord(chord, taken)
            if chord is None:
                report.append(
                    f"skipped {action} = {binding!r}: every candidate chord is already "
                    "taken in Herdr App."
                )
                continue
            if chord != _legacy_chord(binding):
                report.append(
                    f"note: {action} = {binding!r} moved to {chord!r}; the first choice "
                    "was already used by Herdr App."
                )
            sections.setdefault(section, {})[chord] = command
            taken.add(chord)

    prefix_values = _as_list(legacy_keys.get("prefix"))
    if len(prefix_values) > 1:
        report.append(
            "note: the legacy config had several prefixes "
            f"({', '.join(prefix_values)}); only the first was carried over."
        )
    if defaults_used:
        report.append(
            f"note: {defaults_used} binding(s) were still at the legacy defaults and "
            "were left to Herdr App's own defaults."
        )

    for action in ("switch_tab", "switch_workspace", "focus_agent"):
        raw = legacy_keys.get(action)
        if isinstance(raw, str) and ".." in raw:
            report.append(
                f"note: {action} = {raw!r} is an index range; "
                "Herdr App binds these as individual number keys."
            )

    custom = legacy_keys.get("command")
    if isinstance(custom, list) and custom:
        report.append(
            f"note: {len(custom)} legacy custom command binding(s) were not converted; "
            "add them by hand to keys.json (they run shell commands, which Herdr App "
            "does not do from a key)."
        )

    return sections, report


def _existing_bindings() -> set[str]:
    """The chords Herdr App already uses, so a migrated one does not clash."""
    path = Path.home() / ".config" / "herdr-app" / "keys.json"
    taken: set[str] = set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return taken
    if not isinstance(data, dict):
        return taken
    for section in data.values():
        if isinstance(section, dict):
            taken.update(k for k in section if isinstance(k, str))
    return taken


def _free_chord(chord: str, taken: set[str]) -> str | None:
    """The chord itself, or a less crowded variant, or None if none is free."""
    if chord not in taken:
        return chord
    parts = chord.split("-")
    if len(parts) < 2:
        return None
    key = parts[-1]
    for mods in (["ctrl", "alt"], ["cmd", "alt"], ["ctrl", "alt", "shift"]):
        candidate = "-".join([*mods, key])
        if candidate not in taken:
            return candidate
    return None


def convert_settings(cfg: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Build Herdr App settings.json from the legacy config."""
    settings: dict[str, Any] = {}
    report: list[str] = []

    theme = cfg.get("theme") if isinstance(cfg.get("theme"), dict) else {}
    name = theme.get("name")
    if isinstance(name, str) and name:
        key = name.strip().lower().replace("_", "-").replace(" ", "-")
        if key in APP_THEME_NAMES:
            settings["theme"] = key
        elif key in LEGACY_THEME_ALIASES:
            report.append(
                f"note: the legacy theme {name!r} has no Herdr App equivalent "
 f"(the App ships {', '.join(sorted(APP_THEME_NAMES))}); "
                "it was not carried over. Pick one in Settings > Look."
            )
        else:
            report.append(
                f"note: the legacy theme {name!r} is not a Herdr App theme; "
                "it was not carried over."
            )

    # A legacy theme that switched with the system becomes an App theme pair.
    dark_name = theme.get("dark_name")
    light_name = theme.get("light_name")
    if theme.get("auto_switch") is True and isinstance(dark_name, str) and isinstance(light_name, str):
        dark_key = dark_name.strip().lower().replace("_", "-")
        light_key = light_name.strip().lower().replace("_", "-")
        if dark_key in APP_THEME_NAMES and light_key in APP_THEME_NAMES:
            settings["theme"] = {"light": light_key, "dark": dark_key}
        else:
            report.append(
                "note: theme.auto_switch has no Herdr App equivalent; "
                "set appearance to light or dark, or a theme pair, in settings.json."
            )

    custom = theme.get("custom")
    if isinstance(custom, dict):
        colors = {
            COLOR_MAP[k]: v
            for k, v in custom.items()
            if isinstance(v, str) and k in COLOR_MAP
        }
        if colors:
            settings["colors"] = colors
        dropped = [
            k
            for k, v in custom.items()
            if isinstance(v, str) and k not in COLOR_MAP
        ]
        if dropped:
            report.append(
                "note: these legacy theme colours have no Herdr App token and were "
                f"left behind: {', '.join(sorted(dropped))}."
            )

    for legacy_path, app_path in SETTINGS_MAP.items():
        value = _dig(cfg, legacy_path)
        if value is not None:
            settings[app_path] = value

    sound = cfg.get("sound") if isinstance(cfg.get("sound"), dict) else {}
    if "enabled" in sound:
        sounds: dict[str, Any] = {"enabled": bool(sound["enabled"])}
        done = sound.get("done_path")
        blocked = sound.get("request_path")
        if isinstance(done, str) and done:
            sounds["done"] = done
        if isinstance(blocked, str) and blocked:
            sounds["blocked"] = blocked
        settings["sounds"] = sounds

    ignored = []
    for path in (
        "ui.sidebar_width",
        "ui.sidebar_min_width",
        "ui.sidebar_max_width",
        "ui.sidebar_start_collapsed",
        "ui.sidebar_collapsed_mode",
        "ui.mobile_width_threshold",
        "ui.mouse_capture",
        "ui.copy_on_select",
        "ui.host_cursor",
        "ui.right_click_passthrough_modifier",
        "ui.redraw_on_focus_gained",
        "ui.mouse_scroll_lines",
        "ui.confirm_close",
        "ui.prompt_new_tab_name",
        "ui.prompt_new_workspace_name",
        "ui.pane_borders",
        "ui.pane_outer_borders",
        "ui.pane_gaps",
        "ui.show_agent_labels_on_pane_borders",
        "ui.hide_tab_bar_when_single_tab",
        "ui.tab_bar_position",
        "ui.tab_bar_right",
        "ui.tab_bar_right_separator",
        "ui.window_title",
        "ui.agent_panel_sort",
        "ui.status_indicators",
        "terminal.default_shell",
        "terminal.shell_mode",
        "terminal.new_cwd",
        "terminal.kitty_graphics",
        "worktrees.directory",
        "server.headless_cols",
        "server.headless_rows",
        "session.resume_agents_on_restore",
        "session.startup_per_agent_delay_ms",
        "remote.manage_ssh_config",
    ):
        if _dig(cfg, path) is not None:
            ignored.append(path)
    if ignored:
        report.append(
            "note: these legacy settings have no Herdr App equivalent and were "
            f"left behind: {', '.join(sorted(ignored))}."
        )

    return settings, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="legacy ~/.config/herdr/config.toml")
    parser.add_argument(
        "--app-home",
        type=Path,
        default=Path.home() / ".config" / "herdr-app",
        help="Herdr App home (default: ~/.config/herdr-app)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write keys.json and settings.json (otherwise only print)",
    )
    args = parser.parse_args()

    if not args.config.is_file():
        print(f"error: {args.config} does not exist", file=sys.stderr)
        return 2

    with args.config.open("rb") as handle:
        cfg = tomllib.load(handle)

    keys, key_report = convert_keys(cfg)
    settings, settings_report = convert_settings(cfg)
    report = key_report + settings_report

    print(f"legacy config : {args.config}")
    print(f"app home      : {args.app_home}")
    print()
    print("--- keys.json ---")
    print(json.dumps(keys, indent=2, ensure_ascii=False))
    print()
    print("--- settings.json ---")
    print(json.dumps(settings, indent=2, ensure_ascii=False))
    print()
    if report:
        print("--- notes ---")
        for line in report:
            print(f"  - {line}")
        print()

    if not args.apply:
        print("Dry run. Re-run with --apply to write the files.")
        return 0

    app_home: Path = args.app_home
    app_home.mkdir(parents=True, exist_ok=True)
    for name, payload in (("keys.json", keys), ("settings.json", settings)):
        target = app_home / name
        if target.exists():
            backup = target.with_suffix(target.suffix + ".before-migrate")
            backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"backed up {target} -> {backup}")
            if name == "keys.json":
                # Merge into the existing file: Herdr App's own bindings stay,
                # and the migrated ones are added next to them.
                try:
                    existing = json.loads(target.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    existing = {}
                if not isinstance(existing, dict):
                    existing = {}
                for section, bindings in payload.items():
                    merged = dict(existing.get(section, {}))
                    merged.update(bindings)
                    existing[section] = merged
                payload = existing
        target.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
