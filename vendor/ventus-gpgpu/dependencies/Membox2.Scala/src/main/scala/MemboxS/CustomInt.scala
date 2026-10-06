package MemboxS

abstract class CustomInt(val size: Int) {
  var data = new Array[Byte](size)
  def toBigInt = Helper.ByteArray2BigInt(data)
  def apply(ba: Array[Byte]) = {data = ba.take(size)}
  def this(size: Int, x: BigInt) = {
    this(size)
    data = x.toByteArray.take(size).reverse.padTo(size, 0.toByte)
  }
}

class Int32 extends CustomInt(4){
  def this(x: BigInt) = {
    this()
    data = x.toByteArray.takeRight(size).reverse.padTo(size, 0.toByte)
  }
}

class Int64 extends CustomInt(8){
  def this(x: BigInt) = {
    this()
    data = x.toByteArray.takeRight(size).reverse.padTo(size, 0.toByte)
  }
}