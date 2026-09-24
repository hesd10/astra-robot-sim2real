"""Audit published behavior evidence offline; optionally extract it from the archive.

Default: recompute manuscript diagnostics from the released, compact records.
--archive PATH: refresh those records from original API events and tool metadata.
No agent reasoning, account data, images, or hardware access is exported.
"""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results/behavior-evidence.json"


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def extract(archive):
    provenance = {}

    def read(relative):
        path = archive / relative
        provenance[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        return read_jsonl(path)

    fixed = json.loads((ROOT / "results/fixed-start.json").read_text())
    displaced = json.loads((ROOT / "results/perturbation.json").read_text())
    ids = [row["id"] for row in fixed if row["condition"].endswith("E3")]
    ids += [f"pp001-{row['point'].lower()}-i0e3" for row in displaced
            if row["condition"] == "I0E3"]
    deployments = []
    for run in ids:
        events = read(f"experiments/{run}/private/simulation/events.jsonl")
        stages = [(i, e) for i, e in enumerate(events)
                  if e.get("accepted") and e.get("request", {}).get("op") == "move"
                  and any(k.startswith("right_") for k in e["request"]["targets"])]
        assert len(stages) == 2, run
        first, second = stages
        between = events[first[0] + 1:second[0]]
        targets = {}
        for _, event in stages:
            targets.update(event["request"]["targets"])
        deployments.append({
            "run": run,
            "stages": [{"archive_line": i + 1, "sim_seconds": e["sim_time"],
                        "targets": e["request"]["targets"],
                        "duration": e["request"]["duration"]} for i, e in stages],
            "final_right_2_3_4": [targets[f"right_{j}"] for j in (2, 3, 4)],
            "base_commands_between": sum(e.get("accepted", False)
                and e.get("request", {}).get("op") == "base" for e in between),
            "observations_between": sum(e.get("event") == "observation_delivered"
                                        for e in between),
        })

    local = json.loads((ROOT / "results/local-skills.json").read_text())
    loops = []
    for row in local:
        if row["condition"] != "LOOP":
            continue
        run = row["id"]
        events = read(f"experiments/{run}/private/simulation/events.jsonl")
        calls = read(f"experiments/{run}/subject/evidence/local-skill-calls.jsonl")
        bases = [e for e in events if e.get("accepted")
                 and e.get("request", {}).get("op") == "base"]
        press = next(e["sim_time"] for e in events if e.get("event") == "target_pressed")
        cursor = 0
        intervals = []
        for i, call in enumerate(calls):
            steps = call["result"]["steps"]
            pulse_events = bases[cursor:cursor + steps]
            assert steps > 0 and len(pulse_events) == steps
            for e in pulse_events:
                for field in ("vx", "vy", "duration"):
                    assert e["request"][field] == call["parameters"][field]
            start = pulse_events[0]["sim_time"]
            end = call["result"]["observation"]["sim_time"]
            assert all(start <= e["sim_time"] <= end for e in pulse_events)
            intervals.append({"index": i + 1, "start_sim_seconds": start,
                              "end_sim_seconds": end, "steps": steps,
                              "parameters": call["parameters"],
                              "reason": call["result"]["reason"]})
            cursor += steps
        assert cursor == len(bases)
        loops.append({"run": run, "state": row["state"], "repeat": row["repeat"],
                      "calls": intervals, "activation_sim_seconds": press,
                      "activation_to_red_return_seconds": intervals[-1]["end_sim_seconds"] - press,
                      "new_pulses_after_activation": sum(e["sim_time"] > press for e in bases)})

    run = "be001-r1-i0e3"
    events = read(f"experiments/{run}/private/agent-events.jsonl")
    trace = []
    # Only completed public image views and commands calling the trial's control helper.
    # Relative paths remove machine/user directory names; all other item types are ignored.
    for n, e in enumerate(events, 1):
        if e.get("method") != "item/completed":
            continue
        item = e.get("params", {}).get("item", {})
        record = {"archive_line": n, "emitted_at_ms": e.get("emittedAtMs")}
        if item.get("type") == "imageView":
            record.update(kind="image_view", path=item["path"].split("/subject/", 1)[1])
        elif item.get("type") == "commandExecution" and "python3 control.py '" in item.get("command", ""):
            record.update(kind="control_command", command=item["command"])
        else:
            continue
        trace.append(record)
    return {
        "clock_note": "LOOP intervals use the simulator task clock; total trial times use local-skills.json's agent-start clock. Inter-call gaps include all intervening work, not solely model computation.",
        "provenance_sha256": provenance,
        "deployments": deployments,
        "loop_diagnostics": loops,
        "mid_execution_reference_example": {"run": run, "public_tool_sequence": trace},
    }


def audit(data):
    deployments = data["deployments"]
    assert len(deployments) == 15
    assert all(d["final_right_2_3_4"] == [1.0, 1.2, -0.84] for d in deployments)
    assert all(d["observations_between"] >= 1 for d in deployments)
    moving = [d for d in deployments if d["base_commands_between"]]
    assert len(moving) == 11
    assert all(6 <= d["base_commands_between"] <= 10 for d in moving)
    fixed = [d for d in deployments if d["run"].startswith("be001")]
    assert len(fixed) == 6 and sum(d["base_commands_between"] == 6 for d in fixed) == 5
    loops = data["loop_diagnostics"]
    assert len(loops) == 9 and all(d["new_pulses_after_activation"] == 0 for d in loops)
    assert all(d["calls"][-1]["reason"] == "red_detected_verify" for d in loops)
    slow = next(d for d in loops if d["run"] == "lf001-t018")
    calls = slow["calls"]
    local_span = sum(c["end_sim_seconds"] - c["start_sim_seconds"] for c in calls)
    gaps = sum(b["start_sim_seconds"] - a["end_sim_seconds"] for a, b in zip(calls, calls[1:]))
    assert len(calls) == 7 and sum(c["steps"] for c in calls) == 9
    assert round(local_span, 2) == 9.54 and round(gaps, 2) == 130.31
    rows = json.loads((ROOT / "results/local-skills.json").read_text())
    s3 = {c: sorted((r for r in rows if r["state"] == "S3" and r["condition"] == c),
                    key=lambda r: r["repeat"]) for c in ("STEP", "LOOP")}
    increase = 100 * (mean(r["seconds"] for r in s3["LOOP"]) /
                      mean(r["seconds"] for r in s3["STEP"]) - 1)
    assert round(increase, 1) == 15.5
    trace = data["mid_execution_reference_example"]["public_tool_sequence"]
    refs = [i for i, e in enumerate(trace) if e.get("path", "").startswith("prior/experience/observations/0015/")]
    assert len(refs) == 2
    assert any(e["kind"] == "control_command" for e in trace[:refs[0]])
    assert any(e["kind"] == "control_command" for e in trace[refs[-1] + 1:])
    summary = {"staged_deployments": len(deployments), "with_base_motion_between_stages": len(moving),
               "S3_times": {c: [r["seconds"] for r in rs] for c, rs in s3.items()},
               "S3_LOOP_increase_percent": increase, "slow_trial_local_span_seconds": local_span,
               "slow_trial_inter_call_gaps_seconds": gaps,
               "activation_to_red_return_range_seconds": [min(d["activation_to_red_return_seconds"] for d in loops),
                                                          max(d["activation_to_red_return_seconds"] for d in loops)],
               "mid_execution_historical_image_views": len(refs)}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    evidence = extract(args.archive) if args.archive else json.loads(OUTPUT.read_text())
    audit(evidence)
    if args.archive:
        OUTPUT.write_text(json.dumps(evidence, indent=2) + "\n")
