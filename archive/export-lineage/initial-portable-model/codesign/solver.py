"""Sparse matrix construction and the HiGHS adapter; no workload semantics."""

from collections import defaultdict
from math import inf

import highspy
import numpy as np


class SparseMilpMatrix:
    def __init__(self):
        self.lower, self.upper, self.cost, self.integer = [], [], [], []
        self.starts, self.indices, self.values = [0], [], []
        self.row_lower, self.row_upper = [], []

    def var(self, lower=0, upper=1, cost=0, integer=False):
        i = len(self.lower)
        self.lower.append(lower)
        self.upper.append(upper)
        self.cost.append(cost)
        if integer:
            self.integer.append(i)
        return i

    def row(self, terms, lower=-inf, upper=inf):
        acc = defaultdict(float)
        for i, value in terms:
            acc[i] += value
        for i, value in sorted(acc.items()):
            if value:
                self.indices.append(i)
                self.values.append(value)
        self.starts.append(len(self.indices))
        self.row_lower.append(lower)
        self.row_upper.append(upper)

    def highs(self, cfg):
        lp = highspy.HighsLp()
        lp.num_col_ = len(self.lower)
        lp.num_row_ = len(self.row_lower)
        lp.col_cost_ = self.cost
        lp.col_lower_ = self.lower
        lp.col_upper_ = self.upper
        lp.row_lower_ = self.row_lower
        lp.row_upper_ = self.row_upper
        lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
        lp.a_matrix_.start_ = self.starts
        lp.a_matrix_.index_ = self.indices
        lp.a_matrix_.value_ = self.values
        h = highspy.Highs()
        h.setOptionValue("output_flag", False)
        h.setOptionValue("time_limit", cfg["experiment"]["time_limit_s"])
        h.setOptionValue("mip_rel_gap", cfg["experiment"]["relative_gap"])
        h.setOptionValue("random_seed", cfg["experiment"]["solver_seed"])
        h.setOptionValue("threads", 1)
        h.passModel(lp)
        h.changeColsIntegrality(
            len(self.integer),
            np.array(self.integer, dtype=np.int32),
            np.array([highspy.HighsVarType.kInteger] * len(self.integer), dtype=np.uint8),
        )
        return h
