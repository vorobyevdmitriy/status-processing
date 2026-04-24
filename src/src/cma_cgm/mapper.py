from datetime import datetime

from ..container_state import FastContainerStateTracker
from ..domain_context import (
    build_event_context as ctx_build_event_context,
    has_pol_context,
    is_event_at_pod,
    is_event_at_pol,
    is_same_transport_call,
    same_non_empty_text,
)
from ..sequence_mapper_base import SequenceMapperBase


class CmaCgmMapper(SequenceMapperBase):
    STATE_PRE_EXPORT = "pre_export"
    STATE_LOADED = "loaded"
    STATE_DEPARTED = "departed"
    STATE_ARRIVED = "arrived"
    STATE_DISCHARGED = "discharged"
    STATE_DELIVERED = "delivered"

    DIRECT_MAP = {
        "empty picked-up at depot": "CEP",
        "container to shipper": "CEP",
        "empty to shipper": "CEP",
        "empty delivered to shipper": "CEP",
        "in shipper's owned empty": "CEP",
        "inshippersownedempty": "CEP",
        "out shipper's owned full": "CPS",
        "gate in at port terminal": "CGI",
        "ready to be loaded": "UNK",
        "discharged in transhipment": "CDT",
        "gate out to consignee": "CGO",
        "container to consignee": "CGO",
        "container in transit for import": "LTS",
        "container in transit for export": "LTS",
        "received for import transfer": "LTS",
        "received for export transfer": "LTS",
        "full load on rail for import": "LTS",
        "train arrival for import": "LTS",
        "import unload full from rail": "LTS",
        "train arrival": "LTS",
        "train departure": "LTS",
        "full load on rail for export": "LTS",
        "export unload full from rail": "LTS",
        "train arrival for export": "LTS",
        "barge arrival": "BTS",
        "barge departure": "BTS",
        "discharged full at consignee": "UNK",
        "container empty returned": "CER",
        "empty in depot": "CER",
        "loaded empty at consignee": "UNK",
        "unloaded from rail empty": "LTS",
        "loaded on rail empty": "LTS",
        "loaded full at shipper": "UNK",
        "discharged empty at shipper": "UNK",
        "in shipper's owned full": "UNK",
        "out shipper's owned empty": "CER",
        "outshippersownedempty": "CER",
        "customs references": "UNK",
        "plan empty return": "UNK",
        "none": "UNK",
        "": "UNK",
    }

    TERMINAL_RAW = {
        "discharged",
        "gate out to consignee",
        "container empty returned",
        "discharged full at consignee",
    }

    def __init__(self):
        self.state_tracker = FastContainerStateTracker()

    @staticmethod
    def _same_non_empty_text(left, right):
        return same_non_empty_text(left, right)

    def _is_event_at_pod(self, event):
        return is_event_at_pod(event)

    def _has_pol_location_info(self, event):
        return has_pol_context(event)

    def _is_event_at_pol(self, event):
        return is_event_at_pol(event)

    @staticmethod
    def _is_same_transport_call(prev_event, event):
        return is_same_transport_call(prev_event, event)

    @staticmethod
    def _is_valid_event_datetime(value):
        if value is None:
            return False
        raw = str(value).strip()
        if not raw or raw == "\\N":
            return False
        return True

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

    def _has_later_same_call_loaded_after_departure(self, ordered_events, idx):
        departure_event = ordered_events[idx]
        for later_idx in range(idx + 1, len(ordered_events)):
            later_event = ordered_events[later_idx]
            later_status = self.normalize_status(later_event.get("event_status", ""))
            if later_status != "loaded on board":
                continue
            if not self._is_same_transport_call(departure_event, later_event):
                continue
            if self._is_departure_before_loaded(departure_event, later_event):
                return True
        return False

    def _build_chain_context(self, ordered_events):
        count = len(ordered_events)
        base_events = ctx_build_event_context(ordered_events, "event_status_code")
        raw_statuses = [event["raw_status"] for event in base_events]
        has_pol_info = [event["has_pol_info"] for event in base_events]
        event_at_pol = [event["at_pol"] for event in base_events]
        event_at_pod = [event["at_pod"] for event in base_events]
        next_is_same_call_departure = [
            event["next_same_call_departure"] for event in base_events
        ]
        prev_is_same_call_loaded = [event["prev_same_call_loaded"] for event in base_events]
        duplicate_non_actual_unk = [False] * count

        for idx in range(count):
            duplicate_non_actual_unk[idx] = self._should_force_non_actual_duplicate_unk(
                ordered_events, idx
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
            "has_pol_info": has_pol_info,
            "event_at_pol": event_at_pol,
            "event_at_pod": event_at_pod,
            "is_barge_context": [event.get("is_barge_context", False) for event in base_events],
            "next_is_same_call_departure": next_is_same_call_departure,
            "prev_is_same_call_loaded": prev_is_same_call_loaded,
            "duplicate_non_actual_unk": duplicate_non_actual_unk,
            "has_future_terminal": has_future_terminal,
            "has_future_pod_arrival": has_future_pod_arrival,
            "has_future_import_signal": has_future_import_signal,
            "next_barge_idx": next_barge_idx,
            "next_vessel_idx": next_vessel_idx,
        }

    def _map_gate_out_to_consignee(self, state):
        if state in {self.STATE_ARRIVED, self.STATE_DISCHARGED, self.STATE_DELIVERED}:
            return "CGO", "RULE_GATE_OUT_IMPORT"
        return "UNK", "RULE_GATE_OUT_WITHOUT_IMPORT_UNK"

    def _map_ready_to_be_loaded(self, chain_ctx, idx):
        if chain_ctx["has_pol_info"][idx]:
            if chain_ctx["event_at_pol"][idx]:
                return "CGI", "RULE_READY_TO_BE_LOADED_AT_POL_GATE_IN"
            return "CLT", "RULE_READY_TO_BE_LOADED_OUTSIDE_POL_TS"
        return "UNK", "RULE_READY_TO_BE_LOADED_WITHOUT_POL_UNK"

    def _map_export_preparation(self, state, raw_status):
        if state != self.STATE_PRE_EXPORT:
            return "UNK", "RULE_EXPORT_PREPARATION_AFTER_MARINE_UNK"
        return self.DIRECT_MAP[raw_status], "DIRECT_MAP"

    def _map_container_empty_returned(self, state, chain_ctx, idx):
        if chain_ctx["event_at_pod"][idx]:
            return "CER", "RULE_EMPTY_RETURN_AT_POD"
        if state in {self.STATE_ARRIVED, self.STATE_DISCHARGED, self.STATE_DELIVERED}:
            return "CER", "RULE_EMPTY_RETURN_IMPORT"
        if chain_ctx["has_future_pod_arrival"][idx]:
            return "UNK", "RULE_EMPTY_RETURN_PRE_POD_UNK"
        return "UNK", "RULE_EMPTY_RETURN_WITHOUT_IMPORT_UNK"

    def _map_discharged(self, state, chain_ctx, idx):
        if chain_ctx["event_at_pod"][idx]:
            return "CDD", "RULE_DISCHARGED_AT_POD"
        if chain_ctx["is_barge_context"][idx]:
            return "BTS", "RULE_DISCHARGED_BARGE_CONTEXT_BTS"
        if chain_ctx["event_at_pol"][idx] and state in {self.STATE_LOADED, self.STATE_DEPARTED}:
            return "UNK", "RULE_DISCHARGED_AT_POL_AFTER_EXPORT_UNK"
        if "VAD" in chain_ctx.get("mapped_codes_so_far", ()):
            return "UNK", "RULE_DISCHARGED_AFTER_FINAL_ARRIVAL_OUTSIDE_POD_UNK"
        if chain_ctx["has_future_pod_arrival"][idx]:
            return "CDT", "RULE_DISCHARGED_PRE_POD_TS"
        if state in {self.STATE_ARRIVED, self.STATE_DISCHARGED, self.STATE_DELIVERED}:
            return "CDD", "RULE_DISCHARGED_IMPORT_STAGE"
        if chain_ctx["has_future_import_signal"][idx]:
            return "CDD", "RULE_DISCHARGED_IMPORT_TAIL"
        return "CDT", "RULE_DISCHARGED_NON_POD_TS"

    def _map_loaded_on_board(self, state, ordered_events, chain_ctx, idx, mapped_codes):
        event = ordered_events[idx]
        prev_event = ordered_events[idx - 1] if idx > 0 else None
        prev_raw_status = chain_ctx["raw_statuses"][idx - 1] if idx > 0 else ""

        if "VAD" in mapped_codes:
            return "UNK", "RULE_LOADED_ON_BOARD_AFTER_FINAL_ARRIVAL_UNK"

        if (
            prev_event is not None
            and prev_raw_status == "vessel departure"
            and mapped_codes
            and mapped_codes[-1] in {"VDL", "VDT"}
            and self._is_same_transport_call(prev_event, event)
            and self._is_departure_before_loaded(prev_event, event)
        ):
            return "UNK", "RULE_LOADED_ON_BOARD_AFTER_SAME_DEPARTURE_UNK"

        next_barge_idx = chain_ctx["next_barge_idx"][idx]
        next_vessel_idx = chain_ctx["next_vessel_idx"][idx]
        is_barge_context = next_barge_idx is not None and (
            next_vessel_idx is None or next_barge_idx < next_vessel_idx
        )

        if is_barge_context:
            return "BTS", "RULE_LOADED_ON_BOARD_BARGE_CONTEXT_BTS"

        if chain_ctx["has_pol_info"][idx]:
            if chain_ctx["event_at_pol"][idx]:
                if chain_ctx["next_is_same_call_departure"][idx]:
                    return "CLL", "RULE_LOADED_ON_BOARD_POL_MAIN_VESSEL"
                return "CLL", "RULE_LOADED_ON_BOARD_POL_VESSEL"
            return "CLT", "RULE_LOADED_ON_BOARD_OUTSIDE_POL_TS"

        if state in {self.STATE_DEPARTED, self.STATE_ARRIVED, self.STATE_DISCHARGED}:
            return "CLT", "RULE_LOADED_ON_BOARD_AFTER_MARINE_PHASE"

        if state == self.STATE_DELIVERED:
            if chain_ctx["has_future_terminal"][idx]:
                return "CLT", "RULE_LOADED_ON_BOARD_IMPORT_TO_TS"
            return "UNK", "RULE_LOADED_ON_BOARD_IMPORT_UNCLEAR"

        if chain_ctx["next_is_same_call_departure"][idx]:
            return "CLL", "RULE_LOADED_ON_BOARD_EXPORT_MAIN_VESSEL"

        return "UNK", "RULE_LOADED_ON_BOARD_UNCLEAR"

    def _map_vessel_departure(self, state, chain_ctx, idx, mapped_codes):
        if "VAD" in mapped_codes:
            return "UNK", "RULE_VESSEL_DEPARTURE_AFTER_FINAL_ARRIVAL_UNK"

        if chain_ctx["has_pol_info"][idx]:
            if chain_ctx["event_at_pol"][idx]:
                if (
                    mapped_codes
                    and mapped_codes[-1] == "CLL"
                    and chain_ctx["prev_is_same_call_loaded"][idx]
                ):
                    return "VDL", "RULE_VESSEL_DEPARTURE_AFTER_POL_MAIN_LOAD"
                if state in {self.STATE_PRE_EXPORT, self.STATE_LOADED}:
                    return "VDL", "RULE_VESSEL_DEPARTURE_POL_MAIN"
            return "VDT", "RULE_VESSEL_DEPARTURE_OUTSIDE_POL_TS"

        if (
            mapped_codes
            and mapped_codes[-1] == "CLL"
            and chain_ctx["prev_is_same_call_loaded"][idx]
        ):
            return "VDL", "RULE_VESSEL_DEPARTURE_AFTER_MAIN_LOAD"

        if state in {self.STATE_PRE_EXPORT, self.STATE_LOADED}:
            return "VDL", "RULE_VESSEL_DEPARTURE_EXPORT_FALLBACK"

        return "VDT", "RULE_VESSEL_DEPARTURE_AFTER_MARINE_PHASE"

    def _map_vessel_arrival(self, chain_ctx, idx):
        if "VAD" in chain_ctx.get("mapped_codes_so_far", ()):
            return "UNK", "RULE_VESSEL_ARRIVAL_AFTER_FINAL_ARRIVAL_UNK"

        if chain_ctx["event_at_pod"][idx]:
            return "VAD", "RULE_VESSEL_ARRIVAL_POD_MATCH"
        return "VAT", "RULE_VESSEL_ARRIVAL_TS"

    def _map_event(self, state, ordered_events, chain_ctx, idx, mapped_codes):
        chain_ctx["mapped_codes_so_far"] = mapped_codes
        raw_status = chain_ctx["raw_statuses"][idx]

        if raw_status == "loaded on board":
            return self._map_loaded_on_board(
                state, ordered_events, chain_ctx, idx, mapped_codes
            )
        if raw_status == "vessel departure":
            return self._map_vessel_departure(state, chain_ctx, idx, mapped_codes)
        if raw_status == "vessel arrival":
            return self._map_vessel_arrival(chain_ctx, idx)
        if raw_status == "discharged":
            return self._map_discharged(state, chain_ctx, idx)
        if raw_status == "discharged in transhipment":
            if chain_ctx["event_at_pod"][idx] and "VAD" in mapped_codes:
                return "CDD", "RULE_DIT_AFTER_FINAL_ARRIVAL_AT_POD_CDD"
            return self.DIRECT_MAP[raw_status], "DIRECT_MAP"
        if raw_status == "container empty returned":
            return self._map_container_empty_returned(state, chain_ctx, idx)
        if raw_status == "gate out to consignee":
            return self._map_gate_out_to_consignee(state)
        if raw_status == "ready to be loaded":
            return self._map_ready_to_be_loaded(chain_ctx, idx)
        if raw_status in {
            "empty picked-up at depot",
            "container to shipper",
            "gate in at port terminal",
        }:
            return self._map_export_preparation(state, raw_status)
        if raw_status in self.DIRECT_MAP:
            return self.DIRECT_MAP[raw_status], "DIRECT_MAP"
        return "UNK", "NO_RULE_UNK"

    def map_seq(self, ordered_events):
        mapped_codes = []
        mapped_reasons = []
        fsm = self.state_tracker
        fsm.reset()
        chain_ctx = self._build_chain_context(ordered_events)
        chain_ctx["ordered_events"] = ordered_events

        for idx, _event in enumerate(ordered_events):
            state = fsm.current_state_value
            if chain_ctx["duplicate_non_actual_unk"][idx]:
                code = "UNK"
                reason = "RULE_DUPLICATE_NON_ACTUAL_UNK"
            else:
                code, reason = self._map_event(
                    state, ordered_events, chain_ctx, idx, mapped_codes
                )

            mapped_codes.append(code)
            mapped_reasons.append(reason)
            fsm.advance(code)

        return mapped_codes, mapped_reasons
