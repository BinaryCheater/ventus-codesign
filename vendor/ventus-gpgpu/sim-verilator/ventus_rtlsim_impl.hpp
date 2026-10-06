#pragma once

#include "Vdut.h"
#include "cta_sche_wrapper.hpp"
#include "physical_mem.hpp"
#include "ventus_rtlsim.h"
#include <memory>
#include <verilated.h>
#include <verilated_fst_c.h>

extern const std::unordered_map<std::string, int> rtl_parameters;
#ifdef ENABLE_GVM
#include "gvm.hpp"
#endif // ENABLE_GVM

#define SNAPSHOT_WAKEUP_SIGNAL SIGRTMIN
typedef struct {
    bool is_child;
    uint64_t main_exit_time;        // when does the main simulation process exit
    std::deque<pid_t> children_pid; // front is newest, back is oldest
} snapshot_t;

extern "C" struct ventus_rtlsim_t {
    std::shared_ptr<spdlog::logger> logger;
    VerilatedContext* contextp;
    Vdut* dut;
    VerilatedFstC* tfp;
    Cta* cta;
    snapshot_t snapshots;
    ventus_rtlsim_config_t config;
    ventus_rtlsim_step_result_t step_status;
    std::unique_ptr<PhysicalMemory> pmem;
#ifdef ENABLE_GVM
    gvm_t gvm;
#endif // ENABLE_GVM
    bool need_icache_invalidate = false;

    void constructor(const ventus_rtlsim_config_t* config);
    void dut_reset() const;
    const ventus_rtlsim_step_result_t* step();
    void destructor(bool snapshot_rollback_forcing);

    void waveform_dump() const;
    void snapshot_fork();
    void snapshot_rollback(uint64_t time);
    void snapshot_kill_all();
};

inline static paddr_t pmem_get_page_base(paddr_t paddr, uint64_t pagesize) { return paddr - paddr % pagesize; }
