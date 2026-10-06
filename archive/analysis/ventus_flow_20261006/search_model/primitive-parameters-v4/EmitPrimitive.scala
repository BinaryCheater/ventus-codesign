package top
object EmitPrimitive extends App {
  implicit val p: config.config.Parameters = (new L1Cache.MyConfig).toInstance
  if(args(0) == "tensor") chisel3.emitVerilog(new pipeline.vTCexe,
    Array("--target-dir", args(1), "--target", "verilog"))
  else chisel3.emitVerilog(new L1Cache.ShareMem.SharedMemory,
    Array("--target-dir", args(1), "--target", "verilog"))
}
