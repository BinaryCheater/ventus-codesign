// Observe existing Verilator signals without changing the DUT or RTL library.
// Pin compilation to the same generated headers as the original debug binary.
#include "Vdut.h"
#include "Vdut___024root.h"
#include "Vdut_operandCollector.h"
#include "Vdut_Writeback.h"
#include "Vdut_vTCexe.h"
#include <cstdio>
#include <atomic>
#include <string>
#include <cstdlib>
#include <dlfcn.h>

static std::atomic<unsigned long long> current_cycle{0};
static FILE* trace_output = nullptr;

extern "C" void observe_eval(Vdut* dut) asm("_ZN4Vdut9eval_stepEv");
extern "C" void observe_eval(Vdut* dut) {
    static auto original = reinterpret_cast<void (*)(Vdut*)>(dlsym(RTLD_NEXT, "_ZN4Vdut9eval_stepEv"));
    static FILE* out = std::fopen(std::getenv("VENTUS_TRACE_PATH"), "w");
    trace_output = out;
    current_cycle.store(dut->contextp()->time() / 10);
    if (!original || !out) std::abort();
    if (dut->clock && !dut->reset) {
        const auto cycle = dut->contextp()->time() / 10;
        auto emit = [&](const char* kind, unsigned warp, unsigned pc, unsigned inst) {
            std::fprintf(out, "%llu,%s,%u,%08x,%08x\n", (unsigned long long)cycle, kind, warp, pc, inst);
        };
        auto* root = dut->rootp;
        {
        auto* col = root->__PVT__GPGPU_SimTop__DOT__gpgpu__DOT__GPU__DOT__SM_wrapper__DOT__pipe__DOT__operand_collector;
        if (col->io_controlX_valid && col->io_controlX_ready) emit("collect", 0 + col->io_controlX_bits_wid, col->io_controlX_bits_pc, col->io_controlX_bits_inst);
        if (col->io_controlV_valid && col->io_controlV_ready) emit("collect", 0 + col->io_controlV_bits_wid, col->io_controlV_bits_pc, col->io_controlV_bits_inst);
        }
        {
        auto* col = root->__PVT__GPGPU_SimTop__DOT__gpgpu__DOT__GPU__DOT__SM_wrapper_1__DOT__pipe__DOT__operand_collector;
        if (col->io_controlX_valid && col->io_controlX_ready) emit("collect", 8 + col->io_controlX_bits_wid, col->io_controlX_bits_pc, col->io_controlX_bits_inst);
        if (col->io_controlV_valid && col->io_controlV_ready) emit("collect", 8 + col->io_controlV_bits_wid, col->io_controlV_bits_pc, col->io_controlV_bits_inst);
        }
        if (dut->io_mem_rd_en) emit("memory.read", 0, dut->io_mem_rd_addr, 0);
        if (dut->io_mem_wr_en) emit("memory.write", 0, dut->io_mem_wr_addr, 0);
        if (dut->io_host_rsp_valid && dut->io_host_rsp_ready) emit("host.finish", 0, 0, 0);
        std::fflush(out);
    }
    // Optional external launch delay: allow SRAM reset sweeps to finish.
    const char* delay = std::getenv("VENTUS_LAUNCH_NOT_BEFORE");
    if (delay && !dut->clock && current_cycle.load() < std::strtoull(delay, nullptr, 10)) dut->io_host_req_valid = 0;
    original(dut);
}

extern "C" size_t fwrite(const void* ptr, size_t size, size_t count, FILE* stream) {
    static auto original = reinterpret_cast<size_t (*)(const void*,size_t,size_t,FILE*)>(dlsym(RTLD_NEXT, "fwrite"));
    if (trace_output && stream == stderr && size * count > 3) {
        std::string line(static_cast<const char*>(ptr), size * count);
        unsigned sm, warp, pc, inst;
        if (std::sscanf(line.c_str(), "sm %u warp %u 0x%x 0x%x", &sm, &warp, &pc, &inst) == 4) {
            const char* kind = line.find("lsu.w finish") != std::string::npos ? "store.complete" :
                line.find("lsu.") != std::string::npos ? "lsu.issue" :
                line.find("endprg") != std::string::npos ? "end" :
                line.find("barrier") != std::string::npos ? "barrier" : "writeback";
            std::fprintf(trace_output, "%llu,%s,%u,%08x,%08x\n", current_cycle.load(), kind, sm * 8 + warp, pc, inst);
        }
    }
    return original(ptr,size,count,stream);
}
