#pragma once

#include "Vdut.h"
#include "cta_sche_wrapper.hpp"
#include "physical_mem.hpp"
#include "ventus_rtlsim.h"
#include <array>
#include <bitset>
#include <memory>
#include <queue>
#include <verilated.h>
#include <verilated_fst_c.h>

extern const std::unordered_map<std::string, int> rtl_parameters;

#define SNAPSHOT_WAKEUP_SIGNAL SIGRTMIN
typedef struct {
    bool is_child;
    uint64_t main_exit_time;        // when does the main simulation process exit
    std::deque<pid_t> children_pid; // front is newest, back is oldest
} snapshot_t;

using vaddr_t = uint32_t;
constexpr unsigned NUM_THREAD = 32;
constexpr unsigned NUM_SM = 2;

struct dcache_reqrsp_t {
    uint8_t sm_id;
    uint8_t instrId;
    uint8_t opcode;
    uint8_t param;
    vaddr_t setIdx;
    vaddr_t tag;
    std::bitset<NUM_THREAD> mask;
    std::array<vaddr_t, NUM_THREAD> blockOffset;
    std::array<uint8_t, NUM_THREAD> wordOffset1H;
    std::array<uint32_t, NUM_THREAD> data;
};

struct icache_reqrsp_t {
    uint8_t sm_id;
    uint8_t source;
    paddr_t addr;
    uint32_t data[32];
};

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
    std::queue<std::unique_ptr<dcache_reqrsp_t>> dcache_queue;
    std::queue<std::unique_ptr<icache_reqrsp_t>> icache_queue;
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
