package TestFrame

import chisel3._
import chisel3.util._
import chisel3.experimental.BundleLiterals._
import chiseltest._
import org.scalatest.freespec.AnyFreeSpec

object TestUtils{
  def getValid[T <: Data](port: ReadyValidIO[T]) = port.valid.peek().litToBoolean
  def getReady[T <: Data](port: ReadyValidIO[T]) = port.ready.peek().litToBoolean
  def checkFire[T <: Data](port: ReadyValidIO[T]) = getValid(port) && getReady(port)

  class ListenEvent[+T <: Data](val port: ReadyValidIO[T]) {
    def eval = {
      port.ready.poke(true.B)
      val out = port.bits.peek()
      if(getValid(port)) (true, out) else (false, out)
    }
    def mute = {
      port.ready.poke(false.B)
    }
  }

  class EnqEvent[+T <: Data](val port: ReadyValidIO[T], val in: T, var ttl: Int) {
    def step = {
      ttl = if (ttl == 0) 0 else (ttl - 1)
    }
    def eval: Boolean = {
      step
      port.bits.poke(in)
      if(ttl != 0)
        port.valid.poke(false.B)
      else {
        if (getReady(port) && getValid(port))
          return true
        port.valid.poke(true.B)
      }
      return false
    }
  }
}

class TestExample extends AnyFreeSpec with ChiselScalatestTester {
  import TestUtils._
  "test" in {
    val addrList = (0 until 64).map(_.U)
    val fakeMem: scala.collection.mutable.Seq[BigInt] = (0 until 64).toArray.map(BigInt(_))
    test(new MemRequestorSim(addrList)).withAnnotations(Seq(WriteVcdAnnotation)) { m =>
      var cycle = 0
      m.io.host_req.setSourceClock(m.clock)
      m.io.host_rsp.setSinkClock(m.clock)
      m.io.mem_req.setSinkClock(m.clock)
      m.io.mem_rsp.setSourceClock(m.clock)
      var EnqList: Seq[EnqEvent[Data]] = Seq.empty
      val listen_host = new ListenEvent(m.io.host_rsp)
      val listen_mem = new ListenEvent(m.io.mem_req)
      listen_host.mute
      listen_mem.mute

      var finish = false
      m.clock.step(3)
      cycle += 3


      while (!finish && cycle <= 60) {
        if(cycle == 3)
          EnqList :+= new EnqEvent(m.io.host_req, 3.U, 0)
        listen_host.eval match {
          case (true, x) => finish = true
          case (false, x) => {}
        }
        listen_mem.eval match {
          case (true, x) => {
            var tmp: BigInt = 0
            if(x.rw.litValue == 2){
              tmp = fakeMem(x.addr.litValue.toInt)
            }
            else if(x.rw.litValue == 1){
              tmp = x.data.litValue
              fakeMem(x.addr.litValue.toInt) = tmp
            }
            EnqList :+= new EnqEvent(m.io.mem_rsp, chiselTypeOf(m.io.mem_req.bits).Lit(
              _.addr -> x.addr,
              _.data -> tmp.U,
              _.rw -> x.rw
            ), 3)
          }
          case (false, x) => {}
        }

        m.clock.step(1)
        cycle += 1
        EnqList = EnqList.filter{ e =>
          val f = e.eval
          if(f) e.port.valid.poke(false.B)
          !f
        }
      }
    }
  }

}
