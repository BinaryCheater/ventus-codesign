package MemboxS
import MemboxS.Helper._

object SimpleTest extends App{
  val mem = new Memory(SV39.PageSize * 64, SV39)
  val root = mem.createRootPageTable()
  print(f"ROOT: $root%016x\n")
  mem.allocateMemory(root, BigInt("4000000000", 16), SV39.PageSize * 16)
  mem.pmm.blocks.foreach{ b =>
    print(f"[${b.addr}%016x - ${b.addr + b.size}%016x)\n")
  }
  val x = Seq(BigInt("76543210", 16), BigInt("0fedcba98", 16), BigInt("0bbbbaaaa", 16), BigInt("0ddddcccc", 16))
    .map(x => BigInt2ByteArray(x, 4)).reduceLeft(_ ++ _)
  mem.writeDataVirtual(root, BigInt("4000000000", 16), 16, x)
  var y = ByteArray2BigInt(mem.readDataVirtual(root, BigInt("4000000004", 16), 4)._2)
  print(f"${y}%016x\n")

  mem.allocateMemory(root, BigInt("4000010000", 16), SV39.PageSize * 8)
  mem.writeDataVirtual(root, BigInt("4000010000", 16), 16, x)
  y = ByteArray2BigInt(mem.readDataVirtual(root, BigInt("4000010008", 16), 4)._2)
  print(f"${y}%016x\n")

  mem.releaseMemory(root, BigInt("4000000000", 16))

  mem.cleanPageTable(root)
  mem.pmm.blocks.foreach { b =>
    print(f"[${b.addr}%016x - ${b.addr + b.size}%016x)\n")
  }
  mem.cleanTask(root)
  print("After Clean\n")
  mem.pmm.blocks.foreach { b =>
    print(f"[${b.addr}%016x - ${b.addr + b.size}%016x)\n")
  }
}
