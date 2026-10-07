/* Generic BF16 software variants for the instruction frontend. No simulator
 * knows these kernel names. All arithmetic, address generation and traffic
 * below are compiled by official Ventus LLVM. Reductions use warp shuffles;
 * this mapping can be replaced independently. */
static inline float bf(__global const ushort *p, uint i) {
  return __builtin_riscv_ventus_vcvt_fp32_bf16((uint)p[i]);
}
static inline ushort bits(float x) {
  return (ushort)__builtin_riscv_ventus_vcvt_bf16_fp32(x);
}
kernel void embedding_bf16(__global const ushort *w, __global const uint *tokens,
                          __global ushort *out, uint width, uint rows) {
  uint i=get_global_id(0); if(i>=width*rows)return;
  out[i]=w[tokens[i/width]*width+i%width];
}
#define shuffle_xor(value,lane) as_float(__builtin_riscv_ventus_shuffle_bfly_i32(as_uint(value),lane))
kernel void rms_bf16(__global const ushort *x, __global const ushort *w,
                    __global ushort *out, uint width, uint rows, float eps, float inverse_width) {
  uint row=get_group_id(0), lane=get_local_id(0); if(row>=rows)return;
  float sum=0; for(uint c=lane;c<width;c+=32){float v=bf(x,row*width+c);sum+=v*v;}
  sum+=shuffle_xor(sum,16);sum+=shuffle_xor(sum,8);sum+=shuffle_xor(sum,4);
  sum+=shuffle_xor(sum,2);sum+=shuffle_xor(sum,1);
  float r=__builtin_riscv_ventus_vrsqrt_approx_f32(sum*inverse_width+eps);
  for(uint c=lane;c<width;c+=32)out[row*width+c]=bits(__builtin_riscv_ventus_vcvt_fp32_bf16(bits(bf(x,row*width+c)*r))*bf(w,c));
}
/* Split-half rotation, matching Qwen rotate_half. Q/K projection is row-major;
 * output is head-major and writes K directly into its compact shared KV cache. */
kernel void rope_bf16(__global const ushort *x, __global const float *freq,
                     __global ushort *out, uint heads,uint dim,uint rows,
                     uint capacity,uint position,uint append) {
  uint i=get_global_id(0); if(i>=rows*heads*(dim/2))return;
  uint c=i%(dim/2), h=(i/(dim/2))%heads, t=i/(heads*(dim/2));
  float a=bf(x,(t*heads+h)*dim+c), b=bf(x,(t*heads+h)*dim+c+dim/2);
  float angle=(float)(position+t)*freq[c];
  float co=__builtin_riscv_ventus_vcos_approx_f32(angle);
  float si=__builtin_riscv_ventus_vsin_approx_f32(angle);
  uint at=(h*capacity+append+t)*dim+c;
  out[at]=bits(a*co-b*si);out[at+dim/2]=bits(b*co+a*si);
}
kernel void transpose_append_bf16(__global const ushort *x,__global ushort *out,
                                uint heads,uint dim,uint rows,uint capacity,uint append){
 uint i=get_global_id(0);if(i>=rows*heads*dim)return;
 uint c=i%dim,h=(i/dim)%heads,t=i/(heads*dim);
 out[(h*capacity+append+t)*dim+c]=x[i];
}
/* Branchless max for finite inputs: the max instruction keeps the dynamic
 * program independent of tensor values. Causal handling depends only on shape. */
kernel void causal_softmax_bf16(__global const ushort *x,__global ushort *out,
                               __global float *scratch,uint rows,uint cols,uint position,float scale){
 uint row=get_group_id(0),lane=get_local_id(0);if(row>=rows)return;
 float mx=-3.402823466e38F;
 for(uint c=lane;c<cols;c+=32)if(c<=position+row)mx=__builtin_fmaxf(mx,bf(x,row*cols+c)*scale);
 mx=__builtin_fmaxf(mx,shuffle_xor(mx,16));mx=__builtin_fmaxf(mx,shuffle_xor(mx,8));
 mx=__builtin_fmaxf(mx,shuffle_xor(mx,4));mx=__builtin_fmaxf(mx,shuffle_xor(mx,2));mx=__builtin_fmaxf(mx,shuffle_xor(mx,1));
 float sum=0;
 for(uint c=lane;c<cols;c+=32){
  float value=0;if(c<=position+row)value=__builtin_riscv_ventus_vex2_approx_f32((bf(x,row*cols+c)*scale-mx)*1.4426950408889634f);
  scratch[row*cols+c]=value;sum+=value;
 }
 sum+=shuffle_xor(sum,16);sum+=shuffle_xor(sum,8);sum+=shuffle_xor(sum,4);sum+=shuffle_xor(sum,2);sum+=shuffle_xor(sum,1);
 float r=__builtin_riscv_ventus_vrcp_approx_f32(sum);
 for(uint c=lane;c<cols;c+=32)out[row*cols+c]=bits(scratch[row*cols+c]*r);
}
kernel void heads_to_rows_bf16(__global const ushort *x,__global ushort *out,uint heads,uint dim,uint rows){
 uint i=get_global_id(0);if(i>=heads*dim*rows)return;
 uint c=i%dim,h=(i/dim)%heads,t=i/(dim*heads);out[i]=x[(h*rows+t)*dim+c];
}
kernel void packed_add_bf16(__global const uint *a,__global const uint *b,__global uint *out,uint pairs){
 uint i=get_global_id(0);if(i<pairs)out[i]=__builtin_riscv_ventus_vadd_bf16x2(a[i],b[i]);
}
kernel void packed_swiglu_bf16(__global const uint *a,__global const uint *b,__global uint *out,uint pairs){
 uint i=get_global_id(0);if(i<pairs)out[i]=__builtin_riscv_ventus_vmul_bf16x2(__builtin_riscv_ventus_vsilu_approx_bf16x2(a[i]),b[i]);
}

kernel void cast_bf16_f32(__global const ushort *x,__global float *out,uint count){
 uint i=get_global_id(0);if(i<count)out[i]=bf(x,i);
}

kernel void embedding_packed_bf16(__global const ushort *w,__global const uint *tokens,__global ushort *out,uint width,uint rows){
 uint i=get_global_id(0);if(i>=width*rows)return;
 uint token=tokens[i/width],c=i%width,kt=(width+15)/16;
 out[i]=w[((token/16)*kt+c/16)*256+(c%16)*16+token%16];
}
