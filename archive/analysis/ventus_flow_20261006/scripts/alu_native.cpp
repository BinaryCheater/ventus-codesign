#include "VScalarALU.h"
#include "verilated.h"
#include <cstdint>
#include <iostream>

int main() {
    VScalarALU dut;
    uint32_t state = 1;
    unsigned checked = 0;
    for (unsigned i = 0; i < 1000; ++i) {
        state = state * 1664525u + 1013904223u;
        uint32_t a = state;
        state = state * 1664525u + 1013904223u;
        uint32_t b = state;
        const unsigned functions[] = {0, 10, 4, 6, 7};
        const uint32_t expected[] = {a + b, a - b, a ^ b, a | b, a & b};
        for (unsigned j = 0; j < 5; ++j) {
            dut.io_func = functions[j];
            dut.io_in1 = a;
            dut.io_in2 = b;
            dut.eval();
            if (dut.io_out != expected[j]) {
                std::cerr << "ALU mismatch on function " << functions[j] << "\n";
                return 1;
            }
            ++checked;
        }
    }
    std::cout << "Native ALU checks passed: " << checked << "\n";
}
