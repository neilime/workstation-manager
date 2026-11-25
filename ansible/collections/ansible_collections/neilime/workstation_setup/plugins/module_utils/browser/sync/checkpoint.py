"""Fresh per-type download evidence, separate from application and upload checks."""

from __future__ import annotations

import re


class DownloadCheckpoint:
    """Match fresh request/response pairs without treating a download as restored data."""

    def __init__(self, expected_types: list[int]) -> None:
        self.expected = self._types(expected_types)
        if not self.expected:
            raise ValueError("A download checkpoint requires data types")
        self.completed: set[int] = set()
        self.downloaded: set[int] = set()
        self.requested: set[int] | None = None
        self.generation: str | None = None

    def consume(self, packet: object) -> None:
        """Discard evidence from a replaced observer and reject lost protocol events."""

        if (
            not isinstance(packet, dict)
            or set(packet) != {"available", "events", "generation"}
            or packet["available"] is not True
            or not isinstance(packet["events"], list)
            or not isinstance(packet["generation"], str)
        ):
            raise ValueError("Download checkpoint observation was lost")
        if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", packet["generation"]):
            raise ValueError("Download checkpoint generation is unsupported")
        if packet["generation"] != self.generation:
            self.completed.clear()
            self.downloaded.clear()
            self.requested = None
            self.generation = packet["generation"]
        for event in packet["events"]:
            self.observe(event)

    @staticmethod
    def _types(value: object) -> set[int]:
        if not isinstance(value, list) or any(
            not isinstance(item, int) or isinstance(item, bool) or not 0 < item < 2**29 for item in value
        ):
            raise ValueError("Unsupported checkpoint data types")
        if len(value) != len(set(value)):
            raise ValueError("Ambiguous checkpoint data types")
        return set(value)

    @property
    def complete(self) -> bool:
        """Report download and dispatch coverage; model, installation, and upload checks remain separate."""

        return self.expected <= self.completed

    def observe(self, event: object) -> None:
        """Reject ambiguous or unsupported evidence without exposing its contents."""

        if not isinstance(event, dict):
            raise ValueError("Unsupported checkpoint event")  # noqa: TRY004 - Invalid native schema.
        kind = event.get("kind")
        if kind == "applied" and set(event) == {"kind", "types"}:
            applied = self._types(event["types"]) & self.expected
            if not applied <= self.downloaded:
                raise ValueError("Unmatched download application evidence")
            self.completed.update(applied)
            return
        if kind == "request" and set(event) == {"kind", "types"}:
            requested = self._types(event["types"])
            if self.requested is not None or not requested:
                raise ValueError("Ambiguous checkpoint request ordering")
            self.requested = requested
            return
        if kind != "response" or set(event) != {"kind", "types", "remaining", "success"}:
            raise ValueError("Unsupported checkpoint event")
        returned = self._types(event["types"])
        if (
            not isinstance(event["success"], bool)
            or not isinstance(event["remaining"], int)
            or isinstance(event["remaining"], bool)
            or not 0 <= event["remaining"] <= 2**53 - 1
        ):
            raise ValueError("Unsupported checkpoint response")
        pending, self.requested = self.requested, None
        # Observer registration can replay a response whose request preceded it.
        if pending is None:
            return
        affected = pending & self.expected
        if event["success"] and event["remaining"] == 0 and pending <= returned:
            self.downloaded.update(affected)
        else:
            self.downloaded.difference_update(affected)
            self.completed.difference_update(affected)


DOWNLOAD_OBSERVER = r"""(() => {
  if (!window.workstationSyncSettings) return false;
  const callbacks = window.workstationSyncSettings;
  if (window.workstationCheckpoint?.listener) callbacks.removeWebUiListener(window.workstationCheckpoint.listener);
  const state = window.workstationCheckpoint = {
    since: Date.now(), events: [], overflow: false, generation: crypto.randomUUID(),
    requested: null, markers: new Map(), applied: new Set()
  };
  const emit = event => {
    if (state.events.length >= 128) state.overflow = true;
    else state.events.push(event);
  };
  const ids = markers => {
    if (!Array.isArray(markers)) return null;
    // Chromium's diagnostic serializer represents protobuf integers as strings.
    const values = markers.map(marker => {
      const raw = marker?.data_type_id;
      return typeof raw === 'string' && /^\d+$/.test(raw) ? Number(raw) : null;
    });
    if (values.some(value => !Number.isInteger(value) || value <= 0 || value >= 2 ** 29)
        || new Set(values).size !== values.length) return null;
    return values;
  };
  state.listener = callbacks.addWebUiListener('onProtocolEvent', event => {
    if (typeof event.time !== 'number' || event.time <= state.since) return;
    let reduced;
    // The native visitor omits message_contents; request markers distinguish
    // download requests from responses without depending on display labels.
    if (event.proto?.get_updates && Object.hasOwn(event.proto.get_updates, 'from_progress_marker')) {
      const markers = event.proto.get_updates.from_progress_marker;
      const types = ids(markers);
      if (types && state.requested === null) {
        // The following request must use the preceding final response's markers.
        // This crosses the engine's update-dispatch boundary. Model queries made
        // after it queue behind those dispatched updates on each model sequence.
        const applied = markers.filter(marker => state.markers.has(Number(marker.data_type_id))
          && marker.token === state.markers.get(Number(marker.data_type_id)))
          .map(marker => Number(marker.data_type_id));
        if (applied.length) {
          emit({kind: 'applied', types: applied});
          applied.forEach(type => { state.applied.add(type); state.markers.delete(type); });
        }
      }
      state.requested = types;
      reduced = {kind: 'request', types};
    } else if (event.type === 'GetUpdates Response') {
      const success = /^Received \d+ update\(s\)\.( Some updates remain\.)?$/.test(event.details);
      const updates = event.proto?.get_updates;
      const raw = updates?.changes_remaining;
      const remaining = /^\d+$/.test(String(raw)) ? Number(raw) : null;
      reduced = {kind: 'response', success,
        types: success ? ids(updates?.new_progress_marker) : [],
        remaining: success && Number.isSafeInteger(remaining) ? remaining : success ? null : 0};
      const requested = state.requested;
      state.requested = null;
      if (requested) {
        if (success && remaining === 0 && reduced.types && requested.every(type => reduced.types.includes(type))) {
          for (const marker of updates.new_progress_marker) {
            const type = Number(marker.data_type_id);
            if (requested.includes(type) && !state.applied.has(type)
                && typeof marker.token === 'string' && marker.token) {
              state.markers.set(type, marker.token);
            }
          }
        } else {
          requested.forEach(type => { state.applied.delete(type); state.markers.delete(type); });
        }
      }
    }
    if (reduced) {
      emit(reduced);
      if (reduced.kind === 'response' && state.markers.size) chrome.send('triggerRefresh');
    }
  });
  return true;
})()"""

READ_DOWNLOAD_EVENTS = """(() => {
  const state = window.workstationCheckpoint;
  if (!state || state.overflow) return {available: false, events: [], generation: null};
  return {available: true, events: state.events.splice(0), generation: state.generation};
})()"""
