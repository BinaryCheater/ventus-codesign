(* blackbox *) module wgram1_8x77(	// ventus/src/cta/wg_buffer.scala:55:19
  input  [2:0]  R0_addr,
  input         R0_en,
                R0_clk,
  output [76:0] R0_data,
  input  [2:0]  W0_addr,
  input         W0_en,
                W0_clk,
  input  [76:0] W0_data
);
endmodule
(* blackbox *) module wgram2_8x241(	// ventus/src/cta/wg_buffer.scala:56:19
  input  [2:0]   R0_addr,
  input          R0_en,
                 R0_clk,
  output [240:0] R0_data,
  input  [2:0]   W0_addr,
  input          W0_en,
                 W0_clk,
  input  [240:0] W0_data
);
endmodule
(* blackbox *) module mem_8x3(	// ventus/src/cta/resource_table.scala:583:25, :584:25
  input  [2:0] R0_addr,
  input        R0_en,
               R0_clk,
  output [2:0] R0_data,
  input  [2:0] W0_addr,
  input        W0_en,
               W0_clk,
  input  [2:0] W0_data
);
endmodule
(* blackbox *) module addr_8x17(	// ventus/src/cta/resource_table.scala:585:26, :586:26
  input  [2:0]  R0_addr,
  input         R0_en,
                R0_clk,
  output [16:0] R0_data,
  input  [2:0]  W0_addr,
  input         W0_en,
                W0_clk,
  input  [16:0] W0_data
);
endmodule
(* blackbox *) module addr_8x11(	// ventus/src/cta/resource_table.scala:585:26, :586:26
  input  [2:0]  R0_addr,
  input         R0_en,
                R0_clk,
  output [10:0] R0_data,
  input  [2:0]  W0_addr,
  input         W0_en,
                W0_clk,
  input  [10:0] W0_data
);
endmodule
(* blackbox *) module addr_8x10(	// ventus/src/cta/resource_table.scala:585:26, :586:26
  input  [2:0] R0_addr,
  input        R0_en,
               R0_clk,
  output [9:0] R0_data,
  input  [2:0] W0_addr,
  input        W0_en,
               W0_clk,
  input  [9:0] W0_data
);
endmodule
(* blackbox *) module ram_2x8(	// src/main/scala/chisel3/util/Decoupled.scala:256:91
  input        R0_addr,
               R0_en,
               R0_clk,
  output [7:0] R0_data,
  input        W0_addr,
               W0_en,
               W0_clk,
  input  [7:0] W0_data
);
endmodule
(* blackbox *) module ram_2x257(	// src/main/scala/chisel3/util/Decoupled.scala:256:91
  input          R0_addr,
                 R0_en,
                 R0_clk,
  output [256:0] R0_data,
  input          W0_addr,
                 W0_en,
                 W0_clk,
  input  [256:0] W0_data
);
endmodule
(* blackbox *) module wf_gather_ram_16x39(	// ventus/src/cta/cu_interface.scala:127:34
  input  [3:0]  R0_addr,
  input         R0_en,
                R0_clk,
  output [38:0] R0_data,
  input  [3:0]  W0_addr,
  input         W0_en,
                W0_clk,
  input  [38:0] W0_data
);
endmodule
(* blackbox *) module wf_gather_cnt_16x4(	// ventus/src/cta/cu_interface.scala:165:34
  input  [3:0] R0_addr,
  input        R0_en,
               R0_clk,
  output [3:0] R0_data,
  input  [3:0] W0_addr,
  input        W0_en,
               W0_clk,
  input  [3:0] W0_data
);
endmodule
(* blackbox *) module ram_wid_16x3(	// src/main/scala/chisel3/util/Decoupled.scala:256:91
  input  [3:0] R0_addr,
  input        R0_en,
               R0_clk,
  output [2:0] R0_data,
  input  [3:0] W0_addr,
  input        W0_en,
               W0_clk,
  input  [2:0] W0_data
);
endmodule
(* blackbox *) module regs_256x1024(	// ventus/src/pipeline/regfile.scala:53:25
  input  [7:0]    R0_addr,
  input           R0_en,
                  R0_clk,
  output [1023:0] R0_data,
  input  [7:0]    W0_addr,
  input           W0_en,
                  W0_clk,
  input  [1023:0] W0_data,
  input  [31:0]   W0_mask
);
endmodule
(* blackbox *) module regs_1_512x32(	// ventus/src/pipeline/regfile.scala:24:27
  input  [8:0]  R0_addr,
  input         R0_en,
                R0_clk,
  output [31:0] R0_data,
  input  [8:0]  W0_addr,
  input         W0_en,
                W0_clk,
  input  [31:0] W0_data
);
endmodule
(* blackbox *) module data_8x1024(	// ventus/src/pipeline/MSHR.scala:31:17
  input  [2:0]    R0_addr,
  input           R0_en,
                  R0_clk,
  output [1023:0] R0_data,
  input  [2:0]    W0_addr,
  input           W0_en,
                  W0_clk,
  input  [1023:0] W0_data,
  input  [31:0]   W0_mask
);
endmodule
(* blackbox *) module tag_8x248(	// ventus/src/pipeline/MSHR.scala:32:16
  input  [2:0]   R0_addr,
  input          R0_en,
                 R0_clk,
  output [247:0] R0_data,
  input  [2:0]   W0_addr,
  input          W0_en,
                 W0_clk,
  input  [247:0] W0_data,
  input  [2:0]   W1_addr,
  input          W1_en,
                 W1_clk,
  input  [247:0] W1_data
);
endmodule
(* blackbox *) module ram_2x456(	// src/main/scala/chisel3/util/Decoupled.scala:256:91
  input          R0_addr,
                 R0_en,
                 R0_clk,
  output [455:0] R0_data,
  input          W0_addr,
                 W0_en,
                 W0_clk,
  input  [455:0] W0_data
);
endmodule
(* blackbox *) module ram_2x2(	// src/main/scala/chisel3/util/Decoupled.scala:256:91
  input        R0_addr,
               R0_en,
               R0_clk,
  output [1:0] R0_data,
  input        W0_addr,
               W0_en,
               W0_clk,
  input  [1:0] W0_data
);
endmodule
(* blackbox *) module stack_mem_32x96(	// ventus/src/pipeline/branch_join.scala:38:22
  input  [4:0]  R0_addr,
  input         R0_en,
                R0_clk,
  output [95:0] R0_data,
  input  [4:0]  R1_addr,
  input         R1_en,
                R1_clk,
  output [95:0] R1_data,
  input  [4:0]  R2_addr,
  input         R2_en,
                R2_clk,
  output [95:0] R2_data,
  input  [4:0]  W0_addr,
  input         W0_en,
                W0_clk,
  input  [95:0] W0_data,
  input  [2:0]  W0_mask,
  input  [4:0]  W1_addr,
  input         W1_en,
                W1_clk,
  input  [95:0] W1_data,
  input  [2:0]  W1_mask,
  input  [4:0]  W2_addr,
  input         W2_en,
                W2_clk,
  input  [95:0] W2_data,
  input  [2:0]  W2_mask,
  input  [4:0]  W3_addr,
  input         W3_en,
                W3_clk,
  input  [95:0] W3_data,
  input  [2:0]  W3_mask,
  input  [4:0]  W4_addr,
  input         W4_en,
                W4_clk,
  input  [95:0] W4_data,
  input  [2:0]  W4_mask,
  input  [4:0]  W5_addr,
  input         W5_en,
                W5_clk,
  input  [95:0] W5_data,
  input  [2:0]  W5_mask
);
endmodule
(* blackbox *) module array_256x34(	// ventus/src/SRAMTemplate/SRAMTemplate.scala:96:26
  input  [7:0]  R0_addr,
  input         R0_en,
                R0_clk,
  output [33:0] R0_data,
  input  [7:0]  W0_addr,
  input         W0_en,
                W0_clk,
  input  [33:0] W0_data,
  input  [1:0]  W0_mask
);
endmodule
(* blackbox *) module array_256x2048(	// ventus/src/SRAMTemplate/SRAMTemplate.scala:96:26
  input  [7:0]    R0_addr,
  input           R0_en,
                  R0_clk,
  output [2047:0] R0_data,
  input  [7:0]    W0_addr,
  input           W0_en,
                  W0_clk,
  input  [2047:0] W0_data,
  input  [1:0]    W0_mask
);
endmodule
(* blackbox *) module ram_2x1029(	// src/main/scala/chisel3/util/Decoupled.scala:256:91
  input           R0_addr,
                  R0_en,
                  R0_clk,
  output [1028:0] R0_data,
  input           W0_addr,
                  W0_en,
                  W0_clk,
  input  [1028:0] W0_data
);
endmodule
(* blackbox *) module array_256x20(	// ventus/src/SRAMTemplate/SRAMTemplate.scala:96:26
  input  [7:0]  R0_addr,
  input         R0_en,
                R0_clk,
  output [19:0] R0_data,
  input  [7:0]  W0_addr,
  input         W0_en,
                W0_clk,
  input  [19:0] W0_data,
  input  [1:0]  W0_mask
);
endmodule
(* blackbox *) module array_256x256(	// ventus/src/SRAMTemplate/SRAMTemplate.scala:96:26
  input  [7:0]   R0_addr,
  input          R0_en,
                 R0_clk,
  output [255:0] R0_data,
  input  [7:0]   W0_addr,
  input          W0_en,
                 W0_clk,
  input  [255:0] W0_data,
  input  [1:0]   W0_mask
);
endmodule
(* blackbox *) module ram_32x1059(	// src/main/scala/chisel3/util/Decoupled.scala:256:91
  input  [4:0]    R0_addr,
  input           R0_en,
                  R0_clk,
  output [1058:0] R0_data,
  input  [4:0]    W0_addr,
  input           W0_en,
                  W0_clk,
  input  [1058:0] W0_data
);
endmodule
(* blackbox *) module ram_2x1040(	// src/main/scala/chisel3/util/Decoupled.scala:256:91
  input           R0_addr,
                  R0_en,
                  R0_clk,
  output [1039:0] R0_data,
  input           W0_addr,
                  W0_en,
                  W0_clk,
  input  [1039:0] W0_data
);
endmodule
(* blackbox *) module ram_8x1300(	// src/main/scala/chisel3/util/Decoupled.scala:256:91
  input  [2:0]    R0_addr,
  input           R0_en,
                  R0_clk,
  output [1299:0] R0_data,
  input  [2:0]    W0_addr,
  input           W0_en,
                  W0_clk,
  input  [1299:0] W0_data
);
endmodule
(* blackbox *) module array_512x32(	// ventus/src/SRAMTemplate/SRAMTemplate.scala:96:26
  input  [8:0]  R0_addr,
  input         R0_en,
                R0_clk,
  output [31:0] R0_data,
  input  [8:0]  W0_addr,
  input         W0_en,
                W0_clk,
  input  [31:0] W0_data,
  input  [3:0]  W0_mask
);
endmodule
(* blackbox *) module ram_8x32(	// src/main/scala/chisel3/util/Decoupled.scala:256:91
  input  [2:0]  R0_addr,
  input         R0_en,
                R0_clk,
  output [31:0] R0_data,
  input  [2:0]  W0_addr,
  input         W0_en,
                W0_clk,
  input  [31:0] W0_data
);
endmodule
(* blackbox *) module array_1024x32(	// ventus/src/SRAMTemplate/SRAMTemplate.scala:96:26
  input  [9:0]  R0_addr,
  input         R0_en,
                R0_clk,
  output [31:0] R0_data,
  input  [9:0]  W0_addr,
  input         W0_en,
                W0_clk,
  input  [31:0] W0_data,
  input  [3:0]  W0_mask
);
endmodule
(* blackbox *) module head_32x5(	// ventus/src/L2cache/ListBuffer.scala:46:18
  input  [4:0] R0_addr,
  input        R0_en,
               R0_clk,
  output [4:0] R0_data,
  input  [4:0] W0_addr,
  input        W0_en,
               W0_clk,
  input  [4:0] W0_data,
               W1_addr,
  input        W1_en,
               W1_clk,
  input  [4:0] W1_data
);
endmodule
(* blackbox *) module tail_32x5(	// ventus/src/L2cache/ListBuffer.scala:47:18
  input  [4:0] R0_addr,
  input        R0_en,
               R0_clk,
  output [4:0] R0_data,
  input  [4:0] R1_addr,
  input        R1_en,
               R1_clk,
  output [4:0] R1_data,
  input  [4:0] W0_addr,
  input        W0_en,
               W0_clk,
  input  [4:0] W0_data
);
endmodule
(* blackbox *) module next_32x5(	// ventus/src/L2cache/ListBuffer.scala:49:18
  input  [4:0] R0_addr,
  input        R0_en,
               R0_clk,
  output [4:0] R0_data,
  input  [4:0] W0_addr,
  input        W0_en,
               W0_clk,
  input  [4:0] W0_data
);
endmodule
(* blackbox *) module data_32x1152(	// ventus/src/L2cache/ListBuffer.scala:50:18
  input  [4:0]    R0_addr,
  input           R0_en,
                  R0_clk,
  output [1151:0] R0_data,
  input  [4:0]    W0_addr,
  input           W0_en,
                  W0_clk,
  input  [1151:0] W0_data
);
endmodule
(* blackbox *) module array_64x304(	// ventus/src/L2cache/SRAMTemplate.scala:97:26
  input  [5:0]   R0_addr,
  input          R0_en,
                 R0_clk,
  output [303:0] R0_data,
  input  [5:0]   W0_addr,
  input          W0_en,
                 W0_clk,
  input  [303:0] W0_data,
  input  [15:0]  W0_mask
);
endmodule
(* blackbox *) module array_1024x1024(	// ventus/src/L2cache/SRAMTemplate.scala:97:26
  input  [9:0]    R0_addr,
  input           R0_en,
                  R0_clk,
  output [1023:0] R0_data,
  input  [9:0]    W0_addr,
  input           W0_en,
                  W0_clk,
  input  [1023:0] W0_data,
  input  [127:0]  W0_mask
);
endmodule
(* blackbox *) module data_32x1176(	// ventus/src/L2cache/ListBuffer.scala:50:18
  input  [4:0]    R0_addr,
  input           R0_en,
                  R0_clk,
  output [1175:0] R0_data,
  input  [4:0]    W0_addr,
  input           W0_en,
                  W0_clk,
  input  [1175:0] W0_data
);
endmodule
(* blackbox *) module ram_8x1203(	// src/main/scala/chisel3/util/Decoupled.scala:256:91
  input  [2:0]    R0_addr,
  input           R0_en,
                  R0_clk,
  output [1202:0] R0_data,
  input  [2:0]    W0_addr,
  input           W0_en,
                  W0_clk,
  input  [1202:0] W0_data
);
endmodule
(* blackbox *) module ram_2x1270(	// src/main/scala/chisel3/util/Decoupled.scala:256:91
  input           R0_addr,
                  R0_en,
                  R0_clk,
  output [1269:0] R0_data,
  input           W0_addr,
                  W0_en,
                  W0_clk,
  input  [1269:0] W0_data
);
endmodule
