/*
 * Copyright (c) 2021-2022 International Innovation Center of Tsinghua University, Shanghai
 * Ventus is licensed under Mulan PSL v2.
 * You can use this software according to the terms and conditions of the Mulan PSL v2.
 * You may obtain a copy of Mulan PSL v2 at:
 *          http://license.coscl.org.cn/MulanPSL2
 * THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
 * EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
 * MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
 * See the Mulan PSL v2 for more details. */
package L1Cache

import SRAMTemplate._
import chisel3._
import chisel3.util._
import freechips.rocketchip.rocket.ASIdBits
import top.parameters._
import config.config.Parameters
class tagCheckerResult(way: Int) extends Bundle{
  val waymask = UInt(way.W)
  val hit = Bool()
}
//This module contain Tag memory, its valid bits, tag comparator, and Replacement Unit
class L1TagAccess(set: Int, way: Int, tagBits: Int, AsidBits: Int, readOnly: Boolean)(implicit p: Parameters)extends Module{
  val io = IO(new Bundle {
    //From coreReq_pipe0
    val probeRead = Flipped(Decoupled(new SRAMBundleA(set)))//Probe Channel
    val tagFromCore_st1 = Input(UInt(tagBits.W))
    val asidFromCore_st1 = if(MMU_ENABLED) Some(Input(UInt(AsidBits.W))) else None
    val probeIsWrite_st1 = if(!readOnly){Some(Input(Bool()))} else None
    //val coreReqReady = Input(Bool())//TODO try to replace with probeRead.fire
    //To coreReq_pipe1
    val hit_st1 = Output(Bool())
    val waymaskHit_st1 = Output(UInt(way.W))
    //From memRsp_pipe0
    val allocateWrite = Flipped(ValidIO(new SRAMBundleA(set)))//Allocate Channel
    val allocateWriteData_st1 = Input(UInt(tagBits.W))
    val allocateWriteAsid_st1 = if(MMU_ENABLED) Some(Input(UInt(AsidBits.W))) else None
    //From memRsp_pipe1
    val allocateWriteTagSRAMWValid_st1 = Input(Bool())
    //To memRsp_pipe1
    val needReplace = if(!readOnly){
      Some(Output(Bool()))
    } else None
    val waymaskReplacement_st1 = Output(UInt(way.W))//one hot, for SRAMTemplate
    val a_addrReplacement_st1 = if (!readOnly) {
      Some(Output(UInt(xLen.W)))
    } else None
    val asidReplacement_st1 = if(MMU_ENABLED) Some{Output(UInt(AsidBits.W))} else None
    //For InvOrFlu
    val hasDirty_st0 = if (!readOnly) {Some(Output(Bool()))} else None
    val dirtySetIdx_st0 = if (!readOnly) {Some(Output(UInt(log2Up(set).W)))} else None
    val dirtyWayMask_st0 = if (!readOnly) {Some(Output(UInt(way.W)))} else None
    val dirtyTag_st1 = if (!readOnly) {Some(Output(UInt(tagBits.W)))} else None
    val dirtyASID_st1 = if(MMU_ENABLED) {Some(Output(UInt(AsidBits.W)))} else None
    //For InvOrFlu and LRSC
    val flushChoosen = if (!readOnly) {Some(Flipped(ValidIO(UInt((log2Up(set)+way).W))))} else None
    //For Inv
    val invalidateAll = Input(Bool())
    val tagready_st1 = Input(Bool())

    // 本次写入cacheline位置的信息
    val perLaneAddr_st1 = Input(Vec(num_lane, new DCachePerLaneAddr))
    // 全局无效化时，dirty cacheline的 dirty mask
    val dirtyMask_st1 = Output(UInt((dcache_BlockWords * BytesOfWord).W))
    // 分配写要替换的 cacheline 的 dirty mask
    val replace_dirty_mask_st1 = Output(UInt((dcache_BlockWords * BytesOfWord).W))
  })
  //TagAccess internal parameters
  val Length_Replace_time_SRAM: Int = 10
  assert(!(io.probeRead.fire && io.allocateWrite.fire), s"tag probe and allocate in same cycle")
  val probeReadBuf = Queue(io.probeRead,1,pipe=true)
  probeReadBuf.ready := io.tagready_st1

  //access time counter
  val accessFire = io.probeRead.fire || io.allocateWrite.fire
  val (accessCount,accessCounterFull) = Counter(accessFire,1000)

  //For InvOrFlu
  val hasDirty_st0 = Wire(Bool())
  val choosenDirtySetIdx_st0 = Wire(UInt(log2Up(set).W))
  val way_valid = RegInit(VecInit(Seq.fill(set)(VecInit(Seq.fill(way)(0.U(1.W))))))
  // // ***** tag_array::has_dirty *****
  // //val hasDirty_st0 = Wire(Bool())
  // val setDirty = Wire(Vec(set, Bool()))
  // val way_dirtyAfterValid = Wire(Vec(set, Vec(way, Bool())))
  // //val choosenDirtySetIdx_st0 = Wire(UInt(log2Up(set).W))
  // val choosenDirtySetValid = Wire(Vec(way, Bool()))
  // val choosenDirtyWayMask_st0 = Wire(UInt(way.W))//OH
  // val choosenDirtyWayMask_st1 = Wire(UInt(way.W))
  // val choosenDirtyTag_st1 = Wire(UInt(tagBits.W))

    // ***** tag_array::has_dirty *****
  //val hasDirty_st0 = Wire(Bool())
  if(!readOnly) {
    val setDirty = Wire(Vec(set, Bool()))
    val way_dirtyAfterValid = Wire(Vec(set, Vec(way, Bool())))
    //val choosenDirtySetIdx_st0 = Wire(UInt(log2Up(set).W))
    val choosenDirtySetValid = Wire(Vec(way, Bool()))
    val choosenDirtyWayMask_st0 = Wire(UInt(way.W))//OH
    val choosenDirtyWayMask_st1 = Wire(UInt(way.W))
    val choosenDirtyTag_st1 = Wire(UInt(tagBits.W))

  //for Chisel coding convenience, dont set way_dirty to be optional
  val way_dirty = RegInit(VecInit(Seq.fill(set)(VecInit(Seq.fill(way)(0.U(1.W))))))
  //if(!readOnly){Some()} else None
  // allocateWrite_st1
  val Replacement = Module(new ReplacementUnit(Length_Replace_time_SRAM, way))

  val allocateWrite_st1 = RegEnable(io.allocateWrite.bits, io.allocateWrite.fire)
  // ******      tag_array::probe    ******
  val iTagChecker = Module(new tagChecker(way=way,tagIdxBits=tagBits, AsidBits = AsidBits))
  val cachehit_hold = Module(new Queue(new tagCheckerResult(way),1))
  //SRAM to store tag
  val tagBodyAccess = Module(new SRAMTemplate(
    UInt(tagBits.W),
    set=set,
    way=way,
    shouldReset = false,
    holdRead = true,
    singlePort = false,
    bypassWrite = true
  ))
  if(readOnly){
    tagBodyAccess.io.r.req <> io.probeRead
  }else{
    val tagAccessRArb = Module(new Arbiter (new SRAMBundleA(set),3))
    tagBodyAccess.io.r.req <> tagAccessRArb.io.out
    //For probe
    tagAccessRArb.io.in(1)<> io.probeRead
    //For allocate
    tagAccessRArb.io.in(0).valid := io.allocateWrite.valid
    tagAccessRArb.io.in(0).bits.setIdx := io.allocateWrite.bits.setIdx
    //For hasDirty
    tagAccessRArb.io.in(2).valid := !io.probeRead.valid && !io.allocateWrite.valid
    tagAccessRArb.io.in(2).bits.setIdx := choosenDirtySetIdx_st0
    //io.allocateWrite.ready := tagAccessRArb.io.in(0).ready
  }

  // SRAM for storing ASID tag
if(MMU_ENABLED) {
  val ASIDAccess = Module(new SRAMTemplate(
    UInt(AsidBits.W),
    set = set,
    way = way,
    shouldReset = false,
    holdRead = true,
    singlePort = false,
    bypassWrite = true
  ))
  val ASIDAccessRArb = Module(new Arbiter(new SRAMBundleA(set), 2))
  ASIDAccess.io.r.req <> ASIDAccessRArb.io.out //io.probeRead
  ASIDAccessRArb.io.in(0) <> io.probeRead
  ASIDAccessRArb.io.in(1).valid := !io.probeRead.valid && !io.allocateWrite.valid
  ASIDAccessRArb.io.in(1).bits.setIdx := choosenDirtySetIdx_st0
  iTagChecker.io.ASID_of_set.get := ASIDAccess.io.r.resp.data
  iTagChecker.io.ASID_from_pipe.get := io.asidFromCore_st1.get
  val asidReplacement_st1 = ASIDAccess.io.r.resp.data(OHToUInt(Replacement.io.waymask_st1))
  val choosenDirtyASID_st1 = Wire(UInt(AsidBits.W))
  io.asidReplacement_st1.get := asidReplacement_st1
  choosenDirtyASID_st1 := ASIDAccess.io.r.resp.data(OHToUInt(choosenDirtyWayMask_st1))
  io.dirtyASID_st1.get := choosenDirtyASID_st1
  ASIDAccess.io.w.req.valid := io.allocateWriteTagSRAMWValid_st1
  ASIDAccess.io.w.req.bits.apply(data = io.allocateWriteAsid_st1.get, setIdx = allocateWrite_st1.setIdx, waymask = Replacement.io.waymask_st1)
}
  //SRAM for replacement policy
  //store last_access_time for LRU, or last_fill_time for FIFO
  val timeAccess = Module(new SRAMTemplate(
    UInt(Length_Replace_time_SRAM.W),
    set = set,
    way = way,
    shouldReset = false,
    holdRead = true,
    singlePort = false,
    bypassWrite = true
  ))
  timeAccess.io.r.req.valid := io.allocateWrite.fire
  timeAccess.io.r.req.bits.setIdx := io.allocateWrite.bits.setIdx
  //io.allocateWrite.ready := true.B
  //although use arb, src0 and src1 should not come in same cycle
  val timeAccessWArb = Module(new Arbiter (new SRAMBundleAW(UInt(Length_Replace_time_SRAM.W),set,way),2))
  val timeAccessWarbConflict = io.hit_st1 && RegNext(io.allocateWrite.fire, false.B)
  val timeAccessWarbConflictReg = RegNext(timeAccessWarbConflict, false.B)

  assert(!(timeAccessWArb.io.in(0).valid && timeAccessWArb.io.in(1).valid), s"tag probe and allocate in same cycle")
  //LRU replacement policy
  //timeAccessWArb.io.in(0) for regular R/W hit update access time
  timeAccessWArb.io.in(0).valid := Mux(timeAccessWarbConflictReg, RegNext(io.hit_st1, false.B), Mux(timeAccessWarbConflict,false.B,io.hit_st1))//hit already contain probe fire
  timeAccessWArb.io.in(0).bits(
    data = Mux(timeAccessWarbConflictReg,RegNext(accessCount),accessCount),
    setIdx = Mux(timeAccessWarbConflictReg,RegNext(RegNext(io.probeRead.bits.setIdx)),RegNext(io.probeRead.bits.setIdx)),
    waymask = Mux(timeAccessWarbConflictReg,RegNext(io.waymaskHit_st1),io.waymaskHit_st1)
  )
  //timeAccessWArb.io.in(1) for memRsp allocate
  timeAccessWArb.io.in(1).valid := RegNext(io.allocateWrite.fire, false.B)
  timeAccessWArb.io.in(1).bits(
    data = accessCount,
    setIdx = RegNext(io.allocateWrite.bits.setIdx),
    waymask = io.waymaskReplacement_st1
  )
  timeAccess.io.w.req <> timeAccessWArb.io.out//meta_entry_t::update_access_time

  // ******      dirty_mask_array    ******
  //! 不能使用寄存器阵列实现，因为会将verilog代码扩大10倍有余，编译压力太大
  //! 使用阵列的输出同样有个问题，就是阵列是不能一个clk清零的，同时也为了降低写端口的仲裁，直接将way_dirty寄存器用作阵列的valid信号
  // dirty_mask阵列用来记录cacheline中被修改的字节，在写回L2时，只写dirty_mask中为1的位
  // 这个阵列的设计是为了防止多个SM对同一个cacheline的不同部分进行写入时，导致的一致性问题
  // val dirty_mask = RegInit(VecInit(Seq.fill(set)(VecInit(Seq.fill(way)(VecInit(Seq.fill(dcache_BlockWords)(0.U(BytesOfWord.W))))))))  
  val dirtyMaskAccess = Module(new SRAMTemplate(
    UInt((dcache_BlockWords * BytesOfWord).W),
    set = set,
    way = way,
    shouldReset = true,
    holdRead = true,
    singlePort = false,
    bypassWrite = true
  ))
  // 读有3种情况，首先是每次needreplace时，需要读取被冲刷的dirty_mask；然后是无效化时，需要依次读取所有dirty cacheline的dirty_mask；
  // 最后是每次常规读写命中时，需要读取被命中cacheline的dirty_mask与本次写入的dirty_mask，相或得到本次的dirty_mask
  // 因为针对无效化的读是只要有dirty就会一直读，所以要将其优先级放至最低，否则常规写的命中就会一直读不到
  val dirtyMaskArb = Module(new Arbiter(new SRAMBundleA(set),3))
  dirtyMaskAccess.io.r.req <> dirtyMaskArb.io.out
  // 需要在发生分配写的时候就发起读请求，因为在分配写流程的st1阶段，已经能确定被冲刷的cacheline，且要返回给core内
  // 这时候再发起读请求就跟不上时序。所以可以提前于判断是否命中的时候就读出来，反正最后都由need_replace信号作为总的使能
  dirtyMaskArb.io.in(0).valid := io.allocateWrite.fire
  dirtyMaskArb.io.in(0).bits.setIdx := io.allocateWrite.bits.setIdx
  // 在常规写前命中前，需要读取这个set的dirty mask，如果写命中了，需要将读出来的值与本次写入的dirty mask相或
  dirtyMaskArb.io.in(1) <> io.probeRead
  // 只要有dirty时就会发起读请求，但这个读请求只会在顶层的 flushChoosen 信号拉高时才有效
  // 在无效化时，根据之前的流水级，当hasDirty_st0为真时发起读请求，直接将读到的值赋值给out即可
  dirtyMaskArb.io.in(2).valid := hasDirty_st0
  dirtyMaskArb.io.in(2).bits.setIdx := choosenDirtySetIdx_st0


  // 从 perLaneAddr_st1 中构造要写入的dirty mask
  // WireInit不是只执行一次的初始化，而是每个时钟周期都会将Wire重置为初始值,这是组合逻辑，不是寄存器逻辑
  // 会产生类似这样的组合逻辑: assign dirtyMaskPerCL[0] = (条件0满足且blockOffset==0) ? 新值 : 0;
  // dirtyMaskPerCL_init 代表本次要写入的 dirty mask 的初始值，需要与原有的值相或得到本次写入的 dirty mask
  val dirtyMaskPerCL_init = WireInit(VecInit(Seq.fill(dcache_BlockWords)(0.U(BytesOfWord.W))))
  val dirtyMaskPerCL = WireInit(VecInit(Seq.fill(dcache_BlockWords)(0.U(BytesOfWord.W))))
  for (i <- 0 until num_lane) {
    when(io.perLaneAddr_st1(i).activeMask) {
      dirtyMaskPerCL_init(io.perLaneAddr_st1(i).blockOffset) := io.perLaneAddr_st1(i).wordOffset1H 
    }
  }
  dirtyMaskPerCL := (dirtyMaskPerCL_init.asUInt | dirtyMaskAccess.io.r.resp.data(OHToUInt(iTagChecker.io.waymask))).asTypeOf(dirtyMaskPerCL)

  // 一旦用到 dirtyMaskAccess 读出的值，就应该在下个周期将这个位置的 dirty mask 写0，所以写也需要一个仲裁器
  val dirtyMaskWriteArb = Module(new Arbiter(new SRAMBundleAW(UInt((dcache_BlockWords * BytesOfWord).W), set, way), 3))
  dirtyMaskAccess.io.w.req <> dirtyMaskWriteArb.io.out

  // 分配写在st1确定是否需要替换，如果要替换，读出的dirty mask就是被用到，需要在这个阶段发起写0请求
  // 默认 io.needReplace.get 只会拉高一个周期，且不会被阻塞
  dirtyMaskWriteArb.io.in(0).valid := io.needReplace.get
  dirtyMaskWriteArb.io.in(0).bits.apply(data = 0.U, setIdx = allocateWrite_st1.setIdx, waymask = Replacement.io.waymask_st1)
  // 在常规读写命中时，即第一级流水发起写请求，只有这个写请求是给阵列写实际值
  dirtyMaskWriteArb.io.in(1).valid := iTagChecker.io.cache_hit && io.probeIsWrite_st1.get
  dirtyMaskWriteArb.io.in(1).bits.apply(data = dirtyMaskPerCL.asUInt, setIdx = RegNext(io.probeRead.bits.setIdx), waymask = iTagChecker.io.waymask)
  // 只有当 flushChoosen 拉高时，读出来 dirty mask 才会被用到，需要被写0
  // 这里的 valid 需要用 RegNext 延迟一周期是因为在dcache的顶层模块将 InvOrFluMemReqValid_st1 里也延了一个clk
  // 不使用dcache中的 InvOrFluMemReqValid_st1 是因为与tag的发出对齐
  dirtyMaskWriteArb.io.in(2).valid := RegNext(io.flushChoosen.get.valid, false.B)
  dirtyMaskWriteArb.io.in(2).bits.apply(data = 0.U, setIdx = RegNext(choosenDirtySetIdx_st0), waymask = choosenDirtyWayMask_st1)

  iTagChecker.io.tag_of_set := tagBodyAccess.io.r.resp.data//st1
  //iTagChecker.io.ASID_of_set := ASIDAccess.io.r.resp.data
  iTagChecker.io.tag_from_pipe := io.tagFromCore_st1
  //iTagChecker.io.ASID_from_pipe := io.asidFromCore_st1
  iTagChecker.io.way_valid := way_valid(RegEnable(io.probeRead.bits.setIdx,io.probeRead.fire))//st1
  ////st1

  cachehit_hold.io.enq.bits.hit := iTagChecker.io.cache_hit && !probeReadBuf.ready
  cachehit_hold.io.enq.bits.waymask := Mux(!probeReadBuf.ready, iTagChecker.io.waymask ,0.U)
  cachehit_hold.io.enq.valid := probeReadBuf.valid && !probeReadBuf.ready
  cachehit_hold.io.deq.ready := probeReadBuf.ready
  //val cachehit_hold = RegNext(iTagChecker.io.cache_hit && probeReadBuf.valid && !probeReadBuf.ready)
  io.hit_st1 := (iTagChecker.io.cache_hit || cachehit_hold.io.deq.bits.hit && cachehit_hold.io.deq.valid) && probeReadBuf.valid//RegNext(io.probeRead.fire)
  io.waymaskHit_st1 := Mux(cachehit_hold.io.deq.valid & cachehit_hold.io.deq.bits.hit,cachehit_hold.io.deq.bits.waymask,iTagChecker.io.waymask)
  if(!readOnly){//tag_array::write_hit_mark_dirty
    assert(!(iTagChecker.io.cache_hit && io.probeIsWrite_st1.get && io.flushChoosen.get.valid),"way_dirty write-in conflict!")
    when(iTagChecker.io.cache_hit && io.probeIsWrite_st1.get){////meta_entry_t::write_dirty
      way_dirty(RegNext(io.probeRead.bits.setIdx))(OHToUInt(iTagChecker.io.waymask)) := true.B
    }.elsewhen(io.flushChoosen.get.valid){//tag_array::flush_one
      way_dirty(io.flushChoosen.get.bits((log2Up(set)+way)-1,way))(OHToUInt(io.flushChoosen.get.bits(way-1,0))) := false.B
    }.elsewhen(io.needReplace.get) {
      way_dirty(allocateWrite_st1.setIdx)(OHToUInt(Replacement.io.waymask_st1)) := false.B
    }
  }




  if (!readOnly) {
    io.needReplace.get := way_dirty(allocateWrite_st1.setIdx)(OHToUInt(Replacement.io.waymask_st1)).asBool && RegNext(io.allocateWrite.fire, false.B)
  }
  // ******      tag_array::allocate    ******
  Replacement.io.validOfSet := Reverse(Cat(way_valid(allocateWrite_st1.setIdx)))//Reverse(Cat(way_valid(io.allocateWrite.bits.setIdx)))
  Replacement.io.timeOfSet_st1 := timeAccess.io.r.resp.data//meta_entry_t::get_access_time
  io.waymaskReplacement_st1 := Replacement.io.waymask_st1//tag_array::replace_choice
  val tagnset = Cat(tagBodyAccess.io.r.resp.data(OHToUInt(Replacement.io.waymask_st1)), //tag
    allocateWrite_st1.setIdx)

  if (!readOnly) {
    io.a_addrReplacement_st1.get := Cat(tagnset, //setIdx
      0.U((dcache_BlockOffsetBits + dcache_WordOffsetBits).W)) //blockOffset+wordOffset
  }
  // 需要将dirtyMaskAccess读出的数据与way_dirtyAfterValid相与，因为
  io.replace_dirty_mask_st1 := dirtyMaskAccess.io.r.resp.data(OHToUInt(Replacement.io.waymask_st1)).asUInt 

  tagBodyAccess.io.w.req.valid := io.allocateWriteTagSRAMWValid_st1//meta_entry_t::allocate
  tagBodyAccess.io.w.req.bits.apply(data = io.allocateWriteData_st1, setIdx = allocateWrite_st1.setIdx, waymask = Replacement.io.waymask_st1)


  when(RegNext(io.allocateWrite.fire, false.B) && !Replacement.io.Set_is_full){//meta_entry_t::allocate TODO
    way_valid(allocateWrite_st1.setIdx)(OHToUInt(Replacement.io.waymask_st1)) := true.B
  }.elsewhen(io.invalidateAll){//tag_array::invalidate_all()
    way_valid := VecInit(Seq.fill(set)(VecInit(Seq.fill(way)(false.B))))
  }
  assert(!(io.allocateWrite.valid && io.invalidateAll))


    //set一般值为128。
    //评估后，每set配priority mux的成本约为所有set普通mux后共用priority mux的5-6倍，
    //代价是普通 mux 7个2in1 mux的延迟。
    for (i <- 0 until set) {
      way_dirtyAfterValid(i) := VecInit(way_dirty(i).zip(way_valid(i)).map { case (v, d) => v & d })
      setDirty(i) := way_dirtyAfterValid(i).asUInt.orR
    }
    hasDirty_st0 := setDirty.asUInt.orR
    choosenDirtySetIdx_st0 := PriorityEncoder(setDirty)
    choosenDirtySetValid := way_dirtyAfterValid(choosenDirtySetIdx_st0)
    choosenDirtyWayMask_st0 := VecInit(PriorityEncoderOH(choosenDirtySetValid)).asUInt
    choosenDirtyWayMask_st1 := RegNext(choosenDirtyWayMask_st0, 0.U)
    choosenDirtyTag_st1 := tagBodyAccess.io.r.resp.data(OHToUInt(choosenDirtyWayMask_st1))//todo:check correctness

    //val choosenDirtySetIdx_st1 = RegNext(choosenDirtySetIdx_st0)
    //val choosenDirtyWayMask_st1 = RegNext(choosenDirtyWayMask_st0)
    io.dirtyTag_st1.get := choosenDirtyTag_st1
    io.dirtySetIdx_st0.get := choosenDirtySetIdx_st0
    io.dirtyMask_st1 := dirtyMaskAccess.io.r.resp.data(OHToUInt(choosenDirtyWayMask_st1)).asUInt

    io.dirtyWayMask_st0.get := choosenDirtyWayMask_st0
    io.hasDirty_st0.get := hasDirty_st0//RegNext(hasDirty_st0)

}}

class ReplacementUnit(timeLength:Int, way: Int, debug:Boolean=false) extends Module{
  val io = IO(new Bundle {
    val validOfSet = Input(UInt(way.W))//MSB at left
    val timeOfSet_st1 = Input(Vec(way,UInt(timeLength.W)))//MSB at right
    val waymask_st1 = Output(UInt(way.W))
    val Set_is_full = Output(Bool())
  })
  val wayIdxWidth = log2Ceil(way)
  val victimIdx = if (way>1) Wire(UInt(wayIdxWidth.W)) else Wire(UInt(1.W))
  io.Set_is_full := io.validOfSet === Fill(way,1.U)

  if (way>1) {
    val timeOfSetAfterValid = Wire(Vec(way,UInt(timeLength.W)))
    for (i <- 0 until way)
      timeOfSetAfterValid(i) := Mux(io.validOfSet(i),io.timeOfSet_st1(i),0.U)
    val minTimeChooser = Module(new minIdxTree(width=timeLength,numInput=way))
    minTimeChooser.io.candidateIn := timeOfSetAfterValid
    victimIdx := minTimeChooser.io.idxOfMin
  }else victimIdx := 0.U

  io.waymask_st1 := UIntToOH(Mux(io.Set_is_full, victimIdx, PriorityEncoder(~io.validOfSet)))
  // First case, set not full
  //Second case, full set, replacement happens

  //debug use
  if(debug){
    when(io.validOfSet.asBools.reduce(_ | _) === true.B) {
      printf(io.validOfSet.asBools.map{ x => p"${x} " }.reduceOption(_ + _).getOrElse(p"") + p"\n" +
             io.timeOfSet_st1.reverse.map{ x => p"${x} " }.reduceOption(_ + _).getOrElse(p"") +
             p"\noutput: ${io.waymask_st1}\n")
    }
  }
}
class tagChecker(way: Int, tagIdxBits: Int, AsidBits: Int) extends Module{
  val io = IO(new Bundle {
    val tag_of_set = Input(Vec(way,UInt(tagIdxBits.W)))//MSB the valid bit
    val ASID_of_set = if(MMU_ENABLED) Some{Input(Vec(way,UInt(AsidBits.W)))} else None
    //val valid_of_set = Input(Vec(way,Bool()))
    val tag_from_pipe = Input(UInt(tagIdxBits.W))
    val ASID_from_pipe = if(MMU_ENABLED) Some{Input(UInt(AsidBits.W))} else None
    val way_valid = Input(Vec(way,Bool()))

    val waymask = Output(UInt(way.W))//one hot
    val cache_hit = Output(Bool())
  })

  //io.waymask := Cat(io.tag_of_set.zip(io.way_valid).map{ case(tag,valid) => (tag === io.tag_from_pipe) && valid})
  val tagMatch = Wire(UInt(way.W))
  if(MMU_ENABLED){
    val ASIDMatch = Wire(UInt(way.W))
    ASIDMatch := Reverse(Cat(io.ASID_of_set.get.zip(io.way_valid).map{ case(tag,valid) => (tag === io.ASID_from_pipe.get) && valid}))
    io.waymask := tagMatch & ASIDMatch
  } else {
    io.waymask := tagMatch
  }

  tagMatch :=   Reverse(Cat(io.tag_of_set.zip(io.way_valid).map{ case(tag,valid) => (tag === io.tag_from_pipe) && valid}))


  //Reverse(Cat(io.tag_of_set.zip(io.way_valid).map{ case(tag,valid) => (tag === io.tag_from_pipe) && valid}))
  //io.waymask := Reverse(Cat(io.tag_of_set.map{ tag => (tag(tagIdxBits-1,0) === io.tag_from_pipe) && tag(tagIdxBits)}))
  //assert(PopCount(io.waymask) <= 1.U)//if waymask not one-hot, duplicate tags in one set, error
  io.cache_hit := io.waymask.orR
}

class minIdxTree(width: Int, numInput: Int) extends Module{
  val treeLevel = log2Ceil(numInput)
  val io = IO(new Bundle{
    val candidateIn = Input(Vec(numInput, UInt(width.W)))
    val idxOfMin = Output(UInt(treeLevel.W))
  })
  class candWithIdx extends Bundle{
    val candidate = UInt(width.W)
    var index = UInt(treeLevel.W)
  }
  def minWithIdx(a:candWithIdx, b:candWithIdx): candWithIdx = Mux(a.candidate < b.candidate,a,b)

  val candVec = Wire(Vec(numInput,new candWithIdx))
  for(i <- 0 until numInput){
    candVec(i).candidate := io.candidateIn(numInput-1-i)
    candVec(i).index := i.asUInt
  }

  io.idxOfMin := candVec.reduceTree(minWithIdx(_,_)).index
}
class L1TagAccess_ICache(set: Int, way: Int, tagBits: Int, AsidBits: Int)extends Module{
  //This module contain Tag memory, its valid bits, tag comparator, and Replacement Unit
  val io = IO(new Bundle {
    val r = Flipped(new SRAMReadBus(UInt(tagBits.W), set, way))
    val r_asid = if(MMU_ENABLED) Some{Flipped(new SRAMReadBus(UInt(AsidBits.W), set, way))} else None
    val tagFromCore_st1 = Input(UInt(tagBits.W))
    val asidFromCore_st1 = if(MMU_ENABLED) Some{Input(UInt(AsidBits.W))} else None
    val coreReqReady = Input(Bool())

    val w = Flipped(new SRAMWriteBus(UInt(tagBits.W), set, way))
    val w_asid = if(MMU_ENABLED) Some{Flipped(new SRAMWriteBus(UInt(AsidBits.W), set, way))} else None

    val waymaskReplacement = Output(UInt(way.W))//one hot, for SRAMTemplate
    val waymaskHit_st1 = Output(UInt(way.W))

    val hit_st1 = Output(Bool())

    val invalidate = Input(Bool())
  })
  val tagBodyAccess = Module(new SRAMTemplate(
    UInt(tagBits.W),
    set = set,
    way = way,
    shouldReset = false,
    holdRead = true,
    singlePort = false,
    bypassWrite = false
  ))
  tagBodyAccess.io.r <> io.r
  tagBodyAccess.io.r.req.valid := io.r.req.valid && !io.invalidate
  io.r.req.ready := tagBodyAccess.io.r.req.ready && !io.invalidate

  val way_valid = RegInit(VecInit(Seq.fill(set)(VecInit(Seq.fill(way)(0.U(1.W))))))
  //val way_valid = Mem(set, UInt(way.W))
  // ******      Replacement    ******
  val Replacement = Module(new ReplacementUnit_ICache(way))
  // ******      TagChecker    ******
  val iTagChecker = Module(new tagChecker(way = way, tagIdxBits = tagBits, AsidBits = AsidBits))
  iTagChecker.io.tag_of_set := tagBodyAccess.io.r.resp.data //st1
  iTagChecker.io.tag_from_pipe := io.tagFromCore_st1
  if(MMU_ENABLED) {
    val asidAccess = Module(new SRAMTemplate(
      UInt(AsidBits.W),
      set = set,
      way = way,
      shouldReset = false,
      holdRead = true,
      singlePort = false,
      bypassWrite = false
    ))

    asidAccess.io.r <> io.r_asid.get
    asidAccess.io.r.req.valid := io.r.req.valid && !io.invalidate
    io.r.req.ready := asidAccess.io.r.req.ready && !io.invalidate
    iTagChecker.io.ASID_of_set.get := asidAccess.io.r.resp.data
    iTagChecker.io.ASID_from_pipe.get := io.asidFromCore_st1.get
    asidAccess.io.w.req.valid := io.w_asid.get.req.valid && !io.invalidate
    io.w_asid.get.req.ready := asidAccess.io.w.req.ready && !io.invalidate
    asidAccess.io.w.req.bits.apply(data = io.w_asid.get.req.bits.data, setIdx = io.w_asid.get.req.bits.setIdx, waymask = Replacement.io.waymask)
  }
  iTagChecker.io.way_valid := way_valid(RegEnable(io.r.req.bits.setIdx, io.coreReqReady)) //st1
  io.waymaskHit_st1 := iTagChecker.io.waymask //st1
  io.hit_st1 := iTagChecker.io.cache_hit

  Replacement.io.validbits_of_set := Cat(way_valid(io.w.req.bits.setIdx))
  io.waymaskReplacement := Replacement.io.waymask
  tagBodyAccess.io.w.req.valid := io.w.req.valid && !io.invalidate

  io.w.req.ready := tagBodyAccess.io.w.req.ready && !io.invalidate
  tagBodyAccess.io.w.req.bits.apply(data = io.w.req.bits.data, setIdx = io.w.req.bits.setIdx, waymask = Replacement.io.waymask)

  when(io.invalidate) {
    way_valid := 0.U.asTypeOf(way_valid)
  } .elsewhen(io.w.req.valid && !Replacement.io.Set_is_full) {
    way_valid(io.w.req.bits.setIdx)(OHToUInt(Replacement.io.waymask)) := true.B
  }

}
class ReplacementUnit_ICache(way: Int) extends Module{
  val io = IO(new Bundle {
    val validbits_of_set = Input(UInt(way.W))
    val waymask = Output(UInt(way.W))//one hot
    val Set_is_full = Output(Bool())
  })
  val victim_1Hidx = if (way>1) RegInit(1.U(way.W)) else RegInit(0.U(1.W))
  io.Set_is_full := io.validbits_of_set === Fill(way,1.U)
  io.waymask := Mux(io.Set_is_full, victim_1Hidx, UIntToOH(VecInit(io.validbits_of_set.asBools).indexWhere(_===false.B)))
  // First case, set not full
  //Second case, full set, replacement happens
  if (way>1) victim_1Hidx := RegEnable(Cat(victim_1Hidx(way-2,0),victim_1Hidx(way-1)),io.Set_is_full)
}
