"""Capture source provenance and check the declarations used by this model."""

import hashlib
import re
import subprocess
from dataclasses import fields
from pathlib import Path

from . import MODEL_VERSION
from .config import Hardware


def extract(root: Path):
    parameters = "ventus/src/top/parameters.scala"
    anchors = {
        "dependencies/fpuv2/src/main/scala/FPToInt.scala": ["override def latency = 2"],
        "dependencies/fpuv2/src/main/scala/IntToFP.scala": ["override def latency = 2"],
        "dependencies/fpuv2/src/main/scala/FPU.scala": [
            "Module(new FMA(expWidth, precision, ctrlGen))",
            "Module(new FCMP(expWidth, precision, ctrlGen))",
            "val outArbiter = Module(new Arbiter(new FPUOutput(64, ctrlGen), 5))",
        ],
        "dependencies/fpuv2/src/main/scala/FMA.scala": [
            "override def latency: Int = 2",
            "override def latency: Int = 1",
            "val toAddArbiterFIFO = Seq.fill(2)",
            "toAddArbiter.io.in(0) <> toAddArbiterFIFO(0).io.deq",
            "toAddArbiter.io.in(1) <> toAddArbiterFIFO(1).io.deq",
        ],
        parameters: [
            "def num_sm = 2",
            "var num_warp = 8",
            "var num_thread = 32",
            "def num_bank = 4",
            "def num_collectorUnit = num_warp",
            "def num_vgpr:Int = 128*num_warp",
            "def num_sgpr:Int = 256*num_warp",
            "def num_lane = num_thread",
            "def dcache_NSets: Int = 256",
            "def dcache_NWays: Int = 2",
            "def dcache_MshrEntry: Int = 4",
            "def dcache_MshrSubEntry: Int = 2",
            "def dcache_wshr_entry: Int = 4",
            "def sharedmem_depth = 1024",
            "def sharemem_size = sharedmem_depth * sharedmem_BlockWords * 4",
            "def l2cache_NSets: Int = 64",
            "def l2cache_NWays: Int = 16",
            "x = Seq(4, 8, 4)",
        ],
        "dependencies/fpuv2/src/main/scala/Tensor.scala": [
            "override def latency = 2",
            "assert(isPow2(DimN) && DimN > 1)",
            "Seq.fill(DimM*DimK-1)",
            "adds = adds :+",
            "val finalAdd = Module",
            "entries = 1, pipe = true",
            "assert(DimM * DimN <= vl)",
            "assert(DimN * DimK <= vl)",
            "assert(DimM * DimK <= vl)",
        ],
        "dependencies/fpuv2/src/main/scala/utils/HasPipelineReg.scala": [
            "valids.drop(i).reduce(_ && _)",
            "io.in.ready := !(!io.out.ready && valids.drop(1).reduce(_ && _))",
        ],
        "ventus/src/pipeline/execution.scala": [
            "val tensor = Module(new TensorCoreFP32",
            "val result_v=Module(new Queue(new WriteVecCtrl,1,pipe=true))",
        ],
        "ventus/src/pipeline/operandCollector.scala": [
            "val s_idle :: s_add :: s_out",
            "when(valid.asUInt =/= ready.asUInt",
            "io.issue.valid := state===s_out",
            "// bankID = (wid + regIdx) % num_bank",
            "crossBar.io.validArbiterVector := RegNext",
        ],
        "ventus/src/pipeline/scoreboard.scala": [
            "vectorReg.clear(io.wb_v_fire",
            "OpColRegV.clear(io.op_colV_out_fire",
            "vectorReg.read(io.ibuffer_if_ctrl.reg_idxw)",
        ],
        "ventus/src/pipeline/ibuffer.scala": [
            "new RRArbiter(new CtrlSigs(),num_warp)",
            "class InstrBufferV2",
        ],
        "ventus/src/pipeline/writeback.scala": [
            "new Arbiter(new WriteScalarCtrl(),num_x)",
            "new Arbiter(new WriteVecCtrl(),num_v)",
        ],
        "ventus/src/cta/allocator.scala": [
            "Currently we prefer CU after the last allocated CU",
            "wgslot(cu_tmp) :=",
            "wfslot(cu_tmp) :=",
        ],
        "ventus/src/pipeline/CTA2warp.scala": [
            "val idx_next_allocate = PriorityEncoder(~idx_using)",
            "io.warpReq.valid:=io.CTAreq.fire",
        ],
        "ventus/src/pipeline/LSU.scala": [
            "entries=1, pipe=true",
            "val s_idle :: s_save :: s_shared",
            "io.to_shared.valid := state===s_shared",
            "class LSU2WB",
        ],
        "ventus/src/pipeline/MSHR.scala": [
            "val s_idle :: s_add  :: s_out",
            "io.to_pipe.valid := complete.orR && state===s_out",
            "io.from_addr.ready := state===s_idle",
            "complete.bitSet(valid_entry, false.B).orR",
            "when(io.from_addr.fire){",
        ],
        "ventus/src/L1Cache/ShareMem/ShareMem.scala": [
            "flow=false,pipe=true",
            "val coreReqisValidRead_st2 = RegNext",
            "val dataAccess_data_st2 = RegEnable",
        ],
        "ventus/src/L1Cache/ShareMem/BankConflictArbiter.scala": [
            "perBankReqCount.map(_>1.U)",
            "do not merge req to same addr",
        ],
        "ventus/src/L1Cache/DCache/DCache.scala": [
            "entries = 1,flow=false,pipe=true",
            "entries = 8,flow=false,pipe=false",
            "writeMissReq",
            "val memRsp_Q = Module(new Queue",
            "val memReq_Q = Module(new Queue",
            "coreRsp_st2_valid_from_memRsp := RegEnable",
        ],
        "ventus/src/L1Cache/L1MSHR.scala": ["val missRspOut_st1 = Module(new Queue"],
        "ventus/src/top/GPGPU_top.scala": [
            "val memReqBuf = Module(new Queue(new TLBundleA_lite(L2param),2))"
        ],
        "ventus/src/top/GPGPU_SimWrapper.scala": [
            "new DecoupledPipe(new TLBundleA_lite(l2cache_params), 2)",
            "new DecoupledPipe(new TLBundleD_lite(l2cache_params), 2)",
        ],
        "ventus/src/L2cache/Parameters.scala": [
            "max(if (micro.dirReg) 3 else 2, (micro.memCycles + cache.blockBeats - 1) / cache.blockBeats)"
        ],
        "ventus/src/L2cache/Directory_test.scala": [
            "val victimWay = victim_LFSR",
            "val xor = lfsr(0) ^ lfsr(1) ^ lfsr(3) ^ lfsr(4)",
        ],
        "ventus/src/L2cache/SinkD.scala": ["io.resp.valid       := RegNext(d.fire"],
        "ventus/src/L2cache/MSHR.scala": ["sink_d_reg :=true.B", "sche_a_valid := true.B"],
        "ventus/src/L2cache/SourceD.scala": ["stateReg := stage_4"],
        "ventus/src/L1Cache/L1TagAccess.scala": [
            "Counter(accessFire,1000)",
            "//LRU replacement policy",
        ],
        "ventus/src/top/Mem_SimWrapper.scala": [
            "val DELAY_DDR: Int = 2",
            "val DEPTH = 5",
            "rsp_data(i).delay === 0.U",
        ],
    }
    evidence = []
    for path, patterns in anchors.items():
        data = (root / path).read_bytes()
        lines = data.decode().splitlines()
        matched = []
        for pattern in patterns:
            hits = [(i, line.strip()) for i, line in enumerate(lines, 1) if pattern in line]
            if not hits:
                raise ValueError(f"source rule changed/missing: {path}: {pattern}")
            matched.append(
                {
                    "anchor": pattern,
                    "lines": [i for i, _ in hits],
                    "examples": [line for _, line in hits[:2]],
                }
            )
        evidence.append(
            {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "rules": matched}
        )
    snapshot = root / "SOURCE.json"
    if snapshot.is_file():
        import json

        manifest = json.loads(snapshot.read_text())
        for path, expected in manifest["files"].items():
            target = root / path
            if not target.resolve().is_relative_to(root.resolve()):
                raise ValueError("source snapshot path escapes root")
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise ValueError(f"source snapshot changed: {path}")
        git = manifest["commit"]
    else:
        git = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    hw = Hardware().validate()
    # These are expression checks for a pinned source family, not a general Scala evaluator.
    text = (root / parameters).read_text()
    for field, declaration in {
        "sms": "num_sm",
        "warps_per_sm": "num_warp",
        "threads": "num_thread",
        "rf_banks": "num_bank",
        "l1_sets": "dcache_NSets",
        "l1_ways": "dcache_NWays",
        "l1_mshrs": "dcache_MshrEntry",
        "l1_subentries": "dcache_MshrSubEntry",
        "l2_sets": "l2cache_NSets",
        "l2_ways": "l2cache_NWays",
        "blocks_per_sm": "num_block",
        "lsu_per_warp": "lsu_num_entry_each_warp",
    }.items():
        match = re.search(rf"(?:def|var) {declaration}(?::\s*Int)?\s*=\s*(\d+)", text)
        if match is None or int(match[1]) != getattr(hw, field):
            raise ValueError(f"default dimension differs from RTL: {field}")
    return {
        "version": MODEL_VERSION,
        "rtl_commit": git,
        "default_hardware": hw.to_dict(),
        "hardware_dimension_count": len(fields(hw)) - 3,
        "external_memory_dimension_count": 3,
        "uses_fitted_timing": False,
        "derived_defaults": {
            "shared_coalescer_service": "4 cycles/request under saturated full-line LDS traffic; derived by executing source control states",
            "l2_block_beats": 1,
            "l2_mshrs": "max(2, ceil(32 / 1)) = 32",
            "l2_replacement_in_rtl": "global 16-bit LFSR, not PLRU or LRU",
            "cache_replacement_in_prototype": "L1 LRU approximation; L2 source LFSR advanced by modeled data requests (I-cache omitted)",
            "cold_read_stages_added": [
                "L1 memReq queue: 1",
                "SM2cluster queue: 1",
                "wrapper pipe_a: 2",
                "wrapper pipe_d: 2",
                "SourceD stage4: 1",
                "L1 coreRsp_st2 register: 1",
            ],
        },
        "source_evidence": evidence,
        "fidelity": {
            "tensor_and_collector": "source-derived stage graph; validate with independent RTL",
            "lds": "source-derived bank rounds and response stages",
            "global_memory": "transaction approximation with explicit target; inclusive-cache internal timing is not fully translated",
            "scheduling": "ready-driven decoded instruction execution, per-block release and elastic compute backpressure; physical RF/cache arbitration remains approximate",
        },
    }
