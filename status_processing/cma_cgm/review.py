from ..domain_context import same_non_empty_text


class CmaCgmReviewMixin:

    @staticmethod
    def _clean_text(value):
        raw = str(value or "").strip().upper()
        if not raw or raw == "\\N":
            return ""
        return raw


    @classmethod
    def _review_code_from_reason(cls, reason):
        code = str(reason or "")
        if code.startswith("RULE_"):
            code = code[5:]
        if code.endswith("_UNK"):
            code = code[:-4]
        return code


    def _route_key(self, row):
        vessel = self._clean_text(row.get("vessel"))
        voyage = self._clean_text(row.get("voyage"))
        if vessel:
            return ("VESSEL", vessel)
        if voyage:
            return ("VOYAGE", voyage)
        return None


    def _same_route_if_present(self, left, right):
        left_key = self._route_key(left)
        right_key = self._route_key(right)
        if left_key is None or right_key is None:
            return True
        return (
            same_non_empty_text(left.get("vessel"), right.get("vessel"))
            or same_non_empty_text(left.get("voyage"), right.get("voyage"))
        )


    def _has_prior_delivery_tail(self, codes, idx):
        return any(code in self.DELIVERY_CODES for code in codes[:idx])


    def _reset_review_state(self, count):
        self._event_review_codes = [set() for _ in range(count)]
        self._event_review_details = [[] for _ in range(count)]
        self._suppress_event_consistency_checks = set()
        self._misplaced_final_arrival_indices = set()
        self._demoted_chain_head_indices = set()
        self._inverted_pre_export_marine_indices = set()


    def _add_review(self, idx, code, details):
        self._event_review_codes[idx].add(code)
        if details and details not in self._event_review_details[idx]:
            self._event_review_details[idx].append(details)


    def _finalize_review_annotations(self, count):
        event_annotations = []
        for idx in range(count):
            event_codes = "|".join(sorted(self._event_review_codes[idx]))
            event_details = " || ".join(self._event_review_details[idx])
            event_should_review = "1" if event_codes else "0"
            row_annotation = {
                "event_should_review": event_should_review,
                "event_review_codes": event_codes,
                "event_review_details": event_details,
            }
            event_annotations.append(row_annotation)
        return event_annotations


    def _nearby_prev(
        self,
        ordered_events,
        codes,
        idx,
        candidate_codes,
        *,
        same_loc=False,
        same_route=False,
    ):
        start = max(0, idx - self.LOCAL_WINDOW)
        event = ordered_events[idx]
        for prev_idx in range(idx - 1, start - 1, -1):
            if prev_idx in self._inverted_pre_export_marine_indices:
                continue
            if codes[prev_idx] not in self.MARINE_CODES:
                continue
            if codes[prev_idx] not in candidate_codes:
                return False
            prev_event = ordered_events[prev_idx]
            if same_loc and not self._same_location_idx(prev_event, event):
                return False
            if same_route and not self._same_route_if_present(prev_event, event):
                return False
            return True
        return False


    def _nearby_next(
        self,
        ordered_events,
        codes,
        idx,
        candidate_codes,
        *,
        same_loc=False,
        same_route=False,
    ):
        end = min(len(codes), idx + self.LOCAL_WINDOW + 1)
        event = ordered_events[idx]
        for next_idx in range(idx + 1, end):
            if next_idx in self._inverted_pre_export_marine_indices:
                continue
            if codes[next_idx] not in self.MARINE_CODES:
                continue
            if codes[next_idx] not in candidate_codes:
                return False
            next_event = ordered_events[next_idx]
            if same_loc and not self._same_location_idx(event, next_event):
                return False
            if same_route and not self._same_route_if_present(event, next_event):
                return False
            return True
        return False


    def _clear_marine_code(self, chain_ctx, idx, raw_status):
        has_pol_location_index_context = chain_ctx["has_pol_location_index_context"][idx]
        event_at_pol = chain_ctx["event_at_pol"][idx]
        event_at_pod = chain_ctx["event_at_pod"][idx]

        if raw_status == "loaded on board":
            if has_pol_location_index_context:
                return "CLL" if event_at_pol else "CLT"
            return ""
        if raw_status == "vessel departure":
            if has_pol_location_index_context:
                return "VDL" if event_at_pol else "VDT"
            return ""
        if raw_status == "vessel arrival":
            if event_at_pod:
                return "VAD"
            if has_pol_location_index_context:
                return "VAT"
            return ""
        if raw_status == "discharged":
            if event_at_pod:
                return "CDD"
            if has_pol_location_index_context:
                return "CDT"
            return ""
        if raw_status == "discharged in transhipment":
            return "CDT"
        return ""


    def _find_later_foreign_export_block(self, ordered_events, raw_statuses, chain_ctx, idx):
        final_event = ordered_events[idx]
        for later_idx in range(idx + 1, len(ordered_events)):
            raw_status = raw_statuses[later_idx]
            later_event = ordered_events[later_idx]
            is_export_restart = (
                raw_status in self.EXPORT_PREPARATION_RAW_STATUSES
                or (
                    raw_status in {"loaded on board", "vessel departure"}
                    and chain_ctx["event_at_pol"][later_idx]
                )
            )
            if not is_export_restart:
                continue
            if self._same_location_idx(final_event, later_event):
                continue
            if self._same_route_if_present(final_event, later_event):
                continue
            return later_idx
        return None


    def _is_export_restart_event(self, raw_status, chain_ctx, idx):
        if raw_status in self.EXPORT_PREPARATION_RAW_STATUSES:
            return True
        return (
            raw_status == "loaded on board" and chain_ctx["event_at_pol"][idx]
        )


    def _find_export_restart_idx(self, raw_statuses, chain_ctx, start_idx):
        for idx in range(start_idx, len(raw_statuses)):
            if self._is_export_restart_event(raw_statuses[idx], chain_ctx, idx):
                return idx
        return None


    def _empty_reposition_segment_before_commercial_pol(
        self, raw_statuses, chain_ctx, restart_idx, event_idx
    ):
        if raw_statuses[restart_idx] != "loaded on board":
            return ()
        if not chain_ctx["event_at_pol"][restart_idx]:
            return ()
        if raw_statuses[event_idx] not in self.EMPTY_REPOSITION_RAW_STATUSES:
            return ()
        if chain_ctx["event_at_pol"][event_idx] or chain_ctx["event_at_pod"][event_idx]:
            return ()

        segment_indices = []
        reposition_indices = []
        for idx in range(restart_idx):
            raw_status = raw_statuses[idx]
            if raw_status in self.EXPORT_PREPARATION_RAW_STATUSES:
                segment_indices.append(idx)
                continue
            if (
                raw_status in self.EMPTY_REPOSITION_RAW_STATUSES
                and not chain_ctx["event_at_pol"][idx]
                and not chain_ctx["event_at_pod"][idx]
            ):
                segment_indices.append(idx)
                reposition_indices.append(idx)
                continue
            return ()

        if event_idx not in reposition_indices:
            return ()
        if len(reposition_indices) < 4:
            return ()

        load_count = sum(raw_statuses[idx] == "loaded on board" for idx in reposition_indices)
        discharge_count = sum(
            raw_statuses[idx] in {"discharged", "discharged in transhipment"}
            for idx in reposition_indices
        )
        if load_count < 2 or discharge_count < 2:
            return ()
        if not any(
            raw_statuses[idx] in self.EXPORT_PREPARATION_RAW_STATUSES
            for idx in segment_indices
        ):
            return ()

        return tuple(segment_indices)


    def _mark_historical_outlier_events(self, ordered_events, reasons):
        changed = False
        for idx, reason in enumerate(reasons):
            if reason != "RULE_HISTORICAL_OUTLIER_EVENT_UNK":
                continue
            event = ordered_events[idx]
            self._add_review(
                idx,
                "HISTORICAL_OUTLIER_EVENT",
                (
                    f"event_pos={event.get('event_pos')} date={event.get('event_date')} "
                    "is older than 2024-01-01 while the rest of the dated chain "
                    "is within 2025-01-01..2027-01-01"
                ),
            )
            changed = True
        return changed


    def _is_origin_related_restart(self, departure_event, restart_event, chain_ctx, restart_idx):
        return (
            chain_ctx["event_at_pol"][restart_idx]
            or self._same_location_idx(departure_event, restart_event)
            or same_non_empty_text(
                departure_event.get("location_locode"),
                restart_event.get("location_locode"),
            )
        )


    def _find_later_export_restart_and_same_vessel_load(
        self, ordered_events, raw_statuses, chain_ctx, departure_idx
    ):
        departure_event = ordered_events[departure_idx]
        restart_idx = None
        for idx in range(departure_idx + 1, len(raw_statuses)):
            event = ordered_events[idx]
            raw_status = raw_statuses[idx]

            if restart_idx is None:
                if not self._is_export_restart_event(raw_status, chain_ctx, idx):
                    continue
                if not self._is_origin_related_restart(
                    departure_event, event, chain_ctx, idx
                ):
                    continue
                restart_idx = idx

            if raw_status != "loaded on board":
                continue
            if not self._is_same_vessel_or_voyage(departure_event, event):
                continue
            if not self._is_departure_before_loaded(departure_event, event):
                continue
            return restart_idx, idx

        return None


    def _mark_inverted_pre_export_marine_block(
        self, ordered_events, codes, reasons, raw_statuses, chain_ctx
    ):
        changed = False
        for departure_idx, code in enumerate(list(codes)):
            if raw_statuses[departure_idx] != "vessel departure":
                continue
            if code not in {"VDL", "VDT"}:
                continue

            match = self._find_later_export_restart_and_same_vessel_load(
                ordered_events, raw_statuses, chain_ctx, departure_idx
            )
            if match is None:
                continue

            restart_idx, load_idx = match
            departure_event = ordered_events[departure_idx]
            restart_event = ordered_events[restart_idx]
            load_event = ordered_events[load_idx]
            misplaced_indices = [departure_idx]

            for idx in range(departure_idx + 1, restart_idx):
                if raw_statuses[idx] != "vessel arrival":
                    continue
                if codes[idx] not in {"VAT", "VAD"}:
                    continue
                if not self._same_route_if_present(departure_event, ordered_events[idx]):
                    continue
                misplaced_indices.append(idx)

            for idx in misplaced_indices:
                event = ordered_events[idx]
                kept_code = codes[idx]
                self._inverted_pre_export_marine_indices.add(idx)
                self._suppress_event_consistency_checks.add(idx)
                self._add_review(
                    idx,
                    "INVERTED_PRE_EXPORT_MARINE_BLOCK",
                    (
                        f"event_pos={event.get('event_pos')} code={kept_code} "
                        f"raw='{raw_statuses[idx]}' kept_as={kept_code}; appears before "
                        f"export restart event_pos={restart_event.get('event_pos')} "
                        f"and same-vessel load event_pos={load_event.get('event_pos')}; "
                        "likely order inversion"
                    ),
                )
                changed = True

        return changed


    def _mark_misplaced_chain_head_events(
        self, ordered_events, codes, reasons, raw_statuses, chain_ctx
    ):
        changed = False
        marked_empty_reposition_segments = set()
        for idx, code in enumerate(list(codes)):
            code = codes[idx]
            if idx in self._inverted_pre_export_marine_indices:
                continue
            if code == "UNK" or code in {"CEP", "CPS", "CGI"}:
                continue
            if code not in self.MARINE_CODES and code not in self.DELIVERY_CODES:
                continue

            event = ordered_events[idx]
            restart_idx = self._find_later_origin_export_restart_for_event(
                ordered_events, raw_statuses, chain_ctx, idx + 1, event
            )
            if restart_idx is None:
                continue
            if (
                raw_statuses[idx] == "vessel departure"
                and self._has_same_route_arrival_between(
                    ordered_events, raw_statuses, idx, restart_idx
                )
            ):
                continue

            empty_reposition_segment = self._empty_reposition_segment_before_commercial_pol(
                raw_statuses, chain_ctx, restart_idx, idx
            )
            if empty_reposition_segment:
                segment_key = (empty_reposition_segment[0], empty_reposition_segment[-1], restart_idx)
                if segment_key not in marked_empty_reposition_segments:
                    restart_event = ordered_events[restart_idx]
                    for segment_idx in empty_reposition_segment:
                        segment_event = ordered_events[segment_idx]
                        self._add_review(
                            segment_idx,
                            "EMPTY_REPOSITION_BEFORE_COMMERCIAL_POL",
                            (
                                f"event_pos={segment_event.get('event_pos')} raw='{raw_statuses[segment_idx]}' "
                                "kept as pre-commercial empty reposition before POL load "
                                f"event_pos={restart_event.get('event_pos')}"
                            ),
                        )
                        self._suppress_event_consistency_checks.add(segment_idx)
                    marked_empty_reposition_segments.add(segment_key)
                    changed = True
                continue

            restart_event = ordered_events[restart_idx]
            self._demoted_chain_head_indices.add(idx)
            if code in self.MARINE_CODES:
                codes[idx] = "UNK"
                reasons[idx] = "RULE_MISPLACED_CHAIN_HEAD_EVENT_UNK"
            self._add_review(
                idx,
                "MISPLACED_CHAIN_HEAD_EVENT",
                (
                    f"event_pos={event.get('event_pos')} code={code} raw='{raw_statuses[idx]}' "
                    f"appears before export restart event_pos={restart_event.get('event_pos')} "
                    f"raw='{raw_statuses[restart_idx]}'"
                ),
            )
            changed = True

        return changed


    def _find_later_origin_export_restart_for_event(
        self, ordered_events, raw_statuses, chain_ctx, start_idx, head_event
    ):
        for restart_idx in range(start_idx, len(raw_statuses)):
            if not self._is_export_restart_event(raw_statuses[restart_idx], chain_ctx, restart_idx):
                continue
            restart_event = ordered_events[restart_idx]
            if chain_ctx["event_at_pol"][restart_idx] or self._same_location_idx(
                head_event, restart_event
            ):
                return restart_idx
        return None


    def _has_same_route_arrival_between(self, ordered_events, raw_statuses, start_idx, end_idx):
        departure_event = ordered_events[start_idx]
        for idx in range(start_idx + 1, end_idx):
            if raw_statuses[idx] != "vessel arrival":
                continue
            if self._same_route_if_present(departure_event, ordered_events[idx]):
                return True
        return False


    def _mark_misplaced_final_arrivals(
        self, ordered_events, codes, reasons, raw_statuses, chain_ctx
    ):
        changed = False
        for idx, code in enumerate(list(codes)):
            if code != "VAD" or not chain_ctx["event_at_pod"][idx]:
                continue
            later_idx = self._find_later_foreign_export_block(
                ordered_events, raw_statuses, chain_ctx, idx
            )
            if later_idx is None:
                continue

            final_event = ordered_events[idx]
            later_event = ordered_events[later_idx]
            self._misplaced_final_arrival_indices.add(idx)
            self._add_review(
                idx,
                "MISPLACED_FINAL_ARRIVAL_ANCHOR",
                (
                    f"event_pos={final_event.get('event_pos')} VAD at "
                    f"{final_event.get('location_name')} route={self._route_key(final_event)} "
                    f"appears before foreign export/marine block event_pos="
                    f"{later_event.get('event_pos')} raw='{raw_statuses[later_idx]}' "
                    f"location={later_event.get('location_name')} route={self._route_key(later_event)}"
                ),
            )
            changed = True
        return changed


    def _has_prior_final_arrival(self, codes, idx):
        return any(code == "VAD" for code in codes[:idx])


    def _has_prior_misplaced_final_arrival(self, idx):
        return any(anchor_idx < idx for anchor_idx in self._misplaced_final_arrival_indices)


    def _has_prior_demoted_chain_head_event(self, idx):
        return any(head_idx < idx for head_idx in self._demoted_chain_head_indices)


    def _has_prior_inverted_pre_export_marine_event(self, idx):
        return any(
            head_idx < idx for head_idx in self._inverted_pre_export_marine_indices
        )


    def _restore_export_preparation_after_order_anomaly(
        self, ordered_events, codes, reasons, raw_statuses
    ):
        allowed_prior_codes = {"UNK"} | {
            self.EXPORT_PREPARATION_CLEAR_CODES[raw_status]
            for raw_status in self.EXPORT_PREPARATION_RAW_STATUSES
            if self.EXPORT_PREPARATION_CLEAR_CODES.get(raw_status)
        }
        changed = False
        for idx, raw_status in enumerate(raw_statuses):
            if raw_status not in self.EXPORT_PREPARATION_RAW_STATUSES:
                continue
            if reasons[idx] != "RULE_EXPORT_PREPARATION_AFTER_MARINE_UNK":
                continue
            if not (
                self._has_prior_misplaced_final_arrival(idx)
                or self._has_prior_demoted_chain_head_event(idx)
                or self._has_prior_inverted_pre_export_marine_event(idx)
            ):
                continue
            if any(
                code not in allowed_prior_codes
                and prior_idx not in self._inverted_pre_export_marine_indices
                for prior_idx, code in enumerate(codes[:idx])
            ):
                continue
            clear_code = self.EXPORT_PREPARATION_CLEAR_CODES.get(raw_status)
            if not clear_code or clear_code == "UNK":
                continue
            codes[idx] = clear_code
            reasons[idx] = "DIRECT_MAP"
            changed = True
        return changed


    def _restore_tail_fragments_without_import_anchor(self, ordered_events, codes, reasons, raw_statuses):
        tail_mappings = {
            "RULE_GATE_OUT_WITHOUT_IMPORT_UNK": ("CGO", "gate out to consignee"),
            "RULE_EMPTY_RETURN_WITHOUT_IMPORT_UNK": ("CER", "container empty returned"),
        }
        changed = False
        for idx, reason in enumerate(list(reasons)):
            mapping = tail_mappings.get(reason)
            if mapping is None:
                continue
            expected_code, expected_raw = mapping
            if raw_statuses[idx] != expected_raw:
                continue
            if any(code in self.MARINE_CODES for code in codes[idx + 1:]):
                self._add_review(
                    idx,
                    "MISPLACED_IMPORT_TAIL_EVENT",
                    (
                        f"event_pos={ordered_events[idx].get('event_pos')} raw='{raw_statuses[idx]}' "
                        "appears before a later marine block; kept_as=UNK"
                    ),
                )
                changed = True
                continue

            codes[idx] = expected_code
            reasons[idx] = f"RESTORED_TAIL_FRAGMENT_WITHOUT_IMPORT_ANCHOR:{reason}"
            self._add_review(
                idx,
                "IMPORT_TAIL_WITHOUT_IMPORT_ANCHOR",
                (
                    f"event_pos={ordered_events[idx].get('event_pos')} raw='{raw_statuses[idx]}' "
                    f"restored_as={expected_code}; missing VAD/CDD import anchor in partial chain"
                ),
            )
            changed = True
        return changed


    def _nearest_non_barge_marine_idx(self, codes, start, step):
        idx = start
        while 0 <= idx < len(codes):
            code = codes[idx]
            if code in self.MARINE_CODES and code != "BTS":
                return idx
            if code not in {"UNK", "BTS", "LTS"}:
                return None
            idx += step
        return None


    def _mark_barge_intrusions(self, ordered_events, codes, reasons, raw_statuses):
        changed = False
        for idx, code in enumerate(list(codes)):
            if code != "BTS" and "barge" not in raw_statuses[idx]:
                continue
            prev_idx = self._nearest_non_barge_marine_idx(codes, idx - 1, -1)
            next_idx = self._nearest_non_barge_marine_idx(codes, idx + 1, 1)
            if prev_idx is None or next_idx is None:
                continue
            if codes[prev_idx] not in {"VDL", "VDT"}:
                continue
            if codes[next_idx] not in {"VAT", "VAD"}:
                continue

            codes[idx] = "UNK"
            reasons[idx] = "RULE_BARGE_INTRUSION_IN_MARINE_LEG_UNK"
            self._add_review(
                idx,
                "BARGE_INTRUSION_IN_MARINE_LEG",
                (
                    f"event_pos={ordered_events[idx].get('event_pos')} raw='{raw_statuses[idx]}' "
                    f"interrupts marine leg {codes[prev_idx]} event_pos="
                    f"{ordered_events[prev_idx].get('event_pos')} -> {codes[next_idx]} "
                    f"event_pos={ordered_events[next_idx].get('event_pos')}"
                ),
            )
            changed = True
        return changed


    def _mark_contextual_unk_events(self, ordered_events, codes, reasons, raw_statuses):
        changed = False
        for idx, code in enumerate(codes):
            reason = reasons[idx]
            if code != "UNK" or reason in self.NON_REVIEWABLE_UNK_REASONS:
                continue
            if self._event_review_codes[idx]:
                continue
            review_code = self._review_code_from_reason(reason)
            self._add_review(
                idx,
                review_code,
                (
                    f"event_pos={ordered_events[idx].get('event_pos')} raw='{raw_statuses[idx]}' "
                    f"mapped_to=UNK by {reason}"
                ),
            )
            changed = True
        return changed


    def _clean_restored_reason(self, chain_ctx, idx, raw_status, clear_code):
        if raw_status == "loaded on board":
            if chain_ctx["event_at_pol"][idx]:
                return "RULE_LOADED_ON_BOARD_POL_MAIN_VESSEL"
            return "RULE_LOADED_ON_BOARD_OUTSIDE_POL_TS"
        if raw_status == "vessel departure":
            if chain_ctx["event_at_pol"][idx]:
                return "RULE_VESSEL_DEPARTURE_POL_MAIN"
            return "RULE_VESSEL_DEPARTURE_OUTSIDE_POL_TS"
        if raw_status == "vessel arrival":
            if chain_ctx["event_at_pod"][idx]:
                return "RULE_VESSEL_ARRIVAL_POD_MATCH"
            return "RULE_VESSEL_ARRIVAL_TS"
        if raw_status == "discharged":
            if chain_ctx["event_at_pod"][idx]:
                return "RULE_DISCHARGED_AT_POD"
            return "RULE_DISCHARGED_NON_POD_TS"
        if raw_status == "discharged in transhipment":
            return "DIRECT_MAP"
        return f"RESTORED_CLEAR_STATUS:{clear_code}"


    def _restore_reviewable_clear_codes(self, ordered_events, codes, reasons, chain_ctx):
        raw_statuses = chain_ctx["raw_statuses"]
        for idx, code in enumerate(list(codes)):
            if code != "UNK" or reasons[idx] not in self.REVIEWABLE_UNK_REASONS:
                continue

            clear_code = self._clear_marine_code(chain_ctx, idx, raw_statuses[idx])
            if not clear_code:
                continue

            original_reason = reasons[idx]
            codes[idx] = clear_code
            if (
                original_reason in self.AFTER_FINAL_REVIEWABLE_REASONS
                and not self._has_prior_final_arrival(codes, idx)
            ):
                reasons[idx] = self._clean_restored_reason(
                    chain_ctx, idx, raw_statuses[idx], clear_code
                )
                continue

            if original_reason in self.CHAIN_ONLY_REVIEWABLE_REASONS:
                reasons[idx] = self.CLEAN_REASON_OVERRIDES.get(
                    original_reason,
                    f"KEEP_CLEAR_STATUS:{original_reason}",
                )
                self._suppress_event_consistency_checks.add(idx)
                continue

            reasons[idx] = f"KEEP_CLEAR_STATUS_WITH_REVIEW:{original_reason}"
            self._add_review(
                idx,
                self._review_code_from_reason(original_reason),
                (
                    f"event_pos={ordered_events[idx].get('event_pos')} raw='{raw_statuses[idx]}' "
                    f"kept_as={clear_code}; original_reason={original_reason}"
                ),
            )


    def _apply_raw_lts_phase_hints(self, ordered_events, codes, reasons, chain_ctx):
        raw_statuses = chain_ctx["raw_statuses"]
        seen_import_anchor = False
        seen_import_lts_hint = False
        last_import_lts_event_pos = ""
        changed = False

        for idx, raw_status in enumerate(raw_statuses):
            if codes[idx] in self.FINAL_CODES:
                seen_import_anchor = True

            if raw_status in self.IMPORT_LTS_RAW_STATUSES and codes[idx] == "LTS":
                seen_import_lts_hint = True
                last_import_lts_event_pos = str(
                    ordered_events[idx].get("event_pos") or idx
                )

            if raw_status in self.EXPORT_LTS_RAW_STATUSES and codes[idx] == "LTS":
                seen_import_lts_hint = False
                last_import_lts_event_pos = ""

            tail_mapping = self.IMPORT_TAIL_RAW_STATUS_CODES.get(raw_status)
            if (
                tail_mapping is None
                or not seen_import_lts_hint
                or seen_import_anchor
            ):
                continue

            expected_code, import_lts_reason = tail_mapping
            if codes[idx] == "UNK":
                codes[idx] = expected_code
                reasons[idx] = import_lts_reason
                changed = True

            if codes[idx] != expected_code:
                continue

            self._add_review(
                idx,
                "IMPORT_TAIL_WITHOUT_IMPORT_ANCHOR",
                (
                    f"event_pos={ordered_events[idx].get('event_pos')} raw='{raw_status}' "
                    f"kept_as={expected_code}; prior_import_lts_event_pos="
                    f"{last_import_lts_event_pos}; missing VAD/CDD import anchor"
                ),
            )
            changed = True

        return changed


    def _mark_intervening_foreign_load_order_reviews(
        self, ordered_events, raw_statuses, chain_ctx
    ):
        changed = False
        for dep_idx, departure_event in enumerate(ordered_events):
            if raw_statuses[dep_idx] != "vessel departure":
                continue
            if not chain_ctx["event_at_pol"][dep_idx]:
                continue

            foreign_load_indices = []
            for later_idx in range(dep_idx + 1, len(ordered_events)):
                later_event = ordered_events[later_idx]
                later_status = raw_statuses[later_idx]
                if later_status == "loaded on board":
                    if not self._is_same_vessel_or_voyage(departure_event, later_event):
                        foreign_load_indices.append(later_idx)
                    continue
                if later_status != "vessel arrival":
                    continue
                if not self._is_same_vessel_or_voyage(departure_event, later_event):
                    continue
                if not foreign_load_indices:
                    break

                for load_idx in foreign_load_indices:
                    load_event = ordered_events[load_idx]
                    self._add_review(
                        load_idx,
                        "INTERVENING_FOREIGN_LOAD_ORDER",
                        (
                            f"event_pos={load_event.get('event_pos')} foreign load appears between "
                            f"POL departure event_pos={departure_event.get('event_pos')} and "
                            f"same-route arrival event_pos={later_event.get('event_pos')}"
                        ),
                    )
                    changed = True
                break
        return changed


    def _mark_swapped_pairs(self, ordered_events, raw_statuses, codes, reasons):
        changed = False
        for idx in range(len(codes) - 1):
            cur = ordered_events[idx]
            nxt = ordered_events[idx + 1]
            cur_raw = raw_statuses[idx]
            next_raw = raw_statuses[idx + 1]

            if (
                cur_raw == "vessel departure"
                and next_raw == "loaded on board"
                and self._same_route_if_present(cur, nxt)
                and self._same_location_idx(cur, nxt)
            ):
                self._add_review(
                    idx,
                    "SWAPPED_DEPARTURE_LOAD_BLOCK",
                    (
                        f"event_pos={cur.get('event_pos')} departure appears before same-location "
                        f"same-route load at event_pos={nxt.get('event_pos')}"
                    ),
                )
                self._add_review(
                    idx + 1,
                    "SWAPPED_DEPARTURE_LOAD_BLOCK",
                    (
                        f"event_pos={nxt.get('event_pos')} load appears after same-location "
                        f"same-route departure at event_pos={cur.get('event_pos')}"
                    ),
                )
                changed = True

            if (
                cur_raw in {"discharged", "discharged in transhipment"}
                and next_raw == "vessel arrival"
                and self._same_route_if_present(cur, nxt)
                and self._same_location_idx(cur, nxt)
            ):
                self._add_review(
                    idx,
                    "SWAPPED_ARRIVAL_DISCHARGE_BLOCK",
                    (
                        f"event_pos={cur.get('event_pos')} discharge appears before same-location "
                        f"same-route arrival at event_pos={nxt.get('event_pos')}"
                    ),
                )
                self._add_review(
                    idx + 1,
                    "SWAPPED_ARRIVAL_DISCHARGE_BLOCK",
                    (
                        f"event_pos={nxt.get('event_pos')} arrival appears after same-location "
                        f"same-route discharge at event_pos={cur.get('event_pos')}"
                    ),
                )
                changed = True

        return changed


    def _route_segments(self, ordered_events, codes):
        segments = []
        current = None

        for idx, code in enumerate(codes):
            if code not in self.MARINE_CODES:
                continue
            key = self._route_key(ordered_events[idx])
            if key is None:
                continue
            if current is None or current["key"] != key:
                current = {"key": key, "indices": [idx]}
                segments.append(current)
                continue
            current["indices"].append(idx)

        return segments


    def _mark_embedded_foreign_route_blocks(self, ordered_events, codes, reasons):
        changed = False
        segments = self._route_segments(ordered_events, codes)
        for seg_idx in range(1, len(segments) - 1):
            prev_seg = segments[seg_idx - 1]
            cur_seg = segments[seg_idx]
            next_seg = segments[seg_idx + 1]
            if prev_seg["key"] != next_seg["key"] or cur_seg["key"] == prev_seg["key"]:
                continue
            if len(cur_seg["indices"]) > 3:
                continue
            for idx in cur_seg["indices"]:
                self._add_review(
                    idx,
                    "FOREIGN_ROUTE_BLOCK_INSIDE_STABLE_CONTEXT",
                    (
                        f"event_pos={ordered_events[idx].get('event_pos')} route={cur_seg['key']} "
                        f"is embedded between stable route={prev_seg['key']}"
                    ),
                )
                changed = True
        return changed


    def _mark_final_order_reviews(self, ordered_events, codes):
        changed = False
        for idx, code in enumerate(codes):
            if code != "VAD":
                continue
            event = ordered_events[idx]
            for prev_idx in range(idx - 1, -1, -1):
                prev_code = codes[prev_idx]
                if prev_code in {"VAD", "VAT", "VDL", "VDT", "CLL", "CLT", "CDT"}:
                    break
                if prev_code != "CDD":
                    continue
                prev_event = ordered_events[prev_idx]
                if not self._same_location_idx(prev_event, event):
                    continue
                review_code = "FINAL_ARRIVAL_AFTER_DISCHARGE"
                self._add_review(
                    prev_idx,
                    review_code,
                    (
                        f"event_pos={prev_event.get('event_pos')} CDD appears before final "
                        f"arrival event_pos={event.get('event_pos')} at same location"
                    ),
                )
                self._add_review(
                    idx,
                    review_code,
                    (
                        f"event_pos={event.get('event_pos')} VAD appears after CDD "
                        f"event_pos={prev_event.get('event_pos')} at same location"
                    ),
                )
                changed = True
                break
        return changed


    def _unsupported_marine_reason(self, ordered_events, codes, idx, chain_ctx):
        code = codes[idx]
        if code not in self.MARINE_CODES:
            return ""

        if self._has_prior_delivery_tail(codes, idx):
            return "MARINE_AFTER_DELIVERY_TAIL"

        at_pol = chain_ctx["event_at_pol"][idx]
        at_pod = chain_ctx["event_at_pod"][idx]

        if code == "CLL":
            if not at_pol:
                return "CLL_OUTSIDE_POL"
            if self._nearby_prev(
                ordered_events,
                codes,
                idx,
                {"VDL", "VDT"},
                same_loc=True,
                same_route=True,
            ):
                return "CLL_AFTER_DEPARTURE"
            return ""

        if code == "VDL":
            if not at_pol:
                return "VDL_OUTSIDE_POL"
            if self._nearby_prev(
                ordered_events,
                codes,
                idx,
                {"CLL"},
                same_loc=True,
                same_route=True,
            ):
                return ""
            if self._nearby_next(
                ordered_events,
                codes,
                idx,
                {"VAT", "VAD"},
                same_route=True,
            ):
                return ""
            return "VDL_WITHOUT_LOCAL_MAIN_LEG"

        if code == "VAT":
            if at_pod:
                return "VAT_AT_POD"
            if self._nearby_prev(
                ordered_events,
                codes,
                idx,
                {"VDL", "VDT"},
                same_route=True,
            ):
                return ""
            if self._nearby_next(
                ordered_events,
                codes,
                idx,
                {"CDT"},
                same_loc=True,
                same_route=True,
            ):
                return ""
            return "VAT_WITHOUT_LOCAL_TS_LEG"

        if code == "CDT":
            if at_pod:
                return "CDT_AT_POD"
            if self._nearby_prev(
                ordered_events,
                codes,
                idx,
                {"VAT"},
                same_loc=True,
                same_route=True,
            ):
                return ""
            if self._nearby_next(
                ordered_events,
                codes,
                idx,
                {"CLT"},
                same_loc=True,
            ):
                return ""
            return "CDT_WITHOUT_LOCAL_TS_HANDOFF"

        if code == "CLT":
            if at_pol:
                return "CLT_AT_POL"
            if self._nearby_prev(
                ordered_events,
                codes,
                idx,
                {"CDT", "VAT"},
                same_loc=True,
            ):
                return ""
            if self._nearby_next(
                ordered_events,
                codes,
                idx,
                {"VDT"},
                same_loc=True,
                same_route=True,
            ):
                return ""
            return "CLT_WITHOUT_LOCAL_TS_HANDOFF"

        if code == "VDT":
            if at_pol:
                return "VDT_AT_POL"
            if self._nearby_prev(
                ordered_events,
                codes,
                idx,
                {"CLT"},
                same_loc=True,
                same_route=True,
            ):
                return ""
            if self._nearby_next(
                ordered_events,
                codes,
                idx,
                {"VAT", "VAD"},
                same_route=True,
            ):
                return ""
            return "VDT_WITHOUT_LOCAL_TS_LEG"

        if code == "VAD":
            if not at_pod:
                return "VAD_OUTSIDE_POD"
            return ""

        if code == "CDD":
            if not at_pod:
                return "CDD_OUTSIDE_POD"
            return ""

        return ""


    def _annotate_chain_consistency(
        self, ordered_events, codes, reasons, chain_context
    ):
        raw_statuses = chain_context["raw_statuses"]
        changed = False

        changed |= self._mark_historical_outlier_events(ordered_events, reasons)
        changed |= self._mark_inverted_pre_export_marine_block(
            ordered_events, codes, reasons, raw_statuses, chain_context
        )
        changed |= self._mark_misplaced_final_arrivals(
            ordered_events, codes, reasons, raw_statuses, chain_context
        )
        changed |= self._mark_misplaced_chain_head_events(
            ordered_events, codes, reasons, raw_statuses, chain_context
        )
        changed |= self._restore_export_preparation_after_order_anomaly(
            ordered_events, codes, reasons, raw_statuses
        )
        self._restore_reviewable_clear_codes(
            ordered_events, codes, reasons, chain_context
        )
        changed |= self._apply_raw_lts_phase_hints(
            ordered_events, codes, reasons, chain_context
        )
        changed |= self._restore_tail_fragments_without_import_anchor(
            ordered_events, codes, reasons, raw_statuses
        )
        changed |= self._mark_barge_intrusions(
            ordered_events, codes, reasons, raw_statuses
        )
        changed |= self._mark_intervening_foreign_load_order_reviews(
            ordered_events, raw_statuses, chain_context
        )
        changed |= self._mark_swapped_pairs(ordered_events, raw_statuses, codes, reasons)
        changed |= self._mark_embedded_foreign_route_blocks(ordered_events, codes, reasons)
        changed |= self._mark_final_order_reviews(ordered_events, codes)
        changed |= self._mark_contextual_unk_events(
            ordered_events, codes, reasons, raw_statuses
        )

        for idx, code in enumerate(list(codes)):
            if code == "UNK":
                continue
            if idx in self._suppress_event_consistency_checks:
                continue
            reason = self._unsupported_marine_reason(
                ordered_events, codes, idx, chain_context
            )
            if reason:
                self._add_review(
                    idx,
                    reason,
                    (
                        f"event_pos={ordered_events[idx].get('event_pos')} code={code} "
                        f"raw='{raw_statuses[idx]}' violates chain consistency rule {reason}"
                    ),
                )
                changed = True

        return changed

