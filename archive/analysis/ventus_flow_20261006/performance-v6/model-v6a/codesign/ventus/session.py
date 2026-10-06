"""Bounded instruction batches with persistent cache tags and explicit write fences.

Each batch is a software dispatch: all requests drain before the next dispatch.
This deliberately does not claim equivalence to an unbounded concurrent kernel.
"""

from collections import OrderedDict

from .graph import execute
from .online import OnlineEngine
from .timing import Builder, Line


class SummaryBuilder(Builder):
    """Use the same service recurrence without retaining names or DAG edges."""

    def node(self, name, edges=()):
        node = len(self.times)
        time = 0
        times = self.times
        for source, delay in edges:
            candidate = times[source] + delay
            if candidate > time:
                time = candidate
        times.append(time)
        return node

    def prune(self, clock):
        # New requests cannot begin before the online clock. Keep all future
        # bookings; resource capacity histories retain their last release nodes.
        for slots in self.calendars.values():
            for bookings in slots:
                bookings[:] = [booking for booking in bookings if booking[1] > clock]
        retain = max(
            self.hw.l2_mshrs,
            self.hw.l1_mshrs,
            self.hw.l1_subentries,
            self.hw.l1_write_entries,
            self.hw.lsu_entries,
            self.hw.lsu_per_warp,
        )
        for history in self.resources.values():
            if len(history) > retain:
                del history[:-retain]


class TimingSession:
    def __init__(self, hardware, *, mode="summary"):
        hardware.validate()
        if mode not in {"summary", "detailed"}:
            raise ValueError("mode must be summary or detailed")
        self.hw, self.mode = hardware, mode
        self.l1, self.l2 = {}, {}
        self.lfsr = 0
        self.cycles = 0
        self.counters = {}
        self.events = 0
        self.peak_batch_events = 0

    def dispatch(self, workload):
        workload.validate(self.hw)
        builder = (SummaryBuilder if self.mode == "summary" else Builder)(self.hw)
        for key, cache in self.l1.items():
            builder.l1[key] = OrderedDict((line, Line(0, way=r.way)) for line, r in cache.items())
        for key, cache in self.l2.items():
            builder.l2[key] = OrderedDict((line, Line(0, way=r.way)) for line, r in cache.items())
        builder.l2_lfsr = self.lfsr
        graph = OnlineEngine(builder, workload).run()
        cycles = builder.times[graph.terminal]
        if self.mode == "detailed" and execute(graph)["cycles"] != cycles:
            raise RuntimeError("independent DAG replay disagrees with online timing")
        # Explicit software coherence policy: after the dispatch write fence,
        # invalidate written lines on every SM and in the retained L2 directory.
        # Dirty hit lines were drained by OnlineEngine.run, write misses by the
        # terminal fence. Read-only tags are retained, never pinned indefinitely.
        written = {
            a // self.hw.line_bytes * self.hw.line_bytes
            for op in workload.operations
            if op.kind == "store"
            for a in op.addresses
            if not 0x70000000 <= a < 0x70000000 + self.hw.lds_bytes
        }
        for caches in (builder.l1, builder.l2):
            for cache in caches.values():
                for line in written:
                    cache.pop(line, None)
        self.l1, self.l2, self.lfsr = builder.l1, builder.l2, builder.l2_lfsr
        start = self.cycles
        self.cycles += cycles
        events = len(builder.times)
        self.events += events
        self.peak_batch_events = max(self.peak_batch_events, events)
        counters = dict(graph.counters)
        for key, value in counters.items():
            self.counters[key] = self.counters.get(key, 0) + value
        return {
            "start": start,
            "end": self.cycles,
            "cycles": cycles,
            "events": events,
            "counters": counters,
        }
