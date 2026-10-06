#include "Vdut.h"
#include <iostream>
#include <cstdlib>
#include <cstdint>
int main(int argc,char**argv){Verilated::commandArgs(argc,argv);std::cout<<"{\"cases\":[";bool comma=false;
 for(int stride: {1,2,4,8,32}){
 Vdut d;d.reset=1;d.io_coreReq_valid=0;d.io_coreRsp_ready=1;
 for(int c=0;c<5;c++){d.clock=0;d.eval();d.clock=1;d.eval();}d.reset=0;
 for(int write=1;write>=0;write--){bool accepted=false;int start=-1,first=-1,last=-1,count=0;uint32_t mask=0;
 d.io_coreReq_bits_isWrite=write;d.io_coreReq_bits_instrId=write;d.io_coreReq_bits_setIdx=0;
 d.io_coreReq_bits_perLaneAddr_0_activeMask=1;d.io_coreReq_bits_perLaneAddr_0_blockOffset=(0*stride)%32;d.io_coreReq_bits_perLaneAddr_0_wordOffset1H=15;d.io_coreReq_bits_data_0=100+(0*stride)%32;
d.io_coreReq_bits_perLaneAddr_1_activeMask=1;d.io_coreReq_bits_perLaneAddr_1_blockOffset=(1*stride)%32;d.io_coreReq_bits_perLaneAddr_1_wordOffset1H=15;d.io_coreReq_bits_data_1=100+(1*stride)%32;
d.io_coreReq_bits_perLaneAddr_2_activeMask=1;d.io_coreReq_bits_perLaneAddr_2_blockOffset=(2*stride)%32;d.io_coreReq_bits_perLaneAddr_2_wordOffset1H=15;d.io_coreReq_bits_data_2=100+(2*stride)%32;
d.io_coreReq_bits_perLaneAddr_3_activeMask=1;d.io_coreReq_bits_perLaneAddr_3_blockOffset=(3*stride)%32;d.io_coreReq_bits_perLaneAddr_3_wordOffset1H=15;d.io_coreReq_bits_data_3=100+(3*stride)%32;
d.io_coreReq_bits_perLaneAddr_4_activeMask=1;d.io_coreReq_bits_perLaneAddr_4_blockOffset=(4*stride)%32;d.io_coreReq_bits_perLaneAddr_4_wordOffset1H=15;d.io_coreReq_bits_data_4=100+(4*stride)%32;
d.io_coreReq_bits_perLaneAddr_5_activeMask=1;d.io_coreReq_bits_perLaneAddr_5_blockOffset=(5*stride)%32;d.io_coreReq_bits_perLaneAddr_5_wordOffset1H=15;d.io_coreReq_bits_data_5=100+(5*stride)%32;
d.io_coreReq_bits_perLaneAddr_6_activeMask=1;d.io_coreReq_bits_perLaneAddr_6_blockOffset=(6*stride)%32;d.io_coreReq_bits_perLaneAddr_6_wordOffset1H=15;d.io_coreReq_bits_data_6=100+(6*stride)%32;
d.io_coreReq_bits_perLaneAddr_7_activeMask=1;d.io_coreReq_bits_perLaneAddr_7_blockOffset=(7*stride)%32;d.io_coreReq_bits_perLaneAddr_7_wordOffset1H=15;d.io_coreReq_bits_data_7=100+(7*stride)%32;
d.io_coreReq_bits_perLaneAddr_8_activeMask=1;d.io_coreReq_bits_perLaneAddr_8_blockOffset=(8*stride)%32;d.io_coreReq_bits_perLaneAddr_8_wordOffset1H=15;d.io_coreReq_bits_data_8=100+(8*stride)%32;
d.io_coreReq_bits_perLaneAddr_9_activeMask=1;d.io_coreReq_bits_perLaneAddr_9_blockOffset=(9*stride)%32;d.io_coreReq_bits_perLaneAddr_9_wordOffset1H=15;d.io_coreReq_bits_data_9=100+(9*stride)%32;
d.io_coreReq_bits_perLaneAddr_10_activeMask=1;d.io_coreReq_bits_perLaneAddr_10_blockOffset=(10*stride)%32;d.io_coreReq_bits_perLaneAddr_10_wordOffset1H=15;d.io_coreReq_bits_data_10=100+(10*stride)%32;
d.io_coreReq_bits_perLaneAddr_11_activeMask=1;d.io_coreReq_bits_perLaneAddr_11_blockOffset=(11*stride)%32;d.io_coreReq_bits_perLaneAddr_11_wordOffset1H=15;d.io_coreReq_bits_data_11=100+(11*stride)%32;
d.io_coreReq_bits_perLaneAddr_12_activeMask=1;d.io_coreReq_bits_perLaneAddr_12_blockOffset=(12*stride)%32;d.io_coreReq_bits_perLaneAddr_12_wordOffset1H=15;d.io_coreReq_bits_data_12=100+(12*stride)%32;
d.io_coreReq_bits_perLaneAddr_13_activeMask=1;d.io_coreReq_bits_perLaneAddr_13_blockOffset=(13*stride)%32;d.io_coreReq_bits_perLaneAddr_13_wordOffset1H=15;d.io_coreReq_bits_data_13=100+(13*stride)%32;
d.io_coreReq_bits_perLaneAddr_14_activeMask=1;d.io_coreReq_bits_perLaneAddr_14_blockOffset=(14*stride)%32;d.io_coreReq_bits_perLaneAddr_14_wordOffset1H=15;d.io_coreReq_bits_data_14=100+(14*stride)%32;
d.io_coreReq_bits_perLaneAddr_15_activeMask=1;d.io_coreReq_bits_perLaneAddr_15_blockOffset=(15*stride)%32;d.io_coreReq_bits_perLaneAddr_15_wordOffset1H=15;d.io_coreReq_bits_data_15=100+(15*stride)%32;
d.io_coreReq_bits_perLaneAddr_16_activeMask=1;d.io_coreReq_bits_perLaneAddr_16_blockOffset=(16*stride)%32;d.io_coreReq_bits_perLaneAddr_16_wordOffset1H=15;d.io_coreReq_bits_data_16=100+(16*stride)%32;
d.io_coreReq_bits_perLaneAddr_17_activeMask=1;d.io_coreReq_bits_perLaneAddr_17_blockOffset=(17*stride)%32;d.io_coreReq_bits_perLaneAddr_17_wordOffset1H=15;d.io_coreReq_bits_data_17=100+(17*stride)%32;
d.io_coreReq_bits_perLaneAddr_18_activeMask=1;d.io_coreReq_bits_perLaneAddr_18_blockOffset=(18*stride)%32;d.io_coreReq_bits_perLaneAddr_18_wordOffset1H=15;d.io_coreReq_bits_data_18=100+(18*stride)%32;
d.io_coreReq_bits_perLaneAddr_19_activeMask=1;d.io_coreReq_bits_perLaneAddr_19_blockOffset=(19*stride)%32;d.io_coreReq_bits_perLaneAddr_19_wordOffset1H=15;d.io_coreReq_bits_data_19=100+(19*stride)%32;
d.io_coreReq_bits_perLaneAddr_20_activeMask=1;d.io_coreReq_bits_perLaneAddr_20_blockOffset=(20*stride)%32;d.io_coreReq_bits_perLaneAddr_20_wordOffset1H=15;d.io_coreReq_bits_data_20=100+(20*stride)%32;
d.io_coreReq_bits_perLaneAddr_21_activeMask=1;d.io_coreReq_bits_perLaneAddr_21_blockOffset=(21*stride)%32;d.io_coreReq_bits_perLaneAddr_21_wordOffset1H=15;d.io_coreReq_bits_data_21=100+(21*stride)%32;
d.io_coreReq_bits_perLaneAddr_22_activeMask=1;d.io_coreReq_bits_perLaneAddr_22_blockOffset=(22*stride)%32;d.io_coreReq_bits_perLaneAddr_22_wordOffset1H=15;d.io_coreReq_bits_data_22=100+(22*stride)%32;
d.io_coreReq_bits_perLaneAddr_23_activeMask=1;d.io_coreReq_bits_perLaneAddr_23_blockOffset=(23*stride)%32;d.io_coreReq_bits_perLaneAddr_23_wordOffset1H=15;d.io_coreReq_bits_data_23=100+(23*stride)%32;
d.io_coreReq_bits_perLaneAddr_24_activeMask=1;d.io_coreReq_bits_perLaneAddr_24_blockOffset=(24*stride)%32;d.io_coreReq_bits_perLaneAddr_24_wordOffset1H=15;d.io_coreReq_bits_data_24=100+(24*stride)%32;
d.io_coreReq_bits_perLaneAddr_25_activeMask=1;d.io_coreReq_bits_perLaneAddr_25_blockOffset=(25*stride)%32;d.io_coreReq_bits_perLaneAddr_25_wordOffset1H=15;d.io_coreReq_bits_data_25=100+(25*stride)%32;
d.io_coreReq_bits_perLaneAddr_26_activeMask=1;d.io_coreReq_bits_perLaneAddr_26_blockOffset=(26*stride)%32;d.io_coreReq_bits_perLaneAddr_26_wordOffset1H=15;d.io_coreReq_bits_data_26=100+(26*stride)%32;
d.io_coreReq_bits_perLaneAddr_27_activeMask=1;d.io_coreReq_bits_perLaneAddr_27_blockOffset=(27*stride)%32;d.io_coreReq_bits_perLaneAddr_27_wordOffset1H=15;d.io_coreReq_bits_data_27=100+(27*stride)%32;
d.io_coreReq_bits_perLaneAddr_28_activeMask=1;d.io_coreReq_bits_perLaneAddr_28_blockOffset=(28*stride)%32;d.io_coreReq_bits_perLaneAddr_28_wordOffset1H=15;d.io_coreReq_bits_data_28=100+(28*stride)%32;
d.io_coreReq_bits_perLaneAddr_29_activeMask=1;d.io_coreReq_bits_perLaneAddr_29_blockOffset=(29*stride)%32;d.io_coreReq_bits_perLaneAddr_29_wordOffset1H=15;d.io_coreReq_bits_data_29=100+(29*stride)%32;
d.io_coreReq_bits_perLaneAddr_30_activeMask=1;d.io_coreReq_bits_perLaneAddr_30_blockOffset=(30*stride)%32;d.io_coreReq_bits_perLaneAddr_30_wordOffset1H=15;d.io_coreReq_bits_data_30=100+(30*stride)%32;
d.io_coreReq_bits_perLaneAddr_31_activeMask=1;d.io_coreReq_bits_perLaneAddr_31_blockOffset=(31*stride)%32;d.io_coreReq_bits_perLaneAddr_31_wordOffset1H=15;d.io_coreReq_bits_data_31=100+(31*stride)%32;
 for(int cycle=0;cycle<256&&mask!=0xffffffffu;cycle++){
 d.io_coreReq_valid=!accepted;d.clock=0;d.eval();bool req=d.io_coreReq_valid&&d.io_coreReq_ready;
 if(d.io_coreRsp_valid){if(d.io_coreRsp_bits_instrId!=write)return 8;
 if(d.io_coreRsp_bits_activeMask_0){if(mask&(1u<<0))return 6;mask|=1u<<0;if(!write&&d.io_coreRsp_bits_data_0!=100+(0*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_1){if(mask&(1u<<1))return 6;mask|=1u<<1;if(!write&&d.io_coreRsp_bits_data_1!=100+(1*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_2){if(mask&(1u<<2))return 6;mask|=1u<<2;if(!write&&d.io_coreRsp_bits_data_2!=100+(2*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_3){if(mask&(1u<<3))return 6;mask|=1u<<3;if(!write&&d.io_coreRsp_bits_data_3!=100+(3*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_4){if(mask&(1u<<4))return 6;mask|=1u<<4;if(!write&&d.io_coreRsp_bits_data_4!=100+(4*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_5){if(mask&(1u<<5))return 6;mask|=1u<<5;if(!write&&d.io_coreRsp_bits_data_5!=100+(5*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_6){if(mask&(1u<<6))return 6;mask|=1u<<6;if(!write&&d.io_coreRsp_bits_data_6!=100+(6*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_7){if(mask&(1u<<7))return 6;mask|=1u<<7;if(!write&&d.io_coreRsp_bits_data_7!=100+(7*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_8){if(mask&(1u<<8))return 6;mask|=1u<<8;if(!write&&d.io_coreRsp_bits_data_8!=100+(8*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_9){if(mask&(1u<<9))return 6;mask|=1u<<9;if(!write&&d.io_coreRsp_bits_data_9!=100+(9*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_10){if(mask&(1u<<10))return 6;mask|=1u<<10;if(!write&&d.io_coreRsp_bits_data_10!=100+(10*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_11){if(mask&(1u<<11))return 6;mask|=1u<<11;if(!write&&d.io_coreRsp_bits_data_11!=100+(11*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_12){if(mask&(1u<<12))return 6;mask|=1u<<12;if(!write&&d.io_coreRsp_bits_data_12!=100+(12*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_13){if(mask&(1u<<13))return 6;mask|=1u<<13;if(!write&&d.io_coreRsp_bits_data_13!=100+(13*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_14){if(mask&(1u<<14))return 6;mask|=1u<<14;if(!write&&d.io_coreRsp_bits_data_14!=100+(14*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_15){if(mask&(1u<<15))return 6;mask|=1u<<15;if(!write&&d.io_coreRsp_bits_data_15!=100+(15*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_16){if(mask&(1u<<16))return 6;mask|=1u<<16;if(!write&&d.io_coreRsp_bits_data_16!=100+(16*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_17){if(mask&(1u<<17))return 6;mask|=1u<<17;if(!write&&d.io_coreRsp_bits_data_17!=100+(17*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_18){if(mask&(1u<<18))return 6;mask|=1u<<18;if(!write&&d.io_coreRsp_bits_data_18!=100+(18*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_19){if(mask&(1u<<19))return 6;mask|=1u<<19;if(!write&&d.io_coreRsp_bits_data_19!=100+(19*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_20){if(mask&(1u<<20))return 6;mask|=1u<<20;if(!write&&d.io_coreRsp_bits_data_20!=100+(20*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_21){if(mask&(1u<<21))return 6;mask|=1u<<21;if(!write&&d.io_coreRsp_bits_data_21!=100+(21*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_22){if(mask&(1u<<22))return 6;mask|=1u<<22;if(!write&&d.io_coreRsp_bits_data_22!=100+(22*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_23){if(mask&(1u<<23))return 6;mask|=1u<<23;if(!write&&d.io_coreRsp_bits_data_23!=100+(23*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_24){if(mask&(1u<<24))return 6;mask|=1u<<24;if(!write&&d.io_coreRsp_bits_data_24!=100+(24*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_25){if(mask&(1u<<25))return 6;mask|=1u<<25;if(!write&&d.io_coreRsp_bits_data_25!=100+(25*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_26){if(mask&(1u<<26))return 6;mask|=1u<<26;if(!write&&d.io_coreRsp_bits_data_26!=100+(26*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_27){if(mask&(1u<<27))return 6;mask|=1u<<27;if(!write&&d.io_coreRsp_bits_data_27!=100+(27*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_28){if(mask&(1u<<28))return 6;mask|=1u<<28;if(!write&&d.io_coreRsp_bits_data_28!=100+(28*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_29){if(mask&(1u<<29))return 6;mask|=1u<<29;if(!write&&d.io_coreRsp_bits_data_29!=100+(29*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_30){if(mask&(1u<<30))return 6;mask|=1u<<30;if(!write&&d.io_coreRsp_bits_data_30!=100+(30*stride)%32)return 7;}
if(d.io_coreRsp_bits_activeMask_31){if(mask&(1u<<31))return 6;mask|=1u<<31;if(!write&&d.io_coreRsp_bits_data_31!=100+(31*stride)%32)return 7;}
 if(first<0)first=cycle;last=cycle;count++;}
 if(req){accepted=true;start=cycle;}d.clock=1;d.eval();}
 if(mask!=0xffffffffu)return 9;d.io_coreReq_valid=0;
 if(comma)std::cout<<",";comma=true;
 std::cout<<"{\"stride\":"<<stride<<",\"write\":"<<write<<",\"responses\":"<<count<<",\"first_latency\":"<<first-start<<",\"last_latency\":"<<last-start<<",\"lane_mask\":"<<mask<<",\"bit_exact\":true}";
 for(int c=0;c<5;c++){d.clock=0;d.eval();d.clock=1;d.eval();}}
 }std::cout<<"]}\n";
}
