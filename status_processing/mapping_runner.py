import csv
from collections import Counter, defaultdict
from contextlib import ExitStack

from .validation import validator


def copy_events_with_codes(events, codes):
    if len(events) != len(codes):
        raise ValueError("Event context and code sequence lengths differ")
    return [dict(event, code=code) for event, code in zip(events, codes)]


def format_violation(v):
    if v is None:
        return ""
    return f"{v.rule_id}|idx={v.idx}|{v.from_code}->{v.to_code}|{v.details}"


def run_company_mapping(company, input_path, output_events, output_datamart_like, output_chains, mapper):
    chains = defaultdict(list)
    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        input_columns = reader.fieldnames or []
        for row in reader:
            if row.get("company") != company:
                continue
            key = (row["company"], row["track_number"], row["track_number_type"], row["container_number"])
            event_pos = int(row["event_pos"])
            local_row = dict(row)
            local_row["_event_pos_int"] = event_pos
            chains[key].append(local_row)

    total_chains = 0
    evaluated_chains = 0
    skipped_chains = 0

    pass_l1 = 0
    pass_l2 = 0
    pass_l3 = 0

    pass_l1_eval = 0
    pass_l2_eval = 0
    pass_l3_eval = 0

    old_pass_l1 = 0
    old_pass_l2 = 0
    old_pass_l3 = 0

    old_pass_l1_eval = 0
    old_pass_l2_eval = 0
    old_pass_l3_eval = 0

    improved_l3 = 0
    worsened_l3 = 0

    improved_l3_eval = 0
    worsened_l3_eval = 0
    old_unk_events = 0
    unk_events = 0
    total_events = 0
    reason_counts = Counter()

    chain_output = []
    annotation_columns = list(getattr(mapper, "ANNOTATION_COLUMNS", ()))

    for key, evs in chains.items():
        evs.sort(key=lambda r: r["_event_pos_int"], reverse=True)
        mapped_codes, mapped_reasons, event_annotations = mapper.map_seq(evs)
        if len(event_annotations) != len(evs):
            raise ValueError("Event annotations length does not match event count")

        original_codes = []
        for r in evs:
            code = r.get("event_status_code")
            if code is None:
                raise ValueError("Missing original event_status_code")
            code = str(code).strip()
            if not code or code == "\\N":
                raise ValueError("Missing original event_status_code")
            if code not in validator.KNOWN_CODES:
                raise ValueError(f"Unexpected original event_status_code: {code}")
            original_codes.append(code)

        for i, r in enumerate(evs):
            r["mapped_status_code"] = mapped_codes[i]
            r["mapped_reason"] = mapped_reasons[i]
            r["original_status_code"] = original_codes[i]
            annotations = event_annotations[i]
            for col in annotation_columns:
                r[col] = annotations.get(col, "")

        base_events = validator.build_event_context(evs, "mapped_status_code")
        old_events = copy_events_with_codes(base_events, original_codes)
        mapped_events = copy_events_with_codes(base_events, mapped_codes)
        old_l1, old_l2, old_l3, _, _ = validator.evaluate_events(old_events)
        l1, l2, l3, _, _ = validator.evaluate_events(mapped_events)
        skip_reason = validator.get_skip_reason(key[0], mapped_events)

        old_ok = old_l3[0]
        new_ok = l3[0]

        is_skipped = bool(skip_reason)

        for i, r in enumerate(evs):
            r["is_code_changed"] = int(original_codes[i] != mapped_codes[i])
            reason_counts[mapped_reasons[i]] += 1
            total_events += 1
            if original_codes[i] == "UNK":
                old_unk_events += 1
            if mapped_codes[i] == "UNK":
                unk_events += 1

        total_chains += 1
        pass_l1 += 1 if l1[0] else 0
        pass_l2 += 1 if l2[0] else 0
        pass_l3 += 1 if l3[0] else 0

        if is_skipped:
            skipped_chains += 1
        else:
            evaluated_chains += 1
            pass_l1_eval += 1 if l1[0] else 0
            pass_l2_eval += 1 if l2[0] else 0
            pass_l3_eval += 1 if l3[0] else 0

        old_pass_l1 += 1 if old_l1[0] else 0
        old_pass_l2 += 1 if old_l2[0] else 0
        old_pass_l3 += 1 if old_l3[0] else 0

        if not is_skipped:
            old_pass_l1_eval += 1 if old_l1[0] else 0
            old_pass_l2_eval += 1 if old_l2[0] else 0
            old_pass_l3_eval += 1 if old_l3[0] else 0

        if (not old_ok) and new_ok:
            improved_l3 += 1
            if not is_skipped:
                improved_l3_eval += 1
        if old_ok and (not new_ok):
            worsened_l3 += 1
            if not is_skipped:
                worsened_l3_eval += 1

        changed_count = sum(1 for a, b in zip(original_codes, mapped_codes) if a != b)
        changed_share = (changed_count / len(mapped_codes)) if mapped_codes else 0.0

        chain_output.append(
            {
                "company": key[0],
                "track_number": key[1],
                "track_number_type": key[2],
                "container_number": key[3],
                "sequence_length": len(mapped_codes),
                "is_skipped": int(is_skipped),
                "skip_reason": skip_reason,
                "raw_status_sequence": " > ".join(r["event_status"] for r in evs),
                "original_code_sequence": " > ".join(original_codes),
                "mapped_code_sequence": " > ".join(mapped_codes),
                "changed_codes_count": changed_count,
                "changed_codes_share": round(changed_share, 6),
                "old_pass_level_1": int(old_l1[0]),
                "old_pass_level_2": int(old_l2[0]),
                "old_pass_level_3": int(old_l3[0]),
                "pass_level_1": int(l1[0]),
                "pass_level_2": int(l2[0]),
                "pass_level_3": int(l3[0]),
                "violation_level_1": format_violation(l1[1]),
                "violation_level_2": format_violation(l2[1]),
                "violation_level_3": format_violation(l3[1])
            }
        )

    event_columns = (
        input_columns
        + ["original_status_code", "mapped_status_code", "is_code_changed", "mapped_reason"]
        + [col for col in annotation_columns if col not in input_columns]
    )

    datamart_like_columns = list(input_columns)
    if "event_status_code_original" not in datamart_like_columns:
        if "event_status_code" in datamart_like_columns:
            idx = datamart_like_columns.index("event_status_code") + 1
            datamart_like_columns.insert(idx, "event_status_code_original")
        else:
            datamart_like_columns.append("event_status_code_original")

    if "mapped_reason" not in datamart_like_columns:
        if "event_status_code_original" in datamart_like_columns:
            idx = datamart_like_columns.index("event_status_code_original") + 1
            datamart_like_columns.insert(idx, "mapped_reason")
        elif "event_status_code" in datamart_like_columns:
            idx = datamart_like_columns.index("event_status_code") + 1
            datamart_like_columns.insert(idx, "mapped_reason")
        else:
            datamart_like_columns.append("mapped_reason")

    for col in annotation_columns:
        if col not in datamart_like_columns:
            datamart_like_columns.append(col)

    with ExitStack() as stack:
        event_writer = None
        if output_events:
            f_events = stack.enter_context(open(output_events, "w", newline="", encoding="utf-8"))
            event_writer = csv.DictWriter(f_events, fieldnames=event_columns)
            event_writer.writeheader()

        f_datamart = stack.enter_context(open(output_datamart_like, "w", newline="", encoding="utf-8"))
        datamart_writer = csv.DictWriter(f_datamart, fieldnames=datamart_like_columns)
        datamart_writer.writeheader()

        for key in sorted(chains.keys()):
            evs = chains[key]
            evs.sort(key=lambda r: r["_event_pos_int"], reverse=True)
            for r in evs:
                if event_writer is not None:
                    event_out = {k: r.get(k, "") for k in input_columns}
                    event_out["original_status_code"] = r.get("original_status_code", "")
                    event_out["mapped_status_code"] = r.get("mapped_status_code", "")
                    event_out["is_code_changed"] = r.get("is_code_changed", "")
                    event_out["mapped_reason"] = r.get("mapped_reason", "")
                    for col in annotation_columns:
                        event_out[col] = r.get(col, "")
                    event_writer.writerow(event_out)

                datamart_out = {k: r.get(k, "") for k in input_columns}
                datamart_out["event_status_code_original"] = r.get("original_status_code", "")
                datamart_out["event_status_code"] = r.get("mapped_status_code", "")
                datamart_out["mapped_reason"] = r.get("mapped_reason", "")
                for col in annotation_columns:
                    datamart_out[col] = r.get(col, "")
                datamart_writer.writerow(datamart_out)

    if output_chains:
        chain_columns = [
            "company",
            "track_number",
            "track_number_type",
            "container_number",
            "sequence_length",
            "is_skipped",
            "skip_reason",
            "raw_status_sequence",
            "original_code_sequence",
            "mapped_code_sequence",
            "changed_codes_count",
            "changed_codes_share",
            "old_pass_level_1",
            "old_pass_level_2",
            "old_pass_level_3",
            "pass_level_1",
            "pass_level_2",
            "pass_level_3",
            "violation_level_1",
            "violation_level_2",
            "violation_level_3"
        ]
        with open(output_chains, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=chain_columns)
            writer.writeheader()
            writer.writerows(chain_output)

    print("Company:", company)
    print("Total events:", total_events)
    print("Total chains:", total_chains)
    print("Evaluated chains:", evaluated_chains)
    print("Skipped chains:", skipped_chains)
    print(
        "OLD UNK events:",
        old_unk_events,
        f"({old_unk_events / total_events:.4f})" if total_events else ""
    )
    print(
        "NEW UNK events:",
        unk_events,
        f"({unk_events / total_events:.4f})" if total_events else ""
    )
    print("UNK delta (new-old):", unk_events - old_unk_events)
    print(
        "L1 pass (all chains):",
        pass_l1,
        f"({pass_l1 / total_chains:.4f})" if total_chains else ""
    )
    print(
        "L2 pass (all chains):",
        pass_l2,
        f"({pass_l2 / total_chains:.4f})" if total_chains else ""
    )
    print(
        "L3 pass (all chains):",
        pass_l3,
        f"({pass_l3 / total_chains:.4f})" if total_chains else ""
    )
    print(
        "L1 pass (evaluated only):",
        pass_l1_eval,
        f"({pass_l1_eval / evaluated_chains:.4f})" if evaluated_chains else ""
    )
    print(
        "L2 pass (evaluated only):",
        pass_l2_eval,
        f"({pass_l2_eval / evaluated_chains:.4f})" if evaluated_chains else ""
    )
    print(
        "L3 pass (evaluated only):",
        pass_l3_eval,
        f"({pass_l3_eval / evaluated_chains:.4f})" if evaluated_chains else ""
    )
    print(
        "OLD L1 pass (all chains):",
        old_pass_l1,
        f"({old_pass_l1 / total_chains:.4f})" if total_chains else ""
    )
    print(
        "OLD L2 pass (all chains):",
        old_pass_l2,
        f"({old_pass_l2 / total_chains:.4f})" if total_chains else ""
    )
    print(
        "OLD L3 pass (all chains):",
        old_pass_l3,
        f"({old_pass_l3 / total_chains:.4f})" if total_chains else ""
    )
    print(
        "OLD L1 pass (evaluated only):",
        old_pass_l1_eval,
        f"({old_pass_l1_eval / evaluated_chains:.4f})" if evaluated_chains else ""
    )
    print(
        "OLD L2 pass (evaluated only):",
        old_pass_l2_eval,
        f"({old_pass_l2_eval / evaluated_chains:.4f})" if evaluated_chains else ""
    )
    print(
        "OLD L3 pass (evaluated only):",
        old_pass_l3_eval,
        f"({old_pass_l3_eval / evaluated_chains:.4f})" if evaluated_chains else ""
    )
    print("Improved L3 chains:", improved_l3)
    print("Worsened L3 chains:", worsened_l3)
    print("Improved L3 chains (evaluated only):", improved_l3_eval)
    print("Worsened L3 chains (evaluated only):", worsened_l3_eval)

    print("Top mapping rules:")
    for reason, cnt in reason_counts.most_common(15):
        print(" ", reason, cnt)

    if output_events:
        print("Saved events:", output_events)
    print("Saved datamart-like:", output_datamart_like)
    if output_chains:
        print("Saved chains:", output_chains)
