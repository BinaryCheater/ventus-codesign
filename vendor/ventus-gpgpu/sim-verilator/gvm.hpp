// GVM 核心类的头文件

#pragma once

#include <cstdint>
#include <map>
#include <vector>
#include <memory>
#include <spdlog/logger.h>

#include "gvmref_interface.h"
#include "gvm_global_var.hpp"
#include "gvm_structs.hpp"

class gvm_t
{
public:
  gvm_t() = default;
  ~gvm_t() = default;

  void getDut(); // 更新 DUT 成员变量，清空全局变量
  int gvmStep(); // 执行 GVM 步进行为

  std::shared_ptr<spdlog::logger> logger;

private:
  std::map<warp_key_t, dut_active_warp_t> dut_active_warps;

  // getDut() 相关函数
  void getDutWarpNew(); // 添加新 warp 条目
  void getDutWarpFinish(); // 删除已完成 warp 条目
  void getDutInsnDispatch(); // 添加新指令条目
  void getDutInsnFinish();
  void getDutXRegWbFinish();
  void getDutVRegWbFinish();
  void getDutBarDone();
  void getDutXReg(); // 根据 warp 条目更新 XReg 条目
  void getDutWarpNewSetRefXReg();
  void clearGlobal(); // 清空全局变量

  // gvmStep() 相关函数
  void checkRetire();
  retireInfo_t retire_info;
  void stepRef();
  int doSingleInsnCmp();
  float fp32_atol = 1e-3f; // 浮点数比较的绝对误差
  float fp32_rtol = 1e-3f; // 浮点数比较的相对误差
  int doRetireCmp();
  void clearInsnItem();
  void resetRetireInfo();

  // 判断指令是否关心
  bool isInsnCare(uint32_t insn, const std::vector<care_insn_t> care_insns);
  static const std::vector<care_insn_t> retire_care_insns;
  static const std::vector<care_insn_t> single_insn_cmp_care_insns;
  static const std::vector<care_insn_t> fp32_vreg_insns;
  void disasm(uint32_t insn, char* insn_name);
  static const std::vector<care_insn_t> disasm_table;
  static const std::vector<care_insn_t> barrier_insns;
};