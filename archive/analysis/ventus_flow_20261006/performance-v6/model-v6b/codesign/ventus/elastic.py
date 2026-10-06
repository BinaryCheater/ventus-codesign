"""Elastic register stages from FPUv2 HasPipelineReg and non-flow pipe queues."""


class ElasticPipeline:
    def __init__(self, latency):
        if type(latency) is not int or latency < 1:
            raise ValueError("pipeline latency must be a positive integer")
        self.stages = [None] * latency
        self.releases = [None] * latency

    @property
    def output(self):
        return self.stages[-1]

    def ready(self, output_ready):
        result = [False] * len(self.stages)
        following = output_ready
        for i in range(len(self.stages) - 1, -1, -1):
            result[i] = self.stages[i] is None or following
            following = result[i]
        return result

    def advance(self, incoming, output_ready, move=lambda token, stage, release: token):
        ready = self.ready(output_ready)
        outgoing = self.output if output_ready else None
        previous = self.stages[:]
        for i in range(len(previous) - 1, -1, -1):
            if ready[i]:
                token = previous[i - 1] if i else incoming
                self.stages[i] = move(token, i, self.releases[i]) if token is not None else None
                if token is not None and i:
                    # An upstream stage may be replaced on the same edge.
                    self.releases[i - 1] = self.stages[i]
        return incoming is not None and ready[0], outgoing
