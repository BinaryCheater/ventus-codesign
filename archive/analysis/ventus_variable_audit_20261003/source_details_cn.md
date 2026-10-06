# Ventus GPU 源码与完整参数列表

更新日期：2026-10-05。这里保留完整列表、公式和源码链接，供查证使用。结论和建议见 [主文档](${ORIGINAL_PROJECT_ROOT}/analysis/ventus_variable_audit_20261003/report_cn.md)。

## 分析所用的源码与文档


主仓库固定在 [`681172541a8a34ffb43c483a19c075acbc11a4eb`](https://github.com/THU-DSP-LAB/ventus-gpgpu/tree/681172541a8a34ffb43c483a19c075acbc11a4eb)，FPU子模块固定在 [`7ea30df00f9353f2e8645b32665b13f9b3f69e6d`](https://github.com/liuxd17thu/fpuv2/tree/7ea30df00f9353f2e8645b32665b13f9b3f69e6d)。阅读覆盖实际接线、CTA、前端、RF/collector、执行、LSU、L1/LDS、L2、互连及仿真边界。

官方文档包括 [`docs/ventus GPGPU architecture whitepaper v2.01.pdf`](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/docs/ventus%20GPGPU%20architecture%20whitepaper%20v2.01.pdf) 与 [`docs/Ventus_MICRO2025_tutorial_English.pdf`](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/docs/Ventus_MICRO2025_tutorial_English.pdf)。文档与代码有差异时，以接线和实现为依据。教程介绍的新版本能力需要分别查找对应实现，不能自动视为主分支已启用，也不能一概判定为未来规划。

另查公开开发分支 `dev-tc-v2` 的提交 [`159b87756687d16b8247e5ff3fe97d9db04ae17e`](https://github.com/THU-DSP-LAB/ventus-gpgpu/tree/159b87756687d16b8247e5ff3fe97d9db04ae17e)，用于核对低精度支持。下列尺寸和全量统计仍基于上述主分支；开发分支没有混入这些数量。

计数采用“用途不同的部件可以分别配置；相同部件采用同一套设置”。指令编码、由尺寸算出的位宽和运行时状态不自动算作设计变量。写死的容量照样列为可讨论的尺寸；当前同一个常数控制多项资源，也照样把不同用途拆开，并记录绑定。细节是否成为变量由研究范围决定。

表中列出的项目可以研究是否调整；当前RTL没有经过所有取值组合的验证。当前配置未做本次综合/板级性能测量；本次没有实现行为模拟器或运行新的Ventus性能实验。

## 统计的组成与范围

| 统计 | 组成 | 拆分原则 |
|---|---|---|
| 144 项尺寸候选 | 本文 S001–S082 共 82 项；Q001–Q062 共 62 处，其中 18 处当前深度为 0 | 按资源和缓冲用途提取，相同 lane/相同 SM 的重复实例不另计。保留源码绑定的不同资源；端口数量虽写死也单列。 |
| 209 项核心建模描述 | `inventory.json` 中 `scope=core` 且来源为 P/H/C：P=59，H=139，C=11 | P 指显式参数，H 指固定结构或规则，C 指时序关系/待校准项。是按模型需要描述的内容拆分，含尺寸、规则和时序；不代表 209 个可自由选择的数值。 |
| 278 项全部提取内容 | 核心 P/H/C=209；MMU=14；AXI=7；仿真封装及简化外存 P/H=6；外部设置 E=9；软件输入 W=12；派生量 D=13；排除项 X=8 | 外部与软件项按参数族或输入类别记录。例如外存组织是一族，访存地址是一类输入；这里没有逐位枚举所有地址。 |

尺寸表重新按用途拆分了部分原始描述，例如将标量与向量寄存器的端口分别列出；也纳入了当前由其它参数计算的 L2 容量。144 与 209 并非一一对应的两张同结构表。独立设计变量的数量需在选择实现、确定可解耦资源并建立合法性关系后统计。

## 当前 Chisel 的尺寸入口与限制

以下清单只包含核心接线能追到的常用尺寸输入，合计26项；表示源码中的配置位置，未表示所有取值组合都经过生成或功能验证。这里没有增加全量描述和尺寸候选的数量，同一尺寸按“已有配置入口”重新查看。

| 部分 | 参数名称 | 来源及限制 |
|---|---|---|
| 整体（5） | `num_sm`、`num_cluster`、`num_warp`、`num_thread`、`num_block` | `top/parameters.scala:7–9,27,53`；SM分组需整除，WG槽数受warp槽限制，线程宽度同时影响掩码、共享内存和TC。 |
| 前端（2） | `num_fetch`、`size_ibuffer` | `top/parameters.scala:38,45`；`ibuffer.scala:115–116`按尺寸实例化；fetch要求为2的幂，数据与mask队列共用深度。 |
| LSU（1） | `lsu_num_entry_each_warp` | `top/parameters.scala:67`；在途credit限制。总LSU记录数由`lsu_nMshrEntry=num_warp`确定，没有在此重复数为独立输入。 |
| DCache（6） | `dcache_NSets`、`dcache_NWays`、`dcache_BlockWords`、`dcache_MshrEntry`、`dcache_MshrSubEntry`、`dcache_wshr_entry` | `top/parameters.scala:71–90`；line宽度还影响访存合并、LDS和L2；改变相关大小须核对地址位切分和单beat依赖。 |
| ICache（4） | `ICacheParameters.nSets`、`.nWays`、`.nMshrEntry`、`.nMshrSubEntry` | [`ICacheParameters.scala:19–25`](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheParameters.scala#L19)；`MyConfig`通过ICacheParamsKey注入，默认set/way绑定DCache，可在现有构造配置中覆盖。 |
| LDS（1） | `sharedmem_depth` | `top/parameters.scala:93`；BlockWords和bank数另有绑定，此项控制行数。 |
| L2（5） | `num_l2cache`、`l2cache_NSets`、`l2cache_NWays`、`l2cache_writeBytes`、`l2cache_memCycles` | `top/parameters.scala:99–107,132`；`memCycles`控制多个记录池容量。本项表示实际使用的源码参数；具体生成入口、拓扑和池结构仍需验证。 |
| CTA（2） | `CTA_SCHE_CONFIG.WG_BUFFER.NUM_ENTRIES`、`CTA_SCHE_CONFIG.RESOURCE_TABLE.NUM_RESULT` | `top/parameters.scala:191,194`；分别为待分配WG表和空闲段摘要容量。 |

仍有其它局部构造参数、MMU及AXI配置，本节未枚举。26是上表的入口数，没有替代对源码整体参数化能力的完整验证。

| 另外可见的配置或结构 | 当前限制 |
|---|---|
| `num_bank` | RF和collector确实使用，但[`operandCollector.scala:593–594`](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L593)的写回bank ID固定2位。要支持更大的bank数，需要同时参数化这些表示及索引。 |
| `num_vgpr`、`num_sgpr`、`num_collectorUnit` | 分别使用`128*num_warp`、`256*num_warp`、`num_warp`。解耦可从这些定义入手，但寻址和分配表示要一起核对；SGPR存储深度按SGPR槽数分配，地址IO却共用从VGPR容量算出的`depth_regBank`。 |
| `num_lane`、`num_sfu`、`tc_dim` | 执行模块已有相应尺寸传入；顶层默认由线程数推导，多个FU共用参数。分别调整各FU需要修改接入和相关执行/写回规则；TC形状还受寄存器fragment和归约树约束。 |
| `num_issue` | [`pipe.scala:74–75`](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L74)实例化`Issue`；该参数用于另一个`IssueV2`类，修改它不会直接扩大当前发射宽度。 |
| `num_icachebuf`、`num_ibuffer` | 前者未追到核心硬件的有效容量用途；后者出现在未接入的`instbuffer`类。当前用的是`ibuffer2issue`中的`size_ibuffer`。 |
| `l2cache_portFactor` | 当前BankedStore没有用它生成更多读写端口，不能把它当成有效吞吐旋钮。 |
| 14项存储读写端口候选和62处缓冲 | 许多端口由固定的存储实例实现，队列深度分散在局部构造中；没有统一暴露成顶层参数。修改容量常数和增加真实并行端口需要分别处理。 |

实际使用时应冻结生成入口和软件配置，按所需尺寸做生成及功能回归。这里只完成静态接线核对，没有执行该配置矩阵。

## 小范围解绑方案的来源和验证边界

主文档的约40项方案是待实现的配置清单：现有26项入口，加驻留/供数/访存5项、执行宽度4项、RF bank数1项，再用四个L2容量替换一个统一推导入口（净增3），共39项。它不表示39项已通过参数化生成，也没有重新计算完整源码提取数量。固定warp宽度、cache line、L2存储更新粒度和cluster数四个入口后，剩35项；再增加6–10组队列深度，约有40–45项参与搜索。若还有入口被固定，按实际配置继续扣除。

| 拟解绑部分 | 当前源码事实 | 需要核对的内容 |
|---|---|---|
| VGPR、SGPR 容量 | `top/parameters.scala:20–22`分别使用`128*num_warp`、`256*num_warp`，共用`depth_regBank=log2Ceil(num_vgpr/num_bank)`。`resource_table.scala:660–665`已有分别传入LDS、SGPR、VGPR容量的handler和RAM。 | 资源分配算法已有按容量实例化的基础；拆开标量/向量地址位宽，检查基址、bank行地址、分配/回收、最高可用地址。不能仅凭存储行数推断所有地址可正确访问。 |
| collector 数 | `operandCollector.scala:529`按`num_collectorUnit`实例化；bank仲裁、crossbar及输出仲裁沿用该数量。`:464`的单资源特殊分支判断`num_warp == 1`。 | 核对条件是否应按collector数量选择；检查collector少于warp且标量/向量请求同时持续出现时的服务、公平性与进展。`:562`的`widReg`元素位宽也使用collector数，但本轮检索只找到该未使用声明，不能据此认定存在活跃路径上的warp ID截断。 |
| LSU 总记录数 | `top/parameters.scala:69`使用`lsu_nMshrEntry=num_warp`；LSU数据结构按记录数实例化，请求记录ID与warp ID有不同用途。 | 所有请求/响应中的记录ID位宽、credit、分配与回收需一致；分别测试重复访问、多个在途指令、返回背压与记录池满。 |
| 每 WG warp 上限 | `top/parameters.scala:55,144,179`将该上限传给CTA配置；`warp_schedule.scala:105–112`按其构造barrier和结束记录；`GPGPU_top.scala:501`还计算WG内warp ID宽度。 | 与SM驻留warp数分别配置，检查WG局部ID、期望到达数、最后一个warp完成与释放。单元素配置可能出现零位宽，首轮可只接受至少2的菜单。 |
| ALU/MUL/FPU 宽度 | `execution.scala:164–165,476–477,746–758`有逻辑/物理宽度和整除断言；`pipe.scala:77–82`三者共用`num_lane`。 | 增加三个输入并分别传入，验证部分轮次结果、mask、比较/分支、标量指令及写回背压；保留当前发射、共享写回通道和仲裁。分轮结构存在不等于全部宽度已验证。 |
| SFU 宽度 | `top/parameters.scala:91`由线程数推导`num_sfu`，执行模块按此数量实例化除法/开方相关资源。 | 首轮保留整数与浮点路径共享此宽度的关系；核对分轮、完成掩码和结果归并。不把各算术路径都另行拆成独立变量。 |
| RF bank 数 | `top/parameters.scala:18`已有共用`num_bank`；`operandCollector.scala:593–594`写回bank ID固定为2位，地址计算还有固定宽度的中间量。 | 先保留SGPR与VGPR共用bank数及每bank 1R1W；集中替换可由尺寸推导的宽度，核对移位、低位切分、非零宽度、容量整除和冲突仲裁。可先从2/4/8这类有限菜单验证。 |
| L2 四类记录池 | `L2cache/Parameters.scala:164–167`由`memCycles`及`blockBeats`计算MSHR、secondary、putLists、putBeats。 | 给四池加入显式容量，缺省仍复用原公式；外存时序独立设置。逐一检查使用点中的索引、链表、free list及可达完成路径；不能凭容量为正判定不存在死锁。 |

建议首轮固定逻辑warp宽度32、ISA/ABI、cache line与beat传输方案、端口数、发射和写回组织、TC实现与精度。容量和宽度使用有限离散菜单；整除约束只覆盖部分合法性，地址位宽、ID、协议、容量下界和配套数据/控制仍需检查。

物理lane数与分轮比例是同一个选择的两种表示。例如逻辑宽度32时，选择物理宽度8/16/32，轮数由`32/lane数`计算。按bank分配的容量需满足相应布局和寻址条件；每warp资源比例可由独立选择的总容量与warp槽数计算，是否满足程序占用由分配模型检查。

首轮候选队列扩展应从当前已有的正深度缓冲中选择约6–10组，例如指令包及mask、LSU入口、共享内存响应、若干执行结果和写回输入组。保持直通/pipe/flow语义，成对的数据与控制使用同一配置；避免同时开放62处或把当前零深度路径全部插入新队列。具体组数仍取决于接线审查和测试结果。

几天内闭环的前提是已有可运行工具链与仿真环境；当前未确认这一前提。需冻结匹配的RTL、compiler、driver及模拟器版本。现有`ventus-env`固定的RTL提交与本轮尺寸审计主分支提交不同，不能直接宣称已匹配。C++模型也需要追踪对应尺寸及固定延迟，扩展RTL入口不会自动改变SystemC模型。

建议每组补丁保留默认配置、单项变化、尺寸边界与少量交叉变化的功能检查；微程序至少覆盖高位寄存器地址、collector争用、分轮mask、资源耗尽/回收、barrier与返回背压。用短计算、访存、混合算术kernel建立周期锚点，保留未参与校准的配置和输入，分别报告绝对误差、排序错误与最终候选RTL周期。模型未覆盖的机制不要通过任意改延迟参数吸收。

优化比较采用同一预算、输入、工具链与评估成本：原有绑定、解绑后硬件优化、软件优化、联合优化。最终候选与强基线均回到同一RTL版本确认。资源成本未经过综合校准时，报告资源预算或成本代理；周期仿真结果不代表实际芯片的面积、时钟或功耗。软件选择先从现有OpenCL/LLVM生成路径出发，暂不把完整MLIR后端接入作为几天内闭环的前提。

## 软件入口和 MLIR 接入的核查范围

核对了官方LLVM工具链README、ventus-env构建脚本与子项目、官方仓库列表、LLVM fork的MLIR目标/方言目录，以及ventus-pytorch、SBT原型README。

- [LLVM README](https://github.com/THU-DSP-LAB/llvm-project)提供OpenCL C→LLVM IR→Ventus目标汇编/对象→ELF的流程，使用`riscv32`和`ventus-gpgpu`目标，链接crt0、libclc与workitem库；也支持输入自定义汇编。
- [ventus-env](https://github.com/THU-DSP-LAB/ventus-env)包含PoCL、ocl-icd和driver，并支持Spike、RTL和SystemC执行后端。host端运行时与device端编译是不同环节。
- [ventus-pytorch](https://github.com/THU-DSP-LAB/ventus-pytorch)公开小模型推理接入。README记录TF32/FP16/BF16模型验证，也记录FP16 KV-cache数值稳定性限制。此处仅引用作者记录，未运行复现，也未把该仓库所用RTL与本轮主分支基准等同。
- LLVM fork存在上游MLIR目录；检索其目标/方言目录未发现单独命名的Ventus后端。[ventus-env构建脚本](https://github.com/THU-DSP-LAB/ventus-env/blob/7e9790708d58ebf697d74fa8dadbaafa1232ca1d/build-ventus.sh#L158)启用clang、lld、libclc，未启用MLIR。本轮没有找到官方文档或测试证明Ventus专用MLIR/Triton端到端接入；这项结论限于公开资料和上述核查范围。
- [MLIR GPU文档](https://mlir.llvm.org/docs/Dialects/GPU/)说明目标代码生成与host启动转换需分别处理。给Ventus接入时要降低线程ID、地址空间、同步、SIMT控制及TC操作，并匹配ELF和kernel参数ABI。通用RISC-V目标不能自动补全这些GPU语义。
- [SBT原型](https://github.com/THU-DSP-LAB/ventus-gpgpu-sbt-simulator)方向为Ventus ELF→NVIDIA PTX，提供另一种功能执行路线，未描述为Ventus硬件的周期预测模型。

## 低精度实现的源码依据

| 核查对象 | 证据与判断 |
|---|---|
| 主分支普通浮点与 TC | `execution.scala:758` 构造 `VectorFPU(8,24,…)`；`:122` 构造 `TensorCoreFP32`。本轮基准为 FP32 接线。 |
| `dev-tc-v2` 的实际 TC 接入 | [`pipe.scala:110`](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/159b87756687d16b8247e5ff3fe97d9db04ae17e/ventus/src/pipeline/pipe.scala#L110) 实例化 `vTCexe_mix`；[`execution.scala:265`](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/159b87756687d16b8247e5ff3fe97d9db04ae17e/ventus/src/pipeline/execution.scala#L265) 构造 `TensorCore_MixedPrecision(8,8,8,16,…)`。模块不是只有类定义，已经接到执行流水线。 |
| FP16 计算路径 | [`MMA888_SMEM.scala:507`](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/159b87756687d16b8247e5ff3fe97d9db04ae17e/ventus/src/TensorCore/MMA888_SMEM.scala#L507) 将输入按 FP16 拆包；内部使用 `TC_ComputationArray_MixedPrecision(16,8,4,8,…)`。[`Tensor.scala:652`](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/159b87756687d16b8247e5ff3fe97d9db04ae17e/ventus/src/TensorCore/Tensor.scala#L652) 点积的格式为指数 5 位、有效精度 11 位（含隐含位），即 FP16。逻辑 MMA 为 8×8×8，内部 8×4×8 阵列分组处理；逻辑形状不等于每周期完成的运算量。 |
| 混合精度模式 | [`Tensor.scala:279`](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/159b87756687d16b8247e5ff3fe97d9db04ae17e/ventus/src/TensorCore/Tensor.scala#L279) 有 FP16→FP32 转换、FP32 最终加法和 FP16 最终加法。点积乘法及归约树先使用 FP16，再按模式选择最终加法；这与全程 FP32 点积累加有数值区别。`execution.scala:271` 把模式固定为 false，目前顶层走 FP16 结果路径。完整混合精度语义与功能正确性尚未做运行验证。 |
| INT8/INT4 复用类 | 同分支存在 `TC_ComputationArray_848_INT8FP16_Reuse`、整数乘法及位扩展代码；本轮检索未在上述接入路径找到该阵列的实例化。类或运算代码存在，尚不足以说明当前顶层可执行这些格式的指令。 |
| 官方教程范围 | MICRO 2025 教程第14–16页介绍多精度、不同 MMA 形状、MX 格式及稀疏能力。本轮只对上面的 FP16 接线路径作了静态核查，其余能力需逐项定位版本、控制信号、数据通路和测试。 |

若纳入低精度设计，需要分别确定输入/输出与累加格式、格式打包、实际物理并行度、逻辑 MMA 形状和物理阵列形状、算术资源复用及格式切换规则。新增变量数量取决于支持的具体实现；本轮没有给这些扩展编造统一总数。

## 硬件数量和大小的完整列表


优先级较高的是驻留资源、RF供数、物理lane、TC形状、缓存几何及在途容量。端口数属于尺寸，但不同端口组织需要选择匹配实现；L2派生池则值得与名义 `memCycles` 解耦。此处刻意单列不同角色，不沿用源码所有绑定。

| 编号 | 尺寸 / 数量 | 源码默认值 | 尺寸规则、耦合及开放条件 | 证据 |
|---|---|---|---|---|
| S001 | SM 数量 | 2 | 全局并行与内存争用 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L7) |
| S002 | cluster 数量 | 1 | SM 分组和互连扇入；num_sm 必须可整除 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L27) |
| S003 | 每 SM 驻留 warp 槽 | 8 | 隐藏延迟；当前同时绑定多项资源 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L8) |
| S004 | 逻辑 warp 宽度 | 32 | 线程打包、掩码和协同粒度；更改需软件一致 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L9) |
| S005 | 每 SM 驻留 WG 槽 | 8 | block 并发上限；须不超过 warp 数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L53) |
| S006 | 每 WG warp 上限 | num_warp=8 | 当前绑定 warp_slots，可解耦候选 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L55) |
| S007 | 每 SM 向量寄存器槽 | 128*num_warp=1024 | 每槽含 num_thread 个32位元素；绑定 warp 数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L20) |
| S008 | 每 SM 标量寄存器槽 | 256*num_warp=2048 | 寄存器驻留限制；绑定 warp 数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L21) |
| S009 | 共享内存行数 | 1024 | LDS 容量与 occupancy；容量还取决于行宽 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L93) |
| S010 | 待分配 WG 表深度 | 8 | 提交吸收与分配器背压 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L191) |
| S011 | 每资源表保留空洞数 | 2 | 候选空闲段摘要；精细分配仍需扫描 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L194) |
| S012 | 每周期检查 SM 数 | 1 | 可参数化检查并行度，涉及 FSM 改造 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/allocator.scala#L124) |
| S013 | 一组 handler 管理 SM 数 | 1 | 增加共享度改变资源表服务瓶颈 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L620) |
| S014 | CTA splitter 派发宽度 | 每次1个 warp | block 启动服务，不可假设全 warp 同周期就绪 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/cu_interface.scala#L71) |
| S015 | 每次取指指令数 | 2 | 要求2的幂；决定包宽，不等同每 warp 双发射 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L38) |
| S016 | 每 SM 取指请求宽度 | 1 | 一条 ICache 请求通道 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/warp_schedule.scala#L187) |
| S017 | 每 warp 指令包拆分宽度 | 每次1条 | 限制同 warp 分发顺序 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L149) |
| S018 | 拆包暂存容量 | 每 warp 1包 | 须与指令 FIFO 一起考虑可缓存指令数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L147) |
| S019 | 到 collector 的标量分发宽度 | 1 | 可与另一 warp 的向量分发并行 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L64) |
| S020 | 到 collector 的向量类分发宽度 | 1 | 向量类含访存、FP、SFU、TC 和 MUL | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L65) |
| S021 | 每 warp SIMT 栈深度 | num_thread=32 | 当前绑定逻辑线程数；合法嵌套限制 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L129) |
| S022 | SGPR bank 数 | 4 | 源码共同 num_bank；设计时可分开。bankID 部分写死2位，更改需统一。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L18) |
| S023 | VGPR bank 数 | 4 | 源码共同 num_bank；与VGPR容量、bank索引、供数网络耦合。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L18) |
| S024 | collector 单元数 | num_warp=8 | 绑定 warp 数；可独立选择需 RTL 改造 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L19) |
| S025 | SGPR 每 bank 读端口数 | 1 | 四 bank 共最多四个标量读请求 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L25) |
| S026 | VGPR 每 bank 向量读端口数 | 1 | 每次读取一个 warp 向量槽 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L58) |
| S027 | SGPR 每 bank 写端口数 | 1 | 还受全局标量 WB 每周期1条限制 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L28) |
| S028 | VGPR 每 bank 向量写端口数 | 1 | 掩码写入；还受向量 WB 限制 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L64) |
| S029 | collector X 输出通道数 | 1 | 两类可分开开放；前端分发、执行入口和写回也要配套。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L630) |
| S030 | collector V 输出通道数 | 1 | 两类可分开开放；改为多通道需配套仲裁。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L630) |
| S031 | 标量写回通道数 | 1 | 聚合各执行单元；仍受全局写回通道限制 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L47) |
| S032 | 向量写回通道数 | 1 | 整数、FP、LSU、TC 竞争 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L46) |
| S033 | 标量 ALU 数量 | 1 | 标量整数服务 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L76) |
| S034 | 向量 ALU 物理 lane 数 | num_lane=num_thread=32 | 与 FPU/MUL 共用 num_lane，独立 lane 数需解耦 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L77) |
| S035 | 向量 MUL 物理 lane 数 | num_lane=32 | 当前与 ALU/FPU 绑定 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L81) |
| S036 | 向量 FPU 物理 lane 数 | num_lane=32 | lane 时分支路存在；需 softThread 可整除 hardThread | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L78) |
| S037 | 每 SM SFU lane 数 | max(num_thread/4,1)=8 | 与 warp_width 绑定；每 lane 有整数除法和 FP div/sqrt | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L91) |
| S038 | 整数除法物理单元数 | 8 | 当前和FP div/sqrt共用num_sfu；分开配置需重做分组/结果同步。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L846) |
| S039 | 浮点除法/开方物理单元数 | 8 | 当前和整数除法共用num_sfu；每单元同时承担div/sqrt。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L847) |
| S040 | 每 SM Tensor Core 数 | 1 | 可改造为多个独立资源 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L82) |
| S041 | TC 输出矩阵第一轴 | DimM=4 | 默认和 num_thread 绑定 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L124) |
| S042 | TC 输出矩阵第二轴 | 代码DimK=4 | 代码 DimK 是输出轴，数学上记N，避免维度误读 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L213) |
| S043 | TC 点积归约轴 | 代码DimN=8 | 代码 DimN 是归约轴，数学上记K | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L214) |
| S044 | LSU 在途 warp 指令记录数 | num_warp=8 | 合并分段返回，不等于 DCache miss MSHR | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L69) |
| S045 | 每 warp 在途访存上限 | 4 | ShiftBoard credit；与总LSU entries共同限制 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L67) |
| S046 | 地址计算/发起通道数量 | 1条 AddrCalculate FSM | 每条向量访存分多笔 line 请求 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L554) |
| S047 | 全局访存合并粒度 | 128 B line | 绑定 DCache_BlockWords；不能把warp load直接计一笔 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L173) |
| S048 | ICache set 数 | dcache_NSets=256 | MyConfig 默认同 DCache；局部构造参数可改 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheParameters.scala#L21) |
| S049 | ICache ways | dcache_NWays=2 | 当前默认绑定 DCache | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheParameters.scala#L22) |
| S050 | ICache line 大小 | DCache_BlockWords*4=128 B | line 属性继承共用基类 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICache.scala#L85) |
| S051 | ICache primary MSHR | 4 | 独立 miss line 数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheParameters.scala#L24) |
| S052 | ICache 每 miss 合并目标数 | 4 | 同 line 多warp miss 合并 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheParameters.scala#L25) |
| S053 | ICache读端口数 | 1 | 当前同步1R1W；存储端口数和上游请求通道数须分别考虑，增加端口需实现新组织。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICache.scala#L90) |
| S054 | ICache写端口数 | 1 | 当前同步1R1W；存储端口数和上游请求通道数须分别考虑，增加端口需实现新组织。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICache.scala#L90) |
| S055 | DCache data array读端口数 | 1 | 当前同步1R1W；存储端口数和上游请求通道数须分别考虑，增加端口需实现新组织。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L644) |
| S056 | DCache data array写端口数 | 1 | 当前同步1R1W；存储端口数和上游请求通道数须分别考虑，增加端口需实现新组织。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L644) |
| S057 | 每个LDS bank读端口数 | 1 | 当前同步1R1W；存储端口数和上游请求通道数须分别考虑，增加端口需实现新组织。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMem.scala#L152) |
| S058 | 每个LDS bank写端口数 | 1 | 当前同步1R1W；存储端口数和上游请求通道数须分别考虑，增加端口需实现新组织。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMem.scala#L152) |
| S059 | L2 directory读端口数 | 1 | 当前同步1R1W；存储端口数和上游请求通道数须分别考虑，增加端口需实现新组织。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Directory_test.scala#L103) |
| S060 | L2 directory写端口数 | 1 | 当前同步1R1W；存储端口数和上游请求通道数须分别考虑，增加端口需实现新组织。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Directory_test.scala#L103) |
| S061 | L2 data array读端口数 | 1 | 当前同步1R1W；存储端口数和上游请求通道数须分别考虑，增加端口需实现新组织。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/BankedStore.scala#L92) |
| S062 | L2 data array写端口数 | 1 | 当前同步1R1W；存储端口数和上游请求通道数须分别考虑，增加端口需实现新组织。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/BankedStore.scala#L92) |
| S063 | DCache set 数 | 256 | cache locality与容量 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L71) |
| S064 | DCache ways | 2 | 冲突miss与 tag探测 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L73) |
| S065 | DCache line words | 32即128 B | 影响合并；其它多个结构引用该值 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L75) |
| S066 | DCache primary MSHR | 4 | 独立miss并发 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L88) |
| S067 | DCache 每 miss 次级目标 | 2 | 同line miss合并能力 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L90) |
| S068 | DCache WSHR 数 | 4 | 写miss/写回在途追踪 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L76) |
| S069 | DCache dirty记录粒度 | 每cacheline字节掩码 | 脏流量取决于写覆盖字节 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/L1TagAccess.scala#L209) |
| S070 | LDS 每行word数 | DCache_BlockWords=32 | 与cacheline共用定义；按当前地址切片约束 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L95) |
| S071 | LDS bank 数 | NLanes=num_thread=32 | 显式TODO解耦；和线程数绑定 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMemParameters.scala#L40) |
| S072 | L2 slice 数 | 1 | 并行共享内存服务端点 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L132) |
| S073 | 每slice L2 set 数 | 64 | 容量与L2索引 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L99) |
| S074 | L2 associativity | 16 | 冲突miss；victim取低wayBits，变更须合法 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L101) |
| S075 | L2 line 大小 | DCache_BlockWords*4=128 B | 当前绑定L1大小 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L103) |
| S076 | L2内外接口beat大小 | 等于line=128 B | 局部声明可设置，但实际多个路径依赖单beat | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L113) |
| S077 | L2存储更新粒度 | 1 B | mask和data子bank组织 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L105) |
| S078 | L2 MSHR 数 | max(dirReg?3:2,ceil(memCycles/blockBeats))=32 | 当前由memCycles和blockBeats推导；可将此资源容量解耦开放，届时保留池结构与协议约束。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L164) |
| S079 | L2 secondary共享entry池 | max(mshrs,memCycles-mshrs)=32 | 当前由memCycles和blockBeats推导；可将此资源容量解耦开放，届时保留池结构与协议约束。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L165) |
| S080 | L2写数据list数 | memCycles=32 | 当前由memCycles和blockBeats推导；可将此资源容量解耦开放，届时保留池结构与协议约束。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L166) |
| S081 | L2写数据beat池大小 | max(2*blockBeats,memCycles)=32 | 当前由memCycles和blockBeats推导；可将此资源容量解耦开放，届时保留池结构与协议约束。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L167) |
| S082 | 下层通道有效数据 beat 大小 | 128 B | 当前所有相关通道都受128B line/single-beat假设约束；不可单改位宽。 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L550) |

### 3.1 关键尺寸规则应进入模型约束

1. **容量的计量单位必须明确。**VGPR默认1024个向量槽，每槽32个32位元素，容量128 KiB；SGPR默认2048个标量槽，容量8 KiB。LDS默认1024行×32 words×4 B=128 KiB。按统一“寄存器数”或按1024个标量字计算会造成数量级错误。[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L20)、[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L21)、[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L93)
2. **驻留同时受多种资源约束。**每WG所需warp槽、VGPR、SGPR、LDS及WG槽要同时满足；资源表还处理连续空洞和碎片化，单纯容量比最小值只描述上界。基址和分配粒度影响可用容量。[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L305)、[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L468)
3. **逻辑宽度与物理宽度分开。**warp宽度控制软件掩码和布局；ALU/MUL/FPU的物理lane数决定chime。当前共享num_lane，部分路径支持逻辑线程数整除物理lane数的时分，但整机任意配置合法性没有验证。SFU按活动组工作，不能直接套用相同chime公式。[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L78)、[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L227)、[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L828)
4. **bank和端口是不同尺寸。**RF总容量不改变也可能因bank数、地址映射和读端口变化而改变供数。LDS容量、行宽和bank数当前绑定；建模需要按实际字地址/掩码形成冲突。增加数据byte子bank也不会自动得到同样数量的独立请求通道。[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L581)、[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMemParameters.scala#L48)、[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/BankedStore.scala#L92)
5. **cache几何、合并粒度与传输beat耦合。**容量=sets×ways×line bytes；L1/L2 line、LDS行宽、LSU合并粒度和下层single-beat假设当前有共同来源。若解耦，需要桥接/拆包、地址切片和返回聚合规则；不能只改几个容量常数。[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L75)、[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L113)、[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/MSHR.scala#L37)
6. **在途资源逐层约束。**LSU总表、每warp credit、L1 primary/secondary MSHR、WSHR、L2 MSHR、secondary池、put list与beat池互不等价。L2 secondary为共享池，不能按“每MSHR32项”乘开。其当前资源配额参数memCycles=32也不表示真实DDR延迟。[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L67)、[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L165)、[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L107)
7. **TC形状包含输出与归约轴。**默认源码DimM=4、DimN=8、DimK=4；数学上输出M×N=4×4、归约K=8。于是16个dot、128个乘法节点。形状决定fragment layout、供数及归约树；不能把三轴机械当成三个不受约束的整数。[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L124)、[源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L215)

默认容量仅用于定位当前实现。缓存容量、逻辑指令索引位宽、tag/source ID位宽均应从已选尺寸或固定ISA契约导出，避免作为多份可调参数重复优化。

### 3.2 当前绑定与建议开放方式

| 当前绑定 | 建议处理 | 为什么值得讨论 |
|---|---|---|
| num_warp→VGPR/SGPR、collector、LSU总表、每WG warp上限 | 分开列资源；搜索时可解耦，施加驻留/接口约束 | 否则增加warp槽会被动同时扩很多资源，无法研究配比 |
| SGPR/VGPR共用num_bank | 允许独立bank配置作为组织方案 | 两类供数压力不同；需要bank ID与仲裁配套 |
| ALU/MUL/FPU共用num_lane | 将物理宽度分别描述 | 工作负载不同，宽度配比有价值；软件逻辑warp宽度可固定 |
| num_thread→SFU、LDS banks、SIMT stack | 分开描述，按研究范围选择解耦 | 栈容量与执行lane数的物理必要关系较弱；LDS银行数也无需永远等于warp宽度 |
| ICache几何沿用DCache；多处共用line大小 | 可先保留line统一，优先解耦sets/ways | 几何解耦容易有意义；line/beat解耦会改变协议 |
| L2 memCycles→MSHR/secondary/put资源 | 直接列各资源配额与共享池规则 | 可区分读miss、合并和写数据容量，避免一个代理参数混合多个效果 |
| 配套数据/控制/mask FIFO相同深度 | 保留配套约束，或作为一个缓冲实现模板 | 改深度却不保持事务对齐可能破坏功能，不能自由组合 |

以上是研究参数化建议，不代表所有分别配置的组合已实现。已有assert、幂次和整除约束，以及写死的索引位宽都必须纳入合法域。


### 3.3 从尺寸到可检查的约束

以下是拟议行为模型/MILP接口的抽象约束，尚未在本项目中实现。它们区分源码现有合法性和将来解耦所需约束。

| 关系 | 约束或推导 | 边界 |
|---|---|---|
| SM分组 | `N_SM mod N_cluster = 0`；每cluster SM数由商导出 | 当前组织按整组路由；替代组织需改变分发模型 |
| RF总容量 | `C_VGPR_bytes = R_VGPR_slots × W × 4`；`C_SGPR_bytes = R_SGPR_slots × 4` | RV32/FP32契约固定；容量与槽数选一套独立表示 |
| RF每bank深度 | `D_VGPR_bank = R_VGPR_slots / B_VGPR`；SGPR同理 | 当前采用整数分组、bank索引切片；bank数/深度变化需验证合法性 |
| 单SM驻留 | `Σ w_b ≤ W_slots`；`Σ alloc_V(b) ≤ R_VGPR`；`Σ alloc_S(b) ≤ R_SGPR`；`Σ alloc_LDS(b) ≤ C_LDS`；`WG_resident ≤ WG_slots` | alloc使用真实资源表计量与分配结果，含连续空间/碎片；这些总量约束只是必要条件 |
| 物理lane时分 | `W mod H_FU = 0`；合法时chime=`W/H_FU` | 当前ALU/MUL/FPU路径有相应假设；SFU另按活动掩码组与完成规则 |
| 每bank供数 | 在时间步t，发往bank j的服务请求数不超过其读端口数 | 请求归属由实际寄存器索引/warp ID决定，不能只用平均读带宽 |
| cache容量 | `C = sets × ways × line_bytes` | 当前索引逻辑依赖log2与切片；非幂次几何需重新设计映射 |
| 下层beat | `blockBeats = line_bytes / beat_bytes` | 当前line=beat；解耦会引入多beat请求/组装，不能只改blockBeats |
| TC寄存器fragment | 数学轴满足`M×K ≤ W`、`N×K ≤ W`、`M×N ≤ W` | 当前TensorCoreFP32构造器有对应assert；K须为大于1的2次幂 |
| TC算术规模 | dot数=`M×N`；乘法节点=`M×N×K`；树深=`log2(K)` | 当前空间展开乘法与树结构；其它实现需采用其它公式 |
| 配套FIFO | 指令包/mask、FMA数据/控制、DCache下传/mask保持事务对应 | 可用一致深度或一个逻辑队列模板；独立容量须另证功能正确 |

TC形状的原始约束见 [TensorCoreFP32](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L194)，归约长度约束见 [TCDotProduct](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L87)。其余公式是对第3节所列尺寸/源码组织的抽象；没有将总量必要条件当作完整分配可行性证明。

若优化的是秒数、吞吐或成本，尺寸还需与频率、SRAM访问时序、面积/能耗和实现条件耦合。固定时钟下的周期模型可以先比较微架构行为，但无法单独证明某个尺寸组合能达到同一物理频率。

## 队列大小的完整列表


下表按不同用途列出62个队列或直接连接位置。对称复制的lane/warp/SM不重复计数；FMA数据/控制、指令包/mask、DCache下传/mask按必须保持一致的容量处理。部分DCache内部队列仍各自列出，**列出不表示其深度可以彼此独立改变**。

深度0表示当前直接连接，是将来插入缓冲的位置，不表示当前有存储容量。表中有18项深度0。WB输入按不同FU角色拆分，有助于讨论混合指令背压；最终也可选择“统一缓冲深度”模板减少搜索维度。

`pipe`控制满队列时吞吐/ready耦合，`flow`控制空队列时同周期直通/valid耦合；它们会影响性能。初始模型应忠实使用当前规则，初始优化空间可把它们固定，或选择经过验证的缓冲实现模板。深度0时，这些模式开关没有相应存储队列意义。依据为项目依赖的 [Chisel 6.4.0 Queue定义](https://github.com/chipsalliance/chisel/blob/v6.4.0/src/main/scala/chisel3/util/Decoupled.scala)。

| 编号 | 角色 / 配置模板 | 深度 | pipe / flow | 约束及备注 | 证据 |
|---|---|---:|---|---|---|
| Q001 | CTA：allocator→CU interface | 1 | true / false | 当前已接入 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/allocator.scala#L329) |
| Q002 | CTA：资源回收 slot_dealloc | 2 | false / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L769) |
| Q003 | CTA：LDS基址 | 1 | true / true | 三资源路径可分别设容量；可分别配置 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L853) |
| Q004 | CTA：SGPR基址 | 1 | true / true | 三资源路径可分别设容量；可分别配置 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L854) |
| Q005 | CTA：VGPR基址 | 1 | true / true | 三资源路径可分别设容量；可分别配置 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L855) |
| Q006 | CTA：CTA dispatch FIFO | 2 | false / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/cu_interface.scala#L46) |
| Q007 | CTA：warp完成回报 | 16 | false / false | 当前assert要求始终ready；不能任意减小 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/CTA2warp.scala#L73) |
| Q008 | 前端/控制：每warp指令包+mask | 2 | false / false | 数据和mask两FIFO同深度；按一套配置，另有SlowDown暂存 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L115) |
| Q009 | 前端/控制：SIMT branch_ctl | 1 | false / true |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/branch_join.scala#L84) |
| Q010 | 前端/控制：SIMT if_mask | 0 | false / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/branch_join.scala#L85) |
| Q011 | 前端/控制：SIMT reconvergence PC | 1 | false / true |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/branch_join.scala#L86) |
| Q012 | 前端/控制：SIMT redirect结果 | 1 | false / true |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/branch_join.scala#L88) |
| Q013 | 前端/控制：标量分支返回汇聚输入0 | 0 | false / false | Branch_back当前已实例化；当前已接入 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L24) |
| Q014 | 前端/控制：SIMT分支返回汇聚输入1 | 0 | false / false | Branch_back当前已实例化；当前已接入 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L25) |
| Q015 | 发射/写回：Issue X输入 | 0 | false / false | 同类Issue的两条异角色路径；pipe当前各实例1个 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/issue.scala#L54) |
| Q016 | 发射/写回：Issue V输入 | 0 | false / false | 同类Issue的两条异角色路径；pipe当前各实例1个 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/issue.scala#L54) |
| Q017 | 发射/写回：WB X输入0（ALU） | 0 | false / false | 6+6输入按FU角色可独立缓冲；当前全直接连线；连接顺序见pipe.scala:416–427 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L53) |
| Q018 | 发射/写回：WB X输入1（FPU） | 0 | false / false | 6+6输入按FU角色可独立缓冲；当前全直接连线；连接顺序见pipe.scala:416–427 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L53) |
| Q019 | 发射/写回：WB X输入2（LSU） | 0 | false / false | 6+6输入按FU角色可独立缓冲；当前全直接连线；连接顺序见pipe.scala:416–427 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L53) |
| Q020 | 发射/写回：WB X输入3（CSR） | 0 | false / false | 6+6输入按FU角色可独立缓冲；当前全直接连线；连接顺序见pipe.scala:416–427 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L53) |
| Q021 | 发射/写回：WB X输入4（SFU） | 0 | false / false | 6+6输入按FU角色可独立缓冲；当前全直接连线；连接顺序见pipe.scala:416–427 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L53) |
| Q022 | 发射/写回：WB X输入5（MUL） | 0 | false / false | 6+6输入按FU角色可独立缓冲；当前全直接连线；连接顺序见pipe.scala:416–427 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L53) |
| Q023 | 发射/写回：WB V输入0（VALU） | 0 | false / false | 6+6输入按FU角色可独立缓冲；当前全直接连线；连接顺序见pipe.scala:416–427 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L57) |
| Q024 | 发射/写回：WB V输入1（FPU） | 0 | false / false | 6+6输入按FU角色可独立缓冲；当前全直接连线；连接顺序见pipe.scala:416–427 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L57) |
| Q025 | 发射/写回：WB V输入2（LSU） | 0 | false / false | 6+6输入按FU角色可独立缓冲；当前全直接连线；连接顺序见pipe.scala:416–427 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L57) |
| Q026 | 发射/写回：WB V输入3（SFU） | 0 | false / false | 6+6输入按FU角色可独立缓冲；当前全直接连线；连接顺序见pipe.scala:416–427 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L57) |
| Q027 | 发射/写回：WB V输入4（MUL） | 0 | false / false | 6+6输入按FU角色可独立缓冲；当前全直接连线；连接顺序见pipe.scala:416–427 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L57) |
| Q028 | 发射/写回：WB V输入5（TC） | 0 | false / false | 6+6输入按FU角色可独立缓冲；当前全直接连线；连接顺序见pipe.scala:416–427 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L57) |
| Q029 | 执行单元：标量ALU结果 | 1 | true / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L37) |
| Q030 | 执行单元：标量ALU分支结果 | 1 | true / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L38) |
| Q031 | 执行单元：vALUv2结果 | 1 | true / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L504) |
| Q032 | 执行单元：vALUv2 compare→SIMT | 1 | true / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L505) |
| Q033 | 执行单元：vMULv2标量结果 | 1 | true / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L189) |
| Q034 | 执行单元：vMULv2向量结果 | 1 | true / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L190) |
| Q035 | 执行单元：TC wrapper结果 | 1 | true / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L124) |
| Q036 | 执行单元：SFU标量结果 | 1 | true / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L813) |
| Q037 | 执行单元：SFU向量结果 | 1 | true / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L814) |
| Q038 | 执行单元：SFU输入 | 1 | false / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L818) |
| Q039 | 执行单元：CSR结果 | 1 | true / false | 当前已接入 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/CSR.scala#L356) |
| Q040 | FPU/TC内部：FMA direct ADD数据+控制 | 1 | true / false | 控制FIFO[1]在134行；必须与数据对齐 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L145) |
| Q041 | FPU/TC内部：FMA MUL→ADD数据+控制 | 1 | true / false | 控制FIFO[0]在134行；必须与数据对齐 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L152) |
| Q042 | FPU/TC内部：FMA mul输出 | 1 | true / false |  | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L167) |
| Q043 | FPU/TC内部：FMA add输出 | 1 | true / false |  | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L168) |
| Q044 | FPU/TC内部：TC dot product输出 | 1 | true / false | 同构dot/lane统一模板，不乘16个dot或32个lane | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L173) |
| Q045 | LSU：LSU InputFIFO | 1 | true / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L551) |
| Q046 | ICache：memRsp返回 | 2 | true / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICache.scala#L99) |
| Q047 | DCache：coreReq | 1 | true / false | 请求数据与控制st1深度需配套 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L188) |
| Q048 | DCache：coreRsp | 32 | false / false | 当前深度取NLanes | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L191) |
| Q049 | DCache：memRsp | 2 | false / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L194) |
| Q050 | DCache：memReq+请求mask | 8 | false / false | mask队列904行也为8；按必须保持一致的容量一项计 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L198) |
| Q051 | DCache：coreRsp valid暂存 | 1 | true / false | 与相关数据/控制保持同事务对齐，不能默认独立 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L203) |
| Q052 | DCache：coreRsp data暂存 | 1 | true / false | 深度需随流水协议配套 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L204) |
| Q053 | DCache：coreReqControl st1 | 1 | true / false | 与coreReq同事务对齐 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L232) |
| Q054 | DCache：coreRsp st2 | 1 | true / false | 与readHit信息配套 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L246) |
| Q055 | DCache：readHit st2 | 1 | true / false | 深度需随流水协议配套 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L249) |
| Q056 | DCache MSHR：probe st1 | 1 | true / false | 关联DCache st1服务 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/L1MSHR.scala#L108) |
| Q057 | DCache MSHR：missRspOut st1 | 1 | true / false | 当前已接入 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/L1MSHR.scala#L332) |
| Q058 | LDS：coreRsp | 32 | true / false | 当前深度取num_thread | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMem.scala#L73) |
| Q059 | L2：write_buffer | 8 | false / true | 位置参数false,true表示pipe=false、flow=true | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Scheduler.scala#L125) |
| Q060 | L2：directory result buffer | 1 | false / false | 当前已接入 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Scheduler.scala#L244) |
| Q061 | L2：SinkA输入BufferParams | 0 | false / false | 默认innerBuf.a=none；按BufferParams模板描述 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/SinkA.scala#L48) |
| Q062 | 互连：SM→cluster memReqBuf | 2 | false / false |  | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L530) |

L2 `Queue(...,8,false,true)`的位置参数为pipe=false、flow=true，必须按此语义描述。MMU专用ASID/source缓冲属于可选路径，未加入本节默认核心尺寸计数。

## 可选择的硬件实现


单列的依据应是**存在可信替代实现、会改变资源/时序/流量、作用能与其他选择区分，并有明确成本与合法性**。若几个开关只共同描述一个实现，宜合成一个枚举模板；若只是固定协议规则，宜留在行为模型中。

| 技术/细节 | 本次处理建议 | 何时开放为变量 | 证据/限制 |
|---|---|---|---|
| LDS同址广播/合并 | 重要技术候选，可做一个enable或实现枚举 | workload含广播且愿意提供合并硬件和成本模型 | 当前不合并：[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/BankConflictArbiter.scala#L184) |
| RF多端口/多bank | 数量单列；拓扑与访问规则选模板 | 研究供数瓶颈、RF成本与布局 | 每bank当前1R1W，映射与仲裁需一致 |
| 不同FU独立物理宽度 | 主要尺寸变量 | 研究资源配比 | 当前共享num_lane；时分协议必须一致 |
| 一个/多个TC及其形状 | TC数量和形状属于主要尺寸；实现选模板 | 存在多TC或不同阵列方案 | 主分支基准为1个FP32阵列；开发分支已接入FP16阵列，精度与形状按所选版本描述 |
| FMA共享/独立ADD资源 | 一项流水组织选择，配套尺寸和服务规则 | ADD/FMA混合成为主要瓶颈 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L133)；不要给共享开关、冲突延迟、ADD II三份独立旋钮 |
| cache write-back/write-through、write-allocate/no-allocate | 两类policy关系用实现模板表示 | 比较内存流量与缓存/队列成本，替代实现可信 | 当前hit本地dirty、miss PutPartial；[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L315)、[源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L358) |
| cache替换算法 | 低成本离散候选，但可先固定 | 有冲突敏感workload，模型能再现每个算法 | I全局循环、D有限时间戳、L2 LFSR；不要只信plru字符串 |
| fetch/issue/RF/WB/互连仲裁 | 必须保留当前规则；按瓶颈开放少数策略 | 公平性或竞争顺序显著改变周期 | 各位置独立作用；不可随意用单个RR替代全系统 |
| queue pipe/flow、SRAM bypass/hold | 行为规则；优先合成合法实现模板 | 确实研究寄存切分、组合路径与时序收敛 | 开关组合受事务对齐、同址读写和时钟目标约束 |
| SIMT路径先后/重汇合 | 默认行为规则；可选SIMT组织模板 | 研究分歧结构或栈压力 | 当前先较少活动线程路径，不能只用平均分歧比例 |
| divider算法、每轮处理位数 | 可选除法实现模板，延迟由值与模板决定 | SFU占主要时间，提供替代实现及成本 | 延迟类别需来自实际操作数/规则，不能任意调delay获得收益 |
| MMU启用、TLB组织 | 条件子空间；启用后列尺寸和服务规则 | 研究地址空间/多kernel场景 | 默认关闭；SV32约束及walk流量要匹配 |
| 压缩、预取、async DMA、多精度与稀疏扩展 | 按实现版本分别提取，不计入本轮主分支尺寸总数 | 补充确切实现、软件使用方式与功能/性能模型 | FP16已有公开开发分支接入；其余扩展仍需逐项核查 |
| ISA位宽、opcode编码、debug输出 | 固定契约或排除 | 只有研究目标明确改变ISA/实现调试模式时才另建空间 | 当前RV32/FP32契约；debug不当作器件架构优化维度 |

对技术方案更合适的表示是“实现模板+模板所需尺寸”，例如选择一种FMA结构后，其共享资源、队列、LAT/II和面积约束一起生效。模型可以提供很多描述字段，优化只开放其中一部分；保持这一分离可避免搜索器利用互相矛盾的参数。

## 需要保留的执行规则和时序


尺寸最适合优先进入优化，但有些写死规则会改变对尺寸收益的判断。应在行为模型中保留，再按敏感性决定是否成为搜索变量：

- **供数与依赖：**RAW/WAW保持到WB，X/V每warp collector令牌、RF请求仲裁、源收齐、固定WB优先级会限制执行利用率。更多FPU或TC不自动等于更快。
- **启动与回收：**CTA扫描空洞、best-fit和逐warp派发决定实际驻留时间；大的资源容量也可能受分配器服务制约。
- **访存序列：**LSU逐line拆分、最低活动lane次序、DCache/LDS返回竞争、完成聚合，以及cache写回/flush排空会决定最慢依赖何时解除。
- **分歧与同步：**分支路径顺序、掩码变化、barrier到达差和cache维护终点会改变周期。WG结束的flush_dcache接口当前实际请求invalidate，不能单看名称。
- **值相关时序：**整数除法和FP div/sqrt特殊路径，以及SFU等待整组完成，需要操作数延迟类别或等价服务规则。

上述细节的源码位置及完整当前实现见附录。省略的位级算术、临时布线和无性能影响的寄存器可以留在抽象之外；是否可省应由校准误差和失败样例判断。

### 6.1 latency / II 的处理

| 操作/路径 | 当前可见时序 | 建模建议 |
|---|---|---|
| RF读 | 同步读1级，返回/collector协议另计 | 参数随存储实现模板联动 |
| 整数MUL | primitive latency=2 | 整指令服务包含FU结果与WB，不直接设总delay=2 |
| FP MUL / ADD | primitive分别2 / 1 | FMA共享ADD及内部队列必须表达 |
| FP compare/move/转换 | 局部流水各2 | 与五类子单元输出仲裁共同建模 |
| TC | primitive mul/add各2；K=8时内部算术2+2log2(8)+2=10 | 另计dot和wrapper队列、供数、WB；10不是整指令延迟 |
| Int div / FP div/sqrt | 值相关迭代、特殊值、prepare/round路径 | 保留延迟函数；微基准确认边界周期 |
| ICache/DCache/LDS/L2 | 同步SRAM、内部级、FSM和队列混合 | 分清hit latency、请求II、返回吞吐及竞争时停顿；逐路径校准 |

同一个数据路径的流水级数、LAT、II和最大频率存在耦合。可用少量经验证的实现模板，避免把它们独立连续优化成不可能的硬件。

## 各模块的全部说明

以下列表同时包含硬件大小、运行规则、可选模块、程序输入，以及本次不研究的项目。它用于检查遗漏，行数不能当作设计变量数。上面的尺寸表和队列表已经包含其中一些内容，不要把几张表的行数相加。



### 核心 GPU

#### 组织与驻留

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V001 | SM 数量 `sm_count` | 2 | 可研究调整大小；限制见尺寸表和队列表 | 全局并行与内存争用 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L7) |
| V002 | cluster 数量 `cluster_count` | 1 | 可研究调整大小；限制见尺寸表和队列表 | SM 分组和互连扇入；num_sm 必须可整除 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L27) |
| V003 | 每 SM 驻留 warp 槽 `warp_slots` | 8 | 可研究调整大小；限制见尺寸表和队列表 | 隐藏延迟；当前同时绑定多项资源 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L8) |
| V004 | 逻辑 warp 宽度 `warp_threads` | 32 | 可研究调整大小；限制见尺寸表和队列表 | 线程打包、掩码和协同粒度；更改需软件一致 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L9) |
| V005 | 每 SM 驻留 WG 槽 `block_slots` | 8 | 可研究调整大小；限制见尺寸表和队列表 | block 并发上限；须不超过 warp 数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L53) |
| V006 | 每 WG warp 上限 `warps_per_block_limit` | num_warp=8 | 可研究调整大小；限制见尺寸表和队列表 | 当前绑定 warp_slots，可解耦候选 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L55) |
| V007 | 每 SM 向量寄存器槽 `vgpr_vector_slots` | 128*num_warp=1024 | 可研究调整大小；限制见尺寸表和队列表 | 每槽含 num_thread 个32位元素；绑定 warp 数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L20) |
| V008 | 每 SM 标量寄存器槽 `sgpr_scalar_slots` | 256*num_warp=2048 | 可研究调整大小；限制见尺寸表和队列表 | 寄存器驻留限制；绑定 warp 数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L21) |
| V009 | 共享内存行数 `lds_rows` | 1024 | 可研究调整大小；限制见尺寸表和队列表 | LDS 容量与 occupancy；容量还取决于行宽 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L93) |
| V010 | MMU 启用 `mmu_enable` | false | 模拟时按此规则执行；更换方案见上文 | 决定是否启用 TLB/PTW 整条路径 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L15) |

#### CTA 分配与回收

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V011 | 待分配 WG 表深度 `pending_wg_depth` | 8 | 可研究调整大小；限制见尺寸表和队列表 | 提交吸收与分配器背压 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L191) |
| V012 | 每资源表保留空洞数 `resource_result_count` | 2 | 可研究调整大小；限制见尺寸表和队列表 | 候选空闲段摘要；精细分配仍需扫描 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L194) |
| V013 | 每周期检查 SM 数 `cu_scan_width` | 1 | 可研究调整大小；限制见尺寸表和队列表 | 可参数化检查并行度，涉及 FSM 改造 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/allocator.scala#L124) |
| V014 | SM 选择策略 `cu_preference` | 从上次分配 SM 的后继开始 | 模拟时按此规则执行；更换方案见上文 | 影响负载分配和 cache locality | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/allocator.scala#L224) |
| V015 | 资源空洞选择规则 `resource_allocation_policy` | best fit空洞 | 模拟时按此规则执行；更换方案见上文 | 选满足WG大小的最小段；必须保留碎片化 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L305) |
| V016 | 一组 handler 管理 SM 数 `resource_handler_group` | 1 | 可研究调整大小；限制见尺寸表和队列表 | 增加共享度改变资源表服务瓶颈 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L620) |
| V017 | 资源表扫描流水 `resource_scan_pipeline` | 指针、取数、空洞计算排序 | 先用实验核对耗时；换实现后重新确定 | 保留逐段处理与填排空；总延迟依活跃 WG | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L468) |
| V018 | 分配和回收优先级 `alloc_dealloc_priority` | 可抢占扫描；分配优先 | 模拟时按此规则执行；更换方案见上文 | 不同请求竞争改变分配可见时刻 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L141) |
| V019 | 资源槽回收队列深度 `slot_dealloc_queue` | 2 | 可研究调整大小；限制见尺寸表和队列表 | 回收背压 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L769) |
| V020 | LDS/SGPR/VGPR 基址队列深度族 `baseaddr_queue` | 各1，pipe和flow开启 | 可研究调整大小；限制见尺寸表和队列表 | 三条同结构队列作为一个模板字段 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L853) |
| V021 | CTA 到 SM 分发队列深度 `cta_dispatch_queue` | 2 | 可研究调整大小；限制见尺寸表和队列表 | block 分配与逐 warp 派发的解耦 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/cu_interface.scala#L46) |
| V022 | CTA splitter 派发宽度 `warp_dispatch_width` | 每次1个 warp | 可研究调整大小；限制见尺寸表和队列表 | block 启动服务，不可假设全 warp 同周期就绪 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/cu_interface.scala#L71) |
| V023 | SM 内空闲 warp 槽选择 `warp_slot_policy` | 低位优先 | 模拟时按此规则执行；更换方案见上文 | 硬件 warp ID 改变 RF bank 与取指优先级 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/CTA2warp.scala#L59) |
| V024 | warp 完成回报 FIFO 深度 `warp_done_queue` | 16 | 可研究调整大小；限制见尺寸表和队列表 | 隐藏的硬编码队列，回收路径仍要求 ready | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/CTA2warp.scala#L73) |
| V025 | 跨 SM 完成回报仲裁 `completion_arbitration` | round robin | 模拟时按此规则执行；更换方案见上文 | 完成吞吐与资源回收时刻 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/cu_interface.scala#L154) |
| V026 | 完成与回收 FSM `completion_service` | GET_WF→UPDATE→必要时 DEALLOC | 先用实验核对耗时；换实现后重新确定 | 每个 warp 回报占用服务周期；不简化为0 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/cu_interface.scala#L230) |
| V027 | WG 表入队及候选选择 `wg_buffer_policy` | RRPriorityEncoder | 模拟时按此规则执行；更换方案见上文 | 队列竞争与公平性；空位分配也用 RR | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/wg_buffer.scala#L73) |

#### 取指与指令分发

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V028 | 每次取指指令数 `fetch_words` | 2 | 可研究调整大小；限制见尺寸表和队列表 | 要求2的幂；决定包宽，不等同每 warp 双发射 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L38) |
| V029 | 每 warp 指令包 FIFO 深度 `ibuffer_packets` | 2包 | 可研究调整大小；限制见尺寸表和队列表 | 每包 num_fetch 条；另有 SlowDown 寄存器 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L45) |
| V030 | 每 SM 取指请求宽度 `fetch_requests` | 1 | 可研究调整大小；限制见尺寸表和队列表 | 一条 ICache 请求通道 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/warp_schedule.scala#L187) |
| V031 | 取指 warp 选择 `fetch_warp_policy` | 就绪 warp 中低 ID 优先 | 模拟时按此规则执行；更换方案见上文 | 反向循环赋值导致低 ID 覆盖；与发射 RR 区别明显 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/warp_schedule.scala#L185) |
| V032 | 取指准入规则 `fetch_eligibility` | active 且 ibuffer ready | 模拟时按此规则执行；更换方案见上文 | 取指可前推，不直接用 scoreboard_busy 门控 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/warp_schedule.scala#L184) |
| V033 | 每 warp 指令包拆分宽度 `packet_unpack_width` | 每次1条 | 可研究调整大小；限制见尺寸表和队列表 | 限制同 warp 分发顺序 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L149) |
| V034 | 拆包暂存容量 `packet_unpack_storage` | 每 warp 1包 | 可研究调整大小；限制见尺寸表和队列表 | 须与指令 FIFO 一起考虑可缓存指令数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L147) |
| V035 | 到 collector 的标量分发宽度 `scalar_dispatch_width` | 1 | 可研究调整大小；限制见尺寸表和队列表 | 可与另一 warp 的向量分发并行 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L64) |
| V036 | 到 collector 的向量类分发宽度 `vector_dispatch_width` | 1 | 可研究调整大小；限制见尺寸表和队列表 | 向量类含访存、FP、SFU、TC 和 MUL | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L65) |
| V037 | 标量 warp 分发策略 `scalar_dispatch_policy` | round robin | 模拟时按此规则执行；更换方案见上文 | 选择就绪 warp | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L64) |
| V038 | 向量 warp 分发策略 `vector_dispatch_policy` | round robin | 模拟时按此规则执行；更换方案见上文 | 与标量类独立仲裁 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L65) |
| V039 | 指令类别到 X/V 路由 `instruction_class_routing` | mem/fp/mul/sfu/tc 归 V | 模拟时按此规则执行；更换方案见上文 | 标量 load/FP 也会争用向量类资源 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L70) |
| V040 | 分支重定向丢弃范围 `branch_flush_scope` | 对应 warp 指令与取指流水 | 模拟时按此规则执行；更换方案见上文 | 回收错误路径取指，影响分支代价 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L193) |

#### 依赖控制与 SIMT

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V041 | 每 warp 逻辑寄存器依赖表大小 `scoreboard_entries` | 256，来自5+3位 | 模拟时按此规则执行；更换方案见上文 | 架构索引空间；不等于物理 RF 容量 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/scoreboard.scala#L102) |
| V042 | RAW/WAW 依赖规则 `raw_waw_interlock` | 目的 busy 到 WB 才清除 | 模拟时按此规则执行；更换方案见上文 | 相同 opcode 流量但依赖链不同，周期不同 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/scoreboard.scala#L129) |
| V043 | 每 warp X/V collector 在途令牌 `collector_tokens` | X和V各1 | 模拟时按此规则执行；更换方案见上文 | 限制单 warp 指令提前进入 collector | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/scoreboard.scala#L105) |
| V044 | 分支和 barrier 的 warp 互锁 `branch_interlock` | 1个 busy 标志 | 模拟时按此规则执行；更换方案见上文 | 顺序与控制依赖 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/scoreboard.scala#L113) |
| V045 | fence 阻塞范围 `fence_interlock` | 对应 warp 后续访存 | 模拟时按此规则执行；更换方案见上文 | 必须等待访存响应，不能只加固定开销 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/scoreboard.scala#L133) |
| V046 | 依赖清除时点 `scoreboard_release` | WB fire/collector out/控制完成 | 模拟时按此规则执行；更换方案见上文 | 同周期清除与读取规则需保留，边界周期待比对 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/scoreboard.scala#L110) |
| V047 | 每 warp SIMT 栈深度 `simt_stack_depth` | num_thread=32 | 可研究调整大小；限制见尺寸表和队列表 | 当前绑定逻辑线程数；合法嵌套限制 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L129) |
| V048 | 分歧路径先后顺序 `divergent_path_policy` | 优先活动线程较少路径 | 模拟时按此规则执行；更换方案见上文 | 相等时偏 else；需要掩码和真实控制流 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/branch_join.scala#L145) |
| V049 | 分支控制 FIFO 深度与 flow `branch_control_queue` | 1，flow=true | 可研究调整大小；限制见尺寸表和队列表 | 控制与 compare 结果配对 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/branch_join.scala#L84) |
| V050 | 汇合 PC FIFO 深度与 flow `reconvergence_pc_queue` | 1，flow=true | 可研究调整大小；限制见尺寸表和队列表 | 与分支控制队列耦合 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/branch_join.scala#L86) |
| V051 | 重定向结果 FIFO 深度与 flow `redirect_queue` | 1，flow=true | 可研究调整大小；限制见尺寸表和队列表 | 控制背压 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/branch_join.scala#L88) |
| V052 | WG barrier 到达和释放规则 `barrier_release_rule` | 等待 WG 预期 warp 全到齐 | 模拟时按此规则执行；更换方案见上文 | 影响同步停顿；不可用常数替代到达时差 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/warp_schedule.scala#L139) |
| V053 | WG 完成后的 DCache 维护触发 `endprg_flush_rule` | WG 全部 warp 结束触发 invalidate | 模拟时按此规则执行；更换方案见上文 | 必须声明性能终点是否包含最终内存可见 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/warp_schedule.scala#L167) |
| V054 | 分支与 warp 控制响应优先级 `control_response_priority` | branch 优先，flushCache 会阻塞 | 模拟时按此规则执行；更换方案见上文 | 同步、控制指令竞争 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/warp_schedule.scala#L52) |

#### RF 与 Operand Collector

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V055 | SGPR/VGPR bank 数 `rf_banks` | 共用4 | 可研究调整大小；限制见尺寸表和队列表 | 容量相同但 bank 映射不同会影响供数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L18) |
| V056 | collector 单元数 `collector_count` | num_warp=8 | 可研究调整大小；限制见尺寸表和队列表 | 绑定 warp 数；可独立选择需 RTL 改造 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L19) |
| V057 | RF bank 映射 `rf_bank_mapping` | (warp_id+reg_idx) mod banks | 模拟时按此规则执行；更换方案见上文 | 影响多源冲突；bank 宽度部分代码写死2位 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L581) |
| V058 | SGPR 每 bank 读端口数 `sgpr_read_ports` | 1 | 可研究调整大小；限制见尺寸表和队列表 | 四 bank 共最多四个标量读请求 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L25) |
| V059 | VGPR 每 bank 向量读端口数 `vgpr_read_ports` | 1 | 可研究调整大小；限制见尺寸表和队列表 | 每次读取一个 warp 向量槽 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L58) |
| V060 | SGPR 每 bank 写端口数 `sgpr_write_ports` | 1 | 可研究调整大小；限制见尺寸表和队列表 | 还受全局标量 WB 每周期1条限制 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L28) |
| V061 | VGPR 每 bank 向量写端口数 `vgpr_write_ports` | 1 | 可研究调整大小；限制见尺寸表和队列表 | 掩码写入；还受向量 WB 限制 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L64) |
| V062 | RF 同步读延迟 `rf_read_latency` | 1周期 SRAM 读 | 先用实验核对耗时；换实现后重新确定 | collector 返回路径另有协议开销 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L53) |
| V063 | RF 同址读写旁路 `rf_read_write_bypass` | RegNext匹配后旁路 | 模拟时按此规则执行；更换方案见上文 | 不应给同址读写额外 stall | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L22) |
| V064 | VGPR 写掩码粒度 `rf_vector_mask_write` | 每 lane 一个32位元素 | 模拟时按此规则执行；更换方案见上文 | 尾 warp/分歧保留旧元素 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L62) |
| V065 | collector 请求槽数量 `collector_source_slots` | 3源+mask共4槽 | 模拟时按此规则执行；更换方案见上文 | 源数量影响 bank 供数需求 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L67) |
| V066 | 空 collector 选择与 X/V 优先级 `collector_allocation_policy` | 低位空槽；默认V优先 | 模拟时按此规则执行；更换方案见上文 | num_warp=1 时 X/V 每周期轮流优先 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L461) |
| V067 | 每 bank RF 读仲裁 `rf_read_arbitration` | round robin | 模拟时按此规则执行；更换方案见上文 | 所有 collector 源一起争用 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L340) |
| V068 | collector 完成条件 `collector_ready_rule` | 所有要求的源均已收齐 | 模拟时按此规则执行；更换方案见上文 | 须保留指令级源需求；不能统一3次读 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L85) |
| V069 | collector 到执行 X/V 宽度 `collector_output_width` | 各1 | 可研究调整大小；限制见尺寸表和队列表 | 与前端两类分发构成相同两条流 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L630) |
| V070 | 收齐源的 collector 选择 `collector_output_policy` | X/V 独立RR | 模拟时按此规则执行；更换方案见上文 | 源读取和发射可能乱序，执行仍受 scoreboard | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L650) |
| V071 | 标量写回通道数 `scalar_wb_width` | 1 | 可研究调整大小；限制见尺寸表和队列表 | 聚合各执行单元；仍受全局写回通道限制 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L47) |
| V072 | 向量写回通道数 `vector_wb_width` | 1 | 可研究调整大小；限制见尺寸表和队列表 | 整数、FP、LSU、TC 竞争 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L46) |
| V073 | 标量执行结果写回策略 `scalar_wb_priority` | 固定输入优先级 | 模拟时按此规则执行；更换方案见上文 | 以 pipe 的输入连接顺序为准 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L60) |
| V074 | 向量执行结果写回策略 `vector_wb_priority` | 固定输入优先级 | 模拟时按此规则执行；更换方案见上文 | 不能套用 RR | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L61) |
| V075 | WB 聚合器输入暂存深度族 `wb_input_storage` | 全部0 | 可研究调整大小；限制见尺寸表和队列表 | 实际缓冲在 FU 结果队列，禁止重复计算 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L53) |

#### 整数与浮点执行

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V076 | 标量 ALU 数量 `scalar_alu_instances` | 1 | 可研究调整大小；限制见尺寸表和队列表 | 标量整数服务 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L76) |
| V077 | 向量 ALU 物理 lane 数 `vector_alu_lanes` | num_lane=num_thread=32 | 可研究调整大小；限制见尺寸表和队列表 | 与 FPU/MUL 共用 num_lane，独立 lane 数需解耦 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L77) |
| V078 | 向量 MUL 物理 lane 数 `vector_mul_lanes` | num_lane=32 | 可研究调整大小；限制见尺寸表和队列表 | 当前与 ALU/FPU 绑定 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L81) |
| V079 | 向量 FPU 物理 lane 数 `vector_fpu_lanes` | num_lane=32 | 可研究调整大小；限制见尺寸表和队列表 | lane 时分支路存在；需 softThread 可整除 hardThread | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L78) |
| V080 | collector 到 Issue 缓冲深度族 `execution_route_queue` | 0，直接连线 | 可研究调整大小；限制见尺寸表和队列表 | 目的 FU 背压直接传回 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/issue.scala#L54) |
| V081 | 标量 ALU 结果 FIFO `scalar_alu_result_queue` | 1，pipe=true | 可研究调整大小；限制见尺寸表和队列表 | WB 竞争回压 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L37) |
| V082 | 标量分支结果 FIFO `scalar_branch_result_queue` | 1，pipe=true | 可研究调整大小；限制见尺寸表和队列表 | 分支重定向可与普通结果竞争 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L38) |
| V083 | 向量 ALU 结果 FIFO `vector_alu_result_queue` | 1，pipe=true | 可研究调整大小；限制见尺寸表和队列表 | FU 可接收与 WB 延迟不同 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L504) |
| V084 | 向量比较到 SIMT FIFO `vector_compare_result_queue` | 1，pipe=true | 可研究调整大小；限制见尺寸表和队列表 | SIMT 背压 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L422) |
| V085 | 整数乘法内部流水延迟 `mul_pipe_latency` | 2 | 模拟时按此规则执行；更换方案见上文 | 局部流水值；全路径还包含 FU/WB 队列 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/Multiplier.scala#L152) |
| V086 | 乘法 X/V 结果 FIFO 深度族 `mul_result_queue` | 各1，pipe=true | 可研究调整大小；限制见尺寸表和队列表 | 结果输出解耦 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L190) |
| V087 | 逻辑 warp 到物理 lane 时分方式 `lane_serialization` | 按连续 lane 组发送并重组 | 模拟时按此规则执行；更换方案见上文 | 当前32/32无需时分；减少 lane 时必须计填排空 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L227) |
| V088 | 单 lane 浮点单元组成与共享 `fpu_subunit_sharing` | FMA/CMP/MV/FPToInt/IntToFP | 模拟时按此规则执行；更换方案见上文 | 每 lane 内多个子单元共享输入/输出通道 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FPU.scala#L15) |
| V089 | FPU 五类子单元输出策略 `fpu_output_priority` | 固定优先级 | 模拟时按此规则执行；更换方案见上文 | 不同 FP 指令混合吞吐不能仅看峰值 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FPU.scala#L39) |
| V090 | FP 乘法局部流水深度 `fp_mul_pipe_latency` | 2 | 模拟时按此规则执行；更换方案见上文 | 不包含 FMA 内队列 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L34) |
| V091 | FP 加法局部流水深度 `fp_add_pipe_latency` | 1 | 模拟时按此规则执行；更换方案见上文 | FADD/FMA 共享加法流水 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L74) |
| V092 | FMA 中共享 add 选择 `fma_add_arbitration` | mul返回的 FMA 优先于独立add | 模拟时按此规则执行；更换方案见上文 | ADD/FMA 混合竞争 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L133) |
| V093 | 共享 add 两路控制队列模板 `fma_control_queue` | 各1，pipe=true | 可研究调整大小；限制见尺寸表和队列表 | 控制与数据队列必须配对 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L134) |
| V094 | 独立 ADD 数据 FIFO `fma_direct_add_queue` | 1，pipe=true | 可研究调整大小；限制见尺寸表和队列表 | 共享 add 排队 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L145) |
| V095 | MUL 到 ADD 数据 FIFO `fma_mul_to_add_queue` | 1，pipe=true | 可研究调整大小；限制见尺寸表和队列表 | FMA 内部生产消费依赖 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L152) |
| V096 | FMA 的 mul/add 输出 FIFO 模板 `fma_output_queue` | 各1，pipe=true | 可研究调整大小；限制见尺寸表和队列表 | FMA 内输出竞争 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L167) |
| V097 | FMA 内 add/mul 输出优先级 `fma_output_priority` | add/FMA 优先于mul | 模拟时按此规则执行；更换方案见上文 | 影响持续混合指令 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L178) |
| V098 | 浮点比较局部流水延迟 `fp_cmp_latency` | 2 | 模拟时按此规则执行；更换方案见上文 | 与转换同数值也保留独立操作族 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FCMP.scala#L11) |
| V099 | 浮点搬移局部流水延迟 `fp_move_latency` | 2 | 模拟时按此规则执行；更换方案见上文 | 实际执行路径为 FPU 子模块 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FPMV.scala#L11) |
| V100 | 浮点转整数局部延迟 `fp_to_int_latency` | 2 | 模拟时按此规则执行；更换方案见上文 | 转换类时序 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FPToInt.scala#L12) |
| V101 | 整数转浮点局部延迟 `int_to_fp_latency` | 2 | 模拟时按此规则执行；更换方案见上文 | 转换类时序 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/IntToFP.scala#L11) |
| V102 | 每 SM SFU lane 数 `sfu_units` | max(num_thread/4,1)=8 | 可研究调整大小；限制见尺寸表和队列表 | 与 warp_width 绑定；每 lane 有整数除法和 FP div/sqrt | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L91) |
| V103 | SFU 指令暂存 FIFO `sfu_input_queue` | 1 | 可研究调整大小；限制见尺寸表和队列表 | 默认整个 SFU 逐指令处理 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L818) |
| V104 | SFU X/V 结果 FIFO 模板 `sfu_output_queue` | 各1，pipe=true | 可研究调整大小；限制见尺寸表和队列表 | SFU 与 WB 竞争 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L813) |
| V105 | SFU 分组及空组跳过规则 `sfu_mask_group_policy` | 优先低位活动组；每组num_sfu条 | 模拟时按此规则执行；更换方案见上文 | 按掩码组数计服务；组内慢 lane 可拖全组 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L828) |
| V106 | SFU 组完成与 lane 同步 `sfu_group_completion` | 等待整组输出 valid | 模拟时按此规则执行；更换方案见上文 | 操作数相关慢 lane 与掩码填充有影响 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L849) |
| V107 | 整数除法迭代与特殊值规则 `int_div_latency_function` | 依前导零差/除零/溢出变化 | 先用实验核对耗时；换实现后重新确定 | 需要值或延迟类别输入，不能一个固定delay | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/IntDivMod.scala#L46) |
| V108 | FP div/sqrt 迭代与特殊值规则 `fp_div_sqrt_latency_function` | 28位 recurrence + prepare/round | 先用实验核对耗时；换实现后重新确定 | 特殊值捷径和正常路径需 FSM/微基准确认 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/FloatDivSqrt.scala#L34) |
| V109 | SFU 新指令准入规则 `sfu_initiation_rule` | 等待当前指令 finish并消费 | 模拟时按此规则执行；更换方案见上文 | SFU 内部延迟与整个 warp II 不同 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L897) |

#### Tensor Core

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V110 | 每 SM Tensor Core 数 `tc_instances` | 1 | 可研究调整大小；限制见尺寸表和队列表 | 可改造为多个独立资源 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L82) |
| V111 | TC 输出矩阵第一轴 `matrix_output_m` | DimM=4 | 可研究调整大小；限制见尺寸表和队列表 | 默认和 num_thread 绑定 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L124) |
| V112 | TC 输出矩阵第二轴 `matrix_output_n` | 代码DimK=4 | 可研究调整大小；限制见尺寸表和队列表 | 代码 DimK 是输出轴，数学上记N，避免维度误读 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L213) |
| V113 | TC 点积归约轴 `matrix_reduction_k` | 代码DimN=8 | 可研究调整大小；限制见尺寸表和队列表 | 代码 DimN 是归约轴，数学上记K | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L214) |
| V114 | TC 碎片寄存器布局 `matrix_lane_layout` | A[m*DimN+n]、B[k*DimN+n]、C[m*DimK+k] | 模拟时按此规则执行；更换方案见上文 | 决定编译器数据重排和供数 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L215) |
| V115 | TC 计算与舍入结构 `matrix_arithmetic` | FP32 mul→平衡add tree→add C | 模拟时按此规则执行；更换方案见上文 | 逐节点舍入；与单指令全融合语义需区分 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L161) |
| V116 | TC 每乘法节点流水延迟 `tc_mul_latency` | 2 | 模拟时按此规则执行；更换方案见上文 | primitive 时序字段 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L14) |
| V117 | TC 每树加法节点流水延迟 `reduction_add_latency` | 2 | 模拟时按此规则执行；更换方案见上文 | 按log2(归约轴) 层累计；源中该类latency=2 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L11) |
| V118 | 每 TC dot-product 输出 FIFO `tc_dot_output_queue` | 1，pipe=true | 可研究调整大小；限制见尺寸表和队列表 | 同模板，按M*N复制但只计一个字段 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L173) |
| V119 | TC wrapper 向量输出 FIFO `tc_warp_output_queue` | 1，pipe=true | 可研究调整大小；限制见尺寸表和队列表 | TC 与其它执行单元竞争 VGPR WB | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L124) |
| V120 | TC 输入与输出背压 `matrix_accept_rule` | head dot 控制，整阵列同 valid/ready | 模拟时按此规则执行；更换方案见上文 | 吞吐受数据供给与 WB 共同约束 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L209) |

#### LSU 与合并返回

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V121 | LSU 指令 FIFO 深度 `lsu_input_queue` | 1，pipe=true | 可研究调整大小；限制见尺寸表和队列表 | 访存发射缓冲 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L551) |
| V122 | LSU 在途 warp 指令记录数 `lsu_instruction_entries` | num_warp=8 | 可研究调整大小；限制见尺寸表和队列表 | 合并分段返回，不等于 DCache miss MSHR | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L69) |
| V123 | 每 warp 在途访存上限 `lsu_per_warp_credit` | 4 | 可研究调整大小；限制见尺寸表和队列表 | ShiftBoard credit；与总LSU entries共同限制 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L67) |
| V124 | 地址计算/发起通道数量 `lsu_address_width` | 1条 AddrCalculate FSM | 可研究调整大小；限制见尺寸表和队列表 | 每条向量访存分多笔 line 请求 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L554) |
| V125 | 地址生成模式 `lsu_address_modes` | unit stride/stride/index/private swizzle | 模拟时按此规则执行；更换方案见上文 | 对合并与外存局部性影响显著 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L153) |
| V126 | 全局访存合并粒度 `lsu_coalescing_granularity` | 128 B line | 可研究调整大小；限制见尺寸表和队列表 | 绑定 DCache_BlockWords；不能把warp load直接计一笔 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L173) |
| V127 | 合并时下一 line 选择 `lsu_line_selection` | 最低活动 lane 所在 line | 模拟时按此规则执行；更换方案见上文 | 影响多 line 请求的顺序 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L169) |
| V128 | 多 line 请求拆分发出规则 `lsu_request_serialization` | 逐 line 清除已发掩码 | 模拟时按此规则执行；更换方案见上文 | 由 FSM 逐笔服务，II 需微基准，不预设1 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L283) |
| V129 | 全局与 LDS 路由判定 `lsu_shared_routing` | 活动 lane 都落在 LDS 才选shared | 模拟时按此规则执行；更换方案见上文 | 混合地址不能任意逐 lane 分别路由 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L164) |
| V130 | byte/half/word 访问掩码粒度 `lsu_byte_masks` | 1/2/4 byte | 模拟时按此规则执行；更换方案见上文 | 影响合并字节与写回掩码 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L183) |
| V131 | DCache/LDS 返回仲裁 `lsu_response_priority` | DCache固定优先 | 模拟时按此规则执行；更换方案见上文 | LDS与global同时返回时争用 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L560) |
| V132 | 分段返回聚合规则 `lsu_response_accumulation` | 收齐原指令活动掩码才可 WB | 模拟时按此规则执行；更换方案见上文 | 不同 line 的最慢响应决定完成 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/MSHR.scala#L37) |
| V133 | 在途槽分配和完成选择 `lsu_entry_selection` | 低位优先 | 模拟时按此规则执行；更换方案见上文 | 返回/再分配次序 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/MSHR.scala#L38) |
| V134 | LSU 表同时分配和返回更新 `lsu_mshr_update_conflict` | 返回优先；新分配延至s_add | 模拟时按此规则执行；更换方案见上文 | 合并表服务本身会产生瓶颈 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/MSHR.scala#L50) |
| V135 | LSU 表到 WB 的 FSM 服务 `lsu_return_service` | idle/add/out，out 时才能释放 | 先用实验核对耗时；换实现后重新确定 | 表数再大也不保证每周期完整指令完成 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/MSHR.scala#L106) |
| V136 | LSU fence 完成条件 `lsu_fence_rule` | 相应warp全部在途请求完成 | 模拟时按此规则执行；更换方案见上文 | fence效果由credit与响应时序决定 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L572) |
| V137 | LSU cache维护和新访存优先 `lsu_flush_priority` | idle 时优先处理flush_dcache；实际opcode为invalidate | 模拟时按此规则执行；更换方案见上文 | WG结束flush与普通访存竞争 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L371) |

#### L1 指令缓存

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V138 | ICache set 数 `icache_sets` | dcache_NSets=256 | 可研究调整大小；限制见尺寸表和队列表 | MyConfig 默认同 DCache；局部构造参数可改 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheParameters.scala#L21) |
| V139 | ICache ways `icache_ways` | dcache_NWays=2 | 可研究调整大小；限制见尺寸表和队列表 | 当前默认绑定 DCache | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheParameters.scala#L22) |
| V140 | ICache line 大小 `icache_line_bytes` | DCache_BlockWords*4=128 B | 可研究调整大小；限制见尺寸表和队列表 | line 属性继承共用基类 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICache.scala#L85) |
| V141 | ICache primary MSHR `icache_mshr_entries` | 4 | 可研究调整大小；限制见尺寸表和队列表 | 独立 miss line 数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheParameters.scala#L24) |
| V142 | ICache 每 miss 合并目标数 `icache_mshr_targets` | 4 | 可研究调整大小；限制见尺寸表和队列表 | 同 line 多warp miss 合并 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheParameters.scala#L25) |
| V143 | ICache 下层返回 FIFO `icache_response_queue` | 2，pipe=true | 可研究调整大小；限制见尺寸表和队列表 | refill吸收与背压 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICache.scala#L99) |
| V144 | ICache 命中核心路径 `icache_hit_latency` | req fire 到 st2 response | 先用实验核对耗时；换实现后重新确定 | 静态推断2级；全路径仍有拆包开销 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICache.scala#L201) |
| V145 | ICache 数据存储端口组织 `icache_ports` | 同步1R1W，双端口 | 可研究调整大小；限制见尺寸表和队列表 | 读命中可与refill写并存；同址规则需保持 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICache.scala#L90) |
| V146 | ICache 替换策略 `icache_replacement` | 全局循环one-hot victim | 模拟时按此规则执行；更换方案见上文 | 替换状态不按set独立，不能替成通用LRU | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/L1TagAccess.scala#L516) |
| V147 | ICache miss/replay 规则 `icache_miss_replay` | 返回miss status，refill后重取 | 模拟时按此规则执行；更换方案见上文 | miss等待不能只加一次固定delay | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICache.scala#L220) |
| V148 | 同warp近邻miss冲突窗口 `icache_replay_hazard` | 检查前2/3级 warp与miss | 模拟时按此规则执行；更换方案见上文 | 影响取指密集及 miss 模式 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICache.scala#L276) |
| V149 | 同line miss目标返送顺序 `icache_refill_target_service` | 一次返送一个 target | 模拟时按此规则执行；更换方案见上文 | subentry>1仍有逐个服务 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheMSHR.scala#L175) |

#### L1 数据缓存

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V150 | DCache set 数 `dcache_sets` | 256 | 可研究调整大小；限制见尺寸表和队列表 | cache locality与容量 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L71) |
| V151 | DCache ways `cache_ways` | 2 | 可研究调整大小；限制见尺寸表和队列表 | 冲突miss与 tag探测 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L73) |
| V152 | DCache line words `cache_line_words` | 32即128 B | 可研究调整大小；限制见尺寸表和队列表 | 影响合并；其它多个结构引用该值 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L75) |
| V153 | DCache primary MSHR `cache_mshr_entries` | 4 | 可研究调整大小；限制见尺寸表和队列表 | 独立miss并发 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L88) |
| V154 | DCache 每 miss 次级目标 `cache_mshr_targets` | 2 | 可研究调整大小；限制见尺寸表和队列表 | 同line miss合并能力 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L90) |
| V155 | DCache WSHR 数 `cache_write_status_entries` | 4 | 可研究调整大小；限制见尺寸表和队列表 | 写miss/写回在途追踪 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L76) |
| V156 | DCache core request FIFO `cache_request_queue` | 1，pipe=true，flow=false | 可研究调整大小；限制见尺寸表和队列表 | lookup 准入与流水寄存 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L188) |
| V157 | DCache core response FIFO `cache_response_queue` | NLanes=32，非pipe/flow | 可研究调整大小；限制见尺寸表和队列表 | 当前绑定warp线程数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L190) |
| V158 | DCache 下层响应 FIFO `cache_refill_queue` | 2，非pipe/flow | 可研究调整大小；限制见尺寸表和队列表 | 命中与refill竞争 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L194) |
| V159 | DCache 下层请求 FIFO `cache_outgoing_queue` | 8，非pipe/flow | 可研究调整大小；限制见尺寸表和队列表 | miss、dirty替换、flush共享 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L198) |
| V160 | DCache 内部1槽暂存模板 `cache_internal_elasticity` | control/readHit/st2/data均1 | 可研究调整大小；限制见尺寸表和队列表 | 作为同结构族，不逐个临时寄存器扩张计数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L232) |
| V161 | DCache hit流水与响应服务 `cache_hit_service` | tag探测→data→coreRsp队列 | 先用实验核对耗时；换实现后重新确定 | 准确边界周期及背压需要RTL确认 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L249) |
| V162 | DCache store hit策略 `cache_store_hit_policy` | 本地更新并标脏，后续写回 | 模拟时按此规则执行；更换方案见上文 | 当前RTL含dirty mask，早期写穿通文档过时 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L315) |
| V163 | DCache store miss策略 `cache_store_miss_policy` | PutPartial下传，不经读分配 | 模拟时按此规则执行；更换方案见上文 | 区分hit和miss写策略 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L358) |
| V164 | DCache victim 选择 `cache_replacement_policy` | 有限accessCount时间戳规则 | 模拟时按此规则执行；更换方案见上文 | 接近LRU意图但有1000次counter循环，模型须按源码 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/L1TagAccess.scala#L77) |
| V165 | DCache dirty记录粒度 `cache_dirty_granularity` | 每cacheline字节掩码 | 可研究调整大小；限制见尺寸表和队列表 | 脏流量取决于写覆盖字节 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/L1TagAccess.scala#L209) |
| V166 | DCache data array组织 `cache_data_bank_layout` | 每line word独立字节掩码SRAM | 模拟时按此规则执行；更换方案见上文 | 实际按BlockWords实例化，勿把NBanks别名当物理组织 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L637) |
| V167 | DCache data array端口 `cache_data_ports` | 同步1R1W双端口 | 可研究调整大小；限制见尺寸表和队列表 | refill写与writehit的实际mux优先级需保留 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L644) |
| V168 | DCache 下层请求策略 `cache_downstream_priority` | dirty victim→普通miss→flush | 模拟时按此规则执行；更换方案见上文 | 三个固定优先输入 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L785) |
| V169 | tag探测与分配写冲突规则 `cache_lookup_refill_conflict` | probe遇allocate则阻塞 | 模拟时按此规则执行；更换方案见上文 | 命中与refill并发不总为满吞吐 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L623) |
| V170 | 写miss与已有miss互锁 `cache_write_miss_interlock` | inflightreadwritemiss等状态阻塞 | 模拟时按此规则执行；更换方案见上文 | MSHR增加不能消除所有阻塞 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L210) |
| V171 | 同word字节写合并规则 `cache_sameword_merge` | genDataMapSameWord重映射 | 模拟时按此规则执行；更换方案见上文 | 字节覆盖与冲突影响实际请求数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L201) |
| V172 | DCache flush/invalidate排空条件 `cache_flush_rule` | dirty扫描、WSHR与L2确认 | 模拟时按此规则执行；更换方案见上文 | kernel尾部代价由dirty状态决定 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L207) |

#### 共享内存 LDS

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V173 | LDS 每行word数 `lds_line_words` | DCache_BlockWords=32 | 可研究调整大小；限制见尺寸表和队列表 | 与cacheline共用定义；按当前地址切片约束 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L95) |
| V174 | LDS bank 数 `lds_banks` | NLanes=num_thread=32 | 可研究调整大小；限制见尺寸表和队列表 | 显式TODO解耦；和线程数绑定 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMemParameters.scala#L40) |
| V175 | LDS bank地址映射 `lds_bank_address_map` | word地址低位 | 模拟时按此规则执行；更换方案见上文 | stride与布局决定冲突 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMemParameters.scala#L48) |
| V176 | LDS 每bank端口 `lds_bank_ports` | 1R1W双端口 | 可研究调整大小；限制见尺寸表和队列表 | 与bank冲突仲裁和写占用准入耦合 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMem.scala#L152) |
| V177 | LDS data读时序 `lds_read_latency` | 同步读+st1/st2响应路径 | 先用实验核对耗时；换实现后重新确定 | 准确请求到响应周期需验证 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMem.scala#L128) |
| V178 | LDS 返回 FIFO `lds_response_queue` | num_thread=32，pipe=true | 可研究调整大小；限制见尺寸表和队列表 | warp_width绑定返回缓冲 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMem.scala#L72) |
| V179 | 每bank多个lane仲裁 `lds_conflict_policy` | 低位lane优先；余者逐轮服务 | 模拟时按此规则执行；更换方案见上文 | 要按实际地址/掩码计算冲突，非平均系数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/BankConflictArbiter.scala#L164) |
| V180 | LDS 同地址广播合并 `lds_same_address_merge` | 不合并 | 模拟时按此规则执行；更换方案见上文 | 32 lane同word读也排队，不能套用NVIDIA广播假设 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/BankConflictArbiter.scala#L184) |
| V181 | LDS 新请求与重放/写重叠 `lds_access_overlap` | 冲突重放及st1写阻塞新请求 | 模拟时按此规则执行；更换方案见上文 | 1R1W能力不等于每周期一条向量指令 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMem.scala#L194) |
| V182 | LDS 写掩码和旁路 `lds_byte_write` | 字节掩码；bypassWrite=true | 模拟时按此规则执行；更换方案见上文 | 影响同址读写语义；保持精确访问粒度 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMem.scala#L153) |

#### L2 缓存与服务

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V183 | L2 slice 数 `l2_slices` | 1 | 可研究调整大小；限制见尺寸表和队列表 | 并行共享内存服务端点 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L132) |
| V184 | 每slice L2 set 数 `l2_sets` | 64 | 可研究调整大小；限制见尺寸表和队列表 | 容量与L2索引 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L99) |
| V185 | L2 associativity `l2_ways` | 16 | 可研究调整大小；限制见尺寸表和队列表 | 冲突miss；victim取低wayBits，变更须合法 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L101) |
| V186 | L2 line 大小 `l2_line_bytes` | DCache_BlockWords*4=128 B | 可研究调整大小；限制见尺寸表和队列表 | 当前绑定L1大小 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L103) |
| V187 | L2内外接口beat大小 `l2_beat_bytes` | 等于line=128 B | 可研究调整大小；限制见尺寸表和队列表 | 局部声明可设置，但实际多个路径依赖单beat | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L113) |
| V188 | L2存储更新粒度 `l2_write_bytes` | 1 B | 可研究调整大小；限制见尺寸表和队列表 | mask和data子bank组织 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L105) |
| V189 | L2资源配额的memory cycles参数 `l2_sizing_mem_cycles` | 32 | 模拟时按此规则执行；更换方案见上文 | 只用于MSHR/secondary/put尺寸，绝非真实DDR延迟 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L107) |
| V190 | L2 MSHR 数 `l2_mshr_entries` | max(dirReg?3:2,ceil(memCycles/blockBeats))=32 | 当前按公式计算，今后可研究单独配置 | 由资源配额导出；不能当独立upstream参数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L164) |
| V191 | L2 secondary共享entry池 `l2_secondary_entries` | max(mshrs,memCycles-mshrs)=32 | 当前按公式计算，今后可研究单独配置 | ListBuffer全局pool，非每MSHR32项 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L165) |
| V192 | L2写数据list数 `l2_put_lists` | memCycles=32 | 当前按公式计算，今后可研究单独配置 | 写数据追踪，绑定memory sizing | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L166) |
| V193 | L2写数据beat池大小 `l2_put_beats` | max(2*blockBeats,memCycles)=32 | 当前按公式计算，今后可研究单独配置 | 统一beat池，非list数乘beat数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L167) |
| V194 | L2 MSHR服务选择 `l2_mshr_policy` | round robin filter | 模拟时按此规则执行；更换方案见上文 | directory、sourceA和sourceD多资源竞争 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Scheduler.scala#L103) |
| V195 | L2同set请求合并/排队规则 `l2_merge_semantics` | ListBuffer关联到MSHR列表 | 模拟时按此规则执行；更换方案见上文 | 必须检查MSHR/queued请求具体状态，非纯miss率模型 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Scheduler.scala#L89) |
| V196 | L2 dirty下传FIFO `l2_writeback_queue` | 8，pipe=false、flow=true | 可研究调整大小；限制见尺寸表和队列表 | dirty victim与普通miss解耦 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Scheduler.scala#L125) |
| V197 | L2下层A通道优先级 `l2_writeback_priority` | write_buffer优先 | 模拟时按此规则执行；更换方案见上文 | 写回占用带宽并延迟读miss | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Scheduler.scala#L143) |
| V198 | L2实际victim策略 `l2_replacement` | 16位LFSR低wayBits | 模拟时按此规则执行；更换方案见上文 | 配置字符串plru未接入实际victim逻辑 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Directory_test.scala#L227) |
| V199 | L2 LFSR种子和推进规则 `l2_replacement_sequence` | reset=0；result.fire推进 | 模拟时按此规则执行；更换方案见上文 | 同策略不同序列也影响冲突trace，可固定为校准常量 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Directory_test.scala#L219) |
| V200 | L2 directory存储端口 `l2_directory_ports` | 1R1W，sync、hold、bypass | 可研究调整大小；限制见尺寸表和队列表 | lookup/refill同set竞争与旁路 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Directory_test.scala#L103) |
| V201 | L2 directory查询和冲突协议 `l2_directory_service` | 同步读+结果保持/冲突处理 | 先用实验核对耗时；换实现后重新确定 | 命中延迟不能只由capacity推得 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Directory_test.scala#L229) |
| V202 | L2 data array端口 `l2_data_ports` | 1R1W、同步读 | 可研究调整大小；限制见尺寸表和队列表 | 单共享访问端口，byte banks不提供独立128路请求 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/BankedStore.scala#L92) |
| V203 | L2 refill和store数据写优先级 `l2_refill_store_priority` | sinkD优先于sourceD写 | 模拟时按此规则执行；更换方案见上文 | refill吞吐与store hit相互竞争 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/BankedStore.scala#L109) |
| V204 | L2 hit/miss/dirty返回服务FSM `l2_source_d_service` | 8状态路径，依请求类型 | 先用实验核对耗时；换实现后重新确定 | hit与dirty miss服务时间分开，精确边界待校准 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/SourceD.scala#L68) |
| V205 | L2 flush/invalidate协议 `l2_flush_service` | 排空putbuffer；invalidate还待MSHR空 | 模拟时按此规则执行；更换方案见上文 | 跨SM共享缓存状态影响尾部flush | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Scheduler.scala#L154) |
| V206 | L2 A通道输入buffer模板 `l2_input_buffer` | BufferParams.none | 模拟时按此规则执行；更换方案见上文 | 仅实际消费的innerBuf.a纳入 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/SinkA.scala#L48) |

#### 互连与争用

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V207 | SM内I/D下层请求仲裁 `l1_to_l2_policy` | 固定优先级 | 模拟时按此规则执行；更换方案见上文 | 输入连接顺序须纳入模型 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/L1Cache2L2Arbiter.scala#L32) |
| V208 | SM到cluster仲裁 `sm_to_cluster_policy` | 固定优先级 | 模拟时按此规则执行；更换方案见上文 | 改变sm数量改变争用 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L529) |
| V209 | cluster入口请求FIFO `sm_to_cluster_queue` | 2 | 可研究调整大小；限制见尺寸表和队列表 | 有限缓冲与背压 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L530) |
| V210 | cluster到L2仲裁 `cluster_to_l2_policy` | 固定优先级 | 模拟时按此规则执行；更换方案见上文 | 多个cluster共L2端点 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L610) |
| V211 | L2 slice地址映射 `l2_slice_address_map` | offset→set→slice→tag | 模拟时按此规则执行；更换方案见上文 | 多slice地址条带布局 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L222) |
| V212 | L2到cluster返回仲裁 `l2_to_cluster_response_policy` | 固定优先级 | 模拟时按此规则执行；更换方案见上文 | 各slice响应争用返程通道 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L590) |
| V213 | 互连每通道服务宽度 `interconnect_beat_service` | 每次一个128B beat | 可研究调整大小；限制见尺寸表和队列表 | 当前为分层仲裁互连；无路由器、VC或mesh模型 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L550) |

### 可选 MMU

#### 可选 MMU

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V214 | 基本page offset位数 `virtual_page_offset_bits` | 12即4 KiB | 模拟时按此规则执行；更换方案见上文 | 固定ISA和地址翻译契约时应冻结 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/PTW.scala#L24) |
| V215 | 页表层数 `page_table_levels` | SV32=2 | 模拟时按此规则执行；更换方案见上文 | superpage路径与walk流量 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/PTW.scala#L27) |
| V216 | ASID位数 `asid_bits` | 16 | 模拟时按此规则执行；更换方案见上文 | 上下文隔离，不随active kernel数重复展开 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/PTW.scala#L20) |
| V217 | 每I/D L1 TLB ways `l1_tlb_entries` | 8 | 模拟时按此规则执行；更换方案见上文 | top实际实例传入；不要用unused trait nWays重复计数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L134) |
| V218 | L1 TLB lookup/miss等待规则 `l1_tlb_service` | L1TLB FSM | 先用实验核对耗时；换实现后重新确定 | 仅MMU路径；命中延迟待边界核对 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/L1TLB.scala#L121) |
| V219 | 共享L2 TLB set数 `l2_tlb_sets` | 16合计 | 模拟时按此规则执行；更换方案见上文 | 跨bank总数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/L2TLB.scala#L10) |
| V220 | L2 TLB ways `l2_tlb_ways` | 4 | 模拟时按此规则执行；更换方案见上文 | 翻译冲突 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/L2TLB.scala#L11) |
| V221 | L2 TLB bank数 `l2_tlb_banks` | 2 | 模拟时按此规则执行；更换方案见上文 | translation并行 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/L2TLB.scala#L13) |
| V222 | 每L2 TLB项sector数 `l2_tlb_sectors` | L2 line words=32 | 模拟时按此规则执行；更换方案见上文 | 绑定cacheline；可覆盖相邻VPN | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/L2TLB.scala#L12) |
| V223 | L2 TLB miss/walk/refill服务 `l2_tlb_service` | bank内FSM和sector fill | 先用实验核对耗时；换实现后重新确定 | 精确延迟/并发需校准 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/L2TLB.scala#L216) |
| V224 | 页表遍历器并行度 `ptw_parallelism` | 按TLB banks实例 | 模拟时按此规则执行；更换方案见上文 | 每bank一条walk状态；与nBanks绑定 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/PTW.scala#L159) |
| V225 | PTW与普通L2请求仲裁 `ptw_memory_sharing` | 固定优先级 | 模拟时按此规则执行；更换方案见上文 | page miss抢占实际内存服务 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L272) |
| V226 | ASID到PTBR表项 `asid_lookup_entries` | 8 | 模拟时按此规则执行；更换方案见上文 | top中硬编码 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L226) |
| V227 | ASID替换及失效范围 `asid_invalidation` | fill更新时传播flush_tlb | 模拟时按此规则执行；更换方案见上文 | 多kernel迁移和TLB冷状态 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/AsidLookup.scala#L17) |

### 可选 AXI

#### 可选 AXI 包装

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V228 | AXI data位宽 `axi_data_bits` | 64 | 模拟时按此规则执行；更换方案见上文 | 硬件包装，默认cached Verilator走另一接口 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L117) |
| V229 | AXI读返回暂存容量 `axi_read_line_buffer` | 1个line | 模拟时按此规则执行；更换方案见上文 | 允许的完成缓冲，不能据此声称只有1个已发读地址 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/axi/AXI4Adapter.scala#L55) |
| V230 | AXI写数据暂存容量 `axi_write_line_buffer` | 1个line | 模拟时按此规则执行；更换方案见上文 | burst序列化 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/axi/AXI4Adapter.scala#L59) |
| V231 | AXI突发模式与长度 `axi_burst_mode` | INCR；line/beat-1 | 模拟时按此规则执行；更换方案见上文 | 长度为派生量；改变line和beat需验证adapter | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/axi/AXI4Adapter.scala#L71) |
| V232 | AXI读写请求准入耦合 `axi_read_write_admission` | AR/AW ready和buffer忙共同门控 | 模拟时按此规则执行；更换方案见上文 | 不能把读写当两个完全独立满速通道 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/axi/AXI4Adapter.scala#L173) |
| V233 | AXI B/R返回选择 `axi_response_priority` | B优先于读line完成 | 模拟时按此规则执行；更换方案见上文 | 下游ready协议需检查 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/axi/AXI4Adapter.scala#L167) |
| V234 | AXI允许的在途与ID匹配约束 `axi_max_outstanding` | 单读拼包缓冲，地址接收需另外审计 | 先用实验核对耗时；换实现后重新确定 | 当前单读拼包结构的合法traffic与吞吐需验证 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/axi/AXI4Adapter.scala#L57) |

### 仿真边界及外部系统

#### 仿真边界与外存

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V235 | RTLsim请求wrapper流水级 `wrapper_request_stages` | 2 | 模拟时按此规则执行；更换方案见上文 | 必须注明比较周期是否包含wrapper | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_SimWrapper.scala#L101) |
| V236 | RTLsim响应wrapper流水级 `wrapper_response_stages` | 2 | 模拟时按此规则执行；更换方案见上文 | RTLSim测试边界，与核心结构分开描述 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_SimWrapper.scala#L102) |
| V237 | 当前RTLSim伪DDR延迟设置 `sim_ddr_delay` | DELAY_DDR=2 | 模拟时按此规则执行；更换方案见上文 | 是wrapper delay设置，不含完整DRAM时序 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V238 | MemSim LDS地址区delay设置 `sim_lds_delay` | DELAY_LDS=0 | 模拟时按此规则执行；更换方案见上文 | shared通常走片上专用路径；只描述该wrapper规则 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V239 | MemSim外存响应槽数 `sim_response_entries` | 5 | 模拟时按此规则执行；更换方案见上文 | 有限在途credit | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L24) |
| V240 | MemSim已到期响应仲裁 `sim_response_selection` | 低槽位优先 | 模拟时按此规则执行；更换方案见上文 | 延迟到期及slot占用影响返回 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L73) |
| V241 | 核心实际频率 `core_clock_hz` | 未提供物理校准值 | 需要目标设备或外存资料 | 周期转秒必需；不能从RTL常数直接得到 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V242 | DRAM channel及子通道数 `memory_channels` | 当前RTLsim未建模 | 需要目标设备或外存资料 | 需要目标板/DRAM模型证据；不能由L2 slice数推出 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V243 | DRAM rank/bank/row组织 `dram_bank_geometry` | 未提取 | 需要目标设备或外存资料 | 若用DRAM状态模型需拆为多个字段 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V244 | DRAM地址映射规则 `memory_address_mapping` | 未提取 | 需要目标设备或外存资料 | 影响row locality与bank冲突 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V245 | DRAM时序参数族 `dram_command_timing` | tRCD/tRP/tRAS/tCCD/tRRD/tFAW/tRFC等未提取 | 需要目标设备或外存资料 | 族字段需按所选DDR规格展开，暂不声称一个独立变量 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V246 | 实际内存bus宽度速率 `memory_bus_service` | 未校准 | 需要目标设备或外存资料 | 带宽和burst传输周期 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V247 | 内存控制器排队和仲裁策略族 `memory_controller_policy` | 未提取 | 需要目标设备或外存资料 | 读写队列、row policy、读写切换需进一步展开 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V248 | DRAM刷新规则 `refresh_policy` | 当前RTLsim无模型 | 需要目标设备或外存资料 | 长kernel下可能改变尾延迟 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V249 | host启动和完成固定开销 `host_launch_completion` | 未测量 | 需要目标设备或外存资料 | 定义kernel设备周期/端到端时间时分开计费 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/sim-verilator/kernel.hpp#L17) |

### 软件输入和共同设计

#### 软件输入与共同设计

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V250 | workgroup grid形状 `wg_grid_shape` | kernel_size[3] | 来自程序，算法或编译器改变时更新 | 三轴值来自程序；不计硬件可调参数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/sim-verilator/kernel.hpp#L38) |
| V251 | 逻辑warp活动线程数 `threads_per_warp_active` | wf_size | 来自程序，算法或编译器改变时更新 | 尾warp掩码 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/sim-verilator/kernel.hpp#L41) |
| V252 | 每workgroup warp数 `warps_per_workgroup` | wg_size | 来自程序，算法或编译器改变时更新 | block软件选择与occupancy约束 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/sim-verilator/kernel.hpp#L40) |
| V253 | 每warp VGPR用量 `kernel_vgpr_usage` | vgprUsage | 来自程序，算法或编译器改变时更新 | 决定资源驻留与spill tradeoff | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/sim-verilator/kernel.hpp#L46) |
| V254 | 每warp SGPR用量 `kernel_sgpr_usage` | sgprUsage | 来自程序，算法或编译器改变时更新 | block分配用总量 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/sim-verilator/kernel.hpp#L45) |
| V255 | 每WG LDS用量 `kernel_lds_usage` | ldsSize | 来自程序，算法或编译器改变时更新 | shared tiling与驻留耦合 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/sim-verilator/kernel.hpp#L42) |
| V256 | 每thread private用量 `kernel_private_usage` | pdsSize | 来自程序，算法或编译器改变时更新 | private/swizzle访存与spill | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/sim-verilator/kernel.hpp#L51) |
| V257 | 指令序列及寄存器读写依赖 `instruction_trace` | 编译产物/动态执行 | 来自程序，算法或编译器改变时更新 | 仅opcode频率不足，依赖链必须来自程序 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L57) |
| V258 | 各lane实际地址与访问掩码 `lane_address_trace` | 动态输入 | 来自程序，算法或编译器改变时更新 | cache、coalescing、bank conflict可由此计算 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L173) |
| V259 | 分支结果及活动lane掩码 `branch_mask_trace` | 动态输入 | 来自程序，算法或编译器改变时更新 | 路径顺序和SFU服务取决于掩码 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/branch_join.scala#L143) |
| V260 | GEMM分块及fragment布局 `matrix_tile_layout` | 软件选择 | 来自程序，算法或编译器改变时更新 | 供数流量、RF占用、TC利用率 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L215) |
| V261 | 同步指令位置 `barrier_placement` | 软件选择 | 来自程序，算法或编译器改变时更新 | 消除或增加barrier改变依赖和停顿 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/warp_schedule.scala#L136) |

### 派生项与排除项

#### 派生量与不单独优化的项目

| 编号 | 项目 | 当前大小或运行规则 | 如何使用 | 性能影响和相关限制 | 证据 |
|---|---|---|---|---|---|
| V262 | 每cluster SM数 `sm_per_cluster` | num_sm/num_cluster=2 | 按已有参数计算，不再设独立变量 | 无需独立设计变量 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L29) |
| V263 | 每SM VGPR容量 `vgpr_bytes` | 1024*32*4=131072 B | 按已有参数计算，不再设独立变量 | 向量槽乘warp宽度；勿当作1024个32bit总计 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L20) |
| V264 | 每SM SGPR容量 `sgpr_bytes` | 2048*4=8192 B | 按已有参数计算，不再设独立变量 | 容量和slot不重复计数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L21) |
| V265 | 每SM LDS容量 `lds_bytes` | 1024*32*4=131072 B | 按已有参数计算，不再设独立变量 | 来自行数和行宽；不重复计独立轴 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L97) |
| V266 | 每SM ICache容量 `icache_bytes` | 256*2*128=65536 B | 按已有参数计算，不再设独立变量 | 来自sets/ways/line | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheParameters.scala#L21) |
| V267 | 每SM DCache容量 `cache_bytes` | 256*2*128=65536 B | 按已有参数计算，不再设独立变量 | 来自sets/ways/line | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L71) |
| V268 | 每L2 slice容量 `l2_bytes` | 64*16*128=131072 B | 按已有参数计算，不再设独立变量 | 来自sets/ways/line；total还乘slice数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L99) |
| V269 | TC乘法节点数量 `tc_parallel_multipliers` | 4*8*4=128 | 按已有参数计算，不再设独立变量 | 输出16个dot，每dot8个乘法；来自矩阵轴 | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L203) |
| V270 | TC点积内部流水理论深度 `tc_dot_pipeline` | 2+2*log2(8)+2=10 | 按已有参数计算，不再设独立变量 | 还未包含dot输出FIFO和wrapper FIFO，不作整条指令delay | [源码](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L161) |
| V271 | 顶层num_issue `nominal_issue_parameter` | 1 | 本次保持不变或不计入 | 当前pipe用Issue各一，num_issue只在未接入IssueV2使用 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L43) |
| V272 | 顶层num_ibuffer `legacy_ibuffer_parameter` | 2 | 本次保持不变或不计入 | 当前用InstrBufferV2/size_ibuffer；legacy instbuffer未接入 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L63) |
| V273 | 顶层num_icachebuf `legacy_icache_buffer_parameter` | 1 | 本次保持不变或不计入 | 未见当前核心实例消耗 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L59) |
| V274 | L2 portFactor `l2_port_factor` | 2 | 本次保持不变或不计入 | 当前BankedStore未用其生成端口；不可当实际吞吐控制旋钮 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L109) |
| V275 | L2 replacement字符串 `l2_replacement_string` | plru | 本次保持不变或不计入 | actual Directory_test用LFSR；名义参数无实际policy效果 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L32) |
| V276 | L2 outerBuf全通道模板 `l2_outer_buffer_template` | full | 本次保持不变或不计入 | 本lite实现未按完整A/B/C/D/E通道消费，禁止展开15个可调参数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L126) |
| V277 | ISA数据/指令/地址基本位宽 `isa_data_width` | 当前RV32/FP32/32bit指令 | 本次保持不变或不计入 | 固定ISA契约下冻结；不拆多个宽度凑维度 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L47) |
| V278 | debug、GVM、计数输出 `logging_debug_flags` | 源码配置 | 本次保持不变或不计入 | 影响仿真开销/实现形式但非设备架构性能可调参数 | [源码](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L11) |
