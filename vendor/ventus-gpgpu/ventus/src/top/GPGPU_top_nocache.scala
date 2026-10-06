package top
import chisel3._
import chisel3.util._
import parameters._
import L1Cache.MyConfig
import L1Cache.ICache.{InstructionCache, ICacheMemReq_p, ICacheMemRsp, ICacheBundle}
import pipeline.{CTAreqData, CTArspData, CTA2warp, pipe}
import pipeline.{ICachePipeReq_np, ICachePipeRsp_np, DCacheCoreReq_np, DCacheCoreRsp_np}
import L1Cache.ShareMem.SharedMemory
import chisel3.experimental.hierarchy.{Definition, Instance, instantiable, public, Instantiate}
import config.config.Parameters

class SMIO_icache(SV: Option[mmu.SVParam] = None)(implicit p: Parameters) extends ICacheBundle {
  val req = DecoupledIO(new ICacheMemReq_p(SV.getOrElse(mmu.SV32)))
  val rsp = Flipped(DecoupledIO(new ICacheMemRsp()))
}

@instantiable
class SM_wrapper_nocache(val sm_id: Int = 0) extends Module {
  val param = (new MyConfig).toInstance
  @public val io = IO(new Bundle{
    val CTAreq = Flipped(Decoupled(new CTAreqData))
    val CTArsp = Decoupled(new CTArspData)
    val icache = new SMIO_icache()(param)
    val dcache_req = DecoupledIO(new DCacheCoreReq_np)
    val dcache_rsp = Flipped(DecoupledIO(new DCacheCoreRsp_np))
    val icache_invalidate = Input(Bool())
  })

  val cta2warp = Module(new CTA2warp)
  cta2warp.io.CTAreq :<>= io.CTAreq
  io.CTArsp :<>= cta2warp.io.CTArsp

  val pipe = Module(new pipe(sm_id))

  val cnt = Counter(10)
  when(cnt.value < 5.U) { cnt.inc() }
  pipe.io.pc_reset := (cnt.value < 5.U) // Reset the pipe for the first 5 cycles

  pipe.io.warpReq :<>= cta2warp.io.warpReq
  cta2warp.io.warpRsp :<>= pipe.io.warpRsp
  cta2warp.io.wg_id_lookup := pipe.io.wg_id_lookup
  pipe.io.wg_id_tag:=cta2warp.io.wg_id_tag

  val sharedmem = Module(new SharedMemory()(param))
  sharedmem.io.coreReq.bits.data:=pipe.io.shared_req.bits.data
  sharedmem.io.coreReq.bits.instrId:=pipe.io.shared_req.bits.instrId
  sharedmem.io.coreReq.bits.isWrite:=pipe.io.shared_req.bits.isWrite
  sharedmem.io.coreReq.bits.setIdx:=pipe.io.shared_req.bits.setIdx
  sharedmem.io.coreReq.bits.perLaneAddr:=pipe.io.shared_req.bits.perLaneAddr
  sharedmem.io.coreReq.valid:=pipe.io.shared_req.valid
  pipe.io.shared_req.ready:=sharedmem.io.coreReq.ready
  sharedmem.io.coreRsp.ready:=pipe.io.shared_rsp.ready
  pipe.io.shared_rsp.valid:=sharedmem.io.coreRsp.valid
  pipe.io.shared_rsp.bits.data:=sharedmem.io.coreRsp.bits.data
  pipe.io.shared_rsp.bits.instrId:=sharedmem.io.coreRsp.bits.instrId
  pipe.io.shared_rsp.bits.activeMask:=sharedmem.io.coreRsp.bits.activeMask

  val icache = Module(new InstructionCache()(param))
  icache.io.invalidate := io.icache_invalidate
  // **** icache coreReq ****
  pipe.io.icache_req.ready:=icache.io.coreReq.ready
  icache.io.coreReq.valid:=pipe.io.icache_req.valid
  icache.io.coreReq.bits.addr:=pipe.io.icache_req.bits.addr
  icache.io.coreReq.bits.warpid:=pipe.io.icache_req.bits.warpid
  icache.io.coreReq.bits.mask:=pipe.io.icache_req.bits.mask
  if(MMU_ENABLED){ icache.io.coreReq.bits.asid.get := pipe.io.icache_req.bits.asid.get }
  icache.io.coreReq.bits.spike_info.foreach( _ := DontCare )
  // **** icache coreRsp ****
  pipe.io.icache_rsp.valid:=icache.io.coreRsp.valid
  pipe.io.icache_rsp.bits.warpid:=icache.io.coreRsp.bits.warpid
  pipe.io.icache_rsp.bits.data:=icache.io.coreRsp.bits.data
  pipe.io.icache_rsp.bits.addr:=icache.io.coreRsp.bits.addr
  pipe.io.icache_rsp.bits.status:=icache.io.coreRsp.bits.status
  pipe.io.icache_rsp.bits.mask:=icache.io.coreRsp.bits.mask
  icache.io.coreRsp.ready:=pipe.io.icache_rsp.ready
  icache.io.externalFlushPipe.bits.warpid :=pipe.io.externalFlushPipe.bits
  icache.io.externalFlushPipe.valid :=pipe.io.externalFlushPipe.valid

  io.icache.req :<>= icache.io.memReq
  icache.io.memRsp :<>= io.icache.rsp
  io.dcache_req :<>= pipe.io.dcache_req
  pipe.io.dcache_rsp :<>= io.dcache_rsp
}

class GPGPU_top_nocache() extends Module {
  val num_sm = parameters.num_sm
  val param = (new MyConfig).toInstance
  val io = IO(new Bundle {
    val host_req=Flipped(DecoupledIO(new host2CTA_data))
    val host_rsp=DecoupledIO(new CTA2host_data)
    val icache = Vec(num_sm, new SMIO_icache()(param))
    val dcache_req = Vec(num_sm, DecoupledIO(new DCacheCoreReq_np))
    val dcache_rsp = Vec(num_sm, Flipped(DecoupledIO(new DCacheCoreRsp_np)))
    val icache_invalidate = Input(Bool())
  })
  val cta = Module(new CTAinterface)
  val sm_wrapper_inst = Seq.tabulate(num_sm) { i => Instantiate(new SM_wrapper_nocache(i)) }
  val sm_wrapper = VecInit.tabulate(num_sm) { i => sm_wrapper_inst(i).io }

  cta.io.host2CTA :<>= io.host_req
  io.host_rsp :<>= cta.io.CTA2host

  for (i <- 0 until num_sm) {
    sm_wrapper(i).CTAreq :<>= cta.io.CTA2warp(i)
    cta.io.warp2CTA(i) :<>= sm_wrapper(i).CTArsp

    io.icache(i).req :<>= sm_wrapper(i).icache.req
    sm_wrapper(i).icache.rsp :<>= io.icache(i).rsp
    sm_wrapper(i).icache_invalidate := io.icache_invalidate

    io.dcache_req(i) :<>= sm_wrapper(i).dcache_req
    sm_wrapper(i).dcache_rsp :<>= io.dcache_rsp(i)
  }

  import top.ParametersToJson
  ParametersToJson.saveToJson("sim-verilator-nocache/parameters.json")
}
