package TestFrame

import chisel3._
import chisel3.util._

class MemBundle extends Bundle{
  val addr = UInt(8.W)
  val data = UInt(32.W)
  val rw = UInt(2.W)
}

class MemRequestor(list: Seq[UInt]) extends Module{
  val io = IO(new Bundle{
    val host_req = Flipped(DecoupledIO(UInt(8.W)))
    val host_rsp = DecoupledIO(UInt(8.W))
    val mem_req = DecoupledIO(new MemBundle)
    val mem_rsp = Flipped(DecoupledIO(new MemBundle))
    val out = Output(new MemBundle)
  })
  io.out := io.mem_rsp.bits

  val s_off :: s_end :: s_req :: s_rsp :: Nil = Enum(4)
  val nState = WireInit(s_off)
  val cState = RegNext(nState)
  val count = RegInit(0.U(8.W))
  val ptr = Counter(list.length)
  private val addr_mem = VecInit(list)
  val data_gen = random.LFSR(width = 16, io.mem_rsp.fire, seed = Some(BigInt("1234", 16)))
  val reg_rsp = RegInit(0.U.asTypeOf(new MemBundle))

  io.host_req.ready := cState === s_off
  io.host_rsp.valid := cState === s_end
  io.mem_req.valid := cState === s_req
  io.mem_rsp.ready := cState === s_rsp

  io.mem_req.bits.addr := addr_mem(ptr.value)
  io.mem_req.bits.data := Mux(data_gen(0), data_gen, 0.U)
  io.mem_req.bits.rw := Mux(data_gen(0), 1.U, 2.U)
  io.host_rsp.bits := Mux(cState === s_rsp, 15.U, 0.U)

  switch(cState){
    is(s_off){
      when(io.host_req.fire){
        when(io.host_req.bits =/= 0.U) {
          nState := s_req
          count := io.host_req.bits
        }.otherwise{
          nState := s_off
          ptr.reset()
        }
      }
    }
    is(s_req){
      when(io.mem_req.fire){
        nState := s_rsp
      }.otherwise{nState := s_req}
    }
    is(s_rsp){
      when(io.mem_rsp.fire){
        nState := Mux(count <= 1.U, s_end, s_req)
        reg_rsp := io.mem_rsp.bits
        ptr.inc()
        when(count > 0.U){ count := count - 1.U }
      }.otherwise{ nState := s_rsp }
    }
    is(s_end){
      when(io.host_rsp.fire) { nState := s_off }.otherwise{ nState := s_end }
    }
  }
}

class DecoupledPipe[T <: Data](dat: T, latency: Int = 1) extends Module {
  val io = IO(new Bundle {
    val enq = Flipped(DecoupledIO(dat))
    val deq = DecoupledIO(dat)
  })
  val valids = io.enq.valid +: Seq.fill(latency)(RegInit(false.B))
  io.enq.ready := RegNext(io.deq.ready)
  for (i <- 1 to latency) {
    when(!(!io.deq.ready && valids.drop(i).reduce(_ && _))) {
      valids(i) := valids(i - 1)
    }
  }

  def generate: Seq[T] = {
    var regs = Seq(RegEnable(io.enq.bits, valids(0) && !(!io.deq.ready && valids.drop(1).reduce(_ && _))))
    for (i <- 2 to latency) {
      regs = regs :+ RegEnable(regs.last, valids(i - 1) && !(!io.deq.ready && valids.drop(i).reduce(_ && _)))
    }
    regs
  }

  val regs = generate
  io.enq.ready := !(!io.deq.ready && valids.drop(1).reduce(_ && _))
  io.deq.valid := valids.last
  io.deq.bits := regs.last
}

class MemRequestorSim(list: Seq[UInt]) extends Module{
  val internal = Module(new MemRequestor(list))
  val io = IO(internal.io.cloneType)
  io.out := internal.io.out

  val host_req_fifo = Module(new Queue(io.host_req.bits.cloneType, 2, pipe = true))
  host_req_fifo.io.enq <> io.host_req
  host_req_fifo.io.deq <> internal.io.host_req

  io.host_rsp <> internal.io.host_rsp

  val mem_req_pipe = Module(new DecoupledPipe(io.mem_req.bits.cloneType, 1))
  mem_req_pipe.io.enq <> internal.io.mem_req
  mem_req_pipe.io.deq <> io.mem_req
  val mem_rsp_pipe = Module(new DecoupledPipe(io.mem_rsp.bits.cloneType, 1))
  mem_rsp_pipe.io.enq <> io.mem_rsp
  mem_rsp_pipe.io.deq <> internal.io.mem_rsp
}