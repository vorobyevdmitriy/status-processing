class CmaCgmMappingRulesMixin:

    def _map_gate_out_to_consignee(self, state):
        if state in {self.STATE_ARRIVED, self.STATE_DISCHARGED, self.STATE_DELIVERED}:
            return "CGO", "RULE_GATE_OUT_IMPORT"
        return "UNK", "RULE_GATE_OUT_WITHOUT_IMPORT_UNK"


    def _has_delivery_tail_started(self, mapped_codes):
        return bool(self.DELIVERY_TAIL_CODES & set(mapped_codes))


    def _map_ready_to_be_loaded(self, chain_ctx, idx):
        if chain_ctx["has_pol_location_index_context"][idx]:
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
        if self._has_delivery_tail_started(chain_ctx.get("mapped_codes_so_far", ())):
            return "UNK", "RULE_MARINE_EVENT_AFTER_DELIVERY_TAIL_UNK"
        if chain_ctx["event_at_pod"][idx]:
            return "CDD", "RULE_DISCHARGED_AT_POD"
        if self._is_after_raw_barge_for_discharge(
            chain_ctx["ordered_events"], chain_ctx, idx
        ):
            return "BTS", "RULE_DISCHARGED_AFTER_BARGE_CONTEXT_BTS"
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

        if self._has_delivery_tail_started(mapped_codes):
            return "UNK", "RULE_MARINE_EVENT_AFTER_DELIVERY_TAIL_UNK"

        if "VAD" in mapped_codes:
            return "UNK", "RULE_LOADED_ON_BOARD_AFTER_FINAL_ARRIVAL_UNK"

        if (
            prev_event is not None
            and prev_raw_status == "vessel departure"
            and self._is_same_vessel_or_voyage(prev_event, event)
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

        if chain_ctx["has_pol_location_index_context"][idx]:
            if chain_ctx["event_at_pol"][idx]:
                if self._has_empty_transport_ref(
                    event
                ) and self._is_immediately_before_raw_barge(
                    ordered_events, chain_ctx, idx
                ):
                    return "BTS", "RULE_LOADED_ON_BOARD_POL_EMPTY_TRANSPORT_BEFORE_BARGE_BTS"
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
        if self._has_delivery_tail_started(mapped_codes):
            return "UNK", "RULE_MARINE_EVENT_AFTER_DELIVERY_TAIL_UNK"

        if "VAD" in mapped_codes:
            return "UNK", "RULE_VESSEL_DEPARTURE_AFTER_FINAL_ARRIVAL_UNK"

        if chain_ctx["has_pol_location_index_context"][idx]:
            if chain_ctx["event_at_pol"][idx]:
                if (
                    mapped_codes
                    and mapped_codes[-1] == "CLL"
                    and chain_ctx["prev_is_same_call_loaded"][idx]
                ):
                    return "VDL", "RULE_VESSEL_DEPARTURE_AFTER_POL_MAIN_LOAD"
                if state in {self.STATE_PRE_EXPORT, self.STATE_LOADED}:
                    return "VDL", "RULE_VESSEL_DEPARTURE_POL_MAIN"
                return "VDL", "RULE_VESSEL_DEPARTURE_POL_AFTER_PRE_CARRIAGE"
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
        if self._has_delivery_tail_started(chain_ctx.get("mapped_codes_so_far", ())):
            return "UNK", "RULE_MARINE_EVENT_AFTER_DELIVERY_TAIL_UNK"

        if "VAD" in chain_ctx.get("mapped_codes_so_far", ()):
            return "UNK", "RULE_VESSEL_ARRIVAL_AFTER_FINAL_ARRIVAL_UNK"

        if chain_ctx["event_at_pod"][idx]:
            return "VAD", "RULE_VESSEL_ARRIVAL_POD_MATCH"
        return "VAT", "RULE_VESSEL_ARRIVAL_TS"


    def _map_event(self, state, ordered_events, chain_ctx, idx, mapped_codes):
        chain_ctx["mapped_codes_so_far"] = mapped_codes
        raw_status = chain_ctx["raw_statuses"][idx]

        if (
            raw_status == "vessel departure"
            and chain_ctx["departure_before_same_vessel_load_unk"][idx]
        ):
            return "UNK", "RULE_DEPARTURE_BEFORE_SAME_VESSEL_LOAD_UNK"

        if (
            raw_status == "vessel departure"
            and chain_ctx["pol_departure_with_intervening_foreign_load_unk"][idx]
        ):
            return "UNK", "RULE_POL_DEPARTURE_WITH_INTERVENING_FOREIGN_LOAD_UNK"

        if (
            raw_status in self.MARINE_RAW_STATUSES
            and chain_ctx["sandwiched_different_vessel_unk"][idx]
            and not chain_ctx["transshipment_handoff_discharge"][idx]
        ):
            return "UNK", "RULE_SANDWICHED_DIFFERENT_VESSEL_UNK"

        if raw_status == "loaded on board":
            return self._map_loaded_on_board(
                state, ordered_events, chain_ctx, idx, mapped_codes
            )
        if raw_status == "vessel departure":
            return self._map_vessel_departure(state, chain_ctx, idx, mapped_codes)
        if raw_status == "vessel arrival":
            if chain_ctx["arrival_after_foreign_leg_unk"][idx]:
                return "UNK", "RULE_VESSEL_ARRIVAL_AFTER_FOREIGN_LEG_UNK"
            return self._map_vessel_arrival(chain_ctx, idx)
        if raw_status == "discharged":
            return self._map_discharged(state, chain_ctx, idx)
        if raw_status == "discharged in transhipment":
            if self._has_delivery_tail_started(mapped_codes):
                return "UNK", "RULE_MARINE_EVENT_AFTER_DELIVERY_TAIL_UNK"
            if chain_ctx["event_at_pod"][idx] and "VAD" in mapped_codes:
                return "CDD", "RULE_DIT_AFTER_FINAL_ARRIVAL_AT_POD_CDD"
            if not chain_ctx["event_at_pod"][idx] and self._is_after_raw_barge_for_discharge(
                ordered_events, chain_ctx, idx
            ):
                return "BTS", "RULE_DISCHARGED_AFTER_BARGE_CONTEXT_BTS"
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


    def _map_seq_core(self, ordered_events):
        mapped_codes = []
        mapped_reasons = []
        phase_tracker = self.phase_tracker
        phase_tracker.reset()
        chain_ctx = self._build_chain_context(ordered_events)
        chain_ctx["ordered_events"] = ordered_events

        for idx, _event in enumerate(ordered_events):
            state = phase_tracker.current_phase
            if chain_ctx["historical_outlier_unk"][idx]:
                code = "UNK"
                reason = "RULE_HISTORICAL_OUTLIER_EVENT_UNK"
            elif chain_ctx["duplicate_non_actual_unk"][idx]:
                code = "UNK"
                reason = "RULE_DUPLICATE_NON_ACTUAL_UNK"
            else:
                code, reason = self._map_event(
                    state, ordered_events, chain_ctx, idx, mapped_codes
                )

            mapped_codes.append(code)
            mapped_reasons.append(reason)
            phase_tracker.advance(code)

        return mapped_codes, mapped_reasons
