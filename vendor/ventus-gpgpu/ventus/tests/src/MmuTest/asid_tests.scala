package play

import L1Cache.MyConfig
import L2cache.TLBundleD_lite
import chisel3._
import chisel3.util._
import chisel3.experimental.BundleLiterals.AddBundleLiteralConstructor
import chisel3.experimental.VecLiterals.AddVecLiteralConstructor
import chiseltest._
import chiseltest.internal.CachingAnnotation
import org.scalatest.freespec
import org.scalatest.freespec.AnyFreeSpec
import chiseltest.simulator.WriteFstAnnotation
import mmu.{AsidLookupEntry, SVParam}
import play.TestUtils._
import top.{host2CTA_data => HostReq}
import top.{CTA2host_data => HostRsp}
import L2cache.{TLBundleA_lite, TLBundleD_lite}

import scala.collection.mutable.ArrayBuffer
import pipeline.pipe
import top._

// 异常定义
case object AsidException extends Exception("ASID overflow!")

case class AdvTest_asid(name: String, meta: Seq[String], data: Seq[String], var warp: Int, var cycles: Int)

// GPU请求发送器类
class RequestSenderGPU(reqPort: DecoupledIO[HostReq], rspPort: DecoupledIO[HostRsp], gap: Int = 5) 
  extends RequestSender(reqPort, rspPort) {
  var wg_list = Array.fill(1)(Array.fill(1)(false))  // 每个runTestCase会重新设置这个数组的大小
  var current_kernel = 0
  var clock_cnt = 0
  var timestamp = 0

  override def add(req: Seq[HostReq]) = {
    print(s"[DEBUG-DETAIL] RequestSenderGPU.add开始 - 当前send_list长度: ${send_list.length}\n")
    print(s"[DEBUG-DETAIL] 添加新请求数量: ${req.length}\n")
    send_list = req
    print(s"[DEBUG-DETAIL] RequestSenderGPU.add结束 - 新send_list长度: ${send_list.length}\n")
    if (req.nonEmpty) {
      print(s"[DEBUG-DETAIL] 第一个请求的内容: ${req.head}\n")
    }
  }
  
  override def finishWait(): Boolean = {
    val result = clock_cnt - timestamp > gap
    print(s"[DEBUG-DETAIL] finishWait检查 - clock_cnt: ${clock_cnt}, timestamp: ${timestamp}, gap: ${gap}, result: ${result}\n")
    result
  }

  def senderEval(): Unit = {
    print(s"[DEBUG-DETAIL] senderEval开始 - send_list非空: ${send_list.nonEmpty}, finishWait: ${finishWait()}\n")
    if(send_list.nonEmpty && finishWait()){
      reqPort.valid.poke(true.B)
      reqPort.bits.poke(send_list.head)
      print(s"[DEBUG-DETAIL] senderEval: 尝试发送请求, 请求内容: ${send_list.head}\n")
    }
    else{
      reqPort.valid.poke(false.B)
      print(s"[DEBUG-DETAIL] senderEval: 无请求发送\n")
    }
    if(checkForValid(reqPort) && checkForReady(reqPort)){
      print(s"[DEBUG-DETAIL] senderEval: 请求发送成功, 移除已发送请求\n")
      send_list = send_list.tail
    }
  }

  def receiverEval(): Unit = {
    print(s"[DEBUG-DETAIL] receiverEval开始 - rspPort valid: ${checkForValid(rspPort)}, ready: ${checkForReady(rspPort)}\n")
    rspPort.ready.poke(true.B)
    if(checkForValid(rspPort) && checkForReady(rspPort)){
      val rsp = rspPort.bits.peek().litValue
      val extract_rsp = (rsp >> parameters.CU_ID_WIDTH).toInt
      print(s"[DEBUG-DETAIL] receiverEval: 收到响应 kernel=${current_kernel}, rsp=${rsp}, extract_rsp=${extract_rsp}, wg_list大小=${wg_list.length}x${wg_list(current_kernel).length}\n")
      wg_list(current_kernel)(extract_rsp) = true
    }
  }

  override def eval() = {
    print(s"[DEBUG-DETAIL] RequestSenderGPU.eval开始 - clock_cnt: ${clock_cnt}\n")
    clock_cnt += 1
    senderEval()
    receiverEval()
    print(s"[DEBUG-DETAIL] RequestSenderGPU.eval结束 - clock_cnt: ${clock_cnt}, wg_list: ${wg_list.map(_.mkString(",")).mkString(";")}\n")
  }
}

class AsidTests extends AnyFreeSpec with ChiselScalatestTester {
  import top.helper._
  
  // 全局共享的页表相关变量
  val ptbr_table = ArrayBuffer.fill(256)(BigInt(-1))
  var ptbr_pos = 1

  "asid_test" in {
    import TestUtils._
    val testCases = List("adv_matadd", "adv_vecadd")
    
    test(new GPGPU_SimWrapper(FakeCache = false, Some(mmu.SV32)))
      .withAnnotations(Seq(CachingAnnotation, VerilatorBackendAnnotation, WriteFstAnnotation)) { c =>
        
      // 初始化设置
      c.io.host_req.initSource()
      c.io.host_req.setSourceClock(c.clock)
      c.io.out_d.initSource() 
      c.io.out_d.setSourceClock(c.clock)
      c.io.host_rsp.initSink()
      c.io.host_rsp.setSinkClock(c.clock)
      c.io.out_a.initSink()
      c.io.out_a.setSinkClock(c.clock)
      
      // 移除全局超时设置
      // c.clock.setTimeout(6000)
      c.clock.step(5)

      val mem = new MemBox[MemboxS.SV32.type](MemboxS.SV32)
      val host_driver = new RequestSenderGPU(c.io.host_req, c.io.host_rsp, 5)
      val mem_driver = new MemPortDriverDelay[TLBundleA_lite, TLBundleD_lite](c.io.out_a, c.io.out_d, mem, 0, 5)

      // 依次运行每个测试用例
      testCases.foreach { caseName =>
        print(s"\n[DEBUG] 开始处理测试用例: ${caseName}\n")
        // 重置host_driver的状态
        host_driver.wg_list = Array.fill(1)(Array.fill(1)(false))
        host_driver.current_kernel = 0
        host_driver.clock_cnt = 0
        host_driver.timestamp = 0
        host_driver.send_list = Nil
        print(s"[DEBUG] 重置host_driver状态: wg_list=${host_driver.wg_list.map(_.mkString(",")).mkString(";")}, current_kernel=${host_driver.current_kernel}\n")
        
        // 为每个测试用例设置独立的超时时间
        c.clock.setTimeout(10000)
        val cycles = runTestCase(caseName, c, mem, host_driver, mem_driver)
        print(s"[DEBUG] 测试用例 ${caseName} 实际执行周期: ${cycles}\n")
        
        ptbr_pos += 1 // 为下一个测试用例准备新的ASID
        c.clock.step(10) // 测试用例之间添加间隔
      }

      // 最后的清理工作
      Seq.fill(300){
        mem_driver.eval()
        c.clock.step(1)
      }
    }
  }
  
  def runTestCase(caseName: String, c: GPGPU_SimWrapper, mem: MemBox[MemboxS.SV32.type], 
                 host_driver: RequestSenderGPU,
                 mem_driver: MemPortDriverDelay[TLBundleA_lite, TLBundleD_lite]) = {
    val iniFile = new IniFile("./ventus/txt/_cases.ini")
    val section = iniFile.sections(caseName)
    val testbench = AdvTest_asid(
      caseName,
      section("Files").map(_ + ".metadata"), 
      section("Files").map(_ + ".data"),
      section("nWarps").head.toInt,
      section("SimCycles").head.toInt
    )
    
    val metaFileDir = testbench.meta.map("./ventus/txt/" + testbench.name + "/" + _)
    val dataFileDir = testbench.data.map("./ventus/txt/" + testbench.name + "/" + _)
    val maxCycle = testbench.cycles

    print(s"[DEBUG] 元数据文件路径: ${metaFileDir.mkString(", ")}\n")
    print(s"[DEBUG] 数据文件路径: ${dataFileDir.mkString(", ")}\n")

    val metas = metaFileDir.map(MetaData(_))
    print(s"[DEBUG] 读取到的元数据数量: ${metas.length}\n")
    metas.zipWithIndex.foreach { case (meta, idx) =>
      print(s"[DEBUG] 元数据 $idx: wg_size=${meta.wg_size}, wf_size=${meta.wf_size}\n")
    }

    parameters.num_warp = (metas.map(_.wg_size.toInt) :+ testbench.warp).max
    parameters.num_thread = metas.head.wf_size.toInt

    print(s"\n开始测试 $caseName:")
    print(s"硬件配置: num_warp = ${parameters.num_warp}, num_thread = ${parameters.num_thread}\n")

    var meta = new MetaData
    var size3d = Array.fill(3)(0)
    
    // 重置时钟计数
    var clock_cnt = 0
    var timestamp = 0
    host_driver.clock_cnt = clock_cnt
    host_driver.timestamp = timestamp

    // 在进入while循环前打印wg_list的状态
    print(s"[DEBUG] 进入while循环前 wg_list状态: ${host_driver.wg_list.map(_.mkString(",")).mkString(";")}\n")
    print(s"[DEBUG] 进入while循环前 current_kernel: ${host_driver.current_kernel}\n")
    print(s"[DEBUG] 进入while循环前 clock_cnt: ${clock_cnt}, timestamp: ${timestamp}\n")

    while(clock_cnt <= maxCycle && !host_driver.wg_list(host_driver.current_kernel).reduce(_ && _)){
      if(clock_cnt % 100 == 0) {
        print(s"[DEBUG-MEM] 当前周期: ${clock_cnt}\n")
      }
      
      print(s"[DEBUG-DETAIL] 循环中 - clock_cnt: ${clock_cnt}, maxCycle: ${maxCycle}, timestamp: ${timestamp}, clock_cnt-timestamp: ${clock_cnt - timestamp}\n")
      print(s"[DEBUG-DETAIL] send_list状态: 剩余请求数=${host_driver.send_list.length}\n")
      
      if(clock_cnt - timestamp == 0){
        print(s"[DEBUG-MEM] 开始新的kernel处理周期\n")
        print(s"[DEBUG-MEM] ASID = ${ptbr_pos}, PTBR = ${ptbr_table(ptbr_pos)}\n")
        
        if(ptbr_table(ptbr_pos) == -1){
          ptbr_table(ptbr_pos) = mem.createRootPageTable()
          c.io.asid_fill.get.valid.poke(true.B)
          print(s"[DEBUG-MEM] 创建新的根页表: ASID = ${ptbr_pos}, PTBR = ${ptbr_table(ptbr_pos)}\n")
          c.io.asid_fill.get.bits.poke((new AsidLookupEntry(mmu.SV32)).Lit(
            _.ptbr -> ptbr_table(ptbr_pos).U,
            _.asid -> ptbr_pos.U,
            _.valid -> true.B
          ))
        }
        else{ 
          c.io.asid_fill.get.valid.poke(false.B)
          print(s"[DEBUG-MEM] 使用已存在的页表: ASID = ${ptbr_pos}, PTBR = ${ptbr_table(ptbr_pos)}\n")
        }

        meta = mem.loadfile(ptbr_table(ptbr_pos), metas.head, dataFileDir.head)
        print(s"[DEBUG-MEM] 文件加载完成: meta.asid = ${meta.asid}\n")
        print(s"[DEBUG-MEM] Buffer基地址: ${meta.buffer_base.map(b => f"0x${b}%x").mkString(", ")}\n")
        
        meta.asid = ptbr_pos
        size3d = meta.kernel_size.map(_.toInt)
        print(s"[DEBUG] 内核大小: ${size3d.mkString("x")}\n")
        print(s"[DEBUG] 设置wg_list前 current_kernel: ${host_driver.current_kernel}\n")
        host_driver.wg_list(host_driver.current_kernel) = Array.fill(size3d(0) * size3d(1) * size3d(2))(false)
        print(s"[DEBUG] 设置wg_list后 wg_list状态: ${host_driver.wg_list.map(_.mkString(",")).mkString(";")}\n")

        print(s"[DEBUG-DETAIL] 生成请求前检查 - meta: ${meta}, size3d: ${size3d.mkString("x")}\n")
        val requests = for {
          i <- 0 until size3d(0)
          j <- 0 until size3d(1)
          k <- 0 until size3d(2)
        } yield {
          val req = meta.generateHostReq(i, j, k, BigInt(ptbr_pos))
          print(s"[DEBUG-DETAIL] 生成请求: i=$i, j=$j, k=$k, ptbr_pos=$ptbr_pos, req=$req\n")
          req
        }
        
        print(s"[DEBUG] 生成的请求总数: ${requests.length}\n")
        host_driver.add(requests)
        print(s"[DEBUG] 添加请求后 send_list长度: ${host_driver.send_list.length}\n")
        
        // 重置时钟计数
        timestamp = clock_cnt
        host_driver.timestamp = timestamp
      }
      else c.io.asid_fill.get.valid.poke(false.B)

      if(ptbr_pos >= 255) throw AsidException

      // 先更新时钟，再调用eval
      c.clock.step(1)
      clock_cnt += 1
      host_driver.clock_cnt = clock_cnt

      host_driver.eval()
      print(s"[DEBUG-DETAIL] host_driver评估后 - clock_cnt: ${clock_cnt}, wg_list: ${host_driver.wg_list.map(_.mkString(",")).mkString(";")}\n")
      
      mem_driver.eval()
      print(s"[DEBUG-DETAIL] mem_driver评估后 - rsp_queue大小: ${mem_driver.rsp_queue.size}\n")

      if (host_driver.wg_list(host_driver.current_kernel).reduce(_ && _) && host_driver.send_list.isEmpty) {
        print(s"[DEBUG-MEM] Kernel执行完成\n")
        print(s"[DEBUG-MEM] 清理页表: ASID = ${ptbr_pos}, PTBR = ${ptbr_table(ptbr_pos)}\n")
        
        if (mem.cleanPageTable(ptbr_table(ptbr_pos))) {
          print(s"[DEBUG-MEM] 页表清理成功\n")
        } else {
          print(s"[DEBUG-MEM] 页表清理失败\n")
        }
        
        timestamp = clock_cnt
        host_driver.timestamp = timestamp
      }
    }

    print(s"[DEBUG] 退出while循环时 wg_list状态: ${host_driver.wg_list.map(_.mkString(",")).mkString(";")}\n")
    print(s"[DEBUG] 退出while循环时 current_kernel: ${host_driver.current_kernel}\n")
    print(s"完成 ${caseName} 测试, 总时钟周期: ${clock_cnt}\n")
    if(top.parameters.INST_CNT){
      c.io.inst_cnt.zipWithIndex.foreach{ case(x, i) =>
        print(s" [${i}: ${x.peek.litValue.toInt}]")
      }
      print(" | ")
    }
    if(top.parameters.INST_CNT_2){
      c.io.inst_cnt2.foreach{ case xs => xs.zipWithIndex.foreach{ case(x, i) =>
        print(s" [${i}: X: ${x(0).peek.litValue} V: ${x(1).peek.litValue}]")
      }}
      print("\n")
    }

    clock_cnt
  }
}
