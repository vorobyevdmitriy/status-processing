from datetime import datetime

from ..domain_context import build_event_context, same_non_empty_text


class CmaCgmChainContextMixin:

    def _is_same_vessel_or_voyage(self, prev_event, event):
        return (
            same_non_empty_text(prev_event.get("vessel"), event.get("vessel"))
            or same_non_empty_text(prev_event.get("voyage"), event.get("voyage"))
        )


    @staticmethod
    def _is_valid_event_datetime(value):
        if value is None:
            return False
        raw = str(value).strip()
        if not raw or raw == "\\N":
            return False
        return True


    @staticmethod
    def _is_blank_text(value):
        if value is None:
            return True
        raw = str(value).strip()
        return not raw or raw == "\\N"


    def _has_empty_transport_ref(self, event):
        return self._is_blank_text(event.get("vessel")) and self._is_blank_text(
            event.get("voyage")
        )


    def _is_immediately_before_raw_barge(self, ordered_events, chain_ctx, idx):
        next_idx = idx + 1
        raw_statuses = chain_ctx["raw_statuses"]
        if next_idx >= len(raw_statuses):
            return False
        if raw_statuses[next_idx] == "barge arrival":
            return True
        if raw_statuses[next_idx] == "barge departure":
            return self._same_location_idx(ordered_events[idx], ordered_events[next_idx])
        return False


    def _is_after_raw_barge_for_discharge(self, ordered_events, chain_ctx, idx):
        prev_idx = idx - 1
        if prev_idx < 0:
            return False
        prev_raw = chain_ctx["raw_statuses"][prev_idx]
        if prev_raw == "barge arrival":
            return self._same_location_idx(ordered_events[prev_idx], ordered_events[idx])
        return prev_raw == "barge departure"


    @staticmethod
    def _rows_equal_except_duplicate_meta(left, right):
        excluded = {
            "event_date",
            "event_actual",
            "event_pos",
            "_event_pos_int",
        }
        keys = set(left.keys()) | set(right.keys())
        for key in keys:
            if key in excluded:
                continue
            if key.startswith("_"):
                continue
            if str(left.get(key, "")) != str(right.get(key, "")):
                return False
        return True


    @staticmethod
    def _parse_event_datetime(value):
        raw = str(value or "").strip()
        if not raw or raw == "\\N":
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            return None


    def _is_sandwiched_different_vessel_event(self, prev_event, event, next_event):
        if self.parse_nullable_int(event.get("event_actual")) != 1:
            return False
        if not same_non_empty_text(prev_event.get("vessel"), next_event.get("vessel")):
            return False
        if same_non_empty_text(prev_event.get("vessel"), event.get("vessel")):
            return False

        prev_dt = self._parse_event_datetime(prev_event.get("event_date"))
        cur_dt = self._parse_event_datetime(event.get("event_date"))
        next_dt = self._parse_event_datetime(next_event.get("event_date"))
        if prev_dt is None or cur_dt is None or next_dt is None:
            return False

        return prev_dt <= cur_dt <= next_dt


    def _same_location_idx(self, left, right):
        left_loc = self.parse_nullable_int(left.get("event_location_idx"))
        right_loc = self.parse_nullable_int(right.get("event_location_idx"))
        return left_loc is not None and right_loc is not None and left_loc == right_loc


    def _has_prior_same_vessel_marine_event(self, ordered_events, idx):
        event = ordered_events[idx]
        for prev_idx in range(idx - 1, -1, -1):
            prev_event = ordered_events[prev_idx]
            prev_status = self.normalize_status(prev_event.get("event_status", ""))
            if prev_status not in self.MARINE_RAW_STATUSES:
                continue
            if same_non_empty_text(prev_event.get("vessel"), event.get("vessel")):
                return True
        return False


    def _has_future_load_handoff_at_same_location(self, ordered_events, idx):
        event = ordered_events[idx]
        for next_idx in range(idx + 1, len(ordered_events)):
            next_event = ordered_events[next_idx]
            next_status = self.normalize_status(next_event.get("event_status", ""))
            if next_status != "loaded on board":
                continue
            if not self._same_location_idx(event, next_event):
                continue
            if same_non_empty_text(event.get("vessel"), next_event.get("vessel")):
                continue
            return True
        return False


    def _is_transshipment_handoff_discharge(self, ordered_events, idx, event_at_pod):
        event = ordered_events[idx]
        if self.normalize_status(event.get("event_status", "")) != "discharged in transhipment":
            return False
        if event_at_pod:
            return False
        return (
            self._has_prior_same_vessel_marine_event(ordered_events, idx)
            and self._has_future_load_handoff_at_same_location(ordered_events, idx)
        )


    def _has_intervening_foreign_load_before_same_vessel_arrival(self, ordered_events, idx):
        departure_event = ordered_events[idx]
        seen_foreign_load = False
        for later_idx in range(idx + 1, len(ordered_events)):
            later_event = ordered_events[later_idx]
            later_status = self.normalize_status(later_event.get("event_status", ""))
            if later_status == "loaded on board" and not self._is_same_vessel_or_voyage(
                departure_event, later_event
            ):
                seen_foreign_load = True
                continue
            if later_status == "vessel arrival" and self._is_same_vessel_or_voyage(
                departure_event, later_event
            ):
                return seen_foreign_load
        return False


    def _has_previous_foreign_load_or_departure(self, ordered_events, idx):
        event = ordered_events[idx]
        for prev_idx in range(idx - 1, -1, -1):
            prev_event = ordered_events[prev_idx]
            prev_status = self.normalize_status(prev_event.get("event_status", ""))
            if prev_status not in {"loaded on board", "vessel departure"}:
                continue
            return not self._is_same_vessel_or_voyage(prev_event, event)
        return False


    def _is_stale_planned_event(self, event):
        event_dt = self._parse_event_datetime(event.get("event_date"))
        snapshot_dt = self._parse_event_datetime(event.get("timestamp"))
        if event_dt is None or snapshot_dt is None:
            return False
        return snapshot_dt >= event_dt


    def _is_matching_actual_duplicate(self, left, right):
        if self.normalize_status(left.get("event_status", "")) != self.normalize_status(
            right.get("event_status", "")
        ):
            return False
        if self.parse_nullable_int(right.get("event_actual")) != 1:
            return False
        return self._rows_equal_except_duplicate_meta(left, right)


    def _should_force_non_actual_duplicate_unk(self, ordered_events, idx):
        cur = ordered_events[idx]
        if self.parse_nullable_int(cur.get("event_actual")) != 0:
            return False
        if not self._is_stale_planned_event(cur):
            return False

        prev_event = ordered_events[idx - 1] if idx > 0 else None
        next_event = ordered_events[idx + 1] if idx + 1 < len(ordered_events) else None

        if prev_event is not None and self._is_matching_actual_duplicate(cur, prev_event):
            return True
        if next_event is not None and self._is_matching_actual_duplicate(cur, next_event):
            return True

        return False


    def _is_departure_before_loaded(self, departure_event, loaded_event):
        departure_dt = self._parse_event_datetime(departure_event.get("event_date"))
        loaded_dt = self._parse_event_datetime(loaded_event.get("event_date"))
        if departure_dt is None or loaded_dt is None:
            return False
        return loaded_dt > departure_dt


    def _find_historical_outlier_indices(self, ordered_events):
        parsed_dates = [
            self._parse_event_datetime(event.get("event_date"))
            for event in ordered_events
        ]
        outlier_indices = set()
        for idx, event_dt in enumerate(parsed_dates):
            if event_dt is None or event_dt >= self.HISTORICAL_OUTLIER_CUTOFF:
                continue
            other_dates = [
                other_dt for other_idx, other_dt in enumerate(parsed_dates)
                if other_idx != idx and other_dt is not None
            ]
            if not other_dates:
                continue
            if all(
                self.FRESH_CONTEXT_START <= other_dt < self.FRESH_CONTEXT_END
                for other_dt in other_dates
            ):
                outlier_indices.add(idx)
        return outlier_indices


    def _has_later_same_vessel_loaded_after_departure(self, ordered_events, idx):
        departure_event = ordered_events[idx]
        for later_idx in range(idx + 1, len(ordered_events)):
            later_event = ordered_events[later_idx]
            later_status = self.normalize_status(later_event.get("event_status", ""))
            if later_status != "loaded on board":
                continue
            if not self._is_same_vessel_or_voyage(departure_event, later_event):
                continue
            if self._is_departure_before_loaded(departure_event, later_event):
                return True
        return False


    def _build_chain_context(self, ordered_events):
        count = len(ordered_events)
        base_events = build_event_context(ordered_events, "event_status_code")
        raw_statuses = [event["raw_status"] for event in base_events]
        has_pol_location_index_context = [
            event["has_pol_location_index_context"] for event in base_events
        ]
        event_at_pol = [event["at_pol"] for event in base_events]
        event_at_pod = [event["at_pod"] for event in base_events]
        has_pol_date = [
            bool(str(row.get("pol_date") or "").strip())
            and str(row.get("pol_date") or "").strip() != "\\N"
            for row in ordered_events
        ]
        next_is_same_call_departure = [
            event["next_same_call_departure"] for event in base_events
        ]
        prev_is_same_call_loaded = [event["prev_same_call_loaded"] for event in base_events]
        duplicate_non_actual_unk = [False] * count
        historical_outlier_unk = [False] * count
        sandwiched_different_vessel_unk = [False] * count
        departure_before_same_vessel_load_unk = [False] * count
        transshipment_handoff_discharge = [False] * count
        pol_departure_with_intervening_foreign_load_unk = [False] * count
        arrival_after_foreign_leg_unk = [False] * count
        historical_outlier_indices = self._find_historical_outlier_indices(
            ordered_events
        )

        for idx in range(count):
            historical_outlier_unk[idx] = idx in historical_outlier_indices
            duplicate_non_actual_unk[idx] = self._should_force_non_actual_duplicate_unk(
                ordered_events, idx
            )
            departure_before_same_vessel_load_unk[idx] = (
                raw_statuses[idx] == "vessel departure"
                and ((not event_at_pol[idx]) or (not has_pol_date[idx]))
                and self._has_later_same_vessel_loaded_after_departure(
                    ordered_events, idx
                )
            )
            transshipment_handoff_discharge[idx] = self._is_transshipment_handoff_discharge(
                ordered_events, idx, event_at_pod[idx]
            )
            pol_departure_with_intervening_foreign_load_unk[idx] = (
                raw_statuses[idx] == "vessel departure"
                and event_at_pol[idx]
                and self._has_intervening_foreign_load_before_same_vessel_arrival(
                    ordered_events, idx
                )
            )
            arrival_after_foreign_leg_unk[idx] = (
                raw_statuses[idx] == "vessel arrival"
                and not event_at_pod[idx]
                and self._has_previous_foreign_load_or_departure(ordered_events, idx)
            )
            if 0 < idx < count - 1:
                sandwiched_different_vessel_unk[idx] = (
                    self._is_sandwiched_different_vessel_event(
                        ordered_events[idx - 1],
                        ordered_events[idx],
                        ordered_events[idx + 1],
                    )
                )

        has_future_terminal = [False] * count
        has_future_pod_arrival = [False] * count
        has_future_import_signal = [False] * count
        next_barge_idx = [event.get("next_barge_idx") for event in base_events]
        next_vessel_idx = [event.get("next_vessel_idx") for event in base_events]

        future_terminal = False
        future_pod_arrival = False
        future_import_signal = False
        import_raw = {
            "gate out to consignee",
            "container empty returned",
            "container in transit for import",
            "received for import transfer",
            "discharged full at consignee",
        }

        for idx in range(count - 1, -1, -1):
            has_future_terminal[idx] = future_terminal
            has_future_pod_arrival[idx] = future_pod_arrival
            has_future_import_signal[idx] = future_import_signal
            raw_status = raw_statuses[idx]
            if raw_status in self.TERMINAL_RAW:
                future_terminal = True
            if raw_status == "vessel arrival" and event_at_pod[idx]:
                future_pod_arrival = True
            if raw_status in import_raw:
                future_import_signal = True

        return {
            "raw_statuses": raw_statuses,
            "has_pol_location_index_context": has_pol_location_index_context,
            "has_pol_date": has_pol_date,
            "event_at_pol": event_at_pol,
            "event_at_pod": event_at_pod,
            "is_barge_context": [event.get("is_barge_context", False) for event in base_events],
            "next_is_same_call_departure": next_is_same_call_departure,
            "prev_is_same_call_loaded": prev_is_same_call_loaded,
            "duplicate_non_actual_unk": duplicate_non_actual_unk,
            "historical_outlier_unk": historical_outlier_unk,
            "sandwiched_different_vessel_unk": sandwiched_different_vessel_unk,
            "departure_before_same_vessel_load_unk": departure_before_same_vessel_load_unk,
            "transshipment_handoff_discharge": transshipment_handoff_discharge,
            "pol_departure_with_intervening_foreign_load_unk": (
                pol_departure_with_intervening_foreign_load_unk
            ),
            "arrival_after_foreign_leg_unk": arrival_after_foreign_leg_unk,
            "has_future_terminal": has_future_terminal,
            "has_future_pod_arrival": has_future_pod_arrival,
            "has_future_import_signal": has_future_import_signal,
            "next_barge_idx": next_barge_idx,
            "next_vessel_idx": next_vessel_idx,
        }

