module ScalarALU(	// ventus/src/pipeline/ALU.scala:61:7
  input  [4:0]  io_func,	// ventus/src/pipeline/ALU.scala:62:14
  input  [31:0] io_in2,	// ventus/src/pipeline/ALU.scala:62:14
                io_in1,	// ventus/src/pipeline/ALU.scala:62:14
  output [31:0] io_out,	// ventus/src/pipeline/ALU.scala:62:14
  output        io_cmp_out	// ventus/src/pipeline/ALU.scala:62:14
);

  wire        _shout_r_T = io_func > 5'h9;	// ventus/src/pipeline/ALU.scala:49:31, :112:24
  wire [31:0] in2_inv = {32{_shout_r_T & ~(io_func[4])}} ^ io_in2;	// ventus/src/pipeline/ALU.scala:49:{31,42,49}, :73:20
  wire [31:0] _adder_out_T_5 = io_in1 + in2_inv + {31'h0, _shout_r_T & ~(io_func[4])};	// ventus/src/pipeline/ALU.scala:49:{31,42,49}, :73:20, :74:36, :96:47
  wire        slt =
    io_in1[31] == io_in2[31] ? _adder_out_T_5[31] : io_func[1] ? io_in2[31] : io_in1[31];	// ventus/src/pipeline/ALU.scala:51:35, :74:36, :79:{8,15,24,34,53}, :80:10
  wire        _shout_T = io_func == 5'h5;	// ventus/src/pipeline/ALU.scala:85:26
  wire        _shout_T_1 = io_func == 5'hB;	// ventus/src/pipeline/ALU.scala:85:47
  wire [7:0]  _GEN =
    {{io_in1[11:8], io_in1[15:14]} & 6'h33, 2'h0} | {io_in1[15:12], io_in1[19:16]}
    & 8'h33;	// ventus/src/pipeline/ALU.scala:85:74
  wire [18:0] _GEN_0 =
    {io_in1[5:4],
     io_in1[7:6],
     io_in1[9:8],
     _GEN,
     io_in1[19:18],
     io_in1[21:20],
     io_in1[23]} & 19'h55555;	// ventus/src/pipeline/ALU.scala:85:74
  wire [31:0] shin =
    _shout_T | _shout_T_1
      ? io_in1
      : {io_in1[0],
         io_in1[1],
         io_in1[2],
         io_in1[3],
         io_in1[4],
         _GEN_0[18:15] | {io_in1[7:6], io_in1[9:8]} & 4'h5,
         _GEN_0[14:7] | _GEN & 8'h55,
         _GEN[1],
         _GEN_0[5] | io_in1[18],
         io_in1[19],
         io_in1[20],
         {_GEN_0[2:0], 1'h0} | {io_in1[23:22], io_in1[25:24]} & 4'h5,
         io_in1[25],
         io_in1[26],
         io_in1[27],
         io_in1[28],
         io_in1[29],
         io_in1[30],
         io_in1[31]};	// ventus/src/pipeline/ALU.scala:85:{17,26,36,47,74}
  wire [32:0] _shout_r_T_7 =
    $signed($signed({_shout_r_T & ~(io_func[4]) & shin[31], shin}) >>> io_in2[4:0]);	// ventus/src/pipeline/ALU.scala:49:{31,49}, :84:32, :85:17, :86:{21,36,41,64}
  wire [7:0]  _GEN_1 =
    {{_shout_r_T_7[11:8], _shout_r_T_7[15:14]} & 6'h33, 2'h0}
    | {_shout_r_T_7[15:12], _shout_r_T_7[19:16]} & 8'h33;	// ventus/src/pipeline/ALU.scala:85:74, :86:{64,73}, :87:24
  wire [18:0] _GEN_2 =
    {_shout_r_T_7[5:4],
     _shout_r_T_7[7:6],
     _shout_r_T_7[9:8],
     _GEN_1,
     _shout_r_T_7[19:18],
     _shout_r_T_7[21:20],
     _shout_r_T_7[23]} & 19'h55555;	// ventus/src/pipeline/ALU.scala:85:74, :86:64, :87:24
  wire        _maxu_T = io_in1 > io_in2;	// ventus/src/pipeline/ALU.scala:101:22
  wire        _maxs_T = $signed(io_in1) > $signed(io_in2);	// ventus/src/pipeline/ALU.scala:105:20
  assign io_out =
    io_func == 5'h8
      ? io_in2
      : io_func == 5'h9
          ? io_in1
          : io_func[4:2] == 3'h4
              ? (io_func == 5'h11
                   ? (_maxs_T ? io_in2 : io_in1)
                   : io_func == 5'h10
                       ? (_maxs_T ? io_in1 : io_in2)
                       : io_func == 5'h13
                           ? (_maxu_T ? io_in2 : io_in1)
                           : _maxu_T ? io_in1 : io_in2)
              : io_func == 5'h0 | io_func == 5'hA
                  ? _adder_out_T_5
                  : io_func == 5'h2
                      ? {31'h0, io_in1 == io_in2}
                      : io_func == 5'h3
                          ? {31'h0, io_in1 != io_in2}
                          : {31'h0, io_func > 5'hB & ~(io_func[4]) & slt}
                            | (io_func == 5'h4
                                 ? io_in1 ^ io_in2
                                 : io_func == 5'h6
                                     ? io_in1 | io_in2
                                     : io_func == 5'h7 ? io_in1 & io_in2 : 32'h0)
                            | (_shout_T | _shout_T_1 ? _shout_r_T_7[31:0] : 32'h0)
                            | (io_func == 5'h1
                                 ? {_shout_r_T_7[0],
                                    _shout_r_T_7[1],
                                    _shout_r_T_7[2],
                                    _shout_r_T_7[3],
                                    _shout_r_T_7[4],
                                    _GEN_2[18:15] | {_shout_r_T_7[7:6], _shout_r_T_7[9:8]}
                                      & 4'h5,
                                    _GEN_2[14:7] | _GEN_1 & 8'h55,
                                    _GEN_1[1],
                                    _GEN_2[5] | _shout_r_T_7[18],
                                    _shout_r_T_7[19],
                                    _shout_r_T_7[20],
                                    {_GEN_2[2:0], 1'h0}
                                      | {_shout_r_T_7[23:22], _shout_r_T_7[25:24]} & 4'h5,
                                    _shout_r_T_7[25],
                                    _shout_r_T_7[26],
                                    _shout_r_T_7[27],
                                    _shout_r_T_7[28],
                                    _shout_r_T_7[29],
                                    _shout_r_T_7[30],
                                    _shout_r_T_7[31]}
                                 : 32'h0);	// ventus/src/pipeline/ALU.scala:49:{31,49}, :50:31, :54:{27,32}, :61:7, :74:36, :79:8, :81:72, :85:{26,47,74}, :86:{64,73}, :87:24, :88:{18,37}, :89:{8,17}, :92:{18,27,46}, :93:{8,17,35}, :94:{10,19,38}, :96:{40,47,55}, :97:{16,25,36,47,73,82,101,117,126,144}, :101:{15,22}, :102:15, :105:{15,20}, :106:15, :107:{22,30}, :108:{22,30}, :109:{22,30}, :111:{16,24}, :112:{16,24}, :113:16
  assign io_cmp_out = io_func[0] ^ (io_func[3] ? slt : (io_in1 ^ in2_inv) == 32'h0);	// ventus/src/pipeline/ALU.scala:52:35, :53:30, :61:7, :73:20, :75:28, :79:8, :81:{38,43,72}
endmodule
