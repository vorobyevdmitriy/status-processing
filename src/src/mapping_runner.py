import csv
from collections import Counter, defaultdict

from .mapper_registry import MAPPERS
from .validation import validator_v2 as validator


def evaluate_chain(evs, code_field):
    if hasattr(validator, "evaluate_events") and hasattr(validator, "build_event_context"):
        events = validator.build_event_context(evs, code_field)
        l1, l2, l3, _, _ = validator.evaluate_events(events)
        return l1, l2, l3

    seq_codes = [row[code_field] for row in evs]
    l1, l2, l3, _, _ = validator.evaluate_sequence(seq_codes)
    return l1, l2, l3


def get_skip_reason(company, evs, code_field):
    if hasattr(validator, "build_event_context"):
        events = validator.build_event_context(evs, code_field)
        return validator.get_skip_reason(company, events)

    seq_codes = [row[code_field] for row in evs]
    return validator.get_skip_reason(company, seq_codes)


def format_violation(v):
    if v is None:
        return ""
    return f"{v.rule_id}|idx={v.idx}|{v.from_code}->{v.to_code}|{v.details}"


def run_company_mapping(company, input_path, output_events, output_datamart_like, output_chains):
    if company not in MAPPERS:
        raise ValueError(f"No mapper implemented for company '{company}'. Available: {', '.join(MAPPERS.keys())}")

    mapper = MAPPERS[company]

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
    pass_l123 = 0

    pass_l1_eval = 0
    pass_l2_eval = 0
    pass_l3_eval = 0
    pass_l123_eval = 0

    old_pass_l1 = 0
    old_pass_l2 = 0
    old_pass_l3 = 0
    old_pass_l123 = 0

    old_pass_l1_eval = 0
    old_pass_l2_eval = 0
    old_pass_l3_eval = 0
    old_pass_l123_eval = 0

    improved_l123 = 0
    worsened_l123 = 0

    improved_l123_eval = 0
    worsened_l123_eval = 0
    old_unk_events = 0
    unk_events = 0
    total_events = 0
    reason_counts = Counter()

    chain_output = []

    for key, evs in chains.items():
        evs.sort(key=lambda r: r["_event_pos_int"], reverse=True)
        mapped_codes, mapped_reasons = mapper.map_seq(evs)

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

        old_l1, old_l2, old_l3 = evaluate_chain(evs, "original_status_code")
        old_ok = old_l1[0] and old_l2[0] and old_l3[0]

        l1, l2, l3 = evaluate_chain(evs, "mapped_status_code")
        new_ok = l1[0] and l2[0] and l3[0]

        skip_reason = get_skip_reason(key[0], evs, "mapped_status_code")
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
        pass_l123 += 1 if (l1[0] and l2[0] and l3[0]) else 0

        if is_skipped:
            skipped_chains += 1
        else:
            evaluated_chains += 1
            pass_l1_eval += 1 if l1[0] else 0
            pass_l2_eval += 1 if l2[0] else 0
            pass_l3_eval += 1 if l3[0] else 0
            pass_l123_eval += 1 if (l1[0] and l2[0] and l3[0]) else 0

        old_pass_l1 += 1 if old_l1[0] else 0
        old_pass_l2 += 1 if old_l2[0] else 0
        old_pass_l3 += 1 if old_l3[0] else 0
        old_pass_l123 += 1 if (old_l1[0] and old_l2[0] and old_l3[0]) else 0

        if not is_skipped:
            old_pass_l1_eval += 1 if old_l1[0] else 0
            old_pass_l2_eval += 1 if old_l2[0] else 0
            old_pass_l3_eval += 1 if old_l3[0] else 0
            old_pass_l123_eval += 1 if (old_l1[0] and old_l2[0] and old_l3[0]) else 0

        if (not old_ok) and new_ok:
            improved_l123 += 1
            if not is_skipped:
                improved_l123_eval += 1
        if old_ok and (not new_ok):
            worsened_l123 += 1
            if not is_skipped:
                worsened_l123_eval += 1

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
                "old_pass_l1_l2_l3": int(old_ok),
                "pass_level_1": int(l1[0]),
                "pass_level_2": int(l2[0]),
                "pass_level_3": int(l3[0]),
                "pass_l1_l2_l3": int(l1[0] and l2[0] and l3[0]),
                "violation_level_1": format_violation(l1[1]),
                "violation_level_2": format_violation(l2[1]),
                "violation_level_3": format_violation(l3[1])
            }
        )

    event_columns = input_columns + ["original_status_code", "mapped_status_code", "is_code_changed", "mapped_reason"]

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

    with (open(output_events, "w", newline="", encoding="utf-8") as f_events,
          open(output_datamart_like, "w", newline="", encoding="utf-8") as f_datamart):
        event_writer = csv.DictWriter(f_events, fieldnames=event_columns)
        datamart_writer = csv.DictWriter(f_datamart, fieldnames=datamart_like_columns)
        event_writer.writeheader()
        datamart_writer.writeheader()

        for key in sorted(chains.keys()):
            evs = chains[key]
            evs.sort(key=lambda r: r["_event_pos_int"], reverse=True)
            for r in evs:
                event_out = {k: r.get(k, "") for k in input_columns}
                event_out["original_status_code"] = r.get("original_status_code", "")
                event_out["mapped_status_code"] = r.get("mapped_status_code", "")
                event_out["is_code_changed"] = r.get("is_code_changed", "")
                event_out["mapped_reason"] = r.get("mapped_reason", "")
                event_writer.writerow(event_out)

                datamart_out = {k: r.get(k, "") for k in input_columns}
                datamart_out["event_status_code_original"] = r.get("original_status_code", "")
                datamart_out["event_status_code"] = r.get("mapped_status_code", "")
                datamart_out["mapped_reason"] = r.get("mapped_reason", "")
                datamart_writer.writerow(datamart_out)

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
        "old_pass_l1_l2_l3",
        "pass_level_1",
        "pass_level_2",
        "pass_level_3",
        "pass_l1_l2_l3",
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
        "L1+L2+L3 pass (all chains):",
        pass_l123,
        f"({pass_l123 / total_chains:.4f})" if total_chains else ""
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
        "L1+L2+L3 pass (evaluated only):",
        pass_l123_eval,
        f"({pass_l123_eval / evaluated_chains:.4f})" if evaluated_chains else ""
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
        "OLD L1+L2+L3 pass (all chains):",
        old_pass_l123,
        f"({old_pass_l123 / total_chains:.4f})" if total_chains else ""
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
    print(
        "OLD L1+L2+L3 pass (evaluated only):",
        old_pass_l123_eval,
        f"({old_pass_l123_eval / evaluated_chains:.4f})" if evaluated_chains else ""
    )
    print("Improved L1+L2+L3 chains:", improved_l123)
    print("Worsened L1+L2+L3 chains:", worsened_l123)
    print("Improved L1+L2+L3 chains (evaluated only):", improved_l123_eval)
    print("Worsened L1+L2+L3 chains (evaluated only):", worsened_l123_eval)

    print("Top mapping rules:")
    for reason, cnt in reason_counts.most_common(15):
        print(" ", reason, cnt)

    print("Saved events:", output_events)
    print("Saved datamart-like:", output_datamart_like)
    print("Saved chains:", output_chains)
