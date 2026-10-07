# Ventus 软硬件协同优化：任务说明

更新：2026-10-07

目标：在同一面积预算下，联合选择 GPU 配置与软件实现，比较专用配置和兼顾多场景的配置。每个人完成全部任务。评估使用已有性能模拟器和成本模型，不要求跑 RTL。

## 1. Workload 与目标

本轮主任务使用 Qwen2.5-0.5B-Instruct，batch=1、BF16，保留完整网络。

| 场景 | 执行内容 | 周期指标 T |
|---|---|---|
| Q-P128 / Q-P512 | 128 / 512 token 的 prefill | 一次 prefill 总周期 |
| Q-D128 / Q-D512 | 初始 KV 长度 128 / 512，连续 decode 16 步 | 16 步平均周期 |

输入、权重和初始 KV 已在设备外存；每个场景从冷 cache 开始，decode 步间保留 cache。Prefill 的 LM head 计算最后一个位置；decode 每步计算 LM head。不计 tokenizer、采样、模型加载和主机初始传输。

定义 r(w)=候选周期 T(H,S,w)/默认基线周期 T0(w)，越小越好。

| 任务 | 优化场景 | 目标 |
|---|---|---|
| A：Prefill 优化 | Q-P128、Q-P512 | 最小化两个 r 中的最大值 |
| B：Decode 优化 | Q-D128、Q-D512 | 最小化两个 r 中的最大值 |
| C：综合优化 | 四个 Qwen 场景 | 最小化四个 r 中的最大值 |

每个任务输出一套固定硬件，软件可按 kernel、形状和场景选择。三个任务统一使用最大值目标，便于比较；MIP 引入 t，对选定场景约束 r(w)≤t，最小化 t。周期与设计变量的关系需另外建模。

三套结果均在四个场景上交叉评估，观察专用收益和跨场景代价。

### GPT-2、Pythia 现在能否加入

| 模型 | 当前仓库入口 | 本轮使用方式 |
|---|---|---|
| Qwen | `prepare-qwen` → 编译 ELF → `instructions`，已有完整场景记录 | 主任务 |
| GPT-2 | `transformer --preset gpt2`，旧模板生成路径；缺少完整编译 ELF 网络调用入口 | 接通后做迁移评估 |
| Pythia | 已有 FP16 kernel 测试，缺少完整网络调用入口 | 接通后做迁移评估 |

GPT-2 的旧模板入口无法直接反映任意 OpenCL 源码修改，不能与 Qwen 的编译程序结果混作同一评估方法。三模型齐备后，再冻结 A/B/C 硬件，测试 GPT-2 prefill/decode 和 Pythia prefill；本轮先不以它们作为交付前提。

## 2. 硬件与预算

基线为 Ventus 默认结构的多精度派生配置：2 SM、每 SM 8 warp/8 block、32 线程、Tensor (4,8,4)，软件为 `packed64`。完整值见[基线配置](../examples/project-baseline-v2.json)。

统一约束：**总面积 ≤ 1.1039550819992285 mm²**，包含逻辑和容量等效 SRAM，无额外总存储 bits 上限。固定外存 1 通道、64 B/cycle、100 cycles；固定线程宽度 32、cache line 128 B 和多精度时序目标。比较周期数，不搜索频率。

| 类别 | 可选值 |
|---|---|
| 规模与驻留 | SM：1/2/3/4；warp/SM：4/8/16；block/SM：2/4/8/16 |
| RF 与收集器 | banks：4/8/16；读、写、写回 ports：各 1/2；collectors：4/8/16；VGPR slots：256/512/1024/2048；SGPR slots：128/256/512/1024/2048 |
| Tensor | m：2/4/8；n：2/4/8/16；k：2/4/8；units：1/2/4 |
| LDS | 容量：16/32/64/128 KiB；banks：8/16/32；ports：1/2 |
| L1 | sets：64/128/256/512；ways：1/2/4；MSHR：2/4/8/16；subentries：1/2/4/8；write entries：2/4/8/16 |
| L2 | sets：32/64/128/256；ways：4/8/16；MSHR：8/16/32/64 |
| LSU | entries：4/8/16；per-warp：1/2/4/8 |

共 27 个字段，使用[机器可读范围](../examples/search-space-v2.json)。block 数不超过 warp 槽数，寄存器容量按 bank 整除，Tensor 任意两维乘积不超过 32；程序每 block 的寄存器/LDS 需求须能容纳。8 SM 已因最小估计面积超预算排除。

成本查询：`./run costs --model unified-v2 --hardware <hardware.json>`。MIP 成本接口为 `add_unified_area_constraints`，解码复核为 `decode_unified_solution`。公式和采集数据见[面积规则](area-budget.md)。成本是统一结构估计，允许外推；结果称为 Ventus 派生架构的模型优化。

## 3. 软件怎么改，怎样配合硬件

实际路径：

> OpenCL kernel + Python 调用组织 → Ventus LLVM 编译 ELF → 程序启动描述 → 指令级性能模拟器。

- **先用现成变体：** `scalar`、`packed`、`packed64`，通过 `prepare-qwen --mapping ...` 选择。切换变体可复用已有 ELF，重新生成调用描述。
- **增加软件优化：** 修改 `examples/kernels/*.cl`，尝试 tile、循环、数据布局、操作数复用或融合；使用 `compile-kernel` 或 `compile-model-kernels` 编译。修改 `codesign/ventus/model_program.py` 中的 kernel 调用、缓冲布局和启动参数，使新程序进入整网。由 agent 完成新 kernel 的接入。
- **不要求修改 LLVM 或接入 PyTorch：** 编译器负责指令生成；Python 运行器负责网络调用。固定网络、精度及计算语义，布局转换和中间搬运计入执行。

硬件变化后的处理：

| 改动 | 软件处理 |
|---|---|
| SM、cache、队列、bank/port、执行单元数量等资源配置 | ISA/ABI 保持一致时复用 ELF，模拟器按新资源重新调度 |
| 缩小 VGPR、SGPR 或 LDS | 检查编译资源占用；能容纳则重新计算驻留，连一个 block 都放不下则淘汰，或另改 kernel 降低占用 |
| 当前菜单内 Tensor 物理形状 | 模型保持相同 MMA 指令语义，以物理阵列资源计算服务时间；可复用 ELF。这不代表相应 RTL 已实现该指令 |
| 改线程宽度、指令语义或 ABI | 需要适配编译器、kernel 和执行器，本轮不开放 |

软件编写与建模由参与者驱动 agent 完成，不要求开发自动软件生成器。agent 可针对候选硬件改写 OpenCL 和调用组织，编译后读取真实资源需求，再与硬件配对。编译 ELF 入口当前支持每 block 一个 32-lane warp。

agent 同时负责将程序抽象成可搜索的模型：提取 tile、布局、融合与复用等软件选择，计算指令工作量、访存量及依赖，建立寄存器/LDS 占用、驻留和硬件服务能力之间的约束。抽象应能对应到具体源码、编译产物或明确公式；编译可得的资源数据直接读取，估计项单独标明。MIP 选择软硬件组合，agent 实现所选方案，指令模拟器复评实际程序，再据偏差完善抽象。

性能模拟器不计算完整张量数值，无法证明修改后的算法正确。新增软件变体须做小尺寸数值对照或有针对性的功能测试，再用于性能搜索；无需逐候选跑 RTL。编译与运行命令见[程序说明](instruction-programs.md)。

### Agent 的具体工作与调度

每位参与者用一个主 agent 顺序完成下表即可，不要求搭建多 agent 调度系统。参与者指定任务 A/B/C、工作目录和搜索预算；agent 调用编译器、求解器和模拟器完成迭代。下面是工作约定，仓库尚无自动执行整套流程的控制器。

| 步骤 | Agent 做什么 | 可检查的产物 |
|---|---|---|
| 1. 确定改动 | 读取真实形状、已有 kernel 和阶段耗时，提出一个具体优化假设 | 要改的 kernel、软件选项、预期减少的工作量 |
| 2. 写软件 | 修改 OpenCL、编译入口、Python 缓冲及 dispatch；保留原变体 | 新源码、ELF、启动描述和小尺寸功能检查 |
| 3. 做抽象 | 读取编译器的 VGPR/SGPR/LDS 用量；从循环和地址映射推导指令量、流量、依赖及适用形状 | 软件选项表、资源约束和性能公式；每项注明来源 |
| 4. 求解 | 将软件选择与 27 个硬件字段耦合，加入面积与驻留约束，使用近似周期求解 A/B/C | 硬件 JSON、软件选择、求解状态和预测周期 |
| 5. 复评 | 按解生成程序描述，调用指令模拟器；比较预测与模拟结果 | 实际模拟周期、偏差和瓶颈；决定改程序或改抽象 |

具体起点：比较 GEMM 每 warp 处理 16×16、16×64、32×64 输出 tile。已有 `mma_packed_bf16.cl` 和 `mma_reuse_bf16.cl` 可复用；后者以 `two_m` 控制一行或两行 tile。agent 将 `model_program.py` 中按形状写死的选择改成显式软件选项，并把适用条件、packing、尾块及资源用量一起带入模型。不同 tile 若需不同寄存器分配，应编译独立变体；仅修改启动参数不会改变 ELF 的静态寄存器需求。

例如每 block 一个 warp 时，驻留数满足：block 槽数、warp 槽数、⌊VGPR 容量/每 block VGPR 用量⌋、⌊SGPR 容量/每 block SGPR 用量⌋、⌊LDS 容量/每 block LDS 用量⌋的共同上限；用量为零的项忽略。这使 tile 复用收益与寄存器容量发生实际耦合。求解器约束由 agent 实现，模拟器独立复评。

程序调度分两层：agent 编写 kernel 划分、tile 到 block 的映射及 kernel 依赖；当前运行器按 dispatch 顺序串行执行 kernel。SM 分配、block 驻留、warp 发射和资源等待由模拟器根据硬件配置处理。agent 不指定每条指令的实际发射周期，也不假定当前入口支持多 kernel 并发。

可直接交给 agent 的[执行 prompt](../prompts/software-search-agent-cn.md)给出了第一轮范围和完成条件。

## 4. 开始实验

1. 按[环境说明](workflows.md)配置仓库，`./run` 沿用自己的私有执行配置。
2. 使用[已有基线结果](evidence/baseline-run-20261007/README.md)：128 场景已完整模拟，512 为明确标注的递推。当前无需重跑 512。候选的 512 估计需来自该候选的分阶段数据，并记录递推方法，不能直接套用基线加速比。
3. 从真实尺寸 attention 或 FFN 子图开始，让 agent 编写软件并提取参数化抽象，建立 MIP。编译、检查所选方案，用指令模拟器复评，迭代更新程序和抽象。
4. 完成 A/B/C 和四场景交叉表。完整模拟与递推结果分列；记录搜索次数、宿主耗时和求解状态。

准备一个 Qwen 程序并评估（输出目录须为新目录）：

```bash
./run model prepare-qwen --bundle tests/fixtures/compiled-transformer/bundle.json --phase prefill --context 128 --mapping packed64 --out results/qwen-program-001
./run model instructions --input results/qwen-program-001/program.json --hardware examples/baseline-hardware-v1.json --out results/qwen-run-001 --budget 3600
```

## 5. 对照与交付

每人使用相同预算和评估器，保留五种对照：默认 H0+S0、仅软件优化、仅硬件优化、先软件后硬件、联合优化。MIP 应实际参与选解；可结合启发式和 AI，不必预先枚举全部组合。

交付：代码与配置、简短建模说明、三份设计的四场景结果表，以及周期—面积和 prefill—decode 权衡图。说明主要收益来自哪些软件改动或资源调整。记录程序/模型版本、配置 hash、资源占用、总面积、周期、搜索耗时及失败原因；旧结果不覆盖。公共模型修复后，统一复评受影响的结果。
