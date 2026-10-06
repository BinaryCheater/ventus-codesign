"""Source-defined pipeline timing plus an explicit transaction-level memory abstraction.

The graph fixes service order. It is exact for that abstraction, not a claim of
cycle-identical implementation of every Ventus arbitration/state-machine path.
"""

from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass
from math import ceil

from .coalescer import shared_service_intervals
from .config import Hardware
from .graph import TimingGraph, execute
from .ir import Workload


@dataclass
class Line:
    fill: int
    dirty: bool = False
    targets: tuple[int, ...] = ()
    way: int = 0


class Builder:
    def __init__(self, hw):
        self.hw = hw.validate()
        self.graph = TimingGraph()
        self.times = [0]
        self.resources = defaultdict(list)
        self.calendars = {}
        self.l1 = defaultdict(OrderedDict)
        self.l2 = defaultdict(OrderedDict)
        self.l2_lfsr = 0
        self.writes = []
        self.visible_writes = []
        self.shared_admissions = defaultdict(int)

    def node(self, name, edges=()):
        node = self.graph.node(name, edges)
        self.times.append(max(self.times[u] + lag for u, lag in self.graph.predecessors[node]))
        return node

    def reserve(self, key, name, edges, interval=1, capacity=1):
        deps = list(edges)
        ready = max((self.times[u] + lag for u, lag in deps), default=0)
        slots = self.calendars.setdefault(key, [[] for _ in range(capacity)])
        if len(slots) != capacity:
            raise ValueError("resource port count changed during execution")
        options = []
        for slot, bookings in enumerate(slots):
            start, blocker = ready, None
            for begin, end, event, duration in bookings:
                if end <= start:
                    continue
                if start + interval <= begin:
                    break
                start, blocker = end, (event, duration)
            options.append((start, slot, blocker))
        start, slot, blocker = min(options, key=lambda x: (x[0], x[1]))
        if blocker:
            deps.append(blocker)
        node = self.node(name, deps)
        if self.times[node] != start:
            raise RuntimeError("resource calendar and timing graph disagree")
        slots[slot].append((start, start + interval, node, interval))
        slots[slot].sort()
        self.resources[key].append(node)
        return node

    def capacity_start(self, key, edges, capacity):
        history = self.resources[key]
        return [*edges, *(([(history[-capacity], 0)]) if len(history) >= capacity else [])]

    def memory_transfer(self, ready, line, write=False):
        h = self.hw
        # GPGPU_SimWrapper pipe_a and pipe_d are both two registered stages.
        outgoing = self.node("wrapper.pipe_a", [(ready, 2)])
        transfer = ceil(h.line_bytes / h.memory_bytes_per_cycle)
        channel = (line // h.line_bytes) % h.memory_channels
        start = self.reserve(
            ("memory", channel), f"memory.{line:x}.accept", [(outgoing, 0)], transfer
        )
        response = self.node(
            f"memory.{line:x}.{'write' if write else 'read'}",
            [(start, h.memory_latency + transfer)],
        )
        done = self.node("wrapper.pipe_d", [(response, 2)])
        self.graph.count("memory_write_bytes" if write else "memory_read_bytes", h.line_bytes)
        if write:
            self.writes.append(done)
            self.visible_writes.append(start)
        return done

    def writeback(self, op, ready, sm, wid):
        path = op.destination[0] if op.destination else "v"
        bank = (wid + int(op.destination[1:])) % self.hw.rf_banks if op.destination else 0
        # The RF write and WB arbitration consume the same cycle, so reserve jointly.
        requirements = [
            (("rf.write", sm, path, bank), self.hw.rf_write_ports),
            (("writeback", sm, path), self.hw.writeback_ports),
        ]
        start, blockers = self.times[ready], []
        while True:
            choices = []
            for key, capacity in requirements:
                slots = self.calendars.setdefault(key, [[] for _ in range(capacity)])
                options = []
                for index, bookings in enumerate(slots):
                    available, blocker = start, None
                    for begin, end, event, duration in bookings:
                        if end <= available:
                            continue
                        if available + 1 <= begin:
                            break
                        available, blocker = end, (event, duration)
                    options.append((available, index, blocker))
                choices.append((key, min(options, key=lambda x: (x[0], x[1]))))
            next_start = max(choice[0] for _, choice in choices)
            blockers.extend(choice[2] for _, choice in choices if choice[2] is not None)
            if next_start == start:
                break
            start = next_start
        node = self.node(op.name + ".writeback", [(ready, 0), *blockers])
        if self.times[node] != start:
            raise RuntimeError("joint WB reservation and graph disagree")
        for key, (_, slot, _) in choices:
            self.calendars[key][slot].append((start, start + 1, node, 1))
            self.calendars[key][slot].sort()
            self.resources[key].append(node)
        return node

    def lower_read(self, ready, line, *, allocate=True):
        h = self.hw
        cache = self.l2[(line // h.line_bytes) % h.l2_sets]
        probe = self.reserve("l2.probe", f"l2.{line:x}.probe", [(ready, 1)])
        # Directory_test selects the low way bits of a global 16-bit LFSR.
        # Update is per directory result, including hits. I-cache traffic is excluded.
        victim_way = self.l2_lfsr & (h.l2_ways - 1)
        feedback = sum((self.l2_lfsr >> bit) & 1 for bit in [0, 1, 3, 4]) % 2
        self.l2_lfsr = ((self.l2_lfsr << 1) & 0xFFFF) | feedback if self.l2_lfsr else 1
        if line in cache:
            record = cache.pop(line)
            cache[line] = record
            self.graph.count("l2_hit")
            return self.node(f"l2.{line:x}.hit", [(probe, 2), (record.fill, 1)])
        self.graph.count("l2_miss")
        victim = next((tag for tag, value in cache.items() if value.way == victim_way), None)
        if victim is not None and allocate:
            old = cache.pop(victim)
            probe = self.node("l2.evict", [(probe, 0), (old.fill, 0)])
        accepted = self.node(
            "l2.mshr.allocate", self.capacity_start("l2.mshr", [(probe, 1)], h.l2_mshrs)
        )
        response = self.memory_transfer(accepted, line)
        sink = self.node("l2.sink_d.register", [(response, 1)])
        scheduled = self.node("l2.mshr.sink_d", [(sink, 1)])
        done = self.node("l2.source_d.stage4", [(scheduled, 1)])
        self.resources["l2.mshr"].append(done)
        if allocate:
            cache[line] = Line(done, way=victim_way)
        return done

    def global_line(self, ready, sm, line, write):
        h = self.hw
        cache = self.l1[(sm, (line // h.line_bytes) % h.l1_sets)]
        probe = self.reserve(("l1.probe", sm), f"sm{sm}.l1.{line:x}.probe", [(ready, 0)])
        if line in cache:
            record = cache.pop(line)
            cache[line] = record
            if self.times[probe] < self.times[record.fill]:
                self.graph.count("l1_merge")
                probe = self.node(
                    "l1.subentry",
                    self.capacity_start(("l1.targets", sm, line), [(probe, 0)], h.l1_subentries),
                )
            else:
                self.graph.count("l1_hit")
            done = self.node("l1.hit.response", [(probe, 3), (record.fill, 1)])
            self.resources[("l1.targets", sm, line)].append(done)
            record.dirty |= write
            return done
        self.graph.count("l1_write_miss" if write else "l1_read_miss")
        # Ventus forwards write misses; it does not allocate the L1 line on this path.
        if write:
            start = self.node(
                "wshr.allocate", self.capacity_start(("wshr", sm), [(probe, 2)], h.l1_write_entries)
            )
            queued = self.node("l1.write.mem_req.queue", [(start, 1)])
            cluster = self.node("sm2cluster.write.mem_req.queue", [(queued, 1)])
            # MSHR.schedule.a always emits Get, even for a write miss; its
            # directory update is guarded by opcode==Get. SourceD subsequently
            # forwards the write. The preliminary read must not allocate a tag.
            lower = self.lower_read(cluster, line, allocate=False)
            physical_done = self.memory_transfer(lower, line, write=True)
            self.resources[("wshr", sm)].append(physical_done)
            # DCache acknowledges a write miss locally at memReq_Q departure.
            return self.node("l1.write.local_response", [(queued, 0)])
        if len(cache) >= h.l1_ways:
            old_line, old = cache.popitem(last=False)
            probe = self.node("l1.evict.wait", [(probe, 0), (old.fill, 0)])
            if old.dirty:
                probe = self.memory_transfer(probe, old_line, write=True)
        start = self.node(
            "l1.mshr.allocate", self.capacity_start(("l1.mshr", sm), [(probe, 2)], h.l1_mshrs)
        )
        queued = self.node("l1.mem_req.queue", [(start, 1)])
        cluster = self.node("sm2cluster.mem_req.queue", [(queued, 1)])
        lower = self.lower_read(cluster, line)
        # memRsp_Q, MSHR response queue, coreRsp_st2 register, coreRsp_Q.
        done = self.node("l1.fill.response", [(lower, 4)])
        cache[line] = Line(done)
        self.resources[("l1.mshr", sm)].append(done)
        self.resources[("l1.targets", sm, line)] = [done]
        return done

    def memory_instruction(self, issue, op, sm, wid):
        h = self.hw
        groups = OrderedDict()
        for address in op.addresses:
            groups.setdefault(address // h.line_bytes * h.line_bytes, []).append(address)
        gates = self.capacity_start(("lsu.sm", sm), [(issue, 0)], h.lsu_entries)
        gates = self.capacity_start(("lsu.warp", sm, wid), gates, h.lsu_per_warp)
        previous_address = self.resources[("lsu.address.release", sm)]
        if previous_address:
            gates.append((previous_address[-1], 0))
        if all(0x70000000 <= address < 0x70000000 + h.lds_bytes for address in op.addresses):
            # Coupled AddrCalculate/MSHR states constrain sustained LDS throughput.
            # This service template complements latency; it is not a fixed load delay.
            intervals = shared_service_intervals(h.lsu_entries)
            admission = self.shared_admissions[sm]
            service = self.reserve(
                ("shared.coalescer.service", sm),
                op.name + ".coalescer.service",
                gates,
                interval=intervals[admission % len(intervals)],
            )
            self.shared_admissions[sm] += 1
            gates.append((service, 0))
        # InputFIFO -> AddrCalculate.s_save -> s_shared/s_dcache.
        first = self.reserve(
            ("lsu.address", sm), op.name + ".address", gates, interval=2 + len(groups)
        )
        ends = []
        grants = []
        for i, (line, addresses) in enumerate(groups.items()):
            request = self.node(op.name + f".line{i}", [(first, 3 + i)])
            if 0x70000000 <= line < 0x70000000 + h.lds_bytes:
                counts = Counter((a // 4) % h.lds_banks for a in addresses)
                rounds = max(ceil(n / h.lds_ports) for n in counts.values())
                self.graph.count("lds_rounds", rounds)
                # Same-address lanes are not merged by BankConflictArbiter.
                start = self.reserve(
                    ("lds", sm),
                    op.name + ".lds.start",
                    [(request, 0)],
                    interval=rounds + (op.kind == "store"),
                )
                last = self.node(op.name + ".lds.last_round", [(start, rounds - 1)])
                ends.append(self.node(op.name + ".lds.response", [(last, 3)]))
                grants.append(last)
            else:
                ends.append(self.global_line(request, sm, line, op.kind == "store"))
                grants.append(request)
        released = self.node(op.name + ".address.release", [(n, 1) for n in grants])
        self.resources[("lsu.address.release", sm)].append(released)
        done = self.reserve(("lsu.response", sm), op.name + ".memory.done", [(n, 1) for n in ends])
        self.resources[("lsu.sm", sm)].append(done)
        self.resources[("lsu.warp", sm, wid)].append(done)
        return done


def build_graph(workload: Workload, hw: Hardware):
    workload.validate(hw)
    b = Builder(hw)
    g = b.graph
    g.limitations = [
        "Timing begins at decoded instruction availability; host launch, I-cache and end invalidation scans are excluded.",
        "Service order is a frozen round-robin template; RTL ready-aware arbitration and CTA fragmentation are not fully reproduced.",
        "Global cache/memory uses a finite transaction abstraction; replacement timestamps, inclusive probes and detailed backpressure need RTL validation.",
        "LDS coalescer throughput is derived from a saturated full-line control template; arbitrary mixed/partial response state timing is not fully reproduced.",
    ]
    blocks = OrderedDict()
    for op in workload.operations:
        blocks.setdefault(op.block, []).append(op)
    resident = workload.resident_blocks(hw)
    block_gates, block_ends = {}, defaultdict(list)
    completion, last_issue, registers = {}, {}, {}
    ordered = []
    block_list = list(blocks)
    # Each cohort has at most resident blocks per SM. No capacity is overcommitted.
    cohort_size = hw.sms * resident
    previous_cohort = 0
    for offset in range(0, len(block_list), cohort_size):
        cohort = block_list[offset : offset + cohort_size]
        for pos, block in enumerate(cohort):
            sm = pos % hw.sms
            base_wid = (pos // hw.sms) * workload.warps_per_block
            block_gates[block] = (sm, base_wid, previous_cohort)
        for n in range(max(len(blocks[x]) for x in cohort)):
            for block in cohort:
                if n < len(blocks[block]):
                    ordered.append(blocks[block][n])
        for op in ordered:
            sm, base_wid, gate = block_gates[op.block]
            wid = base_wid + op.warp
            warp_key = (op.block, op.warp)
            edges = [(gate, 0)]
            if set(op.dependencies) - completion.keys():
                raise ValueError(
                    "dependency is incompatible with the frozen service-order template"
                )
            edges.extend((completion[x], 1) for x in op.dependencies)
            for reg in (*op.sources, *([op.destination] if op.destination else [])):
                key = (warp_key, reg)
                if reg != "x0" and key in registers:
                    edges.append((registers[key], 1))
            if warp_key in last_issue:
                edges.append((last_issue[warp_key], 1))
            accept = b.node(
                op.name + ".collect", b.capacity_start(("collectors", sm), edges, hw.collectors)
            )
            reads = []
            for k, reg in enumerate(op.sources):
                bank = (wid + int(reg[1:])) % hw.rf_banks
                read = b.reserve(
                    ("rf", sm, reg[0], bank),
                    op.name + f".operand{k}",
                    [(accept, 0)],
                    capacity=hw.rf_read_ports,
                )
                reads.append(read)
            collected = b.node(
                op.name + ".operands", [(r, 3) for r in reads] if reads else [(accept, 1)]
            )
            path = "scalar" if op.kind in {"scalar", "barrier"} else "vector"
            issue = b.reserve(("issue", sm, path), op.name + ".issue", [(collected, 0)])
            last_issue[warp_key] = issue
            b.resources[("collectors", sm)].append(issue)
            if op.kind in {"load", "store"}:
                done = b.memory_instruction(issue, op, sm, wid)
                if op.destination:
                    done = b.writeback(op, done, sm, wid)
            elif op.kind == "barrier":
                done = b.node(
                    op.name + ".barrier", [(issue, 0), *[(x, 0) for x in block_ends[op.block]]]
                )
                # Scope is a supplied block-wide barrier event, not arbitrary partial arrivals.
                for other in range(workload.warps_per_block):
                    last_issue[(op.block, other)] = done
            else:
                latency = {
                    "scalar": 1,
                    "vector": 1,
                    "fadd": 3,
                    "fma": 5,
                    "tensor": hw.tensor_latency,
                }[op.kind]
                unit = b.reserve(
                    ("execute", sm, op.kind),
                    op.name + ".execute",
                    [(issue, 0)],
                    capacity=hw.tensor_units if op.kind == "tensor" else 1,
                )
                result = b.node(op.name + ".result", [(unit, latency)])
                done = b.writeback(op, result, sm, wid)
            completion[op.name] = done
            block_ends[op.block].append(done)
            if op.destination and op.destination != "x0":
                registers[(warp_key, op.destination)] = done
            g.count(op.kind)
        previous_cohort = b.node("cohort.done", [(completion[o.name], 0) for o in ordered])
        ordered = []
    # Dirty hit lines are drained; scan/control overhead is explicitly excluded.
    for cache in b.l1.values():
        for line, record in cache.items():
            if record.dirty:
                b.memory_transfer(
                    b.node("dirty.drain.ready", [(previous_cohort, 0), (record.fill, 0)]),
                    line,
                    write=True,
                )
    g.terminal = b.node("outputs.drained", [(previous_cohort, 0), *[(n, 0) for n in b.writes]])
    # Physical visibility and protocol-response drain are distinct timing windows.
    if b.visible_writes:
        b.node("outputs.visible", [(n, 0) for n in b.visible_writes])
    return g


def simulate(workload, hardware):
    return execute(build_graph(workload, hardware))
