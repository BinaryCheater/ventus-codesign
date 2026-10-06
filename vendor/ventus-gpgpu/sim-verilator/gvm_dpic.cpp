// DPI-C 函数实现

#include <vector>
#include <cstdint>
#include <array>
#include "gvm_global_var.hpp"
#include "gvm_dpic.hpp"
#include <cassert>

extern "C" {

// CTA -> Warp 分配
void c_GvmDutCta2Warp(int software_wg_id,
                       int software_warp_id,
                       int sm_id,
                       int hardware_warp_id,
                       int sgpr_base,
                       int vgpr_base,
                       int wg_slot_id_in_warp_sche,
                       int rtl_num_thread) {
  Cta2WarpData d;
  d.software_wg_id     = software_wg_id;
  d.software_warp_id   = software_warp_id;
  d.sm_id              = sm_id;
  d.hardware_warp_id   = hardware_warp_id;
  d.sgpr_base          = sgpr_base;
  d.vgpr_base          = vgpr_base;
  d.wg_slot_id_in_warp_sche = wg_slot_id_in_warp_sche;
  d.num_thread_in_warp = rtl_num_thread;
  g_cta2warp_data.push_back(d);
}

// Insn Dispatch
void c_GvmDutInsnDispatch(int sm_id,
                            int hardware_warp_id,
                            int pc,
                            int instr,
                            int dispatch_id,
                            bool is_extended) {
  InsnDispatchData d;
  d.sm_id             = sm_id;
  d.hardware_warp_id  = hardware_warp_id;
  d.pc                = pc;
  d.insn             = instr;
  d.dispatch_id       = dispatch_id;
  d.is_extended      = is_extended;
  g_insn_dispatch_data.push_back(d);
}

// XReg Writeback
void c_GvmDutXRegWriteback(int sm_id,
                            int rd,
                            bool is_scalar_wb,
                            int reg_idx,
                            int hardware_warp_id,
                            int pc,
                            int inst,
                            int dispatch_id) {
  XRegWritebackData d;
  d.sm_id             = sm_id;
  d.rd                = rd;
  d.is_scalar_wb      = is_scalar_wb;
  d.reg_idx           = reg_idx;
  d.hardware_warp_id  = hardware_warp_id;
  d.pc                = pc;
  d.insn              = inst;
  d.dispatch_id       = dispatch_id;
  g_xreg_wb_data.push_back(d);
}

// XRegs
void c_GvmDutXReg(int num_sm,
                   int sm_id,
                   int num_bank,
                   int num_sgpr_slots,
                   int xbanks_word,
                   int xbanks_word_idx) {
  // if std::vector<XRegData> g_xreg_data;为空
  // 初始化std::vector<XRegData> g_xreg_data，XRegData的个数为num_bank，g_xreg_data(i).bank_data里的word个数为num_sgpr_slots/num_bank
  // 根据xbanks_word_idx的值，给g_xreg_data(i).bank_data(j)赋值
  // i = xbanks_word_idx/(num_sgpr_slots/num_bank)
  // j = xbanks_word_idx%(num_sgpr_slots/num_bank)
    if (g_xreg_data.empty()) {
      g_xreg_data.resize(num_sm * num_bank);
      for (int i = 0; i < num_sm * num_bank; i++) {
        g_xreg_data[i].bank_data.resize(num_sgpr_slots / num_bank);
      }
    }

    g_xreg_data[sm_id*num_bank + xbanks_word_idx/(num_sgpr_slots/num_bank)].sm_id = sm_id;
    g_xreg_data[sm_id*num_bank + xbanks_word_idx/(num_sgpr_slots/num_bank)].bank_id
      = xbanks_word_idx/(num_sgpr_slots/num_bank);
    g_xreg_data[sm_id*num_bank + xbanks_word_idx/(num_sgpr_slots/num_bank)].num_bank = num_bank;
    g_xreg_data[sm_id*num_bank + xbanks_word_idx/(num_sgpr_slots/num_bank)].num_sgpr_slots
      = num_sgpr_slots;
    g_xreg_data[sm_id*num_bank + xbanks_word_idx/(num_sgpr_slots/num_bank)]
      .bank_data[xbanks_word_idx%(num_sgpr_slots/num_bank)] = xbanks_word;

  }

// VReg Writeback
void c_GvmDutVRegWriteback(int sm_id,
                            int rd_data,    
                            bool is_vector_wb,
                            int reg_idx,
                            int hardware_warp_id,
                            int pc,
                            int inst,
                            int dispatch_id,
                            bool wvd_mask,   
                            int thread_idx) { 
  g_vreg_wb_data[{sm_id, hardware_warp_id, dispatch_id}].sm_id = sm_id;
  g_vreg_wb_data[{sm_id, hardware_warp_id, dispatch_id}].rd_data[thread_idx] = rd_data;
  g_vreg_wb_data[{sm_id, hardware_warp_id, dispatch_id}].is_vector_wb = is_vector_wb;
  g_vreg_wb_data[{sm_id, hardware_warp_id, dispatch_id}].reg_idx = reg_idx;
  g_vreg_wb_data[{sm_id, hardware_warp_id, dispatch_id}].hardware_warp_id = hardware_warp_id;
  g_vreg_wb_data[{sm_id, hardware_warp_id, dispatch_id}].pc = pc;
  g_vreg_wb_data[{sm_id, hardware_warp_id, dispatch_id}].insn = inst;
  g_vreg_wb_data[{sm_id, hardware_warp_id, dispatch_id}].dispatch_id = dispatch_id;
  g_vreg_wb_data[{sm_id, hardware_warp_id, dispatch_id}].wvd_mask[thread_idx] = wvd_mask;
}

// Barrier done
void c_GvmDutBarrierDone(int sm_id,
                          int hardware_warp_id,
                          int pc,
                          int inst,
                          int dispatch_id) {
  BarDoneData d;
  d.sm_id             = sm_id;
  d.wg_slot_id        = hardware_warp_id;
  d.pc                = pc;
  d.insn              = inst;
  d.dispatch_id       = dispatch_id;
  g_bar_done_data.push_back(d);
}

} // extern "C"