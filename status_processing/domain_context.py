from datetime import datetime

from .sequence_mapper_base import SequenceMapperBase


EXPORT_PREPARATION_CODES = {"CEP", "CPS", "CGI"}
LOAD_CODES = {"CLL", "CLT"}
DEPART_CODES = {"VDL", "VDT"}
ARRIVE_CODES = {"VAT", "VAD"}
DISCHARGE_CODES = {"CDT", "CDD"}
DELIVERY_TAIL_CODES = {"CGO", "CDC", "CER"}

ACTION_PREP = "prep"
ACTION_LOAD = "load"
ACTION_DEPART = "depart"
ACTION_ARRIVE = "arrive"
ACTION_DISCHARGE = "discharge"
ACTION_DELIVER = "deliver"
ACTION_OTHER = "other"


def same_non_empty_text(left, right):
    if left is None or right is None:
        return False
    l = str(left).strip().upper()
    r = str(right).strip().upper()
    if not l or not r or l == "\\N" or r == "\\N":
        return False
    return l == r


def has_pol_location_index_context(row):
    event_loc = SequenceMapperBase.parse_nullable_int(row.get("event_location_idx"))
    pol_loc = SequenceMapperBase.parse_nullable_int(row.get("pol_location_idx"))
    return event_loc is not None and pol_loc is not None


def is_event_at_pod(row):
    event_loc = SequenceMapperBase.parse_nullable_int(row.get("event_location_idx"))
    pod_loc = SequenceMapperBase.parse_nullable_int(row.get("pod_location_idx"))
    return event_loc is not None and pod_loc is not None and event_loc == pod_loc


def is_event_at_pol(row):
    event_loc = SequenceMapperBase.parse_nullable_int(row.get("event_location_idx"))
    pol_loc = SequenceMapperBase.parse_nullable_int(row.get("pol_location_idx"))
    return event_loc is not None and pol_loc is not None and event_loc == pol_loc


def is_same_transport_call(left, right):
    if not same_non_empty_text(left.get("location_locode"), right.get("location_locode")):
        return False
    return same_non_empty_text(left.get("vessel"), right.get("vessel")) or same_non_empty_text(left.get("voyage"), right.get("voyage"))


def parse_event_datetime(value):
    raw = (value or "").strip()
    if not raw or raw == "\\N":
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None


def is_actual_event(row):
    actual = SequenceMapperBase.parse_nullable_int(row.get("event_actual"))
    return actual == 1


def action_family(code):
    if code in EXPORT_PREPARATION_CODES:
        return ACTION_PREP
    if code in LOAD_CODES:
        return ACTION_LOAD
    if code in DEPART_CODES:
        return ACTION_DEPART
    if code in ARRIVE_CODES:
        return ACTION_ARRIVE
    if code in DISCHARGE_CODES:
        return ACTION_DISCHARGE
    if code in DELIVERY_TAIL_CODES:
        return ACTION_DELIVER
    return ACTION_OTHER


def build_event_context(rows, code_field):
    count = len(rows)
    events = []
    for row in rows:
        events.append(
            {
                "row": row,
                "code": row.get(code_field, ""),
                "raw_status": SequenceMapperBase.normalize_status(row.get("event_status", "")),
                "has_pol_location_index_context": has_pol_location_index_context(row),
                "at_pol": is_event_at_pol(row),
                "at_pod": is_event_at_pod(row)
            }
        )

    next_barge_idx = [None] * count
    next_vessel_idx = [None] * count
    next_same_call_departure = [False] * count
    prev_same_call_loaded = [False] * count

    next_barge = None
    next_vessel = None
    for idx in range(count - 1, -1, -1):
        next_barge_idx[idx] = next_barge
        next_vessel_idx[idx] = next_vessel

        raw_status = events[idx]["raw_status"]
        if raw_status in {"barge departure", "barge arrival"}:
            next_barge = idx
        if raw_status in {"vessel departure", "vessel arrival"}:
            next_vessel = idx

    for idx in range(count - 1):
        if events[idx + 1]["raw_status"] == "vessel departure":
            next_same_call_departure[idx] = is_same_transport_call(rows[idx], rows[idx + 1])

    for idx in range(1, count):
        if events[idx - 1]["raw_status"] == "loaded on board":
            prev_same_call_loaded[idx] = is_same_transport_call(rows[idx - 1], rows[idx])

    for idx in range(count):
        next_barge = next_barge_idx[idx]
        next_vessel = next_vessel_idx[idx]
        events[idx]["is_barge_context"] = next_barge is not None and (next_vessel is None or next_barge < next_vessel)
        events[idx]["next_same_call_departure"] = next_same_call_departure[idx]
        events[idx]["prev_same_call_loaded"] = prev_same_call_loaded[idx]

    return events
