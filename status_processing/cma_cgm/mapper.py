from datetime import datetime

from ..container_state import ContainerPhaseTracker
from ..sequence_mapper_base import SequenceMapperBase

from .chain_context import CmaCgmChainContextMixin
from .review import CmaCgmReviewMixin
from .rules import CmaCgmMappingRulesMixin


class CmaCgmMapper(
    CmaCgmReviewMixin,
    CmaCgmMappingRulesMixin,
    CmaCgmChainContextMixin,
    SequenceMapperBase,
):
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

    HISTORICAL_OUTLIER_CUTOFF = datetime(2024, 1, 1)
    FRESH_CONTEXT_START = datetime(2025, 1, 1)
    FRESH_CONTEXT_END = datetime(2027, 1, 1)
    DELIVERY_TAIL_CODES = {"CGO", "CDC", "CER"}
    MARINE_RAW_STATUSES = {
        "loaded on board",
        "vessel departure",
        "vessel arrival",
        "discharged",
        "discharged in transhipment",
    }


    LOCAL_WINDOW = 3

    MAIN_CODES = {"CLL", "VDL"}
    TS_CODES = {"VAT", "CDT", "CLT", "VDT"}
    FINAL_CODES = {"VAD", "CDD"}
    MARINE_CODES = MAIN_CODES | TS_CODES | FINAL_CODES
    DELIVERY_CODES = {"CGO", "CDC", "CER"}
    IMPORT_LTS_RAW_STATUSES = {
        "container in transit for import",
        "received for import transfer",
        "full load on rail for import",
        "train arrival for import",
        "import unload full from rail",
    }
    EXPORT_LTS_RAW_STATUSES = {
        "container in transit for export",
        "received for export transfer",
        "full load on rail for export",
        "train arrival for export",
        "export unload full from rail",
    }
    IMPORT_TAIL_RAW_STATUS_CODES = {
        "gate out to consignee": (
            "CGO",
            "RULE_GATE_OUT_IMPORT_AFTER_IMPORT_LTS",
        ),
        "container to consignee": (
            "CGO",
            "RULE_CONTAINER_TO_CONSIGNEE_AFTER_IMPORT_LTS",
        ),
        "container empty returned": (
            "CER",
            "RULE_EMPTY_RETURN_AFTER_IMPORT_LTS",
        ),
        "empty in depot": (
            "CER",
            "RULE_EMPTY_DEPOT_AFTER_IMPORT_LTS",
        ),
    }
    EXPORT_PREPARATION_RAW_STATUSES = {
        "empty picked-up at depot",
        "container to shipper",
        "gate in at port terminal",
        "discharged empty at shipper",
        "loaded full at shipper",
        "ready to be loaded",
    }
    EXPORT_PREPARATION_CLEAR_CODES = {
        "empty picked-up at depot": "CEP",
        "container to shipper": "CEP",
        "gate in at port terminal": "CGI",
        "ready to be loaded": "CGI",
    }
    IMPORT_TAIL_HINT_RAW_STATUSES = {
        "discharged full at consignee",
        "loaded empty at consignee",
    }
    EMPTY_REPOSITION_RAW_STATUSES = {
        "loaded on board",
        "discharged",
        "discharged in transhipment",
    }
    REVIEWABLE_UNK_REASONS = {
        "RULE_DEPARTURE_BEFORE_SAME_VESSEL_LOAD_UNK",
        "RULE_POL_DEPARTURE_WITH_INTERVENING_FOREIGN_LOAD_UNK",
        "RULE_SANDWICHED_DIFFERENT_VESSEL_UNK",
        "RULE_VESSEL_ARRIVAL_AFTER_FOREIGN_LEG_UNK",
        "RULE_LOADED_ON_BOARD_AFTER_SAME_DEPARTURE_UNK",
        "RULE_MARINE_EVENT_AFTER_DELIVERY_TAIL_UNK",
        "RULE_DISCHARGED_AFTER_FINAL_ARRIVAL_OUTSIDE_POD_UNK",
        "RULE_LOADED_ON_BOARD_AFTER_FINAL_ARRIVAL_UNK",
        "RULE_VESSEL_DEPARTURE_AFTER_FINAL_ARRIVAL_UNK",
        "RULE_VESSEL_ARRIVAL_AFTER_FINAL_ARRIVAL_UNK",
    }
    AFTER_FINAL_REVIEWABLE_REASONS = {
        "RULE_DISCHARGED_AFTER_FINAL_ARRIVAL_OUTSIDE_POD_UNK",
        "RULE_LOADED_ON_BOARD_AFTER_FINAL_ARRIVAL_UNK",
        "RULE_VESSEL_DEPARTURE_AFTER_FINAL_ARRIVAL_UNK",
        "RULE_VESSEL_ARRIVAL_AFTER_FINAL_ARRIVAL_UNK",
    }
    NON_REVIEWABLE_UNK_REASONS = {
        "DIRECT_MAP",
        "RULE_DUPLICATE_NON_ACTUAL_UNK",
    }
    CHAIN_ONLY_REVIEWABLE_REASONS = {
        "RULE_POL_DEPARTURE_WITH_INTERVENING_FOREIGN_LOAD_UNK",
    }
    CLEAN_REASON_OVERRIDES = {
        "RULE_POL_DEPARTURE_WITH_INTERVENING_FOREIGN_LOAD_UNK": (
            "RULE_VESSEL_DEPARTURE_POL_MAIN"
        ),
    }
    EVENT_ANNOTATION_COLUMNS = (
        "event_should_review",
        "event_review_codes",
        "event_review_details",
    )
    CHAIN_ANNOTATION_COLUMNS = (
        "chain_should_review",
        "chain_review_codes",
        "chain_review_details",
    )
    ANNOTATION_COLUMNS = EVENT_ANNOTATION_COLUMNS + CHAIN_ANNOTATION_COLUMNS


    def __init__(self):
        self.phase_tracker = ContainerPhaseTracker()
        self._last_event_annotations = []
        self._last_chain_annotation = {}


    def map_seq(self, ordered_events):
        mapped_codes, mapped_reasons = self._map_seq_core(ordered_events)
        self._reset_review_state(len(ordered_events))
        self._annotate_chain_consistency(ordered_events, mapped_codes, mapped_reasons)
        self._finalize_review_annotations(len(ordered_events))
        return mapped_codes, mapped_reasons
