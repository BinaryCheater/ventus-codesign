"""Control-only translation of AddrCalculate + MSHRv2 for full-line LDS traffic.

This derives a saturated service template from RTL states, not measured cycles.
It excludes bank conflicts/backpressure and is used only as a throughput contract;
the main event model retains per-instruction data and dependency latency.
"""

from collections import deque
from functools import lru_cache


@lru_cache(maxsize=None)
def shared_service_intervals(entries):
    address_state = "idle"
    mshr_state = "idle"
    used, complete = set(), set()
    request_tag = None
    responses = deque()
    output_times = []
    for cycle in range(2048):
        free = next((i for i in range(entries) if i not in used), 0)
        output = min(complete) if complete else 0
        allocate = address_state == "save" and mshr_state == "idle" and len(used) < entries
        response = mshr_state == "idle" and bool(responses) and responses[0][0] <= cycle
        fire = mshr_state == "out" and bool(complete)
        next_mshr = mshr_state
        if mshr_state == "idle":
            if response:
                next_mshr = "add" if allocate else "out"
            elif complete:
                next_mshr = "out"
        elif mshr_state == "out":
            # Source uses valid_entry (first free), not output_entry, in this test.
            next_mshr = "out" if complete - {free} else "idle"
        elif mshr_state == "add":
            next_mshr = "out" if complete else "idle"
        if mshr_state == "idle":
            if response:
                _, tag = responses.popleft()
                complete.add(tag)
                if allocate:
                    request_tag = free
            elif allocate:
                used.add(free)
                request_tag = free
        elif mshr_state == "add":
            used.add(free)
            request_tag = free
        elif fire:
            used.remove(output)
            complete.remove(output)
            output_times.append(cycle)
        if address_state == "idle":
            address_state = "save"
        elif address_state == "save" and allocate:
            address_state = "shared"
        elif address_state == "shared":
            responses.append((cycle + 3, request_tag))
            address_state = "idle"
        mshr_state = next_mshr
    intervals = [b - a for a, b in zip(output_times, output_times[1:])][-64:]
    for period in range(1, 17):
        if len(intervals) == 64 and all(
            x == intervals[i % period] for i, x in enumerate(intervals)
        ):
            return tuple(intervals[:period])
    raise ValueError("no bounded shared coalescer service template found")
