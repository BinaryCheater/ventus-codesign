package MemboxS

import scala.language.implicitConversions
import scala.tools.nsc.doc.html.HtmlTags.P

class Memory[T <: BaseSV](max_range: BigInt, SV: T) {
  implicit def fct(x: BigInt): CustomInt = SV.gen(x)
  val wordSize = fct(0).size

  val pmm = new PhysicalMemory(max_range, SV)

  def createRootPageTable(): BigInt = {
    if(SV.PageLevels == 0)
      return 0
    val (flag, root) = pmm.findUsable(SV.PageSize)
    if(flag)
      pmm.insertBlock(new Block(root, SV.PageSize))
    root
  }

  def allocateMemory(root: BigInt, vaddr: BigInt, size: Int): BigInt = {
    if(SV.PageLevels == 0) {
      // 对 size 进行页对齐
      val alignedSize = (size + SV.PageSize - 1) / SV.PageSize * SV.PageSize
      pmm.insertBlock(new Block(vaddr, alignedSize, true))
      println(f"[Memory Allocation] Virtual Address: 0x${vaddr}%X (Paging disabled, no translation. Size: ${alignedSize} bytes, Page Aligned)")
      return vaddr
    }
    val realsize = (size + SV.PageSize - 1) / SV.PageSize * SV.PageSize
    val (flag, paddr) = pmm.findUsable(realsize)
    if(!flag || !pmm.insertBlock(new Block(paddr, realsize, true)))
      return 0
    println(f"[Memory Allocation] Total Allocation Size: ${realsize} bytes (Aligned to page size)")
    var pos: BigInt = 0
    val pt_idx = scala.collection.mutable.Seq.fill[Int](SV.PageLevels)(-1)
    val pt_addr = scala.collection.mutable.Seq[BigInt](root, 0, 0)

    while(pos < realsize){
      for(level <- 0 until SV.PageLevels){ // SV39: 3, SV32: 2
        //may need a new entry in PT
        if(SV.VAExtract(vaddr + pos, level) != pt_idx(level)){
          pt_idx(level) = SV.VAExtract(vaddr + pos, level).toInt
          // entry not exist in PT
          if((pmm.readWord(pt_addr(level) + pt_idx(level) * wordSize)._2.toBigInt & BigInt(SV.V))== 0) {
            level match {
              case l if (l == SV.PageLevels - 1) => {
                val pt_entry_tmp = SV.SetPTE(paddr + pos, SV.R|SV.W|SV.X|SV.V)
                pmm.writeWord(pt_addr(level) + pt_idx(level) * wordSize, fct(pt_entry_tmp))
                println(f"[Memory Mapping] Virtual Address: 0x${vaddr + pos}%X -> Physical Address: 0x${paddr + pos}%X (Page Size: ${SV.PageSize} bytes)")
              }
              case _ => {
                val pt_addr_tmp = pmm.findUsable(SV.PageSize)
                if(!pt_addr_tmp._1) return 0
                // create and insert PT
                pmm.insertBlock(new Block(pt_addr_tmp._2, SV.PageSize, true))
                val pt_entry_tmp = SV.SetPTE(pt_addr_tmp._2, SV.V)
                pmm.writeWord(pt_addr(level) + pt_idx(level) * wordSize, fct(pt_entry_tmp))
              }
            }
          }
        }
        if(level < SV.PageLevels - 1)
          pt_addr(level + 1) = SV.PTEToPA(pmm.readWord(pt_addr(level) + pt_idx(level) * wordSize)._2.toBigInt)
      }

      pos += SV.PageSize
    }
    return paddr
  }
  def addrConvert(root: BigInt, vaddr: BigInt): BigInt = {
    if(SV.PageLevels == 0) {
      if(!pmm.blocks.exists(_ == vaddr))
        return 0
      return vaddr
    }
    var pt_addr = root
    for(level <- 0 until SV.PageLevels){
      val pte = pmm.readWord(pt_addr + SV.VAExtract(vaddr, level) * wordSize)._2.toBigInt
      val tmp = SV.PTEToPA(pte)
      if(tmp == 0 || (pte & SV.V) == 0) return 0
      pt_addr = tmp
    }
    pt_addr | (vaddr & BigInt("0fff", 16))
  }
  def readDataVirtual(root: BigInt, vaddr: BigInt, size: Int): (Boolean, Array[Byte]) = {
    if(SV.PageLevels == 0)
      return pmm.readData(vaddr, size)
    var vpn: BigInt = 0; var len: Int = 0
    var out: Array[Byte] = Array.empty
    var paddr = addrConvert(root, vaddr)
    for(it <- 0 until size){
      if(vpn != SV.getVPN(vaddr + it)){
        if(len > 0){
          out = out ++ pmm.readData(paddr, len)._2
          paddr = addrConvert(root, vaddr + it)
        }
        len = 0
        vpn = SV.getVPN(vaddr + it)
      }
      if(paddr == 0) return (false, Array.empty)
      len += 1
    }
    out = out ++ pmm.readData(paddr, len)._2
    return (true, out)
  }
  def readDataPhysical(paddr: BigInt, size: Int, spike_info_pc: BigInt = 0, spike_info_vaddr: BigInt = 0): (Boolean, Array[Byte]) = {
    // if (paddr >= 0 && paddr < 4096) {
    //   throw new IllegalArgumentException(f"Memory.readDataPhysical: Address out of bounds: paddr = 0x$paddr%X, size = $size")
    // }
    // println("success in entering readDataPhysical")
    pmm.readData(paddr, size, spike_info_pc, spike_info_vaddr)
  }
  def readWordPhysical(paddr: BigInt) = pmm.readWord(paddr)
  def readWordsPhysical(paddr: BigInt, num: Int, mask: Array[Boolean]) = pmm.readWords(paddr, num, mask)
  def writeDataVirtual(root: BigInt, vaddr: BigInt, size: Int, in: Array[Byte], mask: Array[Boolean] = Array.empty): Boolean = {
    var vpn: BigInt = 0; var len: Int = 0
    var paddr = addrConvert(root, vaddr)
    for(it <- 0 until size){
      if(vpn != SV.getVPN(vaddr + it)){
        if(len > 0){
          pmm.writeData(paddr, len, in.slice(it - len, it), mask.slice(it - len, it))
          paddr = addrConvert(root, vaddr + it)
        }
        len = 0
        vpn = SV.getVPN(vaddr + it)
      }
      if(paddr == 0) return false
      len += 1
    }
    pmm.writeData(paddr, len, in.slice(size - len, size), mask.slice(size - len, size))
    true
  }
  def writeDataPhysical(paddr: BigInt, size: Int, in: Array[Byte], mask: Array[Boolean] = Array.empty): Boolean = pmm.writeData(paddr, size, in, mask)
  def writeWordPhysical[T1 <: CustomInt](paddr: BigInt, in: T1): Boolean = pmm.writeWord[T1](paddr, in)
  def writeWordsPhysical[T1 <: CustomInt](paddr: BigInt, num: Int, in: Array[T1], mask: Array[Boolean]): Boolean = pmm.writeWords[T1](paddr, num, in, mask)

  def tryAllocate(root: BigInt, vaddr: BigInt, size: Int): Boolean = {
    val lower = vaddr - vaddr % SV.PageSize
    val upper = ((vaddr + size + SV.PageSize - 1) / SV.PageSize) * SV.PageSize
    (lower until upper by SV.PageSize).foreach{ page =>
      if(addrConvert(root, page) == 0)
        allocateMemory(root, page, SV.PageSize)
    }
    true
  }

  def releaseMemory(root: BigInt, vaddr: BigInt): Boolean = {
    if(SV.PageLevels == 0){
      return pmm.removeBlock(vaddr)
    }
    var paddr = addrConvert(root, vaddr)
    val size = pmm.blocks.find(b => b == paddr) match {
      case Some(b) => b.size
      case None => 0
    }
    if(size == 0) return false
    pmm.removeBlock(paddr)

    val pt_addr = scala.collection.mutable.Seq.fill(SV.PageLevels)(BigInt(0))
    pt_addr(0) = root
    var iter = 0
    while(iter < size){
      for(level <- 1 until SV.PageLevels){
        pt_addr(level) = SV.PTEToPA(pmm.readWord(pt_addr(level - 1) + SV.VAExtract(vaddr, level - 1)*wordSize)._2.toBigInt)
      }
      val pt_idx = SV.VAExtract(vaddr + iter, SV.PageLevels - 1)
      pmm.writeWord(pt_addr(SV.PageLevels - 1) + pt_idx * wordSize, fct(0))

      iter += SV.PageSize
    }
    return true
  }
  def cleanPageTable(root: BigInt): Boolean = {
    if(SV.PageLevels == 0)
      return true
    val pt_addr = scala.collection.mutable.Seq.fill(SV.PageLevels)(BigInt(0)); pt_addr(0) = root

    def cleanLevel(level: Int): Boolean = {
      if(level == SV.PageLevels - 1){
        val allEmpty = (0 until SV.PageSize by wordSize).map{ x =>
          (pmm.readWord(pt_addr(level) + x)._2.toBigInt & SV.V) == 0
        }.reduceLeft(_ && _)

        if(allEmpty){
          pmm.removeBlock(pt_addr(level))
          if(level > 0) pmm.writeWord(pt_addr(level - 1), fct(0))
          return true // Remove
        }
        return false // Keep
      }
      else{
        val allEmpty = (0 until SV.PageSize by wordSize).map{ x =>
          pt_addr(level + 1) = SV.PTEToPA(pmm.readWord(pt_addr(level) + x)._2.toBigInt)
          // is already invalid, or sucessfully cleaned
          (pmm.readWord(pt_addr(level) + x)._2.toBigInt & SV.V) == 0 || cleanLevel(level + 1)
        }.reduceLeft(_ && _)
        if(allEmpty){
          pmm.removeBlock(pt_addr(level))
          if(level > 0) pmm.writeWord(pt_addr(level - 1), fct(0))
          return true
        }
        return false
      }
    }

    cleanLevel(0)
  }
  def cleanTask(root: BigInt): Boolean = {
    if(SV.PageLevels == 0)
      return true
    val pt_addr = scala.collection.mutable.Seq.fill(SV.PageLevels)(BigInt(0)); pt_addr(0) = root

    def cleanLevel(level: Int): Boolean = {
      if(level == SV.PageLevels - 1){
        (0 until SV.PageSize by wordSize).map{x =>
          pmm.readWord(pt_addr(level) + x)._2.toBigInt
        }.filter(x => (x & SV.V) != 0).foreach(x => pmm.removeBlock(SV.PTEToPA(x)))
      }
      else{
        (0 until SV.PageSize by wordSize).map{ x =>
          pmm.readWord(pt_addr(level) + x)._2.toBigInt
        }.filter(x => (x & SV.V) != 0).foreach( p => {
          pt_addr(level + 1) = SV.PTEToPA(p)
          cleanLevel(level + 1)
        })
      }
      pmm.removeBlock(pt_addr(level))
      true
    }

    cleanLevel(0)
  }
}
