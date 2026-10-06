#include "Vdut.h"
#include <iostream>
#include <vector>
#include <cstring>
#include <cstdint>
#include <cstdlib>
uint32_t bits(float v) {uint32_t b;std::memcpy(&b,&v,4);return b;}
int main(int argc,char**argv) {
 Verilated::commandArgs(argc,argv);int m=std::atoi(argv[1]),n=std::atoi(argv[2]),k=std::atoi(argv[3]);
 std::cout<<"{\"modes\":[";
 for(int mode=0;mode<2;mode++) {
 Vdut d; uint32_t* a[]={&d.io_in_bits_in1_0, &d.io_in_bits_in1_1, &d.io_in_bits_in1_2, &d.io_in_bits_in1_3, &d.io_in_bits_in1_4, &d.io_in_bits_in1_5, &d.io_in_bits_in1_6, &d.io_in_bits_in1_7, &d.io_in_bits_in1_8, &d.io_in_bits_in1_9, &d.io_in_bits_in1_10, &d.io_in_bits_in1_11, &d.io_in_bits_in1_12, &d.io_in_bits_in1_13, &d.io_in_bits_in1_14, &d.io_in_bits_in1_15, &d.io_in_bits_in1_16, &d.io_in_bits_in1_17, &d.io_in_bits_in1_18, &d.io_in_bits_in1_19, &d.io_in_bits_in1_20, &d.io_in_bits_in1_21, &d.io_in_bits_in1_22, &d.io_in_bits_in1_23, &d.io_in_bits_in1_24, &d.io_in_bits_in1_25, &d.io_in_bits_in1_26, &d.io_in_bits_in1_27, &d.io_in_bits_in1_28, &d.io_in_bits_in1_29, &d.io_in_bits_in1_30, &d.io_in_bits_in1_31};uint32_t* b[]={&d.io_in_bits_in2_0, &d.io_in_bits_in2_1, &d.io_in_bits_in2_2, &d.io_in_bits_in2_3, &d.io_in_bits_in2_4, &d.io_in_bits_in2_5, &d.io_in_bits_in2_6, &d.io_in_bits_in2_7, &d.io_in_bits_in2_8, &d.io_in_bits_in2_9, &d.io_in_bits_in2_10, &d.io_in_bits_in2_11, &d.io_in_bits_in2_12, &d.io_in_bits_in2_13, &d.io_in_bits_in2_14, &d.io_in_bits_in2_15, &d.io_in_bits_in2_16, &d.io_in_bits_in2_17, &d.io_in_bits_in2_18, &d.io_in_bits_in2_19, &d.io_in_bits_in2_20, &d.io_in_bits_in2_21, &d.io_in_bits_in2_22, &d.io_in_bits_in2_23, &d.io_in_bits_in2_24, &d.io_in_bits_in2_25, &d.io_in_bits_in2_26, &d.io_in_bits_in2_27, &d.io_in_bits_in2_28, &d.io_in_bits_in2_29, &d.io_in_bits_in2_30, &d.io_in_bits_in2_31};uint32_t* c[]={&d.io_in_bits_in3_0, &d.io_in_bits_in3_1, &d.io_in_bits_in3_2, &d.io_in_bits_in3_3, &d.io_in_bits_in3_4, &d.io_in_bits_in3_5, &d.io_in_bits_in3_6, &d.io_in_bits_in3_7, &d.io_in_bits_in3_8, &d.io_in_bits_in3_9, &d.io_in_bits_in3_10, &d.io_in_bits_in3_11, &d.io_in_bits_in3_12, &d.io_in_bits_in3_13, &d.io_in_bits_in3_14, &d.io_in_bits_in3_15, &d.io_in_bits_in3_16, &d.io_in_bits_in3_17, &d.io_in_bits_in3_18, &d.io_in_bits_in3_19, &d.io_in_bits_in3_20, &d.io_in_bits_in3_21, &d.io_in_bits_in3_22, &d.io_in_bits_in3_23, &d.io_in_bits_in3_24, &d.io_in_bits_in3_25, &d.io_in_bits_in3_26, &d.io_in_bits_in3_27, &d.io_in_bits_in3_28, &d.io_in_bits_in3_29, &d.io_in_bits_in3_30, &d.io_in_bits_in3_31};uint32_t* o[]={&d.io_out_v_bits_wb_wvd_rd_0, &d.io_out_v_bits_wb_wvd_rd_1, &d.io_out_v_bits_wb_wvd_rd_2, &d.io_out_v_bits_wb_wvd_rd_3, &d.io_out_v_bits_wb_wvd_rd_4, &d.io_out_v_bits_wb_wvd_rd_5, &d.io_out_v_bits_wb_wvd_rd_6, &d.io_out_v_bits_wb_wvd_rd_7, &d.io_out_v_bits_wb_wvd_rd_8, &d.io_out_v_bits_wb_wvd_rd_9, &d.io_out_v_bits_wb_wvd_rd_10, &d.io_out_v_bits_wb_wvd_rd_11, &d.io_out_v_bits_wb_wvd_rd_12, &d.io_out_v_bits_wb_wvd_rd_13, &d.io_out_v_bits_wb_wvd_rd_14, &d.io_out_v_bits_wb_wvd_rd_15, &d.io_out_v_bits_wb_wvd_rd_16, &d.io_out_v_bits_wb_wvd_rd_17, &d.io_out_v_bits_wb_wvd_rd_18, &d.io_out_v_bits_wb_wvd_rd_19, &d.io_out_v_bits_wb_wvd_rd_20, &d.io_out_v_bits_wb_wvd_rd_21, &d.io_out_v_bits_wb_wvd_rd_22, &d.io_out_v_bits_wb_wvd_rd_23, &d.io_out_v_bits_wb_wvd_rd_24, &d.io_out_v_bits_wb_wvd_rd_25, &d.io_out_v_bits_wb_wvd_rd_26, &d.io_out_v_bits_wb_wvd_rd_27, &d.io_out_v_bits_wb_wvd_rd_28, &d.io_out_v_bits_wb_wvd_rd_29, &d.io_out_v_bits_wb_wvd_rd_30, &d.io_out_v_bits_wb_wvd_rd_31};
 d.reset=1;d.io_in_valid=0;d.io_out_v_ready=1;d.io_rm=0;
 for(int t=0;t<5;t++){d.clock=0;d.eval();d.clock=1;d.eval();}d.reset=0;
 int sent=0,received=0,first=-1,last=-1,minlat=10000,maxlat=0,stalls=0;std::vector<int> accepted;
 for(int cycle=0;cycle<2000&&received<64;cycle++) {
 for(int i=0;i<32;i++){*a[i]=bits(float((i+sent*3)%7-3));*b[i]=bits(float((i*2+sent)%5-2));*c[i]=bits(float((i+sent)%3-1));}
 d.io_in_bits_ctrl_reg_idxw=sent%32;d.io_in_valid=sent<64&&(mode==0||cycle%3!=1);d.io_out_v_ready=mode==0||cycle%11<6;
 d.clock=0;d.eval();bool infire=d.io_in_valid&&d.io_in_ready;bool outfire=d.io_out_v_valid&&d.io_out_v_ready;
 if(outfire){
 for(int i=0;i<32;i++){float expect=0;if(i<m*k){expect=float((i+received)%3-1);for(int j=0;j<n;j++)expect+=float((i/k*n+j+received*3)%7-3)*float(((i%k*n+j)*2+received)%5-2);}
 if(*o[i]!=bits(expect)){std::cerr<<"mismatch mode "<<mode<<" output "<<received<<" lane "<<i<<" got "<<*o[i]<<" expected "<<bits(expect)<<"\n";return 2;}}
 if(d.io_out_v_bits_reg_idxw!=received%32)return 3;if(accepted.size()<=size_t(received))return 4;
 int lat=cycle-accepted[received];minlat=std::min(minlat,lat);maxlat=std::max(maxlat,lat);if(first<0)first=cycle;last=cycle;received++;}
 if(d.io_in_valid&&!d.io_in_ready)stalls++;if(infire){accepted.push_back(cycle);sent++;}d.clock=1;d.eval();}
 if(received!=64)return 5;if(mode)std::cout<<",";
 std::cout<<"{\"mode\":"<<mode<<",\"accepted\":"<<sent<<",\"outputs\":"<<received<<",\"first_output\":"<<first<<",\"last_output\":"<<last<<",\"min_latency\":"<<minlat<<",\"max_latency\":"<<maxlat<<",\"input_stalls\":"<<stalls<<",\"bit_exact\":true}";
 }std::cout<<"]}\n";
}
