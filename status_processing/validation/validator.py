import argparse
import csv
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import dataclass

from ..config.paths import (
    MAPPED_DATAMART_CMA_CGM,
    VALIDATION_RESULTS_CMA_CGM,
)
from ..domain_context import (
    ACTION_ARRIVE,
    ACTION_DEPART,
    ACTION_DELIVER,
    ACTION_DISCHARGE,
    ACTION_LOAD,
    ACTION_OTHER,
    ACTION_PREP,
    ARRIVE_CODES,
    DEPART_CODES,
    DELIVERY_TAIL_CODES,
    DISCHARGE_CODES,
    EXPORT_PREPARATION_CODES,
    LOAD_CODES,
    action_family,
    build_event_context,
    is_actual_event,
    is_same_transport_call,
    parse_event_datetime,
    same_non_empty_text,
)


KNOWN_CODES = {
    "CEP",
    "CPS",
    "CGI",
    "CLL",
    "VDL",
    "VAT",
    "CDT",
    "TSD",
    "CLT",
    "VDT",
    "VAD",
    "CDD",
    "CGO",
    "CDC",
    "CER",
    "LTS",
    "BTS",
    "UNK",
}

PHASE_MAP = {
    "CEP": 1,
    "CPS": 2,
    "CGI": 2,
    "CLL": 2,
    "VDL": 2,
    "VAT": None,
    "CDT": None,
    "TSD": None,
    "CLT": None,
    "VDT": None,
    "LTS": None,
    "BTS": None,
    "VAD": 4,
    "CDD": 4,
    "CGO": 4,
    "CDC": 4,
    "CER": 5,
    "UNK": None,
}

ALLOWED_START = {
    "CEP",
    "CPS",
    "CGI",
    "CDT",
    "CLL",
    "CLT",
    "VDL",
    "VDT",
    "VAT",
    "VAD",
    "LTS",
    "BTS",
    "UNK",
}

MEANINGFUL_CODES = {c for c in KNOWN_CODES if c != "UNK"}

ALLOWED_NEXT = {
    "CEP": {"CPS", "CGI", "CLL", "VDL", "VAT", "VAD", "LTS", "BTS", "UNK"},
    "CPS": {"CGI", "CLL", "VDL", "VAT", "VAD", "LTS", "BTS", "UNK"},
    "CGI": {"CLL", "VDL", "VAT", "VAD", "LTS", "BTS", "UNK"},
    "CLL": {"CDT", "VDL", "VAT", "VAD", "LTS", "BTS", "UNK"},
    "VDL": {"VAT", "VAD", "LTS", "BTS", "UNK"},
    "VAT": {"CDT", "TSD", "CLT", "VDT", "LTS", "BTS", "UNK"},
    "CDT": {"TSD", "CLL", "CLT", "VDL", "VDT", "VAD", "LTS", "BTS", "UNK"},
    "TSD": {"CLT", "VDT", "CDT", "VAT", "VAD", "LTS", "BTS", "UNK"},
    "CLT": {"CDT", "VDT", "VAT", "VAD", "LTS", "BTS", "UNK"},
    "VDT": {"VAT", "CDT", "TSD", "CLT", "VAD", "LTS", "BTS", "UNK"},
    "VAD": {"CDD", "CGO", "CDC", "CER", "LTS", "BTS", "UNK"},
    "CDD": {"CGO", "CDC", "CER", "LTS", "BTS", "UNK"},
    "CGO": {"CDC", "CER", "LTS", "BTS", "UNK"},
    "CDC": {"CER", "UNK"},
    "CER": {"UNK", "LTS", "BTS"},
    "LTS": MEANINGFUL_CODES | {"UNK"},
    "BTS": MEANINGFUL_CODES | {"UNK"},
    "UNK": MEANINGFUL_CODES | {"UNK"},
}

STRICT_ALLOWED_START = {"CEP", "CPS", "CGI"}

STRICT_ALLOWED_NEXT = {
    "CEP": {"CPS", "CGI", "CLL", "VDL", "LTS", "BTS", "UNK"},
    "CPS": {"CGI", "CLL", "VDL", "LTS", "BTS", "UNK"},
    "CGI": {"CLL", "VDL", "UNK"},
    "CLL": {"CDT", "VDL"},
    "VDL": {"VAT", "VAD", "UNK"},
    "VAT": {"CDT", "CLT", "VAD", "TSD", "UNK"},
    "CDT": {"TSD", "CLL", "CLT", "VDL", "VAD", "LTS", "BTS", "UNK"},
    "TSD": {"CLT", "VDT", "CDT", "VAT", "VAD", "LTS", "BTS", "UNK"},
    "CLT": {"CDT", "VDT", "VAD", "TSD", "UNK"},
    "VDT": {"VAT", "VAD", "UNK"},
    "VAD": {"CDD", "CGO", "CDC", "CER", "UNK"},
    "CDD": {"CGO", "CDC", "CER"},
    "CGO": {"CDC", "CER"},
    "CDC": {"CER", "UNK"},
    "CER": {"UNK", "LTS", "BTS", "CEP"},
    "LTS": {"LTS", "BTS", "UNK"},
    "BTS": {"BTS", "LTS", "UNK"},
    "UNK": {"UNK", "LTS", "BTS"},
}

STRICT_REQUIRED_CODES = {"CGI", "CLL", "VDL", "VAD", "CDD", "CGO"}

CURRENT_STATUS_ONLY_COMPANIES = {
    "OOCL",
    "Trcont",
    "Meratus Line",
    "Cordelia",
    "Tanto",
    "Seaboard Marine",
}

SINGLETON_CODES = {
    "CEP",
    "CPS",
    "CGI",
    "CLL",
    "VDL",
    "VAD",
    "CDD",
    "CGO",
    "CDC",
    "CER",
}


RAW_ALLOWED_CODES = {
    "empty picked-up at depot": {"CEP", "UNK"},
    "container to shipper": {"CEP", "UNK"},
    "gate in at port terminal": {"CGI", "UNK"},
    "ready to be loaded": {"CGI", "CLT", "UNK"},
    "discharged in transhipment": {"CDD", "CDT", "BTS", "UNK"},
    "loaded on board": {"CLL", "CLT", "BTS", "UNK"},
    "vessel departure": {"VDL", "VDT", "UNK"},
    "vessel arrival": {"VAT", "VAD", "UNK"},
    "discharged": {"CDD", "CDT", "BTS", "UNK"},
    "gate out to consignee": {"CGO", "UNK"},
    "container empty returned": {"CER", "UNK"},
    "barge arrival": {"BTS", "UNK"},
    "barge departure": {"BTS", "UNK"},
    "container in transit for import": {"LTS", "UNK"},
    "container in transit for export": {"LTS", "UNK"},
    "received for import transfer": {"LTS", "UNK"},
    "received for export transfer": {"LTS", "UNK"},
    "full load on rail for import": {"LTS", "UNK"},
    "train arrival for import": {"LTS", "UNK"},
    "import unload full from rail": {"LTS", "UNK"},
    "train arrival": {"LTS", "UNK"},
    "train departure": {"LTS", "UNK"},
    "full load on rail for export": {"LTS", "UNK"},
    "export unload full from rail": {"LTS", "UNK"},
    "train arrival for export": {"LTS", "UNK"},
    "unloaded from rail empty": {"LTS", "UNK"},
    "loaded on rail empty": {"LTS", "UNK"},
    "customs references": {"UNK"},
    "plan empty return": {"UNK"},
    "discharged full at consignee": {"UNK"},
    "loaded empty at consignee": {"UNK"},
    "loaded full at shipper": {"UNK"},
    "discharged empty at shipper": {"UNK"}
}

EXPORT_PREPARATION_RAW = {
    "empty picked-up at depot",
    "container to shipper",
    "gate in at port terminal"
}
IMPORT_TAIL_RAW = {
    "gate out to consignee",
    "container empty returned",
    "discharged full at consignee"
}
TRANSIT_CODES = {"VAT", "CDT", "CLT", "VDT", "BTS", "TSD"}
POST_FINAL_VAD_ALLOWED_CODES = {"CDD", "CGO", "CDC", "CER", "LTS", "BTS", "UNK"}
MARINE_OR_IMPORT_CODES = {
    "CLL",
    "CLT",
    "VDL",
    "VDT",
    "VAT",
    "VAD",
    "CDT",
    "CDD",
    "CGO",
    "CDC",
    "CER"
}
ARRIVE_CODES = {"VAT", "VAD"}


@dataclass
class Violation:
    rule_id: str
    idx: int
    from_code: str
    to_code: str
    details: str


class Phase:
    def __init__(self):
        self.current_phase = 0

    def reset(self):
        self.current_phase = 0

    def advance(self, code):
        normalized = "UNK" if code == "TSD" else code
        phase = PHASE_MAP.get(normalized)
        if phase is None:
            return True, self.current_phase, self.current_phase

        prev_phase = self.current_phase
        if prev_phase and phase < prev_phase:
            return False, prev_phase, phase

        self.current_phase = phase
        return True, prev_phase, phase


class Code:
    def __init__(self, allowed_start, allowed_next):
        self.allowed_start = allowed_start
        self.allowed_next = allowed_next
        self.current_code = "START"

    def reset(self):
        self.current_code = "START"

    def advance(self, code):
        prev_code = self.current_code
        if prev_code == "START":
            if code not in self.allowed_start:
                return False, prev_code
        elif code not in self.allowed_next.get(prev_code, set()):
            return False, prev_code

        self.current_code = code
        return True, prev_code


class ContainerPhaseTracker:
    PRE_EXPORT = "pre_export"
    LOADED = "loaded"
    DEPARTED = "departed"
    ARRIVED = "arrived"
    DISCHARGED = "discharged"
    DELIVERED = "delivered"

    PRE_EXPORT_CODES = {"CEP", "CPS", "CGI"}
    LOADED_CODES = {"CLL", "CLT"}
    DEPARTED_CODES = {"VDL", "VDT"}
    ARRIVED_CODES = {"VAT", "VAD", "TSD"}
    DISCHARGED_CODES = {"CDT", "CDD"}
    DELIVERED_CODES = {"CGO", "CDC", "CER"}

    def __init__(self):
        self.reset()

    def reset(self):
        self.current_state = self.PRE_EXPORT

    def advance(self, code):
        if code in self.PRE_EXPORT_CODES:
            self.current_state = self.PRE_EXPORT
        elif code in self.LOADED_CODES:
            self.current_state = self.LOADED
        elif code in self.DEPARTED_CODES:
            self.current_state = self.DEPARTED
        elif code in self.ARRIVED_CODES:
            self.current_state = self.ARRIVED
        elif code in self.DISCHARGED_CODES:
            self.current_state = self.DISCHARGED
        elif code in self.DELIVERED_CODES:
            self.current_state = self.DELIVERED


class ActionOrder:
    PRE_EXPORT = "pre_export"
    LOADED = "loaded"
    DEPARTED = "departed"
    ARRIVED = "arrived"
    DISCHARGED = "discharged"
    DELIVERED = "delivered"

    def __init__(self):
        self.reset()

    def reset(self):
        self.state = self.PRE_EXPORT

    def advance(self, action):
        prev_state = self.state

        if action in {ACTION_OTHER, ACTION_PREP}:
            return True, prev_state

        if prev_state == self.PRE_EXPORT:
            if action == ACTION_LOAD:
                self.state = self.LOADED
                return True, prev_state
            if action == ACTION_DEPART:
                self.state = self.DEPARTED
                return True, prev_state
            if action == ACTION_ARRIVE:
                self.state = self.ARRIVED
                return True, prev_state
            if action == ACTION_DISCHARGE:
                self.state = self.DISCHARGED
                return True, prev_state
            return False, prev_state

        if prev_state == self.LOADED:
            if action == ACTION_LOAD:
                return True, prev_state
            if action == ACTION_DEPART:
                self.state = self.DEPARTED
                return True, prev_state
            if action == ACTION_ARRIVE:
                self.state = self.ARRIVED
                return True, prev_state
            if action == ACTION_DISCHARGE:
                self.state = self.DISCHARGED
                return True, prev_state
            return False, prev_state

        if prev_state == self.DEPARTED:
            if action == ACTION_DEPART:
                return True, prev_state
            if action == ACTION_ARRIVE:
                self.state = self.ARRIVED
                return True, prev_state
            if action == ACTION_DISCHARGE:
                self.state = self.DISCHARGED
                return True, prev_state
            return False, prev_state

        if prev_state == self.ARRIVED:
            if action == ACTION_ARRIVE:
                return True, prev_state
            if action == ACTION_DISCHARGE:
                self.state = self.DISCHARGED
                return True, prev_state
            if action == ACTION_DEPART:
                self.state = self.DEPARTED
                return True, prev_state
            if action == ACTION_LOAD:
                self.state = self.LOADED
                return True, prev_state
            return False, prev_state

        if prev_state == self.DISCHARGED:
            if action == ACTION_DISCHARGE:
                return True, prev_state
            if action == ACTION_LOAD:
                self.state = self.LOADED
                return True, prev_state
            if action == ACTION_DEPART:
                self.state = self.DEPARTED
                return True, prev_state
            if action == ACTION_DELIVER:
                self.state = self.DELIVERED
                return True, prev_state
            return False, prev_state

        if prev_state == self.DELIVERED:
            if action == ACTION_DELIVER:
                return True, prev_state
            return False, prev_state

        return False, prev_state


PHASE = Phase()
NORMAL = Code(ALLOWED_START, ALLOWED_NEXT)
STRICT = Code(STRICT_ALLOWED_START, STRICT_ALLOWED_NEXT)
ACTION = ActionOrder()


def format_violation(v: Violation):
    if v is None:
        return ""
    return f"{v.rule_id}|idx={v.idx}|{v.from_code}->{v.to_code}|{v.details}"


def _same_non_empty_vessel(left, right):
    return same_non_empty_text(left.get("vessel"), right.get("vessel"))


def _is_sandwiched_vessel_anomaly(prev_event, cur_event, next_event):
    if not is_actual_event(cur_event["row"]):
        return False

    if not _same_non_empty_vessel(prev_event["row"], next_event["row"]):
        return False

    if _same_non_empty_vessel(prev_event["row"], cur_event["row"]):
        return False

    prev_dt = parse_event_datetime(prev_event["row"].get("event_date"))
    cur_dt = parse_event_datetime(cur_event["row"].get("event_date"))
    next_dt = parse_event_datetime(next_event["row"].get("event_date"))
    if prev_dt is None or cur_dt is None or next_dt is None:
        return False

    return prev_dt <= cur_dt <= next_dt


def detect_post_final_anomaly(events):
    final_vad_idx = None
    final_vad_locode = None
    delivery_tail_started = False

    for idx, event in enumerate(events):
        code = event["code"]
        locode = (event["row"].get("location_locode") or "").strip()

        if final_vad_idx is not None:
            if code == "VAD" and event["at_pod"]:
                if delivery_tail_started or (final_vad_locode and locode and locode != final_vad_locode):
                    return Violation(
                        rule_id="L1_REPEATED_FINAL_VAD",
                        idx=idx,
                        from_code="VAD",
                        to_code="VAD",
                        details="repeated final VAD in another location or after delivery tail started"
                    )

            if code not in POST_FINAL_VAD_ALLOWED_CODES:
                return Violation(
                    rule_id="L1_NON_TERMINAL_AFTER_FINAL_VAD",
                    idx=idx,
                    from_code="VAD",
                    to_code=code,
                    details="only CDD/CGO/CDC/CER/LTS/BTS/UNK are allowed after final VAD at POD"
                )

        if code in DELIVERY_TAIL_CODES:
            delivery_tail_started = True

        if code == "VAD" and event["at_pod"] and final_vad_idx is None:
            final_vad_idx = idx
            final_vad_locode = locode or final_vad_locode

    return None


def detect_location_anomaly(events):
    has_departure_at_pol = any(event["code"] in DEPART_CODES and event["at_pol"] for event in events)
    if not has_departure_at_pol:
        return Violation(
            rule_id="L3_NO_DEPARTURE_AT_POL",
            idx=0,
            from_code="",
            to_code="",
            details="sequence has no departure event at POL"
        )

    for idx, event in enumerate(events):
        code = event["code"]
        raw_status = event["raw_status"]

        if code == "CLL" and not event["at_pol"]:
            return Violation(
                rule_id="L3_CLL_OUTSIDE_POL",
                idx=idx,
                from_code="",
                to_code=code,
                details="CLL must happen at POL"
            )

        if code == "CLT" and event["at_pol"] and not event["is_barge_context"]:
            return Violation(
                rule_id="L3_CLT_AT_POL_WITHOUT_BARGE",
                idx=idx,
                from_code="",
                to_code=code,
                details="CLT at POL requires barge/feeder context"
            )

        if code == "VDL" and not event["at_pol"]:
            return Violation(
                rule_id="L3_VDL_OUTSIDE_POL",
                idx=idx,
                from_code="",
                to_code=code,
                details="VDL must happen at POL"
            )

        if code == "VDT" and event["at_pol"]:
            return Violation(
                rule_id="L3_VDT_AT_POL",
                idx=idx,
                from_code="",
                to_code=code,
                details="VDT should be outside POL"
            )

        if code == "VAD" and not event["at_pod"]:
            return Violation(
                rule_id="L3_VAD_OUTSIDE_POD",
                idx=idx,
                from_code="",
                to_code=code,
                details="VAD must happen at POD"
            )

        if code == "VAT" and event["at_pod"]:
            return Violation(
                rule_id="L3_VAT_AT_POD",
                idx=idx,
                from_code="",
                to_code=code,
                details="VAT should be outside POD"
            )

        if code == "CDD" and not event["at_pod"]:
            return Violation(
                rule_id="L3_CDD_OUTSIDE_POD",
                idx=idx,
                from_code="",
                to_code=code,
                details="CDD must happen at POD"
            )

        if code == "CDT" and event["at_pod"]:
            return Violation(
                rule_id="L3_CDT_AT_POD",
                idx=idx,
                from_code="",
                to_code=code,
                details="CDT should be outside POD"
            )

        if raw_status == "ready to be loaded":
            if (
                event["has_pol_location_index_context"]
                and event["at_pol"]
                and code != "CGI"
            ):
                return Violation(
                    rule_id="L3_READY_TO_BE_LOADED_AT_POL_NOT_CGI",
                    idx=idx,
                    from_code="ready to be loaded",
                    to_code=code,
                    details="ready to be loaded at POL must map to CGI"
                )
            if (
                event["has_pol_location_index_context"]
                and not event["at_pol"]
                and code != "CLT"
            ):
                return Violation(
                    rule_id="L3_READY_TO_BE_LOADED_OUTSIDE_POL_NOT_CLT",
                    idx=idx,
                    from_code="ready to be loaded",
                    to_code=code,
                    details="ready to be loaded outside POL must map to CLT"
                )
            if (not event["has_pol_location_index_context"]) and code != "UNK":
                return Violation(
                    rule_id="L3_READY_TO_BE_LOADED_WITHOUT_POL_NOT_UNK",
                    idx=idx,
                    from_code="ready to be loaded",
                    to_code=code,
                    details="ready to be loaded without POL context must map to UNK"
                )

    return None


def detect_edge_anomaly(events):
    cer_idx = next((idx for idx, event in enumerate(events) if event["code"] == "CER"), None)
    if cer_idx is not None:
        for idx in range(cer_idx + 1, len(events)):
            code = events[idx]["code"]
            if code in LOAD_CODES | DEPART_CODES | ARRIVE_CODES | DISCHARGE_CODES:
                return Violation(
                    rule_id="L3_NON_TERMINAL_AFTER_CER",
                    idx=idx,
                    from_code="CER",
                    to_code=code,
                    details="marine/load/discharge tail appears after CER"
                )

    first_terminal_idx = next((idx for idx, event in enumerate(events) 
                               if event["code"] in EXPORT_PREPARATION_CODES | LOAD_CODES | DEPART_CODES), None)
    if first_terminal_idx is not None:
        for idx in range(first_terminal_idx):
            code = events[idx]["code"]
            if code in LOAD_CODES | DEPART_CODES | ARRIVE_CODES | DISCHARGE_CODES | DELIVERY_TAIL_CODES:
                return Violation(
                    rule_id="L3_NON_TERMINAL_AT_SEQUENCE_START",
                    idx=idx,
                    from_code="",
                    to_code=code,
                    details="sequence starts with marine/import tail before export start"
                )

    return None


def detect_transport_anomaly(events):
    for idx in range(1, len(events) - 1):
        prev_event = events[idx - 1]
        cur_event = events[idx]
        next_event = events[idx + 1]

        if not _is_sandwiched_vessel_anomaly(prev_event, cur_event, next_event):
            continue

        return Violation(
            rule_id="L3_SANDWICHED_DIFFERENT_VESSEL_EVENT",
            idx=idx,
            from_code=prev_event["code"],
            to_code=cur_event["code"],
            details="actual event with different vessel is sandwiched between two same-vessel events by date"
        )

    for idx, event in enumerate(events):
        if event["raw_status"] != "vessel departure":
            continue

        for later_idx in range(idx + 1, len(events)):
            later_event = events[later_idx]
            if later_event["raw_status"] != "loaded on board":
                continue
            if is_same_transport_call(event["row"], later_event["row"]):
                return Violation(
                    rule_id="L3_SAME_CALL_DEPARTURE_BEFORE_LOAD",
                    idx=idx,
                    from_code=event["code"],
                    to_code=later_event["code"],
                    details="departure appears before load in the same transport call"
                )

    for idx, event in enumerate(events):
        if event["code"] not in {"VDL", "VDT"}:
            continue

        locode = (event["row"].get("location_locode") or "").strip()
        if not locode or locode == "\\N":
            continue

        for later_idx in range(idx + 1, len(events)):
            later_event = events[later_idx]
            later_locode = (later_event["row"].get("location_locode") or "").strip()
            if later_locode != locode:
                continue
            if later_event["code"] in {"VAT", "CDT", "CLT"}:
                return Violation(
                    rule_id="L3_TS_PORT_BLOCK_WRONG_ORDER",
                    idx=idx,
                    from_code=event["code"],
                    to_code=later_event["code"],
                    details=(f"departure appears before prior TS milestones in the same port ({locode})"))

    return None


def evaluate_level1(events):
    state = ACTION
    state.reset()
    last_action_code = ""
    seen_import_anchor = False
    seen_marine_or_import = False

    for idx, event in enumerate(events):
        code = event["code"]

        if code in DELIVERY_TAIL_CODES and not seen_import_anchor:
            return False, Violation(
                rule_id="L1_DELIVERY_TAIL_BEFORE_IMPORT",
                idx=idx,
                from_code="",
                to_code=code,
                details="delivery-tail code appears before VAD/CDD import anchor"
            )

        if code in EXPORT_PREPARATION_CODES and seen_marine_or_import:
            return False, Violation(
                rule_id="L1_EXPORT_PREPARATION_AFTER_MARINE",
                idx=idx,
                from_code="",
                to_code=code,
                details="export-preparation code appears after marine/import phase started"
            )

        action = action_family(code)
        ok, prev_state = state.advance(action)
        if not ok:
            return False, Violation(
                rule_id="L1_ACTION_BACKWARD",
                idx=idx,
                from_code=last_action_code or prev_state,
                to_code=code,
                details=f"action {action} is not allowed after state {prev_state}"
            )

        if action != ACTION_OTHER:
            last_action_code = code

        if code in {"VAD", "CDD"}:
            seen_import_anchor = True
        if code in MARINE_OR_IMPORT_CODES:
            seen_marine_or_import = True

    post_final_anomaly = detect_post_final_anomaly(events)
    if post_final_anomaly is not None:
        return False, post_final_anomaly

    return True, None


def evaluate_level2(events):
    if not events:
        return False, Violation(
            rule_id="L2_EMPTY_SEQUENCE",
            idx=0,
            from_code="",
            to_code="",
            details="sequence is empty"
        )

    state = NORMAL
    state.reset()

    for idx, event in enumerate(events):
        code = event["code"]
        ok, prev_code = state.advance(code)
        if ok:
            continue
        if prev_code == "START":
            return False, Violation(
                rule_id="L2_INVALID_START",
                idx=idx,
                from_code="START",
                to_code=code,
                details="invalid start code"
            )
        return False, Violation(
            rule_id="L2_INVALID_TRANSITION",
            idx=idx,
            from_code=prev_code,
            to_code=code,
            details="transition is not allowed"
        )

    return True, None


def evaluate_level3(events):
    phase = ContainerPhaseTracker()
    seen_codes = set()
    seen_singletons = {}

    for idx, event in enumerate(events):
        code = event["code"]
        raw_status = event["raw_status"]
        allowed = RAW_ALLOWED_CODES.get(raw_status)

        if allowed is not None and code not in allowed:
            return False, Violation(
                rule_id="L3_CODE_RAW_MISMATCH",
                idx=idx,
                from_code=raw_status,
                to_code=code,
                details="code does not match raw event kind"
            )

        if code in SINGLETON_CODES:
            if code in seen_singletons:
                return False, Violation(
                    rule_id="L3_REPEATED_SINGLETON",
                    idx=idx,
                    from_code=code,
                    to_code=code,
                    details=f"{code} appears more than once (first at idx={seen_singletons[code]})"
                )
            seen_singletons[code] = idx

        if code == "CLL" and not event["at_pol"]:
            return False, Violation(
                rule_id="L3_CLL_OUTSIDE_POL",
                idx=idx,
                from_code="",
                to_code=code,
                details="CLL must happen at POL"
            )

        if code == "CLT" and event["at_pol"] and not event["is_barge_context"]:
            return False, Violation(
                rule_id="L3_CLT_AT_POL_WITHOUT_BARGE",
                idx=idx,
                from_code="",
                to_code=code,
                details="CLT at POL requires barge/feeder context"
            )

        if code == "VDL" and not event["at_pol"]:
            return False, Violation(
                rule_id="L3_VDL_OUTSIDE_POL",
                idx=idx,
                from_code="",
                to_code=code,
                details="VDL must happen at POL"
            )

        if code == "VDT" and event["at_pol"]:
            return False, Violation(
                rule_id="L3_VDT_AT_POL",
                idx=idx,
                from_code="",
                to_code=code,
                details="VDT should be outside POL"
            )

        if code == "VAD" and not event["at_pod"]:
            return False, Violation(
                rule_id="L3_VAD_OUTSIDE_POD",
                idx=idx,
                from_code="",
                to_code=code,
                details="VAD must happen at POD"
            )

        if code == "VAT" and event["at_pod"]:
            return False, Violation(
                rule_id="L3_VAT_AT_POD",
                idx=idx,
                from_code="",
                to_code=code,
                details="VAT should be outside POD"
            )

        if code == "CDD" and not event["at_pod"]:
            return False, Violation(
                rule_id="L3_CDD_OUTSIDE_POD",
                idx=idx,
                from_code="",
                to_code=code,
                details="CDD must happen at POD"
            )

        if code == "CDT" and event["at_pod"]:
            return False, Violation(
                rule_id="L3_CDT_AT_POD",
                idx=idx,
                from_code="",
                to_code=code,
                details="CDT should be outside POD"
            )

        if raw_status == "ready to be loaded":
            if (
                event["has_pol_location_index_context"]
                and event["at_pol"]
                and code != "CGI"
            ):
                return False, Violation(
                    rule_id="L3_READY_TO_BE_LOADED_AT_POL_NOT_CGI",
                    idx=idx,
                    from_code="ready to be loaded",
                    to_code=code,
                    details="ready to be loaded at POL must map to CGI"
                )
            if (
                event["has_pol_location_index_context"]
                and not event["at_pol"]
                and code != "CLT"
            ):
                return False, Violation(
                    rule_id="L3_READY_TO_BE_LOADED_OUTSIDE_POL_NOT_CLT",
                    idx=idx,
                    from_code="ready to be loaded",
                    to_code=code,
                    details="ready to be loaded outside POL must map to CLT"
                )
            if (not event["has_pol_location_index_context"]) and code != "UNK":
                return False, Violation(
                    rule_id="L3_READY_TO_BE_LOADED_WITHOUT_POL_NOT_UNK",
                    idx=idx,
                    from_code="ready to be loaded",
                    to_code=code,
                    details="ready to be loaded without POL context must map to UNK"
                )

        if (raw_status in EXPORT_PREPARATION_RAW and phase.current_state != phase.PRE_EXPORT and code != "UNK"):
            return False, Violation(
                rule_id="L3_EXPORT_PREPARATION_AFTER_MARINE",
                idx=idx,
                from_code=phase.current_state,
                to_code=code,
                details="export preparation event appears after marine/import phase"
            )

        if (raw_status in IMPORT_TAIL_RAW and phase.current_state not in {phase.ARRIVED, phase.DISCHARGED, phase.DELIVERED} 
            and code != "UNK"):
            return False, Violation(
                rule_id="L3_IMPORT_TAIL_BEFORE_IMPORT",
                idx=idx,
                from_code=phase.current_state,
                to_code=code,
                details="import-tail event appears before import phase"
            )

        if "VAD" in seen_codes and code in TRANSIT_CODES:
            return False, Violation(
                rule_id="L3_TRANSIT_AFTER_FINAL_ARRIVAL",
                idx=idx,
                from_code="VAD",
                to_code=code,
                details="transit code appears after final POD arrival"
            )

        if code == "CGO" and not ({"VAD", "CDD"} & seen_codes):
            return False, Violation(
                rule_id="L3_CGO_WITHOUT_IMPORT",
                idx=idx,
                from_code="",
                to_code=code,
                details="gate out without VAD/CDD"
            )

        if code == "CER" and not ({"VAD", "CDD", "CGO", "CDC"} & seen_codes):
            return False, Violation(
                rule_id="L3_CER_WITHOUT_IMPORT",
                idx=idx,
                from_code="",
                to_code=code,
                details="CER appears without import context"
            )

        phase.advance(code)
        seen_codes.add(code)

    transport_anomaly = detect_transport_anomaly(events)
    if transport_anomaly is not None:
        return False, transport_anomaly

    return True, None


def first_index(codes, code):
    for i, c in enumerate(codes):
        if c == code:
            return i
    return -1


def evaluate_level4(events):
    if not events:
        return False, Violation(
            rule_id="L4_EMPTY_SEQUENCE",
            idx=0,
            from_code="",
            to_code="",
            details="sequence is empty"
        )

    state = STRICT
    state.reset()
    codes = [event["code"] for event in events]

    for idx, code in enumerate(codes):
        ok, prev_code = state.advance(code)
        if ok:
            continue
        if prev_code == "START":
            return False, Violation(
                rule_id="L4_INVALID_STRICT_START",
                idx=idx,
                from_code="START",
                to_code=code,
                details="invalid strict start code"
            )
        return False, Violation(
            rule_id="L4_INVALID_STRICT_TRANSITION",
            idx=idx,
            from_code=prev_code,
            to_code=code,
            details="transition is not allowed"
        )

    for idx, event in enumerate(events):
        code = event["code"]
        if code == "CLL" and not event["next_same_call_departure"]:
            return False, Violation(
                rule_id="L4_CLL_WITHOUT_SAME_CALL_DEPARTURE",
                idx=idx,
                from_code="",
                to_code=code,
                details="strict CLL requires same-call vessel departure next"
            )

        if (code == "VDL" and idx > 0 and codes[idx - 1] == "CLL" and not event["prev_same_call_loaded"]):
            return False, Violation(
                rule_id="L4_VDL_WITHOUT_SAME_CALL_LOAD",
                idx=idx,
                from_code="CLL",
                to_code=code,
                details="strict VDL after CLL requires same transport call"
            )

    idx_vad = first_index(codes, "VAD")
    if idx_vad >= 0 and not ({"VDL", "VDT"} & set(codes[:idx_vad])):
        return False, Violation(
            rule_id="L4_VAD_WITHOUT_DEPARTURE",
            idx=idx_vad,
            from_code="",
            to_code="VAD",
            details="VAD without prior VDL/VDT"
        )

    if "CGO" in codes and "CDD" not in codes:
        return False, Violation(
            rule_id="L4_CGO_WITHOUT_CDD",
            idx=first_index(codes, "CGO"),
            from_code="",
            to_code="CGO",
            details="CGO requires CDD in strict level"
        )

    return True, None


def evaluate_level5(events):
    codes = [event["code"] for event in events]
    for code in STRICT_REQUIRED_CODES:
        cnt = codes.count(code)
        if cnt != 1:
            return False, Violation(
                rule_id="L5_REQUIRED_SINGLE_OCCURRENCE",
                idx=first_index(codes, code) if cnt > 0 else 0,
                from_code="",
                to_code=code,
                details=f"{code} must appear exactly once (actual={cnt})"
            )

    if codes[-1] not in {"CGO", "CDC", "CER"}:
        return False, Violation(
            rule_id="L5_INVALID_END",
            idx=len(codes) - 1,
            from_code="",
            to_code=codes[-1],
            details="final strict end must be CGO/CDC/CER"
        )

    has_transit = any(code in TRANSIT_CODES for code in codes)
    if has_transit:
        required_ts = {"VAT", "CDT", "CLT", "VDT"}
        if not required_ts.issubset(set(codes)):
            missing = sorted(required_ts - set(codes))
            return False, Violation(
                rule_id="L5_INCOMPLETE_TS_BLOCK",
                idx=0,
                from_code="",
                to_code="TS",
                details=f"missing TS milestones: {', '.join(missing)}"
            )
        if codes.count("CLT") != codes.count("VDT"):
            return False, Violation(
                rule_id="L5_UNPAIRED_TS_LEGS",
                idx=0,
                from_code="CLT",
                to_code="VDT",
                details="CLT and VDT counts must be equal"
            )

    return True, None


def evaluate_events(events):
    l1, violation_l1 = evaluate_level1(events)
    if not l1:
        return (
            (False, violation_l1),
            (False, violation_l1),
            (False, violation_l1),
            (False, violation_l1),
            (False, violation_l1),
        )

    l2, violation_l2 = evaluate_level2(events)
    if not l2:
        return (
            (True, None),
            (False, violation_l2),
            (False, violation_l2),
            (False, violation_l2),
            (False, violation_l2),
        )

    l3, violation_l3 = evaluate_level3(events)
    if not l3:
        return (
            (True, None),
            (True, None),
            (False, violation_l3),
            (False, violation_l3),
            (False, violation_l3),
        )

    l4, violation_l4 = evaluate_level4(events)
    if not l4:
        return (
            (True, None),
            (True, None),
            (True, None),
            (False, violation_l4),
            (False, violation_l4),
        )

    l5, violation_l5 = evaluate_level5(events)
    if not l5:
        return (
            (True, None),
            (True, None),
            (True, None),
            (True, None),
            (False, violation_l5),
        )

    return (True, None), (True, None), (True, None), (True, None), (True, None)


def load_sequences(csv_path, code_field="mapped_status_code", original_code_field="original_status_code"):
    grouped = defaultdict(list)
    has_original_status_col = False
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required_cols = {
            "company",
            "track_number",
            "track_number_type",
            "container_number",
            "event_pos",
            code_field,
            "event_status"
        }
        missing_cols = sorted(required_cols - set(reader.fieldnames or []))
        if missing_cols:
            raise ValueError(
                f"Input has no required columns for validator: {', '.join(missing_cols)}"
            )

        has_original_status_col = original_code_field in (reader.fieldnames or [])
        for row in reader:
            key = (
                row["company"],
                row["track_number"],
                row["track_number_type"],
                row["container_number"],
            )
            row["_event_pos_int"] = int(row["event_pos"])
            grouped[key].append(dict(row))

    return grouped, has_original_status_col


REVIEW_COLUMNS = [
    "chain_should_review",
    "chain_review_codes",
    "chain_review_details",
]


def _split_review_codes(value):
    return [part for part in str(value or "").split("|") if part]


def collect_review_fields(rows):
    chain_codes = set()
    chain_details = []
    seen_chain_details = set()
    chain_should_review = False

    for row in rows:
        row_event_codes = _split_review_codes(row.get("event_review_codes"))
        row_chain_codes = _split_review_codes(row.get("chain_review_codes"))
        if row_event_codes or row_chain_codes:
            chain_should_review = True
        if str(row.get("event_should_review", "")).strip() == "1":
            chain_should_review = True
        if str(row.get("chain_should_review", "")).strip() == "1":
            chain_should_review = True

        for code in row_event_codes:
            chain_codes.add(code)

        for code in row_chain_codes:
            chain_codes.add(code)

        chain_detail = str(row.get("chain_review_details", "") or "").strip()
        if not chain_detail:
            chain_detail = str(row.get("event_review_details", "") or "").strip()
        if chain_detail and chain_detail not in seen_chain_details:
            seen_chain_details.add(chain_detail)
            chain_details.append(chain_detail)

    return [
        int(chain_should_review),
        "|".join(sorted(chain_codes)),
        " || ".join(chain_details),
    ]


def get_skip_reason(company, events):
    if company in CURRENT_STATUS_ONLY_COMPANIES:
        return "SKIP_CURRENT_STATUS_ONLY_SOURCE"
    if len(events) <= 1:
        return "SKIP_SINGLE_EVENT_CHAIN"
    return ""


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input", default=str(MAPPED_DATAMART_CMA_CGM)
    )
    parser.add_argument(
        "--output",
        default=str(VALIDATION_RESULTS_CMA_CGM),
    )
    parser.add_argument(
        "--output-failed-l123",
        default="",
    )
    parser.add_argument("--code-field", default="event_status_code")
    parser.add_argument("--original-code-field", default="event_status_code_original")
    parser.add_argument(
        "--include-review-fields",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    args = parser.parse_args(argv)

    grouped, has_original_status_col = load_sequences(
        args.input,
        code_field=args.code_field,
        original_code_field=args.original_code_field,
    )

    total = 0
    evaluated = 0
    skipped = 0
    pass_l1 = 0
    pass_l2 = 0
    pass_l3 = 0
    pass_l4 = 0
    pass_l5 = 0

    violations_l1 = Counter()
    violations_l2 = Counter()
    violations_l3 = Counter()
    violations_l4 = Counter()
    violations_l5 = Counter()

    output_header = [
        "company",
        "track_number",
        "track_number_type",
        "container_number",
        "sequence_length",
        "sequence_codes",
        "has_transport_anomaly",
        "transport_anomaly_rule",
        "has_location_anomaly",
        "location_anomaly_rule",
        "has_post_final_anomaly",
        "post_final_anomaly_rule",
        "has_edge_anomaly",
        "edge_anomaly_rule",
        "is_skipped",
        "skip_reason",
        "pass_level_1",
        "pass_level_2",
        "pass_level_3",
        "pass_level_4",
        "pass_level_5",
        "strict_final_pass",
        "is_worsened",
        "violation_level_1",
        "violation_level_2",
        "violation_level_3",
        "violation_level_4",
        "violation_level_5"
    ]
    if args.include_review_fields:
        output_header.extend(REVIEW_COLUMNS)

    with ExitStack() as stack:
        out_f = stack.enter_context(open(args.output, "w", newline="", encoding="utf-8"))
        writer = csv.writer(out_f)
        failed_writer = None
        if args.output_failed_l123:
            fail_f = stack.enter_context(open(args.output_failed_l123, "w", newline="", encoding="utf-8"))
            failed_writer = csv.writer(fail_f)

        writer.writerow(output_header)
        if failed_writer is not None:
            failed_writer.writerow(output_header)

        for key, rows in grouped.items():
            company, track, track_type, container = key
            rows.sort(key=lambda row: row["_event_pos_int"], reverse=True)
            events = build_event_context(rows, args.code_field)
            codes = [event["code"] for event in events]
            if not codes:
                continue

            review_fields = (
                collect_review_fields(rows)
                if args.include_review_fields
                else []
            )
            total += 1
            skip_reason = get_skip_reason(company, events)
            transport_anomaly = detect_transport_anomaly(events)
            location_anomaly = detect_location_anomaly(events)
            post_final_anomaly = detect_post_final_anomaly(events)
            edge_anomaly = detect_edge_anomaly(events)
            if skip_reason:
                skipped += 1
                row_data = [
                    company,
                    track,
                    track_type,
                    container,
                    len(codes),
                    " > ".join(codes),
                    int(transport_anomaly is not None),
                    format_violation(transport_anomaly),
                    int(location_anomaly is not None),
                    format_violation(location_anomaly),
                    int(post_final_anomaly is not None),
                    format_violation(post_final_anomaly),
                    int(edge_anomaly is not None),
                    format_violation(edge_anomaly),
                    1,
                    skip_reason,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    f"{skip_reason}|idx=0|->|sequence skipped from validation",
                    "",
                    "",
                    "",
                    ""
                ]
                row_data.extend(review_fields)
                writer.writerow(row_data)
                if failed_writer is not None:
                    failed_writer.writerow(row_data)
                continue

            evaluated += 1
            l1, l2, l3, l4, l5 = evaluate_events(events)

            if l1[0]:
                pass_l1 += 1
            else:
                violations_l1[l1[1].rule_id] += 1
            if l2[0]:
                pass_l2 += 1
            else:
                violations_l2[l2[1].rule_id] += 1
            if l3[0]:
                pass_l3 += 1
            else:
                violations_l3[l3[1].rule_id] += 1
            if l4[0]:
                pass_l4 += 1
            else:
                violations_l4[l4[1].rule_id] += 1
            if l5[0]:
                pass_l5 += 1
            else:
                violations_l5[l5[1].rule_id] += 1

            is_worsened = 0
            if has_original_status_col:
                old_events = build_event_context(rows, args.original_code_field)
                old_l1, old_l2, old_l3, _, _ = evaluate_events(old_events)
                is_worsened = int((old_l1[0] and old_l2[0] and old_l3[0])
                                    and not (l1[0] and l2[0] and l3[0]))

            row_data = [
                company,
                track,
                track_type,
                container,
                len(codes),
                " > ".join(codes),
                int(transport_anomaly is not None),
                format_violation(transport_anomaly),
                int(location_anomaly is not None),
                format_violation(location_anomaly),
                int(post_final_anomaly is not None),
                format_violation(post_final_anomaly),
                int(edge_anomaly is not None),
                format_violation(edge_anomaly),
                0,
                "",
                int(l1[0]),
                int(l2[0]),
                int(l3[0]),
                int(l4[0]),
                int(l5[0]),
                int(l5[0]),
                is_worsened,
                format_violation(l1[1]),
                format_violation(l2[1]),
                format_violation(l3[1]),
                format_violation(l4[1]),
                format_violation(l5[1])
            ]
            row_data.extend(review_fields)
            writer.writerow(row_data)

            if failed_writer is not None and not (l1[0] and l2[0] and l3[0]):
                failed_writer.writerow(row_data)

    print("Total sequences:", total)
    print("Evaluated sequences:", evaluated)
    print("Skipped sequences:", skipped)
    print("Level 1 pass:", pass_l1, f"({pass_l1 / evaluated:.4f})" if evaluated else "")
    print("Level 2 pass:", pass_l2, f"({pass_l2 / evaluated:.4f})" if evaluated else "")
    print("Level 3 pass:", pass_l3, f"({pass_l3 / evaluated:.4f})" if evaluated else "")
    print("Level 4 pass:", pass_l4, f"({pass_l4 / evaluated:.4f})" if evaluated else "")
    print("Level 5 pass:", pass_l5, f"({pass_l5 / evaluated:.4f})" if evaluated else "")

    print("\nTop violations L1:")
    for rule, cnt in violations_l1.most_common(10):
        print(" ", rule, cnt)
    print("\nTop violations L2:")
    for rule, cnt in violations_l2.most_common(10):
        print(" ", rule, cnt)
    print("\nTop violations L3:")
    for rule, cnt in violations_l3.most_common(10):
        print(" ", rule, cnt)
    print("\nTop violations L4:")
    for rule, cnt in violations_l4.most_common(10):
        print(" ", rule, cnt)
    print("\nTop violations L5:")
    for rule, cnt in violations_l5.most_common(10):
        print(" ", rule, cnt)

    print("\nSaved:", args.output)
    if args.output_failed_l123:
        print("Saved failed/skip L1-L3:", args.output_failed_l123)


if __name__ == "__main__":
    main()
    
    
