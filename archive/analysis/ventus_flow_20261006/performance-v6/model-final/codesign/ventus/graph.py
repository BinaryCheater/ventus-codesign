"""Causal timing graph and independent longest-path execution."""

from dataclasses import dataclass, field


@dataclass
class TimingGraph:
    names: list[str] = field(default_factory=lambda: ["start"])
    predecessors: list[list[tuple[int, int]]] = field(default_factory=lambda: [[]])
    terminal: int = 0
    counters: dict[str, int] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)

    def node(self, name, predecessors=()):
        index = len(self.names)
        edges = list(predecessors)
        if not edges:
            edges = [(0, 0)]
        if any(
            type(u) is not int or not 0 <= u < index or type(d) is not int or d < 0
            for u, d in edges
        ):
            raise ValueError("graph edges must be forward with nonnegative integer delays")
        self.names.append(name)
        self.predecessors.append(edges)
        return index

    def count(self, key, value=1):
        self.counters[key] = self.counters.get(key, 0) + value


def execute(graph: TimingGraph):
    times = [0]
    critical = [-1]
    for edges in graph.predecessors[1:]:
        u, delay = max(edges, key=lambda e: times[e[0]] + e[1])
        times.append(times[u] + delay)
        critical.append(u)
    path, current = [], graph.terminal
    while current > 0:
        path.append(graph.names[current])
        current = critical[current]
    return {
        "cycles": times[graph.terminal],
        "events": len(times),
        "counters": graph.counters,
        "critical_path": path[::-1],
        "times": times,
        "limitations": graph.limitations,
    }
