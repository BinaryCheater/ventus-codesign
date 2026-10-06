# Ventus GPU 架构与成本采集计划

日期：2026-09-23。状态：远端环境、默认 RTL 生成及一个 `vecadd` RTL 功能烟雾测试已验证；完整基线、综合和 Transformer kernel 尚未完成，也未修改 Break Layer 的成本版本与课程评分器。本文用于建立 GPU 架构数据锚点，实验结论须以随后冻结的运行快照为准。

## 1. 基线与边界

- Ventus 已克隆到 `${OWNER_UPSTREAM_CHECKOUT}`，主仓库提交为 `681172541a8a34ffb43c483a19c075acbc11a4eb`，递归子模块已检出，工作树干净。保持它为独立仓库；Break Layer 记录上游提交、子模块提交、改动补丁和生成 RTL 的哈希。
- [Ventus 主仓库](https://github.com/THU-DSP-LAB/ventus-gpgpu)使用 Chisel，`sim-verilator/`提供 RTL 仿真；完整 OpenCL 工具链由 [ventus-env](https://github.com/THU-DSP-LAB/ventus-env)组织。先使用仓库已有 testcase，再生成本项目 kernel。`ventus-env` 自身锁定的 GPGPU 子模块提交与本次主仓库提交不同，后续完整软件栈实验须选择并记录一套相互兼容的提交。
- 当前 Break Layer 的硬件主导候选菜单以阵列、RF、L1/L2 和 NoC 为核心，尚未实现新成本模型。转向 GPU 实例后，需要把 SM、warp、occupancy、SIMT 执行和 tensor 指令纳入候选契约，并升级成本版本。旧 toy 最优性、分数和剪枝界均不能转作 Ventus 的证据。
- 固定研究 workload 初选仍为单个 FP32 Transformer block，B=1、S=128、D=128、4 heads、FFN=512、causal prefill。阶段一只测代表性 kernel；完整 block 的编译和数值验证在工具链可运行后进行。明确 FP32 FMA 与现有 Python reference 的运算顺序和容差。

## 2. 先测什么、哪些参数进入搜索

Ventus 当前源码的默认配置见 [`top/parameters.scala`](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/master/ventus/src/top/parameters.scala)：2 SM、每 SM 8 warp、每 warp 32 thread、寄存器堆 4 bank、shared memory 128 KiB，FP32 tensor core 尺寸为 `(M,N,K)=(4,8,4)`。这些是**源码默认值**，还不是本机实测配置。

| 层级 | 首轮处理 | 候选值或观测量 | 开放条件 |
|---|---|---|---|
| SM 数 | 搜索 | 2、4；2 为原基线 | 两档都能生成、执行同一语义 kernel；记录实际使用的 SM 数、面积和流量 |
| warp slot / SM | 搜索 | 4、8；8 为基线 | `num_block`、CTA 资源表和 host 元数据同步调整；比较 occupancy、调度空泡与寄存器占用 |
| lane / warp | 首轮固定 | 32 | 改动会同时影响指令数据形状、shared-memory bank 和 tensor core 接口；以后单独开展兼容性实验 |
| VGPR / SGPR 容量 | 搜索 | 基线容量的 0.5、1、2 倍，各自独立取值 | CTA allocator 必须按真实寄存器使用量约束驻留；生成 RTL 后核对存储位数与综合面积 |
| 寄存器 bank | 第二轮搜索 | 4、8 | operand collector、bank 寻址、冲突与回放均通过模块回归；不将 bank 增加写成免费带宽 |
| shared memory 容量 | 搜索 | 64、128、256 KiB；由 `sharedmem_depth` 参数实现，128 KiB 为基线 | 地址范围、CTA 分配和 kernel 的 LDS 占用一致；SRAM 面积/能量单独建模 |
| shared memory bank | 第二轮研究 | 先固定 Ventus 原结构；解耦后再试 16、32 bank | 当前源码 `NBanks = NLanes`，冲突仲裁器也假定二者相等，须修改接口并验证所有地址映射后才开放 |
| FP32 tensor core | 首轮固定、第二轮搜索 | 基线 `(4,8,4)`；后续试满足源码维度断言的 `(2,8,2)`、`(8,4,4)` | 每档重编译或重排同一 GEMM，核对指令语义、FMA 数、正确性及利用率；仅成功 elaboration 不算通过 |
| L1/L2 cache 与外存 | 首轮固定 | 记录 miss、传输字节、等待；外存时序单列 | RTL 仿真本身没有 DDR timing，先固定外存契约；逐项开放 cache 参数前须能区分容量与带宽收益 |
| NoC 拓扑/宽度 | 首轮固定 | 记录端点活动、链路请求和拥塞代理量 | 有可验证的逐周期路由与面积/能耗锚点后再搜索；否则保持同一固定连接假设 |

首轮采用**单变量变化**，再选 4–8 个计算偏重、存储偏重、均衡配置做交叉组合。先检验参数是否真的改变合法性、周期或成本；冗余维度不进入最终菜单。每个设计使用相同输入、目标频率、库角和编译器版本。

## 3. 模块来源和自写边界

| 对象 | 来源 | 处理方式与原因 |
|---|---|---|
| CTA 分配与资源表、warp 调度、scoreboard / operand collector | Ventus `ventus/src/cta/`、`ventus/src/pipeline/` | 保留上游实现作 GPU 行为基线；添加可开关计数器，收集 occupancy、发射与停顿。修改参数时先跑上游 testcase。 |
| VGPR/SGPR 寄存器堆 | Ventus `ventus/src/pipeline/regfile.scala` | 提取位数、端口、bank 与访问事件；综合 RF 逻辑和存储需分开记账，避免把寄存器推断结果当 SRAM 宏。 |
| shared memory、bank 冲突仲裁 | Ventus `ventus/src/L1Cache/ShareMem/` | 首轮按原结构测试；独立 bank 参数需要专门改造或另写小型参数化原型，并与原结构逐事务对照。源码注释指出当前同址读请求不会合并。 |
| FP32 tensor core 与 FMA | Ventus 的 `dependencies/fpuv2/src/main/scala/Tensor.scala`、`FMA.scala` | 作为算术 RTL 锚点；保留上游依赖与许可来源，用数值测试核对 fused 运算语义。阶段一不重写 FP32 FMA。 |
| L1/L2、内存接口 | Ventus 现有实现 | 首轮只采集请求/字节/等待和局部面积；不把完整 cache、MMU 或总线搬入 Break Layer。 |
| kernel 微基准、活动计数器、结果解析器 | 本项目新写 | 用 AI 编写且以测试与上游仿真交叉检查；统一记录参数、kernel、输入、源码/工具/库哈希、成功或失败状态。 |
| Break Layer 到 GPU 的映射/成本适配 | 本项目新写 | 将 GEMM、reduction、elementwise 的 chunk 与 Ventus kernel/访存事件对齐；保持数值执行、RTL 周期、综合面积和模型能耗各自独立。 |
| NoC/外存周期模型 | 本项目新写小模型 | 明确仲裁、带宽和延迟假设，并做敏感性区间；在没有布局数据时不输出布线后频率。 |

若复制 Ventus 源文件或生成 RTL 到本项目，记录原路径、提交、修改点和许可；Ventus 主库为木兰宽松许可证 v2，部分依赖和文件另有许可。优先在独立克隆中保持上游可复现基线，项目侧存适配与结果摘要。

## 4. 工作负载和采集协议

1. **环境基线。** 先生成默认 Verilog，运行仓库自带的 `vecadd`、`matadd` 和 `wmma484fp32`/tensor testcase；保存输出、周期与日志。固定同一个 baseline 才改参数。
2. **模块微基准。** FP32 tensor core：吞吐、流水延迟、输入空泡和逐位/容差比较；寄存器堆：bank 冲突与端口吞吐；shared memory：无冲突、集中冲突、广播/同址读、读写混合；CTA：寄存器和 LDS 限制下的活跃 warp 数。每类至少包含边界和尾块。
3. **Transformer kernel。** QKV 与 FFN GEMM、attention score/context GEMM、softmax/LN reduction、GELU/残差。对每个 kernel 记录输入输出、指令或 tile 数、FMA 数、访存量、周期及 stall 分类；核对与 Break Layer 数值路径的一致性。完整 block 只在这些 kernel 闭环后拼接。
4. **面积与功耗。** Yosys 映射局部逻辑到同一套 ASAP7 RVT/TT Liberty，保存 cell 面积、cell 组成和综合约束。用仿真活动文件和 OpenSTA 得到标准单元动态/漏电估计；SRAM 宏面积、访问能量与漏电单独查表或给区间。NoC 与片外内存分别记账，禁止将总线开关活动重复计入 SRAM/HBM 能量。
5. **统一快照。** 每个配置保存 `config`、上游和子模块 SHA、补丁/生成 RTL hash、kernel/input hash、工具版本、库 hash、功能结果、周期/计数器、综合/功耗原始报告、提取脚本版本与不确定性区间。结果目录不可覆盖，失败配置也保存失败阶段。旧 Break Layer 结果只读复验。

评分器只有在面积、活动能量与服务周期都能从同一硬件配置和同一 kernel 追溯时才接入。比较设计时同时报告 `(A,E,T)` 和 `J=N/(A·E)`；对 SRAM/NoC 估计范围进行灵敏度检查。如果方案排序会随合理假设翻转，就标记“尚不能定序”，继续采集锚点。

## 5. 依赖清单与当前环境

本机为 macOS arm64；已找到 Yosys 0.69、Verilator 5.052、Icarus Verilog 13、CMake、Ninja、Docker/Colima、`fmt`。`java` 命令存在但没有可用 JDK；未找到 `firtool`、OpenSTA/OpenROAD、`spdlog`、`nproc`。`~/eda_lib` 有 5 个 ASAP7 RVT/TT 标准单元 `.lib`，未见 SRAM 宏、LEF 或 GDS。[Ventus-env Dockerfile](https://github.com/THU-DSP-LAB/ventus-env/blob/main/Dockerfile)下载的是 Linux x86-64 版 `firtool`，因此首选 x86-64 Linux 主机；本机 `linux/amd64` 容器需先验证仿真与编译兼容性，构建墙钟不用于比较硬件性能。

### `${REMOTE_USER}@${REMOTE_HOST}` 只读盘点（2026-09-23）

`ssh ${REMOTE_USER}@${REMOTE_HOST}` 可连接到 Ubuntu 24.04 x86-64，约 31 GiB RAM、当前根分区剩余约 15 GiB。远端非交互 SSH 的默认 PATH 很短；交互 Bash 中存在 Linuxbrew OpenJDK 21.0.11。正式脚本应显式设置 JDK 和工具路径，避免因 shell 类型改变而误判缺失。

| 已找到 | 路径 / 版本 | 用途或限制 |
|---|---|---|
| Chisel 工程和缓存 | `~/project/hardware-exp` 使用 Mill/Chisel 7.0.0；Coursier 已缓存 Chisel 7.0.0 | 证明该机曾配置 Chisel 项目；Ventus 指定 Chisel 6.4.0，仍需下载其对应依赖并验证生成 |
| 综合/仿真工具 | `~/oss-cad-suite/bin/yosys` 0.64+308、`verilator` 5.049 devel、`iverilog`；`~/opt/opensta/bin/sta` 3.1.0 | 可用于 RTL 及单元级流程；Ventus 推荐 Verilator 5.034，版本兼容性待跑基线确认 |
| ASIC 库 | `~/project/eda_lib` 的 5 个 ASAP7 RVT/TT `.lib` | 标准单元库；未见 SRAM 宏、LEF/GDS 或其他 PVT 角 |
| 系统包 | `g++`、CMake、GNU Make、`nproc`、`libfmt-dev`、`zlib1g-dev` | 未发现 `libspdlog-dev`、`firtool`、Ninja 或 OpenROAD |
| 其他 GPU 工程 | `~/simple-gpgpu` 有 SystemVerilog RTL、testbench、CModel 估计报告 | 与 Ventus 是不同工程；其报告自行标记为未校准估计，不能直接充当 Ventus/Break Layer PPA |

盘点时尚无 Ventus 或 Ventus-env 克隆。考虑剩余磁盘空间，P0 优先使用固定提交的 Ventus 主仓库及现成 testcase；完整 Ventus-env、编译器与数据集待估算空间后再部署。部署结果如下。

### `${REMOTE_USER}@${REMOTE_HOST}` 部署与构建记录（2026-09-23）

- Ventus 克隆在 `${REMOTE_PROJECT_ROOT}`，提交 `681172541a8a34ffb43c483a19c075acbc11a4eb`，16 个递归子模块均已检出。源文件工作树干净；生成物由上游 `.gitignore` 排除。`make -C sim-verilator verilog` 成功，得到约 20 MB 的 `sim-verilator/dut.v`，SHA256 为 `9eb262d75b8d1d96fe4ffde0f3d451409dbd8b12ee3990b34638984ed5864c17`。`parameters.json` SHA256 为 `1d1c88fee2dd80200147c35415322878dcd47167bc8b896bd7d661e39552fe06`，其中 `NUMBER_CU=2`、`WF_COUNT_MAX=8`。此步调用缓存的 `firtool` 1.62.0，进程一度占用约 25 GB 常驻内存并使用交换空间；全芯片扫描需控制并发。
- [OpenROAD 发布的 ASAP7 SRAM 仓库](https://github.com/The-OpenROAD-Project/asap7_sram_0p0)克隆在 `${REMOTE_LIBERTY_ROOT}/asap7_sram_0p0`，提交 `9f5af0939e8dd3cc1a9693a50b23441691dd7d25`。含 36 个宏变体的 Liberty、LEF 和同步行为 Verilog，以及 3 个 bank GDS；不能据此推断 36 个变体都有逐一对应的完整 GDS。示例 `srambank_128x4x32_6t122` 为 512×32 bit，LEF 尺寸 16×43.2、Liberty 面积 691.2，标称 0.7 V、25 °C。其 `cell_leakage_power : 0`，不能作为 SRAM 漏电实测值；内部功耗表也须核对事件定义后才能推算每次读写能量。
- 原始 SRAM Liberty 中 12 个 `128x4x*` 宏的地址类型声明 `bit_from=8, bit_to=0, bit_width=8`，Yosys 0.64 会拒绝读取。原仓库保持不变；修正副本在 `${REMOTE_LIBERTY_ROOT}/asap7_sram_yosys_compat/LIB`，仅把这 12 处 `bit_width` 改为 9。转换脚本 `${REMOTE_LIBERTY_ROOT}/normalize_asap7_sram_lib.py` 和 `manifest.json` 保存每个原件、副本的 SHA256 与改动记录。36 个副本均通过 Yosys `read_liberty -lib`，示例宏还通过 OpenSTA `read_liberty`；行为 Verilog 通过 Icarus 语法读取。这些检查不等于宏功能、读写能量或物理时序已被验证。
- `${REMOTE_ENVIRONMENT_SCRIPT}` 固定 JDK、OSS CAD Suite、OpenSTA、SRAM 路径和用户目录安装的 `spdlog` 1.12.0。后者依赖系统 `fmt` 9；脚本设置 `SPDLOG_FMT_EXTERNAL`，并只从 Linuxbrew 引入 LZ4 头文件和库，避免链接到其不兼容的 `fmt` 12。现有 Verilator 5.049 把上游 `--trace-threads` 弃用提示视为致命警告，脚本加入 `-Wno-DEPRECATED`。未修改 Ventus 上游源码。
- 在 `sim-verilator` 下执行 `make -j 4 VLIB_NPROC_CPU=4` 已成功构建 `build/libVentusRTL/debug/libVentusRTL.so` 与 `build/driver_example/debug/sim-VentusRTL`。Verilator 报告 293 个模块、488 个生成 C++ 文件，构建墙钟约 171 s；驱动 `--help` 正常。构建日志位于 `${REMOTE_HOME}/project/ventus_verilator_build.log`，完整调试构建物约 3.7 GB。验证 `ldd` 显示 `fmt.so.9`、用户目录 `spdlog.so.1.12` 和 Linuxbrew `liblz4.so.1`。
- 功能烟雾测试使用仓库原有 `vecadd_32b8w8t.{metadata,data}`，运行目录 `${REMOTE_HOME}/project/ventus-smoke/vecadd-32b8w8t`。驱动默认 200,000 时间单位上限会提前结束但仍返回 0；设 `--sim-time-max 2000000` 后日志记录 `kernel0 vecadd finished` 于 1,177,445 单位，仿真于 1,227,445 单位结束。追加 `--dump-mem 0x90002000,0x90002FFC` 后，1024 个 FP32 输出均为 `0x44800000`（1024.0），与测试文件的 `i + (1024-i)` 一致。原始输出见 `sim-2m-dump.stdout.log`。日志另有一条 `PMEM page at 0x80003000 not allocated, read as all zero`；需要判断其是否是无害预取，不能把本次单一用例扩展解释为全设计正确性或性能测量。
- 容量上，默认 `sharedmem_depth=1024`、32 lane/bank、每 bank 32 bit，恰与 `srambank_256x4x32_6t122` 的 1024×32 bit 相同。但 Ventus `SharedMemory` 实例化的 `SRAMTemplate` 带字节写掩码、独立读写端口和写旁路；所下载宏的行为 Verilog 只有单个读写互斥端口、整字写。故容量匹配不能直接视为可替换的实现或准确的面积/延迟点，P1 须测真实端口活动并明确外围逻辑、复制或时分方案。

远端最小入口：`ssh ${REMOTE_USER}@${REMOTE_HOST} 'source ${REMOTE_ENVIRONMENT_SCRIPT}; cd ${REMOTE_PROJECT_ROOT}; make -C sim-verilator verilog'`。构建仿真器时限制并发：在 `sim-verilator` 目录运行 `make -j 4 VLIB_NPROC_CPU=4`。testcase 的完成状态与输出正确性须单独记录；驱动返回码 0 并不保证 kernel 已完成。

| 优先级 | 依赖 | 用途与安装/选择原则 |
|---|---|---|
| 必需：默认 RTL 基线 | 可用 JDK、仓库 `./mill`、递归子模块；Linux 构建环境、Verilator、`spdlog`、`fmt`、C++ 构建工具 | Ventus 官方 `ventus-env` 推荐 Ubuntu 24.04、至少 32 GiB RAM、Verilator 5.034；本机 5.052 需做兼容性验证。现有 `sim-verilator/verilate.mk`使用 `nproc`、`.so`、`-latomic`，首轮优先在 x86-64 Linux 环境运行。 |
| 必需：本项目 kernel | Ventus 编译器/POCL/driver 或可复现的预编译 kernel 与 `.metadata`/`.data` | 既有 testcase 可直接作 smoke；新 OpenCL kernel 需要 Ventus 软件栈。`ventus-env` 提供 Spike、RTL 与 cycle simulator；其说明指出当前 RTL 仿真不支持 DDR timing。 |
| 必需：有物理口径的面积/能量 | ASAP7 标准单元 Liberty；OpenSTA；同技术条件下的 SRAM 面积、读写能量和漏电锚点 | 现有 `.lib`可用于标准单元映射，缺 SRAM。若无兼容 SRAM 宏，用参数区间与敏感性分析；不可将跨工艺的 CACTI 数字直接当作 ASAP7 测量。 |
| 后续：更稳健的时序 | ASAP7 其他 PVT 角、时钟/IO SDC、必要的负载假设 | 首轮 TT 的综合后时序是无布线估计。开放频率变量或宣称时序裕量前补不同工艺角。 |
| 特定 Verilog 路径 | CIRCT `firtool` | 默认仿真 Verilog 生成已由 Chisel 自动调用缓存的 1.62.0 版。Ventus 的 `make fpga-verilog` 另在 shell 中直接调用 `firtool`；若走该路径还须显式配置 PATH。 |
| 后续：布局布线 | 完整 ASAP7 平台 LEF/宏视图、OpenROAD flow | 可帮助校准拥塞、连线与时钟，但不作为首轮采集和课程题目建模前置条件。 |

## 6. 执行顺序与阶段产物

| 阶段 | 动作 | 产物/继续条件 |
|---|---|---|
| P0 | 优先在 `${REMOTE_USER}@${REMOTE_HOST}` 的隔离目录跑默认 Ventus 三类 testcase，核对子模块提交与仿真输出 | 可复现 baseline、工具与环境清单；若失败，保存完整错误并只修环境兼容性 |
| P1 | 对 FP32 tensor core、RF、shared memory、CTA 做模块测试与参数扫描 | 参数—周期—活动—面积表，数值/协议检查；明确哪些参数在原实现中耦合 |
| P2 | 编译并执行代表性 Transformer kernel，加入事件计数器；对 SRAM/NoC/DDR 做范围分析 | 相同 kernel 的多硬件比较与瓶颈归因；至少三种结构取向有合法且可核对的测点 |
| P3 | 将可审计组件表接到新版本 Break Layer GPU 成本模型，重跑搜索难度和基线 | 新 config/instance/code hash、结果目录、有效上界与可行分数；更新实践规范、推导、需求验收及 research brief |

**当前只完成 P0 的一个 `vecadd` 功能烟雾测试，尚未完成基线采样。** 下一步在相同 RTL/工具条件下跑 `matadd` 与 `wmma484fp32`，为三个 kernel 各建独立目录，记录输出和完成周期；先核对 `PMEM` 警告来源，再采集多次运行与事件计数。随后开展 P1 的 shared memory 端口适配、RF/CTA/tensor 模块测试与面积锚定。该计划不预设哪一组 GPU 参数会赢，也不把 RTL 周期、综合面积或解析 NoC 延迟描述成芯片实测。
