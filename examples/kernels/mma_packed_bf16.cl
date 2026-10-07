/* Software layout variant of official addmm_mma_bf16 (PyTorch 2b0e0cff).
 * Weight tiles are supplied in the initial device layout. Activation packing
 * below is a timed device dispatch. The MMA and BF16 conversion builtins are
 * the official ABI, with the same fragment and accumulator register windows. */
kernel void pack_a_bf16(__global const ushort *a,__global uint *out,uint m,uint k){
 uint tid=get_global_id(0),lane=tid&31,tile=tid>>5;
 uint kt=(k+15)/16,mt=tile/kt,kk=tile%kt;
 for(uint reg=0;reg<4;reg++){
  uint i=reg*64+lane*2,row=mt*16+i/16,col=kk*16+i%16;
  uint lo=0,hi=0;
  if(row<m&&col<k)lo=a[row*k+col];
  if(row<m&&col+1<k)hi=a[row*k+col+1];
  out[tile*128+reg*32+lane]=lo|(hi<<16);
 }
}
kernel void mma_packed_bf16(__global const uint *a,__global const uint *b,
                          __global const ushort *bias,__global ushort *out,
                          uint m,uint n,uint k,uint has_bias){
 uint tid=get_global_id(0),lane=tid&31,tile=tid>>5;
 uint nt=(n+15)/16,kt=(k+15)/16,mt=tile/nt,nn=tile%nt;
 float bv=0;
 if(has_bias && nn*16+(lane&15)<n)bv=__builtin_riscv_ventus_vcvt_fp32_bf16((uint)bias[nn*16+(lane&15)]);
 float8 acc=(float8)(bv);
 uint ai=mt*kt*128+lane,bi=nn*kt*128+lane;
 for(uint kk=0;kk<kt;kk++,ai+=128,bi+=128){
  uint4 aa=(uint4)(a[ai],a[ai+32],a[ai+64],a[ai+96]);
  uint4 bb=(uint4)(b[bi],b[bi+32],b[bi+64],b[bi+96]);
  acc=__builtin_riscv_ventus_mma_m16n16k16_row_col_f32_bf16_bf16_f32(aa,bb,acc);
 }
 for(uint reg=0;reg<8;reg++){
  uint linear=reg*32+lane,row=mt*16+linear/16,col=nn*16+linear%16;
  if(row<m&&col<n)out[row*n+col]=(ushort)__builtin_riscv_ventus_vcvt_bf16_fp32(acc[reg]);
 }
}
