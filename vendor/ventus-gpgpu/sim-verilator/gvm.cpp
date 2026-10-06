// GVM 核心类的实现

#include <cstdint>
#include <map>
#include <vector>
#include <memory>
#include <spdlog/logger.h>

#include "gvmref_interface.h"
#include "gvm_global_var.hpp"
#include "gvm.hpp"
#include "gvm_structs.hpp"
#include <bitset>
#include <array>
#include "gvm_macro.h"
#include <string>

//
// ------------------------- insn related ----------------------------------------
//

bool gvm_t::isInsnCare(uint32_t insn, const std::vector<care_insn_t> care_insns) {
  // 判断指令是否 care
  for (const auto& pattern : care_insns) {
    if ((insn & pattern.mask) == pattern.value) {
      return true;
    }
  }
  return false;
}

void gvm_t::disasm(uint32_t insn, char* insn_name) {
  std::vector<std::string> matched_names;
  for (const auto& pattern : disasm_table) {
    if ((insn & pattern.mask) == pattern.value) {
      matched_names.push_back(pattern.name);
    }
  }
  if (matched_names.empty()) {
    strcpy(insn_name, " ");
    return;
  }
  if (matched_names.size() > 1) {
    logger->error("GVM error: multiple disasm matches for insn 0x{:08x}: {}"
      , insn, fmt::join(matched_names, " "));
    assert(0);
  } else {
    strcpy(insn_name, matched_names[0].c_str());
  }
  return;
}

//
// ------------------------- gvm_t::getDut() ----------------------------------------------
//

static std::array<bool, 32> unpack_to_array(uint32_t v, size_t n) {
    std::bitset<32> bs(v);
    std::array<bool, 32> a{};
    for (size_t i = 0; i < n; ++i) {
        a[i] = bs[i]; // 保持一致：a[0] 对应最低位
    }
    return a;
}

static std::string mask_to_string(const std::array<bool, 32>& mask, size_t n) {
    std::string s;
    for (size_t i = 0; i < n; ++i) {
        s.push_back(mask[i] ? '1' : '0');
    }
    return s;
}

void gvm_t::getDut() {
  getDutWarpNew(); // 添加新 warp 条目
  getDutWarpFinish(); // 删除已完成 warp 条目
  getDutInsnDispatch(); // 添加新指令条目，其中不关心的指令直接置为 single_insn_cmp.cmp_pass = 1
  getDutInsnFinish(); // 标记指令条目为已完成，维护 dut_done 与 dut_result
  getDutXReg(); // 根据 warp 条目更新 XReg 条目
  getDutWarpNewSetRefXReg();
  clearGlobal(); // 清空全局变量
}

void gvm_t::getDutWarpNew() {
  for (const auto& item : g_cta2warp_data) {
    dut_active_warp_t d;
    d.sm_id = item.sm_id;
    d.hardware_warp_id = item.hardware_warp_id;
    d.software_wg_id = item.software_wg_id;
    d.software_warp_id = item.software_warp_id;
    d.xreg_base = item.sgpr_base;
    d.xreg_usage = g_sgprUsage; // 临时特殊处理
    // d.vreg_base = item.vgpr_base;
    d.base_dispatch_id_set = 0;
    d.wg_slot_id_in_warp_sche = item.wg_slot_id_in_warp_sche;
    d.num_thread = item.num_thread_in_warp;

    // check if the warp is already in the list
    bool found_sw = false;
    bool found_hw = false;
    for (const auto& warp : dut_active_warps) {
      if (warp.second.software_wg_id == d.software_wg_id && warp.second.software_warp_id == d.software_warp_id) {
        found_sw = true;
      }
      if (warp.second.sm_id == d.sm_id && warp.second.hardware_warp_id == d.hardware_warp_id) {
        found_hw = true;
      }
    }
    if (found_sw) {
      logger->error("GVM error: repeated cta2warp dispatch with same software_wg_id {} & software_warp_id {}.\n",
        d.software_wg_id, d.software_warp_id);
      assert(0);
    }
    if (found_hw) {
      logger->error("GVM error: repeated cta2warp dispatch with same sm_id {} & hardware_warp_id {}.\n",
        d.sm_id, d.hardware_warp_id);
      assert(0);
    }
    dut_active_warps[{d.software_wg_id, d.software_warp_id}] = d;
  }
}

void gvm_t::getDutWarpFinish() {
  for (const auto& item : g_insn_dispatch_data) {
    if (item.insn == 0x0000400B) {
      // 0x0000400B 是 endprg 指令
      // delete dut_active_warp
      bool found_dut_active_warp = false;
      for (auto warp_it = dut_active_warps.begin(); warp_it != dut_active_warps.end();) {
        if (warp_it->second.sm_id == item.sm_id && warp_it->second.hardware_warp_id == item.hardware_warp_id) {
          if (found_dut_active_warp) {
            printf("GVM error in `gvm_t::getDutWarpFinish`: "
              "multiple items in `dut_active_warps` with same sm_id and hardware_warp_id\n");
            assert(0);
          }
          logger->debug(fmt::format("GVM info: endprg dispatched, deleting warp with sm_id: {}, hardware_warp_id: {}\n",
            warp_it->second.sm_id, warp_it->second.hardware_warp_id));
          warp_it = dut_active_warps.erase(warp_it);
          found_dut_active_warp = true;
        } else {
          ++warp_it;
        }
      }
      if (!found_dut_active_warp) {
        printf("GVM error in `gvm_t::getDutWarpFinish`: "
          "no item in `dut_active_warps` with required sm_id and hardware_warp_id\n");
        assert(0);
      }
      // 这里最好把对应的 ref warp 跑到头
    }
  }
}

void gvm_t::getDutInsnDispatch() {
  for (const auto& item : g_insn_dispatch_data) {
    insn_t d;
    d.pc = item.pc;
    d.insn = item.insn;
    d.extended = item.is_extended;
    d.care = isInsnCare(item.insn, retire_care_insns);
    d.done = 0;
    d.retired = 0;
    d.single_insn_cmp.care = isInsnCare(item.insn, single_insn_cmp_care_insns);
    d.single_insn_cmp.dut_done = 0;
    d.single_insn_cmp.ref_done = 0;
    d.single_insn_cmp.cmp_pass = 0;
    if (!d.single_insn_cmp.care) {
      d.single_insn_cmp.cmp_pass = 1; // 不关心的指令直接置为比对通过
    }
    d.dispatch_id = item.dispatch_id;

    bool found = false;
    for (auto& warp : dut_active_warps) {
      if (warp.second.sm_id == item.sm_id && warp.second.hardware_warp_id == item.hardware_warp_id) {
        if (found) {
          printf("GVM error in `gvm_t::getDutInsnDispatch`: "
            "multiple item in `dut_active_warps` with same sm_id and hardware_warp_id\n");
          assert(0);
        }
        assert(warp.second.insns.find(d.dispatch_id) == warp.second.insns.end()); // 错误：指令已被 dispatch 过一次
        warp.second.insns[d.dispatch_id] = d;
        found = true;
        if (!warp.second.base_dispatch_id_set) {
          // 设置本 warp 的首条指令的 dispatch_id
          warp.second.base_dispatch_id = d.dispatch_id;
          warp.second.base_dispatch_id_set = 1;
          warp.second.next_retire_dispatch_id = d.dispatch_id;
        }
      }
    }
    // 目前获取 warp 结束的标志是 endprg dispatch，
    // 但这距离 endprg 真正执行完成还有一段时间，
    // 在此期间仍有其他指令会 dispatch，但 dut_active_warps 中的 warp 已经被删除了
  }
}

void gvm_t::getDutInsnFinish() {
  // 将 insns 中 care 的指令标记为已完成
  // 并记录 insn_t.single_insn_cmp 中 care 的指令的完成信息
  getDutXRegWbFinish();
  getDutVRegWbFinish();
  getDutBarDone();
}
void gvm_t::getDutXRegWbFinish() {
  for (const auto& item : g_xreg_wb_data) {
    if (!isInsnCare(item.insn, retire_care_insns)) {
      logger->error("GVM error in `gvm_t::getDutXRegWbFinish`: "
        "xreg writeback for instruction that does not care for retire\n"
        "getDutXRegWbFinish Error: sm_id: {}, hardware_warp_id: {}, dispatch_id: {}, pc: 0x{:08x}, insn: 0x{:08x}",
        item.sm_id, item.hardware_warp_id, item.dispatch_id, item.pc, item.insn);
    }
    assert(isInsnCare(item.insn, retire_care_insns));
    assert(!isInsnCare(item.insn, barrier_insns));
    assert(!isInsnCare(item.insn, single_insn_cmp_care_insns));
    bool found_warp = false;
    for (auto& warp : dut_active_warps) {
      if (warp.second.sm_id == item.sm_id && warp.second.hardware_warp_id == item.hardware_warp_id) {
        found_warp = true;
        auto insn_it = warp.second.insns.find(item.dispatch_id);
        if ((insn_it != warp.second.insns.end()) && (insn_it->second.done != 1)) {
          // 如果找到了该条指令，并且该指令尚未被标记为已完成
          assert(insn_it->second.pc == item.pc);
          assert(insn_it->second.insn == item.insn);
          assert(insn_it->second.care == true); // 标量寄存器写回指令需指导 retire
          // 维护 retire 相关变量
          insn_it->second.done = true;
          // 维护 single insn cmp 相关变量
          if (insn_it->second.single_insn_cmp.care == true) {
            insn_it->second.single_insn_cmp.dut_done = 1;
            insn_it->second.single_insn_cmp.dut_result.insn_type = InsnType::XREG;
            insn_it->second.single_insn_cmp.dut_result.xreg_result.rd = item.rd;
            insn_it->second.single_insn_cmp.dut_result.xreg_result.reg_idx = item.reg_idx;
          }
        } else {
          logger->debug(
              "GVM info in `gvm_t::getDutInsnFinish`: "
              "sm_id & hardware_warp_id match successful, but no item in this warp's unfinished "
              "dispatched insns with required dispatch_id"
          );
          logger->debug(
              "getDutInsnFinish info: sm_id: {}, hardware_warp_id: {}, dispatch_id: {}, pc: 0x{:08x}, insn: "
              "0x{:08x}",
              item.sm_id, item.hardware_warp_id, item.dispatch_id, item.pc, item.insn
          );
          // assert(0);
        }
      }
    }
    if (!found_warp) {
      // logger->error("GVM error in `gvm_t::getDutXRegWbFinish`: "
      //   "no warp in `dut_active_warps` with required sm_id and hardware_warp_id\n"
      //   "getDutXRegWbFinish Error: sm_id: {}, hardware_warp_id: {}, dispatch_id: {}, pc: 0x{:08x}, insn: 0x{:08x}",
      //   item.sm_id, item.hardware_warp_id, item.dispatch_id, item.pc, item.insn);
      // assert(0);
    }
  }
}

void gvm_t::getDutVRegWbFinish() {
  for (const auto& item : g_vreg_wb_data) {
    assert(!isInsnCare(item.second.insn, barrier_insns));
    assert(!isInsnCare(item.second.insn, retire_care_insns));
    if (isInsnCare(item.second.insn, single_insn_cmp_care_insns)) {
      bool found_warp = false;
      for (auto& warp : dut_active_warps) {
        if ((warp.second.sm_id == item.second.sm_id) && (warp.second.hardware_warp_id == item.second.hardware_warp_id)) {
          found_warp = true;
          auto insn_it = warp.second.insns.find(item.second.dispatch_id);
          if (insn_it != warp.second.insns.end() && (insn_it->second.single_insn_cmp.dut_done != 1)) {
            // 如果找到了该条指令，并且该指令尚未被标记为已完成
            assert(insn_it->second.pc == item.second.pc);
            assert(insn_it->second.insn == item.second.insn);
            assert(insn_it->second.care == false); // 向量寄存器写回指令不参与 retire
            // 维护 single insn cmp 相关变量
            if (insn_it->second.single_insn_cmp.care == true) {
              insn_it->second.single_insn_cmp.dut_done = 1;
              insn_it->second.single_insn_cmp.dut_result.insn_type = InsnType::VREG;
              insn_it->second.single_insn_cmp.dut_result.vreg_result.rd = item.second.rd_data;
              insn_it->second.single_insn_cmp.dut_result.vreg_result.reg_idx = item.second.reg_idx;
              insn_it->second.single_insn_cmp.dut_result.vreg_result.mask = item.second.wvd_mask;
            }
          } else {
            logger->debug(
                "GVM info in `gvm_t::getDutVRegWbFinish`: "
                "sm_id & hardware_warp_id match successful, but no item in this warp's unfinished "
                "dispatched insns with required dispatch_id"
            );
            logger->debug(
                "getDutVRegWbFinish info: sm_id: {}, hardware_warp_id: {}, dispatch_id: {}, pc: 0x{:08x}, insn: 0x{:08x}",
                item.second.sm_id, item.second.hardware_warp_id, item.second.dispatch_id, item.second.pc, item.second.insn
            );
            // assert(0);
          }
        }
      }
      if (!found_warp) {
        // logger->error("GVM error in `gvm_t::getDutVRegWbFinish`: "
        //   "no warp in `dut_active_warps` with required sm_id and hardware_warp_id\n"
        //   "getDutVRegWbFinish Error: sm_id: {}, hardware_warp_id: {}, dispatch_id: {}, pc: 0x{:08x}, insn: 0x{:08x}",
        //   item.second.sm_id, item.second.hardware_warp_id, item.second.dispatch_id, item.second.pc, item.second.insn);
        // assert(0);
      }
    } else {
      logger->debug("GVM warning in `gvm_t::getDutVRegWbFinish`: "
        "ignoring VReg Writeback from pc 0x{:08x}, insn 0x{:08x}",
        item.second.pc, item.second.insn);
    }
  }
}

void gvm_t::getDutBarDone() {
  for (const auto& item : g_bar_done_data) {
    assert(isInsnCare(item.insn, barrier_insns));
    if(isInsnCare(item.insn, single_insn_cmp_care_insns)){
      char buffer[128];
      disasm(item.insn, buffer);
      printf("%s\n", buffer);
      assert(0);
    } // barrier 指令不参与单指令比对
    assert(isInsnCare(item.insn, retire_care_insns)); // barrier 指令需指导 retire
    bool found = false;
    for (auto& warp: dut_active_warps) {
      if (warp.second.sm_id == item.sm_id && warp.second.wg_slot_id_in_warp_sche == item.wg_slot_id) {
        for (auto& insn: warp.second.insns) {
          if (insn.second.pc == item.pc) {
            if(insn.second.done == false) {
              found = true;
            }
            // 为什么这里不用 dispatch_id 来识别指令？因为各个 warp 的分支行为可能不同
            // 进而导致对同一条 barrier 指令的 dispatch_id 不同
            // 而这里拿到的 dispatch_id 只是最后一个完成的 warp 的 dispatch_id
            // 因此使用 pc 识别 barrier 指令
            // 激进地假设不会同时存在两个相同 pc 的未 retire 的 barrier 指令
            assert(insn.second.care == true); // barrier 指令需指导 retire
            insn.second.done = true; // 标记该指令已完成
          }
        }
      }
    }
    if(found == false) {
      logger->debug("GVM info in `gvm_t::getDutBarDone`: "
        "no insn in `dut_active_warps` with required unfinished barrier insn\n"
        "getDutBarDone info: sm_id: {}, wg_slot_id: {}, pc: 0x{:08x}, insn: 0x{:08x}",
        item.sm_id, item.wg_slot_id, item.pc, item.insn);
      // assert(0);
    }
  }
}

void gvm_t::getDutXReg() {
  // 从交织的寄存器板块中，提取每个 warp 各自的寄存器
  std::map<uint32_t, std::map<uint32_t, XRegData>> g_xreg_data_mapped;
  assert(!g_xreg_data.empty());
  for (const auto& item : g_xreg_data) {
    g_xreg_data_mapped[item.sm_id][item.bank_id] = item;
  }
  for (auto& warp : dut_active_warps) {
    warp.second.curr_xreg.resize(warp.second.xreg_usage);
    // 将这个 warp 的寄存器从交织的板块中提取出来
    uint32_t num_bank = g_xreg_data_mapped[warp.second.sm_id].begin()->second.num_bank;
    assert((num_bank & (num_bank - 1)) == 0); // 断言 num_bank 是 2 的幂
    // 断言 warp 的寄存器是对齐到板块个数的
    assert(warp.second.xreg_base % num_bank == 0);
    assert(warp.second.xreg_usage % num_bank == 0);
    for (int i = 0; i < warp.second.xreg_usage; ++i) {
      warp.second.curr_xreg[i] = g_xreg_data_mapped[warp.second.sm_id]
        [(i + warp.second.hardware_warp_id) % num_bank].bank_data[(warp.second.xreg_base + i) >> __builtin_ctz(num_bank)];
    }
    warp.second.curr_xreg[0] = 0; // 强制 x0 为 0，认为 DUT 已经正确地对 x0 做了特殊处理
  }
}

void gvm_t::getDutWarpNewSetRefXReg() {
  // 这个函数是为了解决以下问题：
  // REF 对每一个 warp 的标量寄存器都是零初始化的；
  // 但 RTL DUT 的 CTA 调度器在向 SM 分派新 warp 时，只会在寄存器堆中分配一块空间，但不会零初始化；
  // 导致大量寄存器不匹配。
  // 因此这里在 DUT 的 CTA 调度器向 SM 分派新 warp 时，将 DUT 的该 warp 的寄存器数据同步到 REF 的对应 warp。
  for (const auto& item : g_cta2warp_data) {
    auto warp_it = dut_active_warps.find({ item.software_wg_id, item.software_warp_id });
    if (warp_it == dut_active_warps.end()) {
      logger->error("GVM error in `gvm_t::getDutWarpNewSetRefXReg`: "
        "no warp in `dut_active_warps` with required software_wg_id and software_warp_id\n"
        "getDutWarpNewSetRefXReg Error: software_wg_id: {}, software_warp_id: {}",
        item.software_wg_id, item.software_warp_id);
      assert(0);
    }
    auto &warp = warp_it->second;

    gvmref_warp_xreg_t xreg_data;
    xreg_data.xreg.resize(warp.xreg_usage);
    for (uint32_t i = 0; i < warp.xreg_usage; ++i) {
      xreg_data.xreg[i] = warp.curr_xreg[i];
    }
    gvmref_set_warp_xreg(item.software_wg_id, item.software_warp_id, warp.xreg_usage, xreg_data);
  }
}

void gvm_t::clearGlobal() {
  // 清空全局变量
  g_cta2warp_data.clear();
  g_insn_dispatch_data.clear();
  // g_sgprUsage.clear();
  g_xreg_wb_data.clear();
  g_xreg_data.clear();
  g_vreg_wb_data.clear();
  g_bar_done_data.clear();
}

//
// ------------------------- gvm_t::gvmStep() ----------------------------------------------
//

int gvm_t::gvmStep() {
  checkRetire(); // 判断是否有 retire 指令，并将相关信息写入 retire_info
  stepRef(); // 根据 retire_info 步进 REF，每次步进前确认 PC，维护 ref_done 与 ref_result
  doSingleInsnCmp();
  doRetireCmp(); // 根据 retire_info 比对 DUT 和 REF 的特定 warp 的寄存器堆
  clearInsnItem(); // 删除已 retire 且已 single_insn_cmp 通过的指令条目
  resetRetireInfo(); // 重置 retire_info
  return 0;
}


void gvm_t::checkRetire() {
  for (auto& warp: dut_active_warps) {
    auto it = warp.second.insns.find(warp.second.next_retire_dispatch_id);
    assert(it == warp.second.insns.end() || it->second.retired == false);

    if (it == warp.second.insns.end()) {
      continue;
    }

    auto insn_it_begin = it;
    uint32_t final_cnt = 0;
    uint32_t temp_retire_cnt = 0;
    bool barriered = false;
    for (; it != warp.second.insns.end(); ++it) {
      if (it->second.care == false) {
        assert(isInsnCare(it->second.insn, barrier_insns) == false);
        temp_retire_cnt++;
      } else if (it->second.done == true) {
        final_cnt += temp_retire_cnt;
        temp_retire_cnt = 0;
        final_cnt++;
        if(isInsnCare(it->second.insn, barrier_insns)) {
          barriered = true;
          break;
        }
      } else {
        break;
      }
    }
    ++it;
    bool retiring = true;
    for (; it != warp.second.insns.end(); ++it) {
      if (barriered) {
        assert(it->second.care == false || it->second.done == false); // RTL 中，不应当有指令越过 barrier 完成
      }
      else if (it->second.care == true && it->second.done == true) {
        retiring = false;
        break;
      }
    }
    if (final_cnt == 0 || retiring == false) {
      continue;
    }
    retireInfo_t::retire_cnt_item_t r;
    r.sm_id = warp.second.sm_id;
    r.hardware_warp_id = warp.second.hardware_warp_id;
    r.software_wg_id = warp.second.software_wg_id;
    r.software_warp_id = warp.second.software_warp_id;
    r.retire_cnt = final_cnt;
    r.barrier_included = barriered;
    r.barrier_retry = false;
    retire_info.warp_retire_cnt.push_back(r);

    logger->debug(fmt::format("GVM retire message from gvm_t::checkRetire()"));

    // 打印 retire log（遍历最终 retire 的那一段）
    auto print_it = insn_it_begin;
    for (uint32_t i = 0; i < final_cnt && print_it != warp.second.insns.end(); ++i, ++print_it) {
      char insn_name[64];
      disasm(print_it->second.insn, insn_name);
      logger->debug(fmt::format(
        "GVM retire: sm_id: {}, hardware_warp_id: {}, software_wg_id: {}, software_warp_id: {}, dispatch_id: {}, pc: 0x{:08x}, insn: 0x{:08x} {}",
        warp.second.sm_id, warp.second.hardware_warp_id, warp.second.software_wg_id,
        warp.second.software_warp_id, print_it->second.dispatch_id, print_it->second.pc, print_it->second.insn, insn_name
      ));
    }
  }
}


void gvm_t::stepRef() {
  for (auto& item : retire_info.warp_retire_cnt) {
    // 分别步进 REF 的每个 warp
    auto warp_it = dut_active_warps.find({ item.software_wg_id, item.software_warp_id });
    assert(warp_it != dut_active_warps.end());
    assert(item.retire_cnt > 0);

    for (int i=0; i<item.retire_cnt; i++) {
      gvmref_step_return_info_t gvmref_step_return_info;

      auto& cur_insn = warp_it->second.insns[warp_it->second.next_retire_dispatch_id];

      if (cur_insn.extended) {
        gvmref_step(item.software_wg_id, item.software_warp_id, &gvmref_step_return_info); // 跳过 regext
      }

      // 确认 DUT 与 REF 的 PC 一致
      uint32_t next_gvmref_pc;
      next_gvmref_pc = gvmref_get_next_pc(item.software_wg_id, item.software_warp_id);
      uint32_t next_dut_pc;
      next_dut_pc = cur_insn.pc;
      if (next_dut_pc != next_gvmref_pc) {
        logger->error(fmt::format("GVM error: DUT and REF next PC mismatch on sm_id: {}, hardware_warp_id: {}, software_wg_id: {}, software_warp_id: {}. DUT next PC: 0x{:08x}, REF next PC: 0x{:08x}",
          item.sm_id, item.hardware_warp_id, item.software_wg_id, item.software_warp_id, next_dut_pc, next_gvmref_pc));
      }
      assert(next_dut_pc == next_gvmref_pc);

      // 步进 REF 并维护 insn_t.single_insn_cmp
      gvmref_step(item.software_wg_id, item.software_warp_id, &gvmref_step_return_info);
      uint32_t next2_gvmref_pc = gvmref_get_next_pc(item.software_wg_id, item.software_warp_id);
      if (next2_gvmref_pc == next_gvmref_pc) {
        logger->debug(fmt::format("GVM info: REF PC not advanced after step on sm_id: {}, hardware_warp_id: {}, software_wg_id: {}, software_warp_id: {}. REF next PC before step: 0x{:08x}, after step: 0x{:08x}",
          item.sm_id, item.hardware_warp_id, item.software_wg_id, item.software_warp_id, next_gvmref_pc, next2_gvmref_pc));
        if (isInsnCare(cur_insn.insn, barrier_insns)) {
          assert(item.barrier_retry == false); // barrier_retry 应当只被置一次
          item.barrier_retry = true; // 该 warp 包含 barrier 指令，且 REF PC 未前进，标记 barrier_retry
        }
      }
      // assert(next2_gvmref_pc != next_gvmref_pc); // REF 的 PC 应当已经更新

      if (cur_insn.single_insn_cmp.care) {
        // 若为 single_insn_cmp.care 的指令，则从 spike 返回值中提取指令执行结果
        switch (gvmref_step_return_info.insn_result.insn_type) {
          // 对于相同的指令类型，gvmref 认为的指令集合可为 RTL 认为的指令集合的子集
          case XREG:
            assert(cur_insn.single_insn_cmp.cmp_pass == 0);
            cur_insn.single_insn_cmp.ref_done = 1;
            cur_insn.single_insn_cmp.ref_result.insn_type = InsnType::XREG;
            cur_insn.single_insn_cmp.ref_result.xreg_result.rd =
              gvmref_step_return_info.insn_result.xreg_result.rd;
            cur_insn.single_insn_cmp.ref_result.xreg_result.reg_idx =
              gvmref_step_return_info.insn_result.xreg_result.reg_idx;
            break;
          case VREG:
            assert(cur_insn.single_insn_cmp.cmp_pass == 0);
            cur_insn.single_insn_cmp.ref_done = 1;
            cur_insn.single_insn_cmp.ref_result.insn_type = InsnType::VREG;
            cur_insn.single_insn_cmp.ref_result.vreg_result.rd =
              gvmref_step_return_info.insn_result.vreg_result.rd;
            cur_insn.single_insn_cmp.ref_result.vreg_result.reg_idx =
              gvmref_step_return_info.insn_result.vreg_result.reg_idx;
            cur_insn.single_insn_cmp.ref_result.vreg_result.mask =
              unpack_to_array(gvmref_step_return_info.insn_result.vreg_result.mask, warp_it->second.num_thread);
            break;
        }
        if (cur_insn.single_insn_cmp.ref_done == 0) {
          logger->debug(fmt::format("GVM warning: suspected dut and ref insn-type mismatch on pc: 0x{:08x}, insn: 0x{:08x}.",
            cur_insn.pc, cur_insn.insn)); // cmp care 但 ref 返回的 insn type 非 care
          volatile bool temp_flag = cur_insn.single_insn_cmp.ref_done;
        }
        cur_insn.single_insn_cmp.ref_done = 1;
        // 即便 gvmref_step_return_info.insn_result.insn_type 不在上面的 switch-case 中，也置为 ref_done = 1
        // 避免因 care == 1 但 ref_done 恒为 0 导致该条目永远无法删除
        // 在下面的 doSingleInsnCmp() 中会将其忽略而不进行比较（insn type switch-case 的 default）
      }
      if (!item.barrier_retry) {
        cur_insn.retired = true;
        warp_it->second.next_retire_dispatch_id++;
      }
    }
  }
  // 步进末尾的 barrier
  for (const auto& item : retire_info.warp_retire_cnt) {
    // 分别步进 REF 的每个 warp
    auto warp_it = dut_active_warps.find({ item.software_wg_id, item.software_warp_id });
    assert(warp_it != dut_active_warps.end());

    if (item.barrier_included && item.barrier_retry) {
      gvmref_step_return_info_t gvmref_step_return_info;
      auto& cur_insn = warp_it->second.insns[warp_it->second.next_retire_dispatch_id];
      assert(!cur_insn.extended);

      // 确认 DUT 与 REF 的 PC 一致
      uint32_t next_gvmref_pc;
      next_gvmref_pc = gvmref_get_next_pc(item.software_wg_id, item.software_warp_id);
      uint32_t next_dut_pc;
      next_dut_pc = cur_insn.pc;
      if (next_dut_pc != next_gvmref_pc) {
        logger->error(fmt::format("GVM error: DUT and REF next PC mismatch on sm_id: {}, hardware_warp_id: {}, software_wg_id: {}, software_warp_id: {}. DUT next PC: 0x{:08x}, REF next PC: 0x{:08x}",
          item.sm_id, item.hardware_warp_id, item.software_wg_id, item.software_warp_id, next_dut_pc, next_gvmref_pc));
      }
      assert(next_dut_pc == next_gvmref_pc);

      // 步进 REF 并维护 insn_t.single_insn_cmp
      gvmref_step(item.software_wg_id, item.software_warp_id, &gvmref_step_return_info);
      uint32_t next2_gvmref_pc = gvmref_get_next_pc(item.software_wg_id, item.software_warp_id);
      if (next2_gvmref_pc == next_gvmref_pc) {
        logger->debug(fmt::format("GVM info: REF PC not advanced after step on sm_id: {}, hardware_warp_id: {}, software_wg_id: {}, software_warp_id: {}. REF next PC before step: 0x{:08x}, after step: 0x{:08x}",
          item.sm_id, item.hardware_warp_id, item.software_wg_id, item.software_warp_id, next_gvmref_pc, next2_gvmref_pc));
        logger->error("GVM error: REF PC not advanced after stepping over barrier instruction.");
        assert(0);
      }
      // assert(next2_gvmref_pc != next_gvmref_pc); // REF 的 PC 应当已经更新

      assert(!cur_insn.single_insn_cmp.care);
      cur_insn.retired = true;
      warp_it->second.next_retire_dispatch_id++;
    }
  }
}

int gvm_t::doSingleInsnCmp() {
  volatile int dut_active_warps_size = dut_active_warps.size();
  volatile auto dut_active_warps_begin = dut_active_warps.begin();
  volatile auto dut_active_warps_end = dut_active_warps.end();
  // assert(0);
  for (auto warpIt = dut_active_warps.begin(); warpIt != dut_active_warps.end(); ++warpIt) {
    for (auto insnIt = warpIt->second.insns.begin(); insnIt != warpIt->second.insns.end(); ++insnIt) {
      if (insnIt->second.single_insn_cmp.care) {
        if (insnIt->second.single_insn_cmp.dut_done && insnIt->second.single_insn_cmp.ref_done) {
          switch (insnIt->second.single_insn_cmp.dut_result.insn_type) {
            case InsnType::XREG: {
              assert(insnIt->second.single_insn_cmp.ref_result.insn_type == InsnType::XREG);
              if ((insnIt->second.single_insn_cmp.dut_result.xreg_result.rd
                != insnIt->second.single_insn_cmp.ref_result.xreg_result.rd)
                || (insnIt->second.single_insn_cmp.dut_result.xreg_result.reg_idx
                != insnIt->second.single_insn_cmp.ref_result.xreg_result.reg_idx)) {
                logger->error(fmt::format(
                  "GVM error: DUT and REF insn result mismatch at sm_id {}, hardware_warp_id {}, software_wg_id {}, software_warp_id {}, dispatch_id {}, pc 0x{:08x}, insn 0x{:08x}"
                  "insn_type XREG, DUT reg_idx: {}, REF reg_idx: {}, DUT rd: 0x{:08x}, REF rd: 0x{:08x}",
                  warpIt->second.sm_id, warpIt->second.hardware_warp_id, warpIt->second.software_wg_id,
                  warpIt->second.software_warp_id, insnIt->second.dispatch_id, insnIt->second.pc, insnIt->second.insn,
                  insnIt->second.single_insn_cmp.dut_result.xreg_result.reg_idx,
                  insnIt->second.single_insn_cmp.ref_result.xreg_result.reg_idx,
                  insnIt->second.single_insn_cmp.dut_result.xreg_result.rd,
                  insnIt->second.single_insn_cmp.ref_result.xreg_result.rd
                ));
                insnIt->second.single_insn_cmp.cmp_pass = -1;
              } else {
                insnIt->second.single_insn_cmp.cmp_pass = 1;
              }
              break;
            }
            case InsnType::VREG: {
              assert(insnIt->second.single_insn_cmp.ref_result.insn_type == InsnType::VREG);
              bool mask_same = std::equal(
                insnIt->second.single_insn_cmp.dut_result.vreg_result.mask.begin(),
                insnIt->second.single_insn_cmp.dut_result.vreg_result.mask.begin() + warpIt->second.num_thread,
                insnIt->second.single_insn_cmp.ref_result.vreg_result.mask.begin()
              );
              if ((insnIt->second.single_insn_cmp.dut_result.vreg_result.mask
                != insnIt->second.single_insn_cmp.ref_result.vreg_result.mask)
                || (!mask_same))
              {
                logger->error(fmt::format(
                  "GVM error: DUT and REF vreg insn result writeback mask or reg_idx mismatch at sm_id {}, hardware_warp_id {}, software_wg_id {}, software_warp_id {}, dispatch_id {}, pc 0x{:08x}, insn 0x{:08x}, "
                  "insn_type VREG, DUT reg_idx: {}, REF reg_idx: {}, DUT mask: {}, REF mask: {}, DUT reg_idx: {}, REF reg_idx: {}",
                  warpIt->second.sm_id, warpIt->second.hardware_warp_id, warpIt->second.software_wg_id,
                  warpIt->second.software_warp_id, insnIt->second.dispatch_id, insnIt->second.pc, insnIt->second.insn,
                  insnIt->second.single_insn_cmp.dut_result.vreg_result.reg_idx,
                  insnIt->second.single_insn_cmp.ref_result.vreg_result.reg_idx,
                  mask_to_string(insnIt->second.single_insn_cmp.dut_result.vreg_result.mask, warpIt->second.num_thread),
                  mask_to_string(insnIt->second.single_insn_cmp.ref_result.vreg_result.mask, warpIt->second.num_thread),
                  insnIt->second.single_insn_cmp.dut_result.vreg_result.reg_idx,
                  insnIt->second.single_insn_cmp.ref_result.vreg_result.reg_idx
                ));
                insnIt->second.single_insn_cmp.cmp_pass = -1;
              } else {
                bool is_fp32 = isInsnCare(insnIt->second.insn, fp32_vreg_insns);
                for (int i = 0; i < warpIt->second.num_thread; i++) {
                  if (insnIt->second.single_insn_cmp.dut_result.vreg_result.mask[i]) {
                    if (is_fp32) {
                      float dut_value = *reinterpret_cast<float*>(&insnIt->second.single_insn_cmp.dut_result.vreg_result.rd[i]);
                      float ref_value = *reinterpret_cast<float*>(&insnIt->second.single_insn_cmp.ref_result.vreg_result.rd[i]);
                      if (std::abs(dut_value - ref_value) > fp32_atol + fp32_rtol * std::abs(ref_value)) {
                        logger->error(fmt::format(
                          "GVM error: DUT and REF vreg-float mismatch at sm_id {}, hardware_warp_id {}, software_wg_id {}, software_warp_id {}, dispatch_id {}, pc 0x{:08x}, insn 0x{:08x}, "
                          "vreg_idx {}, vec_element_idx {}, DUT value: {}, REF value: {}",
                          warpIt->second.sm_id, warpIt->second.hardware_warp_id, warpIt->second.software_wg_id, warpIt->second.software_warp_id,
                          insnIt->second.dispatch_id, insnIt->second.pc, insnIt->second.insn,
                          insnIt->second.single_insn_cmp.dut_result.vreg_result.reg_idx,
                          i, dut_value, ref_value
                        ));
                        insnIt->second.single_insn_cmp.cmp_pass = -1;
                      }
                    } else {
                      if (insnIt->second.single_insn_cmp.dut_result.vreg_result.rd[i]
                        != insnIt->second.single_insn_cmp.ref_result.vreg_result.rd[i]) {
                        logger->error(fmt::format(
                          "GVM error: DUT and REF vreg mismatch at sm_id {}, hardware_warp_id {}, software_wg_id {}, software_warp_id {}, dispatch_id {}, pc 0x{:08x}, insn 0x{:08x}, "
                          "vreg_idx {}, vec_element_idx {}, DUT value: 0x{:08x}, REF value: 0x{:08x}",
                          warpIt->second.sm_id, warpIt->second.hardware_warp_id, warpIt->second.software_wg_id, warpIt->second.software_warp_id,
                          insnIt->second.dispatch_id, insnIt->second.pc, insnIt->second.insn,
                          insnIt->second.single_insn_cmp.dut_result.vreg_result.reg_idx,
                          i,
                          insnIt->second.single_insn_cmp.dut_result.vreg_result.rd[i],
                          insnIt->second.single_insn_cmp.ref_result.vreg_result.rd[i]
                        ));
                        insnIt->second.single_insn_cmp.cmp_pass = -1;
                      }
                    }
                  }
                }
                if (insnIt->second.single_insn_cmp.cmp_pass == 0) {
                  insnIt->second.single_insn_cmp.cmp_pass = 1; // 比对通过
                }
              }
              break;
            }
            default: {
              insnIt->second.single_insn_cmp.cmp_pass = -2; // unknown insn type
              break;
            }
          }
        }
      }
    }
  }
  return 0;
}

int gvm_t::doRetireCmp() {
  gvmref_xreg_t gvmref_xreg;
  for (const auto& item : retire_info.warp_retire_cnt) {    
  gvmref_get_xreg(&gvmref_xreg, item.software_wg_id, item.software_warp_id);
    auto& warp = dut_active_warps[{item.software_wg_id, item.software_warp_id}];
    for (int i=0; i<warp.xreg_usage; i++) {
      if (static_cast<uint32_t>(gvmref_xreg.xpr[i]) != warp.curr_xreg[i]) {
        logger->error(fmt::format(
          "GVM error: DUT and REF xreg mismatch at sm_id {}, hardware_warp_id {}, software_wg_id {}, software_warp_id {}, reg x{}: DUT = 0x{:08x}, REF = 0x{:08x}",
          warp.sm_id, warp.hardware_warp_id, warp.software_wg_id, warp.software_warp_id, i,
          warp.curr_xreg[i],
          static_cast<uint32_t>(gvmref_xreg.xpr[i])
        ));
      }
    }
  }
  return 0;
}

void gvm_t::clearInsnItem() {
  for (auto& warp: dut_active_warps) {
    for (auto insn_it = warp.second.insns.begin(); insn_it != warp.second.insns.end(); ) {
      if ((insn_it->second.single_insn_cmp.cmp_pass != 0)
        && (insn_it->second.retired == true)) {
        insn_it = warp.second.insns.erase(insn_it);
      }
      else {
        break;
      }
    }
  }
}

void gvm_t::resetRetireInfo() {
  retire_info.warp_retire_cnt.clear();
}