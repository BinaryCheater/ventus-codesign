"""Ready-driven instruction service and per-block residency.

Decoded streams feed finite collectors and elastic execution pipelines. The
memory transaction abstraction remains explicit; it is not a complete cache or
CTA controller translation. Event graphs record the chosen service execution,
for independent replay and the finite-menu MIP.
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from heapq import heappop, heappush

from .elastic import ElasticPipeline


@dataclass(frozen=True, slots=True)
class Token:
    operation: object
    sm: int
    wid: int
    node: int


class OnlineEngine:
    def __init__(self, builder, workload):
        self.b = builder
        self.hw = builder.hw
        self.workload = workload
        self.streams = defaultdict(deque)
        self.block_ops = defaultdict(list)
        self.fences = {}
        preceding = defaultdict(list)
        has_fences = {op.block for op in workload.operations if op.kind == "barrier"}
        last_fence = {}
        for op in workload.operations:
            self.streams[(op.block, op.warp)].append(op)
            self.block_ops[op.block].append(op)
            self.fences[op.name] = (
                tuple(preceding[op.block])
                if op.kind == "barrier"
                else tuple([last_fence[op.block]])
                if op.block in last_fence
                else ()
            )
            if op.block in has_fences:
                preceding[op.block].append(op.name)
            if op.kind == "barrier":
                last_fence[op.block] = op.name
        self.waiting = deque(self.block_ops)
        self.active = {}
        self.sm_blocks = [set() for _ in range(self.hw.sms)]
        self.warp_free = [set(range(self.hw.warps_per_sm)) for _ in range(self.hw.sms)]
        self.sm_release = [0] * self.hw.sms
        self.last_allocated = self.hw.sms - 1
        self.collectors = [dict() for _ in range(self.hw.sms)]
        self.issue_ready = defaultdict(list)
        self.completion = {}
        self.registers = {}
        self.last_issue = {}
        self.warp_busy = set()
        self.retired = defaultdict(list)
        self.pending = []
        self.serial = 0
        self.clock = 0
        self.clocks = {}
        self.rr_collect = defaultdict(int)
        self.rr_issue = defaultdict(int)
        self.pipelines = {}
        self.lsu_buffer = [None] * self.hw.sms
        self.lsu_output = [deque() for _ in range(self.hw.sms)]
        self.address_until = [0] * self.hw.sms
        self.lsu_warp_count = defaultdict(int)
        self.lsu_count = [0] * self.hw.sms
        self.memory_ops = set()
        self.block_ends = []
        self.wait_stats = defaultdict(int)
        self.blocked_keys = set()
        self.ready_waiters = defaultdict(set)
        self.collect_after = {}

    def at(self, when, action):
        self.serial += 1
        heappush(self.pending, (when, self.serial, action))

    def now(self):
        if self.clock not in self.clocks:
            self.clocks[self.clock] = self.b.node(f"service.clock{self.clock}", [(0, self.clock)])
        return self.clocks[self.clock]

    def allocate(self):
        resident = self.workload.resident_blocks(self.hw)
        while self.waiting:
            choices = [
                (self.last_allocated + 1 + offset) % self.hw.sms for offset in range(self.hw.sms)
            ]
            sm = next(
                (
                    s
                    for s in choices
                    if len(self.sm_blocks[s]) < resident
                    and len(self.warp_free[s]) >= self.workload.warps_per_block
                ),
                None,
            )
            if sm is None:
                break
            block = self.waiting.popleft()
            wids = sorted(self.warp_free[sm])[: self.workload.warps_per_block]
            gate = self.b.node(
                f"block{block}.allocate", [(self.sm_release[sm], 0), (self.now(), 0)]
            )
            self.active[block] = (sm, wids, gate)
            self.sm_blocks[sm].add(block)
            self.warp_free[sm].difference_update(wids)
            self.last_allocated = sm

    def ready_edges(self, key, op):
        if (
            key in self.warp_busy
            or key in self.blocked_keys
            or self.collect_after.get(key, 0) > self.clock
        ):
            return None
        edges = [(self.active[op.block][2], 0)]
        for name in (*op.dependencies, *self.fences[op.name]):
            if name not in self.completion:
                self.blocked_keys.add(key)
                self.ready_waiters[name].add(key)
                return None
            edges.append((self.completion[name], 1))
        for reg in (*op.sources, *([op.destination] if op.destination else [])):
            writer = self.registers.get((key, reg)) if reg != "x0" else None
            if writer:
                if writer not in self.completion:
                    self.blocked_keys.add(key)
                    self.ready_waiters[writer].add(key)
                    return None
                edges.append((self.completion[writer], 1))
        if key in self.last_issue:
            edges.append((self.last_issue[key], 1))
        ready = max(self.b.times[n] + lag for n, lag in edges)
        if ready > self.clock:
            self.collect_after[key] = ready
            return None
        return edges

    @staticmethod
    def path(op):
        return "scalar" if op.kind in {"scalar", "barrier"} else "vector"

    def collect(self):
        for sm in range(self.hw.sms):
            initial_free = sorted(set(range(self.hw.collectors)) - self.collectors[sm].keys())
            source_demux = self.hw.collectors == self.hw.warps_per_sm > 1
            for path in ["vector", "scalar"]:
                free = sorted(set(range(self.hw.collectors)) - self.collectors[sm].keys())
                if not free:
                    continue
                # Source instDemux reserves the first free unit for V when >1 warp.
                # A new unbound collector geometry uses the declared generic allocation.
                if path == "scalar" and source_demux and len(initial_free) < 2:
                    continue
                ready = []
                for key, stream in self.streams.items():
                    if not stream or key[0] not in self.active or self.active[key[0]][0] != sm:
                        continue
                    op = stream[0]
                    if self.path(op) != path or key in self.warp_busy:
                        continue
                    edges = self.ready_edges(key, op)
                    if edges is not None:
                        wid = self.active[key[0]][1][key[1]]
                        ready.append((wid, key, op, edges))
                if not ready:
                    continue
                pivot = self.rr_collect[(sm, path)]
                wid, key, op, edges = min(
                    ready, key=lambda r: (r[0] - pivot) % self.hw.warps_per_sm
                )
                collector = free[0]
                if path == "scalar" and source_demux:
                    collector = initial_free[1]
                accept = self.b.node(op.name + ".collect", [*edges, (self.now(), 0)])
                reads = []
                for index, reg in enumerate(op.sources):
                    bank = (wid + int(reg[1:])) % self.hw.rf_banks
                    reads.append(
                        self.b.reserve(
                            ("rf", sm, reg[0], bank),
                            op.name + f".operand{index}",
                            [(accept, 0)],
                            capacity=self.hw.rf_read_ports,
                        )
                    )
                operands = self.b.node(
                    op.name + ".operands", [(n, 3) for n in reads] if reads else [(accept, 1)]
                )
                token = Token(op, sm, wid, operands)
                self.collectors[sm][collector] = token
                self.streams[key].popleft()
                self.warp_busy.add(key)
                if op.destination and op.destination != "x0":
                    self.registers[(key, op.destination)] = op.name
                self.at(
                    self.b.times[operands],
                    lambda t=token, c=collector: self.issue_ready[
                        (t.sm, self.path(t.operation))
                    ].append((c, t)),
                )
                self.rr_collect[(sm, path)] = (wid + 1) % self.hw.warps_per_sm
                self.b.graph.count(op.kind)

    def pipeline(self, sm, kind, index=0):
        key = (sm, kind, index)
        if key not in self.pipelines:
            latency = {
                "scalar": 1,
                "vector": 1,
                "fadd": 1,
                "fp_add": 2,
                "ftoi": 2,
                "itof": 2,
                "fmax": 2,
                "fma": 3,
                "tensor": self.hw.tensor_latency,
            }[kind]
            self.pipelines[key] = ElasticPipeline(latency)
        return key, self.pipelines[key]

    def retire(self, token, done):
        op = token.operation
        self.completion[op.name] = done
        for key in self.ready_waiters.pop(op.name, ()):
            self.blocked_keys.discard(key)
        self.retired[op.block].append(done)
        if op.name in self.memory_ops:
            self.memory_ops.remove(op.name)
            self.lsu_count[token.sm] -= 1
            self.lsu_warp_count[(token.sm, token.wid)] -= 1
        if len(self.retired[op.block]) == len(self.block_ops[op.block]):
            sm, wids, _ = self.active.pop(op.block)
            end = self.b.node(f"block{op.block}.release", [(n, 0) for n in self.retired[op.block]])
            self.sm_release[sm] = end
            self.block_ends.append(end)
            self.sm_blocks[sm].remove(op.block)
            self.warp_free[sm].update(wids)

    def writebacks(self):
        consumed = set()
        priority = {
            "scalar": 0,
            "vector": 0,
            "fadd": 1,
            "fmax": 1,
            "fma": 1,
            "ftoi": 1,
            "itof": 1,
            "load": 2,
            "tensor": 5,
        }
        for sm in range(self.hw.sms):
            candidates = []
            for key, pipe in self.pipelines.items():
                if key[0] == sm and key[1] not in {"fadd", "fma"} and pipe.output is not None:
                    token = pipe.output
                    candidates.append((priority[token.operation.kind], key, token))
            if self.lsu_output[sm]:
                candidates.append((2, None, self.lsu_output[sm][0]))
            ports, banks = defaultdict(int), defaultdict(int)
            fpu_used = False
            for _, key, token in sorted(
                candidates,
                key=lambda r: (
                    r[0],
                    {"fadd": 0, "fma": 0, "fmax": 1, "ftoi": 3, "itof": 4}.get(
                        r[2].operation.kind, 0
                    ),
                    str(r[1]),
                ),
            ):
                op = token.operation
                path = op.destination[0] if op.destination else "v"
                bank = (
                    (token.wid + int(op.destination[1:])) % self.hw.rf_banks
                    if op.destination
                    else 0
                )
                if (
                    (fpu_used and op.kind in {"fadd", "fma", "fmax", "ftoi", "itof"})
                    or ports[path] >= self.hw.writeback_ports
                    or banks[(path, bank)] >= self.hw.rf_write_ports
                ):
                    self.wait_stats["writeback_stall_cycles"] += 1
                    continue
                ready = self.b.node(op.name + ".wb.ready", [(token.node, 0), (self.now(), 0)])
                done = self.b.writeback(op, ready, sm, token.wid)
                if self.b.times[done] != self.clock:
                    raise RuntimeError("online WB service booked a future cycle")
                fpu_used |= op.kind in {"fadd", "fma", "fmax", "ftoi", "itof"}
                ports[path] += 1
                banks[(path, bank)] += 1
                if key is None:
                    self.lsu_output[sm].popleft()
                else:
                    consumed.add(key)
                    self.pipelines[key].releases[-1] = (done, 1)
                self.retire(token, done)
        return consumed

    def address(self):
        for sm, token in enumerate(self.lsu_buffer):
            if (
                token is None
                or self.address_until[sm] > self.clock
                or self.lsu_count[sm] > self.hw.lsu_entries
            ):
                continue
            start = self.b.node(
                token.operation.name + ".lsu.dequeue", [(token.node, 0), (self.now(), 0)]
            )
            done = self.b.memory_instruction(start, token.operation, sm, token.wid)
            release = self.b.resources[("lsu.address.release", sm)][-1]
            self.address_until[sm] = self.b.times[release]
            self.lsu_buffer[sm] = None
            result = Token(token.operation, token.sm, token.wid, done)
            if token.operation.destination:
                self.at(self.b.times[done], lambda t=result: self.lsu_output[t.sm].append(t))
            else:
                self.at(self.b.times[done], lambda t=result: self.retire(t, t.node))

    def issue(self, consumed):
        incoming = {}
        for sm in range(self.hw.sms):
            for path in ["scalar", "vector"]:
                queue = self.issue_ready[(sm, path)]
                available = []
                for collector, token in queue:
                    op = token.operation
                    target = None
                    if op.kind in {"load", "store"}:
                        if (
                            self.lsu_buffer[sm] is not None
                            or self.lsu_warp_count[(sm, token.wid)] >= self.hw.lsu_per_warp
                        ):
                            continue
                    elif op.kind == "barrier":
                        # IR carries one collective block fence, not individual
                        # hardware arrivals. Its prefix has retired before collection.
                        pass
                    else:
                        count = self.hw.tensor_units if op.kind == "tensor" else 1
                        for i in range(count):
                            key, pipe = self.pipeline(sm, op.kind, i)
                            if pipe.ready(key in consumed)[0] and key not in incoming:
                                target = key
                                break
                        if target is None:
                            self.wait_stats["execution_input_stall_cycles"] += 1
                            continue
                    available.append((collector, token, target))
                if not available:
                    continue
                pivot = self.rr_issue[(sm, path)]
                collector, token, target = min(
                    available, key=lambda r: (r[0] - pivot) % self.hw.collectors
                )
                op = token.operation
                issue = self.b.node(op.name + ".issue", [(token.node, 0), (self.now(), 0)])
                self.last_issue[(op.block, op.warp)] = issue
                self.warp_busy.remove((op.block, op.warp))
                self.collectors[sm].pop(collector)
                queue.remove((collector, token))
                self.rr_issue[(sm, path)] = (collector + 1) % self.hw.collectors
                if op.kind in {"load", "store"}:
                    self.memory_ops.add(op.name)
                    self.lsu_count[sm] += 1
                    self.lsu_warp_count[(sm, token.wid)] += 1
                    self.lsu_buffer[sm] = Token(token.operation, token.sm, token.wid, issue)
                elif op.kind == "barrier":
                    done = self.b.node(
                        op.name + ".barrier",
                        [(issue, 0), *[(n, 0) for n in self.retired[op.block]]],
                    )
                    for warp in range(self.workload.warps_per_block):
                        self.last_issue[(op.block, warp)] = done
                    self.retire(token, done)
                else:
                    unit = self.b.node(op.name + ".execute", [(issue, 0)])
                    incoming[target] = Token(token.operation, token.sm, token.wid, unit)
        return incoming

    def fpu_transfers(self, consumed):
        """One-entry pipe queues feed the shared adder; multiply has priority."""
        incoming = {}
        for sm in range(self.hw.sms):
            feeders = [(sm, kind, 0) for kind in ("fma", "fadd")]
            waiting = [
                key for key in feeders if key in self.pipelines and self.pipelines[key].output
            ]
            if not waiting:
                continue
            target, pipe = self.pipeline(sm, "fp_add")
            if not pipe.ready(target in consumed)[0]:
                self.wait_stats["fpu_add_backpressure_cycles"] += len(waiting)
                continue
            source = waiting[0]
            token = self.pipelines[source].output
            node = self.b.node(
                token.operation.name + ".shared_add", [(token.node, 0), (self.now(), 0)]
            )
            incoming[target] = Token(token.operation, token.sm, token.wid, node)
            consumed.add(source)
            self.pipelines[source].releases[-1] = (node, 1)
            if len(waiting) > 1:
                self.wait_stats["fpu_add_arbitration_stalls"] += 1
        return incoming

    def advance(self, incoming, consumed):
        for key, pipe in self.pipelines.items():

            def move(token, stage, release):
                edges = [(token.node, 1)]
                if release is not None:
                    edges.append(release if isinstance(release, tuple) else (release.node, 0))
                node = self.b.node(token.operation.name + f".pipeline{stage}", edges)
                if self.b.times[node] != self.clock + 1:
                    raise RuntimeError("elastic pipeline causal edges lost a stall")
                if stage == len(pipe.stages) - 1:
                    node = self.b.node(token.operation.name + ".result", [(node, 0)])
                return Token(token.operation, token.sm, token.wid, node)

            accepted, _ = pipe.advance(incoming.get(key), key in consumed, move)
            if key in incoming and not accepted:
                raise RuntimeError("execution accepted a stalled input")

    def run(self):
        while self.waiting or self.active:
            if hasattr(self.b, "prune") and self.clock % 128 == 0:
                self.b.prune(self.clock)
            while self.pending and self.pending[0][0] <= self.clock:
                _, _, action = heappop(self.pending)
                action()
            consumed = self.writebacks()
            self.allocate()
            self.address()
            incoming = self.fpu_transfers(consumed)
            incoming.update(self.issue(consumed))
            # A newly issued memory request may enter an idle address path this cycle.
            self.address()
            self.collect()
            self.advance(incoming, consumed)
            self.clock += 1
            # With no buffered execution work, only a scheduled operand/memory
            # completion can unlock a stream. Preserve the next handshake edge.
            if (
                self.pending
                and not incoming
                and not any(any(p.stages) for p in self.pipelines.values())
                and not any(self.lsu_buffer)
                and not any(self.lsu_output)
                and not any(self.issue_ready.values())
                and all(
                    not stream or self.ready_edges(key, stream[0]) is None
                    for key, stream in self.streams.items()
                    if key[0] in self.active
                )
            ):
                self.clock = max(self.clock, self.pending[0][0])
            if self.clock > 10_000_000:
                raise ValueError("decoded execution did not make bounded progress")
        for cache in self.b.l1.values():
            for line, record in cache.items():
                if record.dirty:
                    self.b.memory_transfer(
                        self.b.node(
                            "dirty.drain.ready",
                            [(n, 0) for n in self.block_ends] + [(record.fill, 0)],
                        ),
                        line,
                        write=True,
                    )
        self.b.graph.terminal = self.b.node(
            "outputs.drained", [(n, 0) for n in self.block_ends] + [(n, 0) for n in self.b.writes]
        )
        if self.b.visible_writes:
            self.b.node("outputs.visible", [(n, 0) for n in self.b.visible_writes])
        self.b.graph.counters.update(self.wait_stats)
        return self.b.graph
