"""Preserve per-profile browser preferences across native Sync recovery."""

from __future__ import annotations

PROFILE_PREFERENCE_DEFAULTS = {"bookmark_bar": "new_tab", "confirm_close_tabs": True}

BOOKMARK_BAR_MODES = ("always", "new_tab", "never")


def bookmark_bar_mode(value: object) -> str:
    """Validate the public per-profile choice without echoing invalid input."""

    if not isinstance(value, str) or value not in BOOKMARK_BAR_MODES:
        raise ValueError("Browser bookmark_bar must be always, new_tab, or never")
    return value


def bookmark_bar_preferences(mode: str) -> dict[str, bool | int]:
    """Keep Brave's visibility, menu, and new-tab preferences consistent."""

    mode = bookmark_bar_mode(mode)
    return {
        "bookmark_bar.visibility_state": BOOKMARK_BAR_MODES.index(mode),
        "bookmark_bar.show_on_all_tabs": mode == "always",
        "brave.always_show_bookmark_bar_on_ntp": mode == "new_tab",
    }


def saved_bookmark_bar(preferences: dict) -> str | None:
    """Read an explicit local choice, leaving an unconfigured profile unmanaged."""

    settings = preferences.get("bookmark_bar", {})
    brave = preferences.get("brave", {})
    if not isinstance(settings, dict) or not isinstance(brave, dict):
        raise ValueError(  # noqa: TRY004 - Schema validation reports ValueError.
            "Expected browser bookmark-bar settings objects"
        )
    if "visibility_state" in settings:
        state = settings["visibility_state"]
        if not isinstance(state, int) or isinstance(state, bool) or not 0 <= state < len(BOOKMARK_BAR_MODES):
            raise ValueError("Invalid browser bookmark-bar visibility state")
        return BOOKMARK_BAR_MODES[state]
    # Brave Stable also stores choices made by its menu in these booleans.
    show = settings.get("show_on_all_tabs", False)
    ntp = brave.get("always_show_bookmark_bar_on_ntp", True)
    if not isinstance(show, bool) or not isinstance(ntp, bool):
        raise ValueError(  # noqa: TRY004 - Schema validation reports ValueError.
            "Invalid browser bookmark-bar visibility flags"
        )
    if "show_on_all_tabs" not in settings and "always_show_bookmark_bar_on_ntp" not in brave:
        return None
    return "always" if show else "new_tab" if ntp else "never"


def close_tabs_confirmation(value: object) -> bool:
    """Reject non-boolean declarations without confusing disabled with absent."""

    if not isinstance(value, bool):
        raise ValueError(  # noqa: TRY004 - Schema validation reports ValueError.
            "Browser confirm_close_tabs must be a boolean"
        )
    return value


def saved_close_tabs_confirmation(preferences: dict) -> bool | None:
    """Return only an explicit per-profile closing confirmation preference."""

    brave = preferences.get("brave", {})
    if not isinstance(brave, dict):
        raise ValueError(  # noqa: TRY004 - Schema validation reports ValueError.
            "Expected a browser settings object for brave"
        )
    if "enable_window_closing_confirm" not in brave:
        return None
    return close_tabs_confirmation(brave["enable_window_closing_confirm"])


def native_profile_preferences(choices: dict) -> dict[str, bool | int]:
    """Map supported, declared choices to Brave's native preference keys."""

    result = {}
    if choices.get("bookmark_bar") is not None:
        result.update(bookmark_bar_preferences(choices["bookmark_bar"]))
    if choices.get("confirm_close_tabs") is not None:
        result["brave.enable_window_closing_confirm"] = close_tabs_confirmation(choices["confirm_close_tabs"])
    return result


# Keep preference values inside the selected settings page. Only status booleans
# cross the debugging pipe, and policy-controlled values cannot be overwritten.
PROFILE_PREFERENCES_SCRIPT = r"""(async (expected, apply) => {
  const api = chrome.settingsPrivate;
  if (!api?.getPref || !api?.setPref) return {supported: false};
  const get = key => new Promise(resolve => api.getPref(key, pref => {
    const error = chrome.runtime.lastError;
    resolve(error ? null : pref);
  }));
  const set = (key, value) => new Promise(resolve => api.setPref(key, value, '', success => {
    const error = chrome.runtime.lastError;
    resolve(!error && success === true);
  }));
  const entries = await Promise.all(Object.entries(expected).map(async ([key, value]) =>
    ({key, value, pref: await get(key)})));
  // Require every requested setting except Brave's extra NTP flag, which is
  // optional when the native bookmark-bar UI uses the visibility enum alone.
  const required = entries.filter(entry => entry.key !== 'brave.always_show_bookmark_bar_on_ntp');
  if (required.some(entry => !entry.pref)) return {supported: false};
  const available = entries.filter(entry => entry.pref);
  if (available.some(({value, pref}) => typeof pref.value !== typeof value)) return {supported: false};
  const differing = available.filter(({value, pref}) => pref.value !== value);
  if (!apply || differing.length === 0) return {supported: true, matches: differing.length === 0, changed: false};
  if (differing.some(({pref}) => pref.enforcement === 'ENFORCED')) {
    return {supported: true, matches: false, changed: false};
  }
  for (const {key, value} of differing) {
    if (!await set(key, value)) return {supported: true, matches: false, changed: true};
  }
  const verified = await Promise.all(available.map(async ({key, value}) => (await get(key))?.value === value));
  return {supported: true, matches: verified.every(Boolean), changed: true};
})"""
