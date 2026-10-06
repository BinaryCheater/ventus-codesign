package MemboxS

import scala.collection.mutable.ArrayBuffer

class Page(size: Int) {
  var data: Array[Byte] = Array.fill(size)(0.toByte)
}

class Block(val addr: BigInt, val size: Int, val create_pages: Boolean = true){
  var pages: Page = null
  if(create_pages){
    val num = (size + SV39.PageSize - 1) / SV39.PageSize
    pages = new Page(num * SV39.PageSize)
  }
  def end: BigInt = addr + size
  def <(thatBlock: Block): Boolean = end <= thatBlock.addr
  def >(thatBlock: Block): Boolean = addr >= thatBlock.end
  def <(thatAddr: BigInt): Boolean = end <= thatAddr
  def >(thatAddr: BigInt): Boolean = addr > thatAddr
  def ==(thatAddr: BigInt): Boolean = addr <= thatAddr && end > thatAddr

  def write(base: Int, length: Int, data: Array[Byte], mask: Array[Boolean] = Array.empty): Boolean = {
    if(base + length > size) false
    else if(mask.isEmpty){
      pages.data = pages.data.take(base) ++ data.take(length) ++ pages.data.drop(base + length)
      true
    }
    else{
      pages.data = pages.data.take(base) ++
        ((pages.data.slice(base, base+length) zip data.take(length)) zip mask.take(length)).map{ case ((p, d), m) =>
          if(m) d else p
        } ++ pages.data.drop(base + length)
      true
    }
  }
//  def read(base: Int, length: Int): (Boolean, Array[Byte]) = {
//    if(base + length > size) (false, Array.empty)
//    else (true, pages.data.slice(base, base + length))
//  }
  def read(base: Int, length: Int, spike_info_pc: BigInt = 0, spike_info_vaddr: BigInt = 0): (Boolean, Array[Byte]) = {
    try {
      if (base + length > size) (false, Array.empty)
      else (true, pages.data.slice(base, base + length))
    } catch {
      case e: NullPointerException =>
        println(s"NullPointerException caught: ${e.getMessage}")
        println(f"Block base address: 0x$addr%x, Block size: 0x$size%x, Pages is null: ${pages == null}")
        println(f"data offset address: 0x$base%x, data phys address: 0x${addr+base}%x")
        println(f"spike_info.pc=0x$spike_info_pc%x, spike_info.vaddr=0x$spike_info_vaddr%x")
        (false, Array.empty)
      case e: Exception =>
        println(s"Exception caught: ${e.getMessage}")
        (false, Array.empty)
    }
  }
}

object Block{
  def apply(addr: BigInt, size: Int, create_pages: Boolean = true) = new Block(addr, size, create_pages)
}

class PhysicalMemory(range: BigInt, val SV: BaseSV) {
  var maxRange: BigInt = {
    val x = (range min SV39.MaxPhyRange)
    (x + SV.PageSize - 1) / SV.PageSize * SV.PageSize
  }
  var blocks: ArrayBuffer[Block] = ArrayBuffer(Block(0, SV.PageSize, false), Block(maxRange, SV.PageSize, false))

  def insertBlock(blk: Block): Boolean = {
    val pos = blocks.lastIndexWhere(_ < blk)
    if (pos == -1 || (pos < blocks.size - 1 && !(blk < blocks(pos + 1))))
      false // Block conflict
    else {
      blocks.insert(pos + 1, blk)
      true
    }
  }

  def removeBlock(addr: BigInt): Boolean = {
    val pos = blocks.indexWhere(b => b == addr)
    if (pos == -1) false
    else {
      blocks.remove(pos)
      true
    }
  }

  def writeData(addr: BigInt, length: Int, in: Array[Byte], mask: Array[Boolean] = Array.empty): Boolean = {
    // println(f"writeData blocks.find args: addr=0x$addr%X, length=$length")
    // println(f"Looking for block where: addr >= b.addr && addr + length <= b.end")
    
    val elem = blocks.find(b => {
      val result = addr >= b.addr && addr + length <= b.end
      // println(f"  Checking block: b.addr=0x${b.addr}%X, b.end=0x${b.end}%X, result=$result")
      result
    })
    
    elem match {
      case Some(b) => {
        b.write((addr - b.addr).toInt, length, in, mask)
        // // 添加打印语句来观察数据写入
        // println(f"writeData called: addr=0x$addr%X, length=$length, data=${in.map(byt => f"$byt%02x").mkString(" ")}, mask=${mask.mkString(",")}")
        
        // // 验证数据是否真正写入，通过读取刚刚写入的内容
        // val (success, verificationData) = readData(addr, length)
        // if(success) {
        //   println(f"Data verification - Read after write at addr=0x$addr%X: ${verificationData.map(byt => f"$byt%02x").mkString(" ")}")
        // } else {
        //   println(f"Failed to verify data at addr=0x$addr%X after write")
        // }
        
        true
      }
      case None => {
        // println(f"No suitable block found for addr=0x$addr%X, length=$length")
        false
      }
    }
  }

  def writeWord[T <: CustomInt](addr: BigInt, in: T): Boolean = {
    val dat = in.data
    writeData(addr, dat.length, dat)
  }

  def writeWords[T <: CustomInt](addr: BigInt, num: Int, in: Array[T], mask: Array[Boolean] = Array.empty): Boolean = {
    val dat = in.map(_.data).reduceLeft((l, r) => l ++ r)
    if (mask.isEmpty) {
      writeData(addr, num * dat.length, dat)
    }
    else {
      (0 until num).filter(mask(_)).map { i =>
        writeWord(addr + i * in(i).size, in(i))
      }.reduceLeft(_ && _)
    }
  }

  def readData(addr: BigInt, length: Int, spike_info_pc: BigInt = 0, spike_info_vaddr: BigInt = 0): (Boolean, Array[Byte]) = {
//    if (addr >= 0 && addr < 4096) {
//      throw new IllegalArgumentException(f"PhysicalMemory.readData: Address out of bounds: addr = 0x$addr%X, length = $length")
//    }
    // println(f"readData blocks.find args: addr=0x$addr%X, length=$length")
    // println(f"Looking for block where: addr >= b.addr && addr + length <= b.end")
    
    val elem = blocks.find(b => {
      val result = addr >= b.addr && addr + length <= b.end
      // println(f"  Checking block: b.addr=0x${b.addr}%X, b.end=0x${b.end}%X, result=$result")
      result
    })
    elem match {
      case Some(b) =>{
        val result = b.read((addr - b.addr).toInt, length, spike_info_pc, spike_info_vaddr)
        // println(f"the result of read_state is $result")
        // if(result._1) {
        //   println(f"Data read from addr=0x$addr%X: ${result._2.map(byt => f"$byt%02x").mkString(" ")}")
        // } else {
        //   println(f"Failed to read data from addr=0x$addr%X")
        // }
        result
      }
      case None => 
        // println("No block found for the given address range.")
        (false, Array.empty)
    }
  }

  def readWord[T <: CustomInt](addr: BigInt)(implicit fct: BigInt => T): (Boolean, T) = {
    val word = fct(0)
    val (f, d) = readData(addr, word.size)
    word.data = d
    (f, word)
  }

  def readWords[T <: CustomInt](addr: BigInt, num: Int, mask: Array[Boolean] = Array.empty)(implicit fct: BigInt => T): (Boolean, IndexedSeq[T]) = {
    val length = fct(0).size
    val res = (0 until num).map{ i => readWord(addr + i * length)}.unzip
    if(mask.isEmpty){
      (res._1.reduceLeft(_ && _), res._2)
    }
    else{
      val f = (res._1 zip mask).map(c => c._1 || !c._2).reduceLeft(_ && _)
      val res2 = (res._2 zip mask).map(c => { if(c._2) c._1 else fct(BigInt(0)) })
      (f, res2)
    }
  }

  def findUsable(size: Int): (Boolean, BigInt) = {
    val realsize = (size + SV.PageSize - 1) / SV.PageSize * SV.PageSize
    val elem = (blocks.dropRight(1) zip blocks.drop(1)).find( b => {
      b._2.addr - b._1.end >= realsize
    })
    elem match {
      case Some(ptr) => (true, ptr._1.end)
      case None => (false, BigInt(0))
    }
  }
}
