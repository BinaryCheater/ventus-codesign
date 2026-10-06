# Ventus GPU 的设计变量与性能建模

更新日期：2026-10-06。尺寸统计以主分支提交 `6811725` 为基准，相同 SM、相同 lane 使用同一套配置；低精度实现另查公开开发分支。

## 可以开放多少设计自由度

**现有常用尺寸入口约二三十项；小范围解绑的完整方案约 40 项硬件设置。**首轮固定四个复杂入口后，约有 35 项参与搜索；再开放 6–10 组已有队列深度，可达到约 40–45 项硬件变量。这些是下面具体改造方案的估计，尚未完成 RTL 修改与功能验证。

完整源码提取还包括 **82 项硬件数量、容量、宽度和端口设置，以及 62 处缓冲容量设置**。这些是按部件用途列出的候选：有的仍由同一个参数控制，有的需要更换实现才能开放。其中 18 处缓冲当前深度为 0；把直连改成队列会改变流水连接，不宜全部放进小范围改造。完整提取统计保留在详情文件中。

对当前研究，更值得优先开放的是计算宽度、驻留资源、供数能力和在途容量的配比。调度、背压、同步等规则仍需进入性能模型，可先保持源码的实现。

## 当前 Chisel 自身能参数化多少

**现有源码的常用尺寸入口在二三十项这个规模。**本轮从接入路径整理出下面 26 个入口：22 个来自顶层参数，4 个来自 ICache 配置。这里统计修改现有参数或构造配置就能传入的尺寸；已经验证能正常生成、运行的配置范围，还需要生成和功能回归来确认。

| 部分 | 现有入口 |
|---|---|
| 整体与驻留（5） | SM 数、cluster 数、每 SM warp 数、warp 线程数、WG 槽数。 |
| 前端（2） | 每次取指的指令数、每 warp 指令包队列深度。 |
| LSU（1） | 每 warp 在途访存上限。 |
| DCache（6） | set 数、way 数、line 的 word 数、MSHR 数、每 miss 合并目标数、写请求记录数。 |
| ICache（4） | set 数、way 数、MSHR 数、每 miss 合并目标数；默认值部分沿用 DCache，可在 ICache 构造配置中分别指定。 |
| 共享内存（1） | 存储行数。 |
| L2（5） | slice 数、set 数、way 数、存储更新粒度、用于计算记录池容量的 `memCycles`。 |
| CTA 分配（2） | 待分配 WG 表深度、资源表保留空闲段数。 |

入口见[顶层参数](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala)和[ICache 配置](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheParameters.scala)。这是一份常用尺寸清单，未把调试、编码宽度、可选 MMU 和 AXI 配置全部纳入。

**自由度受绑定和写死的接线限制。**寄存器容量、collector 数和部分在途容量跟随 warp 数；ALU/MUL/FPU 共用物理 lane 数；共享内存 bank 数跟随线程数；TC 形状按线程数选择。分别研究这些资源，需要修改现有公式或连接。寄存器虽有 `num_bank`，写回 bank ID 仍有写死的 2 位表示，扩展 bank 数需要配套修复；存储读写端口数也没有统一配置入口。

还要排除无效入口：当前流水线使用 `Issue`，`num_issue` 作用于另一个未接入的 `IssueV2`；`l2cache_portFactor` 也没有在当前存储中生成对应数量的端口。只改这些数，不会得到更多发射或访存吞吐。

因此，现成参数化适合先研究资源规模和 cache 几何。分别调整计算单元宽度、增加端口、改变存储 bank 并行服务能力、比较流水或低精度方案，需要继续改造 RTL。后面的 82 项尺寸和 62 处缓冲列出了更广的研究空间。

## 小范围解绑：约 40 项硬件设置从哪里来

**建议扩展已有结构的尺寸和配比。**ALU、MUL、FPU 的实现已经区分逻辑线程数与物理 lane 数，并支持分轮处理；顶层把三者接到同一个 `num_lane`。因此，分别传入三个物理宽度，是较有希望以局部修改开放的自由度。[执行模块](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L164)、[接入位置](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L77)

| 扩展部分 | 拟开放的设置 | 相对现有 26 项的增量及修改范围 |
|---|---|---|
| 驻留、供数和访存 | VGPR 容量、SGPR 容量、collector 数、LSU 总在途记录数、每 WG 的 warp 上限 | **+5**。拆开与 warp 数的绑定，配套核对地址位宽、请求 ID、分配表和 barrier 表示。 |
| 执行资源比例 | ALU、MUL、FPU 的物理 lane 数；SFU 的物理宽度 | **+4**。复用已有分轮结构及 SFU 接入，保留发射和写回组织。 |
| 寄存器 bank | 标量和向量寄存器共用的 bank 数 | **+1**。修复固定 bank ID 和相关索引；先保留每 bank 的读写端口数。 |
| L2 在途资源 | MSHR 数、后续请求共享记录池、写数据链表数、写数据 beat 池 | **净 +3**。用四个容量替换目前统一推导它们的一个 `memCycles` 入口；外存延迟单独给定。需检查池间容量关系和极小配置。 |

这份方案共有 **26 + 5 + 4 + 1 + 3 = 39 项**，即约 40 项硬件设置。它是待实现的配置清单，合法取值之间存在约束。首轮固定 warp 宽度、cache line、L2 存储更新粒度和 cluster 数这四个入口后，剩 **35 项**；若再固定其它尚未验证的入口，数量相应减少。新增约 6–10 组已有队列深度后，可达到约 **40–45 项参与搜索的硬件变量**。队列的数据、控制和 mask 要配套调整，不把每处缓冲都拆成独立变量。

局部改动仍要检查代码中的隐含绑定。例如 collector 分发中的单资源特殊分支目前判断 `num_warp == 1`；解绑 collector 后应根据实际 collector 数核对这一条件，避免单 collector 时某类指令持续得不到服务。寄存器的标量和向量地址共用由 VGPR 容量计算的位宽，也要拆开核对。这些是局部表示或控制条件的修复候选，尚未经过仿真。[collector 与寄存器代码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L464)

**比例可以成为自由度，但不要重复计算同一选择。**固定逻辑 warp 为 32 线程时，可分别选择 ALU/MUL/FPU 为 8、16 或 32 lane，处理轮数为 4、2 或 1。选 lane 数或选处理轮数都能表达这个自由度；另一个按公式计算。寄存器容量与 warp 槽数则可以分别选择，从而改变每个驻留 warp 可获得的资源。尺寸规则包括整除、2 的幂、上下界、地址可表示性和协议匹配；并非所有地方都只要求整除，也不必在研究初期支持所有整数。

增加真实存储端口、重新组织共享内存 bank、多发射、多套执行单元、TC 形状与精度切换，应作为后续阶段。它们涉及仲裁、返回路径、供数、软件 fragment 或指令语义，验证成本明显高于上述解绑方案。

## 软件自由度与几天内的验证范围

软件侧可以先加 **8–10 项有实际代码生成路径的选择**：tile 的 M/N/K、每 WG 的 warp 数、循环顺序、寄存器 blocking/展开方案、共享内存使用方案、数据布局，以及有实现支持的融合或分阶段方案。资源占用从编译产物及实际布局提取；寄存器和共享内存需求与硬件容量共同决定驻留和等待。初期用现有 OpenCL/LLVM 工具链和可生成的 kernel 模板，后续再接 MLIR。

现成参数化足以建立第一条闭环；研究计算、供数、驻留与访存之间的资源分配时，以上解绑更有价值。变量数量本身不能保证题目难度或搜索价值：如果程序几乎只使用固定TC，其它执行宽度可能很少影响结果。应让workload覆盖实际参与优化的资源，并在固定预算下体现容量、吞吐和并发之间的取舍。

**如果工具链和 RTL 仿真环境已能运行，几天内完成第一批解绑和一个小型优化闭环有希望；全部约 40 项配置的可靠开放，需要按测试结果扩展。**建议先跑通匹配版本的 RTL、编译器和运行时，再按模块修改，保留默认配置回归。几天内优先验证计算宽度、寄存器容量、collector 与 LSU 在途容量；bank 和 L2 池的扩展可按剩余时间推进。

验证应分成三个层次：①生成与局部功能检查，覆盖小尺寸、位宽边界、bank 冲突、背压、barrier 和资源释放；②从 RTL 提取周期规则，与少量不同硬件配置和短 kernel 做差分核验，并用未用于调试的配置检查预测误差和方案排序；③在同一资源预算下，比较原有绑定、解绑后仅硬件优化、仅软件优化和联合优化，最终候选再回到 RTL 验证。预算未经综合校准时，应称资源预算或成本代理。

AI 可以协助追踪参数用途、修改位宽、生成配置与测试、定位差分失败。功能正确、性能模型准确和优化有收益需要分别提供证据。C++/SystemC 模型也要核对版本和参数覆盖：模型中的固定 lane、容量或延迟不会随着 RTL 修改自动更新。首轮结论宜限定在已验证的硬件配置和 workload 范围，逐步扩大。

## 82 项硬件尺寸具体包含什么

每行按一个模块归并；括号中的数量对应完整列表。WG 指线程块，collector 指操作数收集单元；MSHR 用来记录尚未完成的 cache miss。

| 模块 | 尺寸、数量和宽度 |
|---|---|
| 整体组织与驻留（9） | SM 数、cluster 数；每 SM 的 warp 槽数、WG 槽数，每 WG 的 warp 上限；warp 线程数；向量寄存器槽数、标量寄存器槽数；共享内存行数。 |
| 线程块分配（5） | 待分配 WG 表深度；资源表保留的空闲段数；每周期检查的 SM 数；每组资源管理器负责的 SM 数；warp 派发宽度。 |
| 取指、分发与分支（7） | 每次取指的指令数；取指请求宽度；每 warp 的指令包拆分宽度、拆包暂存容量；标量、向量类指令各自的分发宽度；每 warp 的 SIMT 栈深度。 |
| 寄存器供数与写回（11） | 标量、向量寄存器各自的 bank 数及每 bank 读、写端口数（6项）；collector 数及标量、向量输出通道数（3项）；标量、向量写回通道数（2项）。 |
| 普通执行单元（7） | 标量 ALU 数；向量 ALU、MUL、FPU 各自的物理 lane 数；SFU lane 数；整数除法单元数；浮点除法/开方单元数。 |
| Tensor Core（4） | 每 SM 的 TC 数；输出矩阵的两个维度 M、N；点积归约维度 K。 |
| 访存发起与返回（4） | LSU 在途 warp 指令记录数；每 warp 在途访存上限；地址计算/发起通道数；全局访存合并粒度。 |
| L1 指令缓存（7） | set 数、way 数、line 大小；独立 miss 记录数、每个 miss 可合并的请求数；读、写端口数。 |
| L1 数据缓存（9） | set 数、way 数、line 大小；读、写端口数；独立 miss 记录数、每个 miss 可合并的请求数；未完成写请求记录数；dirty 记录粒度。 |
| 共享内存访问（4） | bank 数、每行 word 数；每 bank 读、写端口数。容量还由上面的行数决定。 |
| L2 缓存（14） | slice 数、每 slice 的 set 数及 way 数、line 大小；目录读/写端口数、数据读/写端口数；接口 beat 大小、存储更新粒度；MSHR 数、后续请求共享记录池容量、写数据链表数、写数据 beat 池容量。 |
| 下层互连（1） | 每次传输的有效数据大小，即 beat 大小。 |

## 62 处缓冲容量具体包含什么

这里数的是不同用途的缓冲位置；相同 lane 内重复的队列使用同一个深度设置。

| 所在位置 | 要设置深度的缓冲 |
|---|---|
| 线程块分配与回收（7） | 分配器到 SM 接口、资源回收、LDS/标量寄存器/向量寄存器基址、CTA 派发、warp 完成回报。 |
| 前端与分支控制（7） | 每 warp 指令包及 mask；SIMT 的分支控制、if mask、重汇合 PC、跳转结果；标量分支和 SIMT 分支返回的两个汇聚输入。 |
| 发射与写回（14） | 标量、向量发射入口（2处）；标量写回的 ALU/FPU/LSU/CSR/SFU/MUL 输入（6处）；向量写回的 ALU/FPU/LSU/SFU/MUL/TC 输入（6处）。 |
| 执行结果与 SFU 输入（11） | 标量 ALU 的结果和分支；向量 ALU 的结果和比较结果；MUL 的标量、向量结果；TC 结果；SFU 的输入及标量、向量结果；CSR 结果。 |
| FPU 与 TC 内部（5） | 普通 ADD 到共享加法器、MUL 到共享加法器的数据与控制；乘法结果、加法结果；TC 点积结果。 |
| LSU、L1 与共享内存（14） | LSU 输入；ICache 外存返回；DCache 的核心请求/响应、下层请求/响应、响应有效位与数据暂存、请求控制及第二级响应/命中暂存（9处）；DCache MSHR 的探测和 miss 返回（2处）；共享内存响应。 |
| L2 与互连（4） | L2 写缓冲、目录结果、SinkA 输入；SM 到 cluster 的访存请求。 |

## 尺寸之间有哪些重要关系

| 关系 | 建模时怎样表达 |
|---|---|
| cache 几何与容量 | `容量 = set数 × way数 × line字节数`。三个尺寸确定后，总容量按公式计算；地址切分和下层传输也随之确定。 |
| 地址和传输的尺寸限制 | 当前实现的位切分依赖特定尺寸，例如 L2 的 set 数、line 和 beat 大小要求为 2 的幂，beat 不超过 line。部分路径还依赖一条 line 一次传完；扩大 line 或缩小 beat 时需修改对应协议。 |
| 驻留资源与并发 | 一个 WG 要同时获得 warp 槽、寄存器和共享内存。可驻留 WG 数受各资源共同限制；连续空间不足也会妨碍分配。 |
| 当前源码中的绑定 | `num_warp` 同时影响 warp 槽、寄存器容量、collector 等；向量 ALU、MUL、FPU 共用 lane 数；部分 ICache 尺寸继承 DCache 设置。研究资源配比时，可把绑定拆开，再添加兼容约束。 |
| 逻辑线程数与物理 lane 数 | warp 宽度决定一条指令覆盖多少线程，物理 lane 数决定同时处理多少线程。当前相关执行单元要求前者能被后者整除，处理轮数随两者变化。 |
| 端口、通道与执行吞吐 | 增加算术 lane 后，寄存器读端口、collector、发射和写回仍可能限制吞吐。要分别表示资源竞争。 |
| 缓冲与流水连接 | 同一请求的数据、控制和 mask 必须保持对应；部分队列的深度需要配套调整。深度为 0、直通和寄存一级会改变停顿及组合路径。 |
| L2 的记录池 | 部分容量由源码的 `memCycles` 算出。若单独优化硬件容量，应明确拆开这层绑定，外存延迟按外存模型给出。 |

## 其它细节：哪些值得设为设计变量

性能模型需要知道运行规则；其中哪些允许优化，可以另行选择。

| 内容 | 可采用的处理方式 |
|---|---|
| 依赖、背压和同步 | 操作数未就绪时等待、队列满时阻塞、返回数据收齐后完成、barrier 等待线程。通常固定这些规则，等待周期由程序和资源竞争产生。 |
| 调度和仲裁 | warp 取指/发射顺序、寄存器 bank 竞争、写回优先级、cache 和互连仲裁。先保留实际规则；要比较策略时，每个位置选择少数完整算法。 |
| 共享内存同地址广播 | 可以作为一个硬件技术选择。主分支当前[逐个处理冲突请求](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/BankConflictArbiter.scala#L184)，广播实现会改变冲突次数和成本。 |
| 算术与流水组织 | FMA/ADD 是否共用加法器、除法器算法、流水切分和队列直通方式。宜选择一套完整实现，再由实现确定资源和时序，避免把同一结构的每个内部开关都单列。 |
| cache 行为 | 替换算法、写回/直写、写入分配、miss 合并方式。可固定，也可作为离散方案；流量、缓冲和成本需与方案一致。 |
| 可选模块及扩展 | MMU/TLB、不同计算精度、稀疏或其它加速技术。启用后再描述相应尺寸与行为；需要对应的实现和软件使用路径。 |

例如选用共享加法器后，ADD 和 FMA 的竞争等待应由请求顺序算出。把“共享开关”“冲突延迟”“吞吐率”都允许独立选择，会产生互相矛盾的硬件配置。

## Ventus 有低精度 core 吗

**有低精度 Tensor Core 的公开 RTL 实现，但需要明确版本。**本轮尺寸统计使用的主分支基准与开发分支不同。

| 版本或证据 | 核实到的能力 |
|---|---|
| 主分支 `6811725` | 普通向量 FPU 和 Tensor Core 都按 FP32 接入，分别实例化 `VectorFPU(8,24,…)` 和 `TensorCoreFP32`。[接入代码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L122) |
| 开发分支 `dev-tc-v2`，提交 `159b877` | 流水线[接入 `vTCexe_mix`](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/159b87756687d16b8247e5ff3fe97d9db04ae17e/ventus/src/pipeline/pipe.scala#L110)，连接 FP16 TC。输入按 16 位拆包，点积使用 5 位指数、11 位有效精度，当前选择 FP16 加法结果。[计算阵列](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/159b87756687d16b8247e5ff3fe97d9db04ae17e/ventus/src/TensorCore/Tensor.scala#L639) |
| 同分支的混合精度路径 | 模块内存在 FP16 点积结果转 FP32、再与 FP32 的 C 相加的路径。但顶层把 `isMixedPrecisionMode` [固定为 `false`](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/159b87756687d16b8247e5ff3fe97d9db04ae17e/ventus/src/pipeline/execution.scala#L271)，当前接线没有启用该模式；其数值行为也需要进一步核对。 |
| 官方 MICRO 2025 教程，第14–16页 | 介绍多精度 TC，包括 FP16、INT8/INT4、FP8/FP6/FP4、MX 格式及稀疏能力。[官方教程](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/docs/Ventus_MICRO2025_tutorial_English.pdf)；本轮尚未逐项核实这些能力的完整接线和测试。 |

扩大到低精度 Ventus 时，需要明确**输入格式、累加格式、打包方式、各格式的物理并行度、阵列形状及算术资源复用方案**。这些选择会改变访存量、寄存器供数、运算量和时序，不能仅用一个“FP16 性能乘二”系数处理。上面的尺寸数量尚未重算开发分支；普通向量 FPU 的低精度支持也需要另查。

## 距离准确性能预测还缺什么

这些变量可作为参数化模型的起点，准确率仍要验证。程序侧至少需要指令依赖、各 lane 的地址、活动 mask、分支结果和同步关系，才能重现供数、访存合并、bank 冲突及等待。

当前 Ventus 仿真外存采用简化处理，[没有完整 DDR 时序](https://github.com/THU-DSP-LAB/ventus-env)。预测实际设备时还需要外存组织、控制器行为和时钟频率；修改容量、端口或流水后，频率也可能变化。本轮完成的是源码提取，尚未建立或验证性能模拟器。

## 现成模拟器和软件栈

官方已有 [C++/SystemC 周期模型](https://github.com/THU-DSP-LAB/ventus-gpgpu-cpp-simulator)，[ventus-env](https://github.com/THU-DSP-LAB/ventus-env) 可用 `cyclesim` 后端运行，支持 DDR 时序。模型混合使用延迟事件和逐周期唤醒。2026-10-06的配套版本测试已发现计算时序、缓存与驻留资源差异，当前不能直接作为RTL性能评分器；新模型应从RTL提取规则，仿真用于核验，见[测试与源码建模结论](../ventus_flow_20261006/report_cn.md)。

当前完整应用路径以 OpenCL 为主：主机通过 ocl-icd 调用 PoCL，PoCL 管理 kernel、参数与缓冲区，调用 Ventus 驱动；设备程序由定制 Clang/LLVM 后端和 libclc 编译链接为 Ventus ELF，交给 Spike、SystemC 或 RTL 后端执行。[编译和链接流程](https://github.com/THU-DSP-LAB/llvm-project#412-compile-step-by-step)

| 入口或编译设施 | 当前状态 |
|---|---|
| OpenCL | 已提供编译器、运行时、驱动和测试，是最完整的公开运行路径。 |
| LLVM IR / 汇编 | 官方文档提供直接输入 LLVM IR、汇编的编译流程。可复用现有后端，但仍需满足 Ventus kernel ABI、地址空间和启动约定。 |
| PyTorch | 官方 [ventus-pytorch](https://github.com/THU-DSP-LAB/ventus-pytorch) 提供后端接入和小模型推理示例，README 记录 GPT-2、Pythia、Qwen 的验证及数值稳定性限制；本轮未复现这些结果。 |
| MLIR / Triton | 本轮未找到官方可直接使用的 Ventus 专用后端。LLVM fork 包含上游 MLIR 目录；[默认构建](https://github.com/THU-DSP-LAB/ventus-env/blob/7e9790708d58ebf697d74fa8dadbaafa1232ca1d/build-ventus.sh#L158)启用 clang、lld、libclc，没有启用 MLIR。 |
| Ventus ELF → PTX | 官方 [SBT 原型](https://github.com/THU-DSP-LAB/ventus-gpgpu-sbt-simulator)将 Ventus 程序翻译到 NVIDIA GPU 执行，适合另行研究功能执行；该路径不能直接给出 Ventus 硬件周期。 |

**MLIR 可用于我们的高层软件结构选择，但需要补目标接入。**一种路线是从算子和循环出发，在 MLIR 中选择 tile、融合、布局和线程映射，再生成符合 Ventus 约定的 LLVM IR，复用已有 LLVM 后端及驱动。线程 ID、地址空间、barrier、SIMT 分支和 TC 指令都要明确降低方式；仅指定 RISC-V target 不足以完成这些工作。这是建议的研究路线，本轮没有找到已经完整接好的现成实现。

[详情：当前值、尺寸公式和源码位置](${ORIGINAL_PROJECT_ROOT}/analysis/ventus_variable_audit_20261003/source_details_cn.md)

[硬件流程：平台选择、分层验证与两天内跑通的范围](${ORIGINAL_PROJECT_ROOT}/analysis/ventus_flow_20261006/report_cn.md)
