"""Stream actual dispatches; fenced cache recovery with an append-only stage journal."""

import hashlib
import json
import math
import resource
import sys
from time import perf_counter

from .config import Hardware
from .rust import RUST_VERSION, PreparedInstructions, PreparedProgram, RustSession


def prepare(raw, root, hw, session):
    from .__main__ import read_candidate
    from .elf import ELFProgram

    programs = {}
    for dispatch in raw["dispatches"]:
        if "elf" in dispatch:
            path = root / dispatch["elf"]
            if path not in programs:
                programs[path] = ELFProgram.read(path)
            elf = programs[path]
            if elf.sha256 != dispatch["elf_sha256"]:
                raise ValueError("ELF program hash differs")
            launch = elf.launch(
                dispatch["kernel"],
                dispatch["arguments"],
                global_size=dispatch["global_size"],
                local_size=dispatch.get("local_size", [32, 1, 1]),
                resource_override=dispatch.get("resource_override"),
                functional_words=dispatch.get("functional_words"),
            )
            program = PreparedProgram.from_elf(elf, launch)
        elif "compact" in dispatch:
            program = PreparedInstructions.from_bytes((root / dispatch["compact"]).read_bytes())
            if program.sha256 != dispatch["sha256"]:
                raise ValueError("compact instruction hash differs")
        else:
            workload = read_candidate({"hardware": hw.to_dict(), "workload": dispatch["workload"]})
            program = PreparedInstructions.from_workload(workload.workload, hw)
        yield dispatch["name"], program


def write_checkpoint(out, identity, next_dispatch, digest, state):
    pending = out / "checkpoint.tmp"
    pending.write_text(
        json.dumps(
            dict(
                input_sha256=identity,
                next_dispatch=next_dispatch,
                stage_journal="stages.jsonl",
                stage_journal_sha256=digest.hexdigest(),
                session=state,
            )
        )
        + "\n"
    )
    pending.replace(out / "checkpoint.json")


def run(input_path, out, *, budget=60, resume=None, hardware_path=None):
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError("host budget must be finite and positive")
    payload = input_path.read_bytes()
    raw = json.loads(payload)
    if raw.get("schema") != "ventus-dispatches-v1" or not raw.get("dispatches"):
        raise ValueError("expected nonempty ventus-dispatches-v1 manifest")
    names = [d["name"] for d in raw["dispatches"]]
    if any(not isinstance(n, str) or not n for n in names) or len(set(names)) != len(names):
        raise ValueError("dispatch names must be unique and nonempty")
    overrides = json.loads(hardware_path.read_text()) if hardware_path else {}
    hw = Hardware(**{**raw.get("hardware", {}), **overrides}).validate()
    identity = hashlib.sha256(
        payload + json.dumps(hw.to_dict(), sort_keys=True).encode()
    ).hexdigest()
    old = json.loads(resume.read_text()) if resume else None
    if old and old["input_sha256"] != identity:
        raise ValueError("resume program/configuration identity differs")
    stages = []
    digest = hashlib.sha256()
    journal_lines = []
    if old:
        position = old["next_dispatch"]
        if type(position) is not int or not 0 <= position <= len(names):
            raise ValueError("invalid recovery position")
        if old.get("stage_journal") != "stages.jsonl":
            raise ValueError("unsupported recovery journal")
        with (resume.parent / "stages.jsonl").open("rb") as file:
            for _ in range(position):
                line = file.readline()
                if not line.endswith(b"\n"):
                    raise ValueError("truncated recovery journal")
                journal_lines.append(line)
                digest.update(line)
                stages.append(json.loads(line))
        if (
            digest.hexdigest() != old["stage_journal_sha256"]
            or [s["name"] for s in stages] != names[:position]
        ):
            raise ValueError("recovery journal identity differs")
    out.mkdir()
    begin = perf_counter()
    with RustSession(hw, instruction_target=raw.get("instruction_target")) as session:
        build_seconds = perf_counter() - begin
        if old:
            session.restore(old["session"])
        next_dispatch = len(stages)
        state = session.checkpoint()
        write_checkpoint(out, identity, next_dispatch, digest, state)
        start = last_progress = last_checkpoint = perf_counter()
        error = None
        active_name = None
        with (out / "stages.jsonl").open("xb") as journal:
            for line in journal_lines:
                journal.write(line)
            journal.flush()
            try:
                for index, (name, program) in enumerate(
                    prepare(raw, input_path.parent, hw, session)
                ):
                    if index < next_dispatch:
                        if stages[index]["program_sha256"] != program.sha256:
                            raise ValueError("resumed program differs")
                        continue
                    if perf_counter() - start >= budget:
                        break
                    active_name = name
                    begin = perf_counter()
                    row = session.dispatch(program)
                    expected = raw["dispatches"][index].get("work", {}).get("mma_instructions")
                    if (
                        expected is not None
                        and sum(
                            row["counters"].get(k, 0) for k in ("mma_bf16", "mma_f16", "mma_tf32")
                        )
                        != expected
                    ):
                        raise ValueError("dynamic MMA count differs from independent shape check")
                    stage = dict(
                        name=name,
                        **row,
                        host_seconds=perf_counter() - begin,
                        program_sha256=program.sha256,
                        program=getattr(program, "metadata", {"input": "decoded instructions"}),
                    )
                    stages.append(stage)
                    next_dispatch = index + 1
                    line = (json.dumps(stage, separators=(",", ":")) + "\n").encode()
                    journal.write(line)
                    journal.flush()
                    digest.update(line)
                    now = perf_counter()
                    if now - last_checkpoint >= 30:
                        state = session.checkpoint()
                        write_checkpoint(out, identity, next_dispatch, digest, state)
                        last_checkpoint = now
                    if now - last_progress >= 30:
                        print(
                            json.dumps(
                                dict(
                                    progress=next_dispatch,
                                    total_dispatches=len(names),
                                    last=name,
                                    cycles=session.cycles,
                                    instructions=session.instructions,
                                    host_seconds=now - start,
                                )
                            ),
                            flush=True,
                        )
                        last_progress = now
            except (ValueError, KeyboardInterrupt) as failure:
                error = dict(
                    dispatch=active_name, type=type(failure).__name__, message=str(failure)
                )
                # A failed dispatch never becomes a recovery point. Its mutable
                # native state is discarded; the last complete fenced state survives.
        if session.handle and error is None:
            state = session.checkpoint()
            write_checkpoint(out, identity, next_dispatch, digest, state)
        # Failed native state is discarded. The receipt can still report all
        # fully completed journal entries beyond the last periodic recovery point.
        totals_state = {
            key: sum(stage[key] for stage in stages)
            for key in ("cycles", "instructions", "requested_bytes", "host_ticks", "idle_skipped")
        }
        totals_counters = {}
        for stage in stages:
            for key, value in stage["counters"].items():
                totals_counters[key] = totals_counters.get(key, 0) + value
        elapsed = perf_counter() - start
        completed = next_dispatch == len(names) and error is None
        totals = {}
        for stage in stages:
            phase = stage["name"].split(".")[0]
            row = totals.setdefault(
                phase, dict(cycles=0, instructions=0, requested_bytes=0, host_seconds=0)
            )
            for key in row:
                row[key] += stage[key]
        result = dict(
            version=RUST_VERSION,
            source_sha256=session.source_sha256,
            runtime_sha256=session.runtime_sha256,
            input_sha256=identity,
            manifest_sha256=hashlib.sha256(payload).hexdigest(),
            program_sha256=[s["program_sha256"] for s in stages],
            hardware=hw.to_dict(),
            instruction_target=raw.get("instruction_target"),
            low_precision_measured_cost="unsupported; structural-v2 estimates are a separate declared approximation",
            scenario=raw.get("scenario"),
            completed=completed,
            cycles=totals_state["cycles"] if completed else None,
            partial_cycles=totals_state["cycles"],
            instructions=totals_state["instructions"],
            requested_bytes=totals_state["requested_bytes"],
            counters=totals_counters,
            host_ticks=totals_state["host_ticks"],
            idle_cycles_skipped=totals_state["idle_skipped"],
            host_seconds=elapsed,
            accumulated_dispatch_host_seconds=sum(s["host_seconds"] for s in stages),
            build_or_load_seconds=build_seconds,
            process_peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            / (1024**2 if sys.platform == "darwin" else 1024),
            stages=stages,
            phase_totals=totals,
            error=error,
            initial_state="restored fenced checkpoint" if old else "cold cache",
            recovery="fenced checkpoint + hashed stage journal; cache tags, replacement state, counters and cycle offset preserved",
            limitations=[
                "ELF provider currently requires one 32-lane warp per block",
                "unknown numerical control/address requires functional input",
                "extended instruction timing is an explicit uncalibrated target",
                "dispatch boundaries drain writes and invalidate written cache lines",
                "budget checked between complete dispatches; no in-flight checkpoint",
                "checkpoints every 30 host seconds and normal completion; journal may extend beyond recovery point",
            ],
        )
        with (out / "experiment.json").open("x") as file:
            json.dump(result, file, indent=2)
            file.write("\n")
    print(
        json.dumps(
            {k: result[k] for k in ("completed", "cycles", "instructions", "host_seconds", "error")}
        )
    )
    return result
