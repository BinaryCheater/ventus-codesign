# 简介

## 中文
本目录源自`sim-verilator/`目录，但在移除了RTL中的L1 Dcache和L2 cache（L1 Icache仍在），是方便单独调试GPGPU内核实现的*临时性*措施。   
除此之外本目录下的内容基本与`sim-verilator`相同，可直接参看[sim-verilator/README.md](../sim-verilator/README.md)

TODO:  
- [ ] 目前未在RTL中对移除cache后的接口做包装，而是在C++激励代码中处理，导致硬件规模改变时激励代码需要修改

## English
This directory originates from `sim-verilator/`, but with **L1 Dcache** and **L2 cache** removed from the RTL (the **L1 Icache** is still present).
This is a *temporary* measure to facilitate standalone debugging of the GPGPU core implementation.

Other than this difference, the contents here are essentially the same as in `sim-verilator/`.
Please refer to [sim-verilator/README.md](../sim-verilator/README.md) for details.


**TODO:**

* [ ] Currently, the cache-removed interfaces are not wrapped in RTL. Instead, the handling is done in the C++ testbench code, which means the testbench needs modification whenever the hardware configuration changes.
