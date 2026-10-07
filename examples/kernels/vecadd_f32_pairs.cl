// Two adjacent outputs per lane; compare against official vecadd_f32.cl.
// Every output and memory access is retained. Launch N/2 workitems for even N.
kernel void vecadd_f32_pairs(__global const float *a,
                            __global const float *b,
                            __global float *c) {
  unsigned int i = 2 * get_global_id(0);
  c[i] = a[i] + b[i];
  c[i + 1] = a[i + 1] + b[i + 1];
}
