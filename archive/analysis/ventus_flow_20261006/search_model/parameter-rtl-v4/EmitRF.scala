package top
object EmitRF extends App {
  chisel3.emitVerilog(new pipeline.operandCollector,
    Array("--target-dir", args(0), "--target", "verilog"))
}
