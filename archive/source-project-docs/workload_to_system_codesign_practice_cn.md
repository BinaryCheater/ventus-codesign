# Workload-to-System Co-Design：实验实践规范

版本：v0.11，2026-09-24；独立 Ventus 补充：2026-10-06。受限命令后端提供汇编、固定内存与端口、完整 Transformer 执行及模型成本反馈；无 RTL/物理校准。第 1–11 节保留默认解析后端规范，第 12 节为命令后端，第 13 节保留初轮难度标定，第 14 节为固定输入的联合空间与分块程序族，第 15 节记录可编程挑战的两场景实现与发布证据；默认成本与求解行为保持不变。本文为当前工程与实验流程的权威说明。

配套阅读：[数学推导](workload_to_milp_derivation_cn.md)、[需求与验收](requirements_cn.md)、[总体设计](workload_to_system_codesign_v2_cn.md)。历史结果单独放在 [experiments/](experiments/prototype_20260922_cn.md)，外部材料放在 [references/](references/README.md)。

## 1. 实验问题与当前状态

核心问题：在固定 Transformer 语义和有限硬件模板下，自动生成合法 tile/region 实现空间，联合选择计算边界、实现方式、资源数量和调度，能否得到可验证、可解释的设计折中？

第一阶段检验工程闭环；第二阶段才检验结构选择与联合优化的收益。不能因为输出一个好看的 schedule 就宣布研究假设成立。

| 能力 | 当前状态 |
|---|---|
| 配置 → typed DAG → 参数化候选 | 已实现 |
| region covering、实现、资源数量、启动时间联合 MILP | 已实现 |
| 字节级 SRAM 生命周期、资源与带宽限制 | 已实现，采用明确的聚合/保守假设 |
| 导出结果、只读复验、数值差分、tile 覆盖检查 | 已实现 |
| latency 优先、证明后 area tie-break | 已实现；并非每次运行都能证明最优 |
| 三类 fusion 模式与面积扫描入口 | 已实现入口；受控实验结论待完成 |
| 任意 placement/route、在线 softmax、重计算、RTL 校准 | 未实现 |
| 命令汇编 → 硬件行为/周期模型 → 成本反馈 | 已实现独立受限后端，见第 12 节；不替代 P2 |
| 前端展示 | 独立任务维护；不属于本轮后端改动 |

## 2. 冻结 workload contract

默认实例：B=1，S=32，D=128，H=4，head width=32，FFN width=512。

计算语义为：

\[
N_1=LN(X;\gamma_1,\beta_1),\quad [Q,K,V]=N_1W_{qkv}
\]
\[
P=softmax(QK^T/\sqrt{D/H}+causal\ mask),\quad Z=X+(PV)W_o
\]
\[
Y=Z+GELU(LN(Z;\gamma_2,\beta_2)W_1+b_1)W_2+b_2.
\]

- FP32 执行；LN epsilon=1e-5；GELU 固定 tanh 近似。
- QKV/output projection 无 bias；FFN 有 bias；两次 LN 有 affine 参数。
- Softmax 做完整行归约，先 scale/mask 再稳定指数归一化。
- 单次 prefill；不含训练、dropout、KV cache 或跨 block 优化。
- 每次求解固定 shape。改变 shape 后重新构图与生成候选，不改核心 solver。
- reference 使用 Float64 完整算子；执行使用 FP32 tile。默认比较 `abs(error) <= atol + rtol*abs(reference)`，atol=5e-5、rtol=1e-4。
- 测试输入使用记录的 seed；吞吐与调度成本不依赖这些随机 tensor 数值。

`workload.py` 生成 14 个语义节点。typed DAG 的类型信息包括 shape/dtype，边表达 tensor 依赖；节点边界不要求成为最终 kernel 边界。目前支持固定 Transformer 前端，尚无任意 Python/ONNX 导入器。

## 3. 四部分输入与单一配置源

唯一默认配置为 [specs/transformer.yaml](../specs/transformer.yaml)，包含四个 section，暂不拆成多个容易不同步的文件。

| Section | 定义什么 | 不应混入 |
|---|---|---|
| `workload` | 数学语义、shape、dtype、容差与数值 seed | engine 数量、schedule |
| `hardware` | 资源类型、能力、成本、数量范围、tick | 某次求解的答案 |
| `rules` | tile/engine/channel 候选范围、允许的融合规则族 | 每个 shape 手写的结果菜单 |
| `experiment` | 面积/功耗预算、求解时限、gap、solver seed、可选 horizon | 未经说明的跨实验参数变化 |

配置在读取、CLI 覆盖之后及求解入口校验。非有限参数、非法 dtype/shape、分数资源数量、重复菜单、非正时限等均拒绝。

## 4. 硬件抽象级别

采用参数化微架构资源级：基础算术单元内部固定，资源数量和实现映射参与优化。

| 资源 | 默认数量范围 | 模型含义 |
|---|---:|---|
| Matrix | 1–4 | 矩阵计算；每个 engine 带固定 64 KiB 本地 scratchpad |
| SIMD | 1–1 | 通用向量/软件实现；当前默认固定一个 |
| SFU | 1–1 | 归一化、指数、GELU 等特殊函数；当前默认固定一个 |
| epilogue | 0–2 | 可选融合专用资源，单独计面积和功耗 |
| shared SRAM bank | 1–20 | 每 bank 64 KiB，另提供一个带宽单位 |
| HBM channel | 1–4 | 外存带宽单位，同时限制传输并发 |

默认成本为 `toy-analytical-v1`，仍为未经实测校准的解析假设。历史 `toy-analytical-v0` 的成本语义与快照保留。面积/功耗包含固定控制互连开销；Matrix 的单位成本按包含本地存储的整体 toy 单元理解。HBM 面积指片上接口成本，不包含封装内完整外存芯片。

固定拓扑为 HBM ↔ shared SRAM ↔ compute。所有跨 region tensor 保存在 shared SRAM；不搜索任意 route、layout、eviction/reload。HBM channels 同时充当传输并发限制，没有独立 DMA engine 数量变量。

每个计算阶段预留一定数量的 SRAM 带宽单位。聚合带宽单位不绑定具体地址 bank；不宣称模拟了 bank mapping、端口仲裁或物理互连拥塞。

当前软件/硬件边界通过 SIMD/SFU 软件候选和 Matrix/epilogue 候选表达。每次启动、显式传输、数据就绪依赖有成本/约束；默认解析后端未实现任意布局转换、独立同步指令延迟、真实 ISA 或微码生成；第 12 节新增固定命令 ISA 及 QKV/context 布局搬运。

## 5. 从语义生成有限候选

### 5.1 Tile view

MatMul 表示为 `C[I,J] += A[I,K] @ B[K,J]`。当前用一个标量 tile size 同时控制 M/N/K 三轴，默认 16 或 32；尚未开放三个轴独立取值。尾块按实际索引处理，K 分块按升序累加。

Matrix 本地工作集按 `3*tile*tile*4` bytes 检查，表达输入块和 accumulator 的简化占用。这个公式属于 toy 模型，不替代 RTL 存储分析。

### 5.2 三种候选模式

| 模式 | 允许的候选 |
|---|---|
| `none` | 独立语义算子，矩阵/SIMD 实现和 tile 选择 |
| `local` | 加入 MatMul+Bias、MatMul+Bias+GELU、Residual+LayerNorm |
| `pipeline` | 进一步加入 FFN 行块双缓冲流水 |

规则匹配图结构与数据接口，再根据 shape 和资源范围实例化。tile、engine group 与合法模板自动组合；没有按默认 shape 手写 91 行 catalogue。

融合必须保留所有外部消费者仍需的输出。例如 `res1+ln2` 同时输出 Z 和 N2，因为最后的 residual 还要读取 Z。Bias/GELU 必须位于对应输出的完整 K 归约之后。

### 5.3 候选的可执行内容

每个 choice 包含：covered nodes、外部 inputs/outputs、implementation、tile、engine group、内部 stages、临时存储、HBM/SRAM traffic 与规则证据。

每个 stage 保存固定相对 offset、正整数 duration、资源需求与未取整 raw_us。候选时长等于最后阶段结束时间。MILP 选择候选及整体启动时间，不再次自由调整内部阶段。

FFN 流水按行块生成第一层输出，执行 Bias/GELU，再交给第二层计算。最多同时持有两块中间行缓冲；第 b 块复用缓冲前等待第 b−2 块完成。不同阶段可重叠，但重叠资源需求必须相加。

当 S 不大于 tile size 时，只有一个行块；不能仅根据 implementation 名称宣称发生流水加速。

## 6. 成本、搬运和存储口径

1. 计算耗时在 `costs.py` 预计算。v1 将完整输出 tile 的 K 归约分配给阶段内当前工作量最少的抽象 Matrix engine，以最大 engine 工作量计算服务时间。`compute_memory_overlap=max` 默认假设计算/存储充分重叠；`sum` 用于无重叠敏感性检查。两者均非实测上下界，再加启动开销并向上取整到 tick。
2. 输入和每份参数各有显式 HBM load；输出有显式 writeback。weight prefetch 可以与无依赖计算重叠。
3. HBM transfer 的速率为 `min(channels*HBM_rate, SRAM_rate)`，当前每个 transfer 固定占一个 SRAM 带宽单位。
4. HBM 流量只记在 DMA；kernel 计算成本记其内部 SRAM 服务，避免同一 HBM 搬运重复计费。
5. SRAM traffic 是简化的 tile 访问估计；融合仍计行缓冲读写，不能把融合误写成所有中间访问都免费。
6. 边界 tensor 从 producer/load **启动时分配**，一直保留到最后一个外部 consumer 完成；producer 完成前不可读。
7. 内部 temporary bytes 在整个候选活动期间保守预留，包含双缓冲。融合消除的内部完整 tensor 不再作为外部驻留对象重复计数。
8. 固定的配置功耗约束不等于瞬时峰值功耗，也不等于 energy。v0 未提供独立 energy 目标或可靠性模型。

默认 HBM 单通道为 16,384 bytes/µs、单 SRAM 带宽单位为 32,768 bytes/µs。因此两个 channel 已达到单次 DMA 的 SRAM 速率瓶颈；允许四个 channel 不保证该 DMA 更快。

### v1 成本审计与边界

- 专用 epilogue 的普通/特殊操作吞吐与启动成本成为显式配置；默认仍为 toy 假设。每个行块融合 bias 按读取一遍完整 bias 向量计 SRAM 流量。流水末尾占用 SIMD 的 bias 按 SIMD 吞吐及启动成本计费，修正 v0 使用专用 epilogue 吞吐的问题。
- stage 新增可选 `cost` 明细，记录计算、SRAM/HBM 服务、启动、重叠策略和抽象 engine 分工；`cost_audit.json` 汇总全部候选并标记最终选择、tick 取整开销及未建模因素。Residual+LN 仍按串行子操作节约一次启动计费。
- engine 编号只在单个 stage 内有效；行块坐标为局部坐标，`row_origin` 记录原行偏移。没有物理 engine 绑定、本地读写时序、bank/地址/端口映射、互连拥塞或指令发射模型。数值执行未按这些抽象 engine 并行运行。
- 旧 v0 保留原生成成本用于历史比较；`--verify` 始终只读冻结 stage。v1 实验使用新目录与 hash。重叠策略只改变计算阶段服务组合，DMA 仍用 HBM/SRAM 瓶颈速率。
- 动态 stall 协议、资源/buffer 复用事件与物理映射检查按路线图 F 方向后续建设；当前 verifier 与事件重放仍针对固定模板时序。

## 7. MILP 与求解流程

数学展开见 [推导文档](workload_to_milp_derivation_cn.md)。实现步骤为：

1. 按语义节点 exact cover，选择兼容 region；每个被选 region 恰好选择一个 choice 和启动 tick。
2. 选择各硬件资源数量，约束数量范围、面积和配置功耗。
3. 激活选中 region 的外部依赖；内部依赖已包含在模板。
4. 把候选 stage 资源曲线平移到启动时刻，逐 tick 限制总需求。
5. 用累计启动/完成变量推导 tensor residency，逐 tick 限制 SRAM bytes。
6. writeback 完成时间约束 makespan，先最小化 latency。
7. 只有 latency 的整数下界已经闭合，才固定该 latency 并最小化 area；记录第二阶段自己的 status/gap。

`warmstart.py` 提供串行和确定性 list scheduling 候选，经资源/内存检查后选一个可行上界。warm start 只是给 solver 的 incumbent。

若有长度 H 的可行方案，最优 latency 不会超过 H，所以可以安全地只保留结束不晚于 H 的启动变量。若没有可行初始解，要求显式给出 `--horizon`；若人为给得更短，标记 `horizon_scope=explicit_restricted`。此时 optimal/infeasible 的声明均只针对这个有限窗口。

求解器限时、gap 阈值、seed、线程数和版本要记录。达到配置 gap 阈值与严格整数 latency 最优分别报告。默认单线程；相同配置可能存在多个等价 schedule。

## 8. 独立检验与实际执行

### 调度 verifier

只消费图、冻结 catalogue、导出 solution 和硬件配置，不读 MILP 的约束对象。重新检查：choice membership、region/choice 一致性、语义覆盖、load/writeback、时长、数据就绪、逐 tick 资源、SRAM、预算和报告值。

### 数值与索引检查

执行器实际运行所选 tile 和融合计算；不能直接用完整 matmul 充当待验证的分解。记录每次 GEMM 的索引块，检查输出区域不重不漏及 K 分块完整、有序。FP32 输出与 Float64 reference 比较。

reference 与执行器共享可信的 LayerNorm/Softmax/GELU 数学函数；MatMul 路径不同。因此差分检查可以检测分解/组合错误，但不能独立证明共享 primitive 公式本身正确，也不构成所有输入的形式证明。

Python 数值执行按合法顺序求值，不模拟硬件上真正并行的线程。调度合法性由 verifier 与事件重放检查；Python 进程占用的 RAM 不作为硬件 SRAM 测量。

### 事件重放

按阶段生成 acquire/release，区间为 `[start, finish)`，同 tick 先释放后获取。当前使用同一组局部阶段成本，仅是内部一致性证据。未加入另一套经过校准的 latency 模型或随机 stall。

## 9. 结果接口与复现

既有 JSON 文件名和核心字段保持兼容，前端可继续读取。新增字段采用增量方式；本轮不修改 `frontend/`。

| 文件 | 内容 |
|---|---|
| `config.json` | 已应用 CLI 覆盖的配置 |
| `instance.json` | semantic graph 和完整冻结 catalogue |
| `cost_audit.json` | 新运行的逐阶段成本、取整、抽象分工、选择标记和未建模范围；不构成校准或物理映射证明 |
| `manifest.json` | schema、config/instance/code hash、版本、fidelity、run_state |
| `solution.json` | feasible、hardware、schedule、makespan、metadata；可行时补 lifetimes/traffic |
| `verification.json` | 检查结果、逐 tick 占用、重建生命周期 |
| `functional.json` / `output.npy` | 数值误差、tile trace / 实际输出 |
| `simulation.json` | 阶段事件与重放结果 |
| `summary.json` | 简明性能、规模、状态和求解统计；无可行解也保存摘要 |

新增 solver 诊断：latency objective/bound/gap、B&B nodes、simplex iterations、integrality/primal violation、latency/area 分阶段状态、warm start 是否实际提交及是否改善、horizon_scope。

非有限统计量写成 JSON `null`，不把 unavailable bound 写为 0。每次使用新目录，非空目录拒绝覆盖，JSON 文件原子替换。manifest 的 run_state 为 running、complete、no_feasible_solution 或 failed；旧快照缺少 run_state 时可用完整文件集与检查结果识别。

`--verify RUN_DIR` 读取原始 config/instance/solution 并核对配置和实例哈希，运行当前独立检查与数值路径，不调用 solver，不修改快照。原始 code hash 与当前 verifier hash 分别输出。哈希用于一致性检测，不是外部真实性或数学证明证书。

## 10. 受控实验协议

先冻结 workload、成本版本、primitive/rules、tick、solver 版本、时限和容差，再做下列实验。当前历史单次运行不替代这些对照。

| 实验 | 只改变什么 | 记录与可能的解释 |
|---|---|---|
| E0 正确性 | 小 shape、尾块、不同融合候选、破坏样例 | 数值/索引通过；非法覆盖、早读、提前释放、资源超限被拒绝 |
| E1 HBM 敏感性 | 默认成本下，HBM max=2 与 1 | 对照预取、等待、资源数和 latency；不预设一定显著变化 |
| E2 结构消融 | none / local / pipeline | 相同预算、硬件菜单和数值语义；报告实际选择、流量和缓冲 |
| E3 面积折中 | 多个 area budget | 报告非支配 incumbent、各自 bound/gap；不把粗扫描称作完整前沿 |
| E4 参数化 | 改 S 或 D/F，其余契约不变 | 自动重新生成 shape、流量、候选，无需修改 solver 核心 |

E1 的 HBM=4 与 2 可另作“SRAM 服务率已饱和”的对照。当前 generator 会随上限过滤非法候选，变量数可能不同；这与参考报告只改资源上界、保留变量的做法不同，必须记录。

所有对照保存 warm-start latency、最终 incumbent、bound、gap、耗时、硬件、调度、流量、内存和验证状态。不同硬件的串行方案只能作为运行起点，不能当作隔离 fusion 收益的公平 baseline。限时未改善不是证明该自由度无价值；无解点不可静默丢弃。

## 11. 工程要求与完成标准

当前后端质量检查命令：`ruff check codesign tests`、`ruff format --check codesign tests`、`pytest -q`。测试覆盖数学正确性和结果可信度；不依赖完整 Transformer 在固定秒数内证明 optimal。

分三层验收：

- **P0 原型闭环**：自动候选、联合模型、可行导出、独立检查、实际 tile 执行、小实例最优对照。已完成。
- **P1 研究 MVP**：完成 E1–E4，解释结构变化与瓶颈，区分最优和限时可行；至少出现并验证有意义的设计折中。待完成。
- **P2 实现锚点**：至少一个 primitive/region 的 RTL 功能与综合校准；记录工艺/器件、时钟、存储宏与成本误差。待完成。

原草案的“完整 MVP”含实现锚点，因此 P0 通过不能宣称整套 MVP 已完成。扩展自由度时，要同步增加 legality、约束、verifier 和实验条目；优先提高现有模型可信度，再扩大搜索空间。

## 12. 命令模拟器后端（已实现，独立成本版本）

入口 `--executable` 以相同 Transformer 数值契约建设一条独立路径。`specs/command_target.json` 声明 `toy-command-v1` 服务参数；`input_config.json` 保存原始输入，转换后的 `config.json` 明确硬件/规则的实际范围。默认配置 pipeline 在此入口限制为独立算子与 MatMul+Bias，显式 `--fusion pipeline` 拒绝；不尝试降级旧解。

### 机器与数值范围

- 一个固定 2 MiB SRAM 地址空间和共享服务端口、一个 DMA/HBM 服务、1/2 个 Matrix、一个 SIMD 和一个 SFU。默认每周期 64 MAC、16 个 Matrix 内置 bias 操作、16 SIMD 操作、2 特殊操作、64 SRAM bytes、32 HBM bytes；每命令计算/传输启动 4 周期，假设时钟 100 MHz。均为 toy 参数，无硬件库来源。
- Matrix 每个输出 tile 的完整输入 panel 和 accumulator 暂存在 256 KiB 本地缓冲；升序 K tile 累加。超过本地容量的候选过滤；若无法覆盖节点则拒绝运行。Matrix 的 toy 单价沿用配置系数，但本后端将其视作包含本地缓冲与 bias 加法能力的整体假设，不构成 SRAM/IP 面积估计。
- 为全图 tensor 和 QKV/context 转换缓冲分配连续、互不重叠的地址。全程不复用，融合消去的中间 tensor 仍保留地址；容量按完整静态 map 检查。默认占用 1,282,560 bytes。固定 SRAM 单价按原配置每 bank 容量等比例缩放；不搜索 bank 数或端口数。
- `MATMUL/MATMUL.BIAS` 为输出 tile 命令；`ADD/GELU/LN/SOFTMAX` 为行命令；`LAYOUT` 显式搬运 QKV/context 布局。LN/Softmax/GELU 以 NumPy 执行明确的 FP32 数值操作并计服务量，内部浮点电路尚未实现。
- 每条命令包含事件、engine、输入/输出地址 view 和算术参数。汇编格式为 `OPCODE JSON描述符`，`WAIT` 等待先前事件，`HALT` 等待未完成队列排空。循环在代码生成时展开；取指、解析和 WAIT 本身假设零周期，队列可容纳有限程序的全部命令，尚无指令带宽/队列容量搜索。

### 执行、成本与 MILP

每个 engine FIFO 单命令运行。计算命令按“SRAM 读 → 计算 → SRAM 写”推进，在完成写入后发布事件；DMA 同时占用 SRAM 与 HBM，采用瓶颈速率。共享服务按原始发射顺序仲裁，同周期先释放再获取。数值输入从具体内存读取，计算结果写回；缺失/未完成输入、重复写入、越界和无法推进均拒绝。额外固定服务停顿用于协议检查。

专用 emitter 在每个 region 末尾等待其全部事件，因此 region 之间串行，多个 Matrix 仅在 region 内并行。该限制使成本可相加；专用小型 MILP 选择覆盖、tile、engine group 和硬件数量，不引入时间索引。默认受限菜单 52 候选、53 个变量、60 条首阶段约束；原解析模型的 91 候选与时间索引搜索不受影响。算法见推导第 17 节。

两次求解分别使用：

1. `command-estimate-v1`：每个 region 按各 engine/共享服务忙碌总量的最大值估计理想重叠周期。
2. `command-service-v1`：由孤立 region 的事件执行得到包含依赖与仲裁的周期，反馈后重新求解。

首次候选生成即收集两类成本，先用理想估计求解和执行，再将已采集的 region 周期反馈。该流程不进行真实硬件参数学习。在确定服务、串行 region 与相同发射顺序下，反馈后全程序周期应与 region 周期之和一致；两者共用服务假设，不能当作独立性能校准。执行器不读 solution、candidate duration 或 MILP 开始时刻。

### 产物与复验

每次命令实验新建目录，含 `initial/` 与 `feedback/`，以及顶层 `comparison.json`。各阶段保存 config、instance、solution、target、program.asm、memory_map、inputs.npz、output.npy、execution_trace、simulation_report、verification、functional、summary 和 manifest。manifest 保存代码及配置/程序/输入/实例/方案哈希；原解析 JSON 文件语义不变。

`--execute-program STAGE_DIR` 读取文件运行汇编并比较输出，不读 solution；调试自写汇编时使用单独目录。`--verify STAGE_DIR` 额外核对冻结哈希、所选方案与汇编一致性，不求解、不修改快照。固定默认和尾块实例、手算周期、停顿、端口不重叠、非法程序与哈希篡改均纳入回归。实验见[命令 MVP 记录](experiments/command_mvp_20260923_cn.md)。

Icarus Verilog、Verilator、Yosys 已在当前环境发现；本轮未调用综合/RTL 仿真，也未从其输出提取成本。后续硬件库与约束就绪后，以 MatMul+Bias region 建设功能与综合锚点；R12/P2 保持待完成。

## 13. 课程研究问题的难度标定（2026-09-23）

独立实验脚本位于 `scripts/difficulty_*.py`，报告见[课程难度标定](experiments/course_difficulty_20260923_cn.md)。不修改默认 solver、候选成本或历史快照。本轮按嵌套设计菜单与扩大 workload 分组，采用 20/180/600 秒的每求解阶段预算，记录 phase-aware 轨迹、独立验证和端到端墙钟；证明 latency 后面积阶段另计，因此每阶段限时不等同总运行限时。

比较三个方面：原 MILP 的可行值/下界曲线、领域候选或预取调度简化的实际可行值、依赖与资源工作量松弛给出的原空间下界。简单档用来确认直接求解即可完成；领域简化的价值只在复杂档、同一问题与明确预算下评估。完整下界与子空间下界分别记录；求解器 gap 和最好已知解差距分别分档为 0、2%、5%、10% 及更差。

当前标定覆盖单 block FP32、有限候选、硬件数量和静态调度。MAC 阵列尺寸、独立 M/N/K tiling、自由汇编及逐活动能耗尚未纳入这次评估。结果用于选择研究代理问题，不能宣称已经标定多层 Transformer 的 token/(面积×平均功耗) 开放程序搜索难度。配置功耗不替代平均运行功耗。

新辅助下界的必要约束与证明见[推导 §18](workload_to_milp_derivation_cn.md#18-难度标定的辅助下界与领域简化实验工具)，测试见 `tests/test_difficulty_bound.py`。启发式产生的结果仍通过原 verifier、数值执行及事件重放，脚本和候选来源随新结果冻结。失败的初始菜单、修正后的嵌套关系及随机对照均保留，不只报告成功方案。


## 14. 固定 workload 的联合候选空间标定（toy-course-v1）

本轮按用户澄清固定 B=1、S=128、D=128、H=4、F=512 的单个 Transformer block，FP32 causal prefill。各档只开放硬件/程序菜单；不通过改变输入制造难度。入口为 `codesign/course.py` 与 `scripts/course_search.py`，结论见[固定输入报告](experiments/course_fixed_space_20260923_cn.md)。旧第13节及历史快照保留，但其中 workload 扩张结果不用于本轮难度选择。

硬件变量为 cluster 数、MAC 阵列行列、每 cluster 输入 SRAM 与 accumulator 容量、共享 SRAM 总量、bank 数、外存通道数、向量宽度。六个 GEMM 各自选择 M/N/K tile、OS/WS 数据流与双缓冲，另有有限融合和预取窗口。软件候选是有限程序族，尚未允许任意汇编。

成本版本为 **toy-course-v1**：FP32 MAC 3 pJ、local byte 0.15 pJ、共享 byte `3*(1+0.03*log2(KiB/256))` pJ、外存 byte 30 pJ、普通/特殊向量活动 1/5 pJ、启动 2000 pJ；500 MHz，2 µs 时刻粒度，泄漏 `0.025 W/mm²`。矩形尾块计实际激活的阵列 padding；OS/WS 分别计重读与部分和流量；双缓冲使用额外容量且允许计算/访存重叠。系数为未校准的教学假设，与旧 toy-analytical-v1 无数值可比性。

评分明确为 `(token/s)/(mm²*W)=128/(A*E)`，E 使用焦耳，包含逐活动动态能量及 `P_leak*T`；约束 `A≤20 mm²`、`T≤1000 µs`。必须同时输出 A/T/E 和有效分数。面积公式、能量与上界推导见第19节。bridge 仅为复用旧独立 verifier 的资源接口，快照实际成本版本仍是 toy-course-v1。

所有方法共用可行性接口、初始解和必要条件筛选。L4 的整 tensor 程序必须具有至少 640 KiB 共享驻留，因此256/512 KiB均可公开排除；不让随机方法浪费预算于已知必错硬件。记录抽样总数、可行数、规范化去重数、单次随机质量、累计最好值与冷热启动时间。2000评估次数与20/180/600秒墙钟分别比较；并行运行时记录主机争用条件。领域 proposal 的代码开发时间不计搜索墙钟，不能宣称为端到端 LLM agent 加速。

小档完整穷举确认最优。大档必须同时报告最好已知值与原空间有效上界，`J/U` 才是认证质量；最好已知值不充当上界。最终审计中完整 L4 被逐算子松弛与硬件界筛选在数秒内闭合，有限程序族最优为120261.947117。该结果否定“标签数量巨大就适合作为难题”，也否定仅靠普通启发式限时未收敛来宣布题目困难。记忆开/关消融暂未体现额外收益。


### 14.1 分块驻留扩张（toy-course-v2）

`codesign/course_v2.py` 保持相同workload、全部硬件菜单和primitive活动单价；新版本区分程序族与活动计数变化。新增head_group∈{1,2,4}、ffn_rows∈{8,16,32,64,128}、head/row depth或breadth优先级、逐source预取、每个matrix chunk独立矩形tile，以及FFN权重retain/reload。head组完整归约再做该组softmax；FFN以完整输入K归约的行块推进，不采用online softmax或改变数学任务。

共享SRAM按chunk分配/最后使用释放；输入N2及权重retain模式仍保持完整tensor。reload模式逐row显式加载W1、执行up后释放，再加载W2执行down；行间gate和W2等待H确保两份大权重不提前重叠，重复外存字节与DMA启动逐份计费。向量不免费访问本地accumulator，shared行缓冲流量照常收取。该模式是有限的顺序重载程序，不代表一般自由的spill调度。

group4/row128/retain且无逐源或chunk覆写时，v1全部none/local融合、预取程序仍被包含，分数/活动/时长/驻留完全相同。v2所有matrix任务仍占配置全部clusters，其他engine任务可以与其交错；优先级只有两种模板。任意任务cluster分配、具体地址/bank映射和任意汇编仍未开放。

旧640KiB必要条件失效。QKV阶段仍完整同时分配输出，需要X64KiB+N1 64KiB+Wqkv192KiB+QKV192KiB=512KiB；256KiB配置可以对所有搜索方法统一排除。v2粗界只保留必需MAC/外存/泄漏与该512KiB条件，不能直接调用v1串行链紧界。预验证已实际解锁512KiB，调度、chunk覆盖和FP32数值检查通过；正式难度结论以独立报告为准。


### 14.2 并行任务扩张原型（toy-course-v3，尚无正式难度排名）

`codesign/course_v3.py` 在v2上增加每matrix chunk的cluster配额（1/2/4且不超过物理配置）及任意整数任务优先级；每次从拓扑ready的任务中选优先级整数最小者，缺省顺序与v2一致。逻辑配额只影响该stage计算/带宽需求及活动量；面积、静态容量和泄漏始终按完整物理硬件收取。空覆写严格恢复v2。已用2cluster物理硬件验证两个1cluster矩阵chunk实际重叠，原调度verifier及数值重组通过。

v3当前仅完成能力与回归，尚未做正式搜索/难度对照，不据此提高最终题目难度等级。v2中“所有matrix stage串行”的上界推导不可沿用；必须使用针对部分cluster任务重新推导的资源工作量界。有限tile图与优先级也仍不等同任意汇编。

## 15. 可编程 Transformer 挑战的独立原型（2026-09-24）

缩小场景后的[挑战提案 v0.6](programmable_transformer_codesign_challenge_cn.md)采用独立 `codesign/challenge/` 包，不修改本规范第1–14节的默认解析/命令/课程模型，也不改变旧结果。发布交付为 **M1/P1 四层、128-token prefill 加首个新位置**及 **M1/D1 四层、256-token 历史上下文后连续 16 步 decode** 两份完整可评分汇编，供学生运行和修改。`workload_v06.json` 固定这两个场景及官方 FP32 fixture 生成契约；两份基础指令汇编、FP32 微执行、独立 Float64 参考、2 GiB 稀疏符号地址、硬件菜单/面积、全局事件计时器与只读 HTML 资源展示已有实现。旧 v1 实验依据见[历史发布记录](experiments/challenge_two_case_release_evidence_20260924_cn.md)；当前 v2 的独立正确性与资源展示按[验收](challenge_release_acceptance_cn.md)重新核对。

四层[完整 M1/P1 与 M1/D1 汇编](../examples/challenge/README.md)由基础指令展开 LayerNorm、softmax 和 GELU。旧 `serial-service-v0.1` 的 M1/P1 112,452,822 周期与 `pipeline-cache0-v0.3-experimental` 的 79,210,901 周期仅作历史对照；旧 `pipeline-global-events-v1` 的公开及受信各三组通过、签名与 1000.0 分也只属于[历史 v1 报告](experiments/challenge_two_case_release_evidence_20260924_cn.md)。修正跨组 HBM happens-before 与全局 `STEP.COMMIT` 后，当前 `pipeline-global-events-v2` 的[完整冻结基线](../examples/challenge/release_v06_r3/baseline_manifest.json)仍为 P1/D1 79,210,901/41,235,284 模拟周期，manifest SHA256 为 `a5fbbb50d2d413e6a27b1a1c0b5b7b257783ecec70f1c390810857f115badaf5`；新受信隐藏报告已签发 v2 模型分数 1000.0；本轮功能、评分和资源验收已完成；完整报告只读复算按用户要求提前停止，见[当前发布记录](experiments/challenge_two_case_release_evidence_r3_20260924_cn.md)。公开 `grade` 仍只给 `experimental_score`。旧 v0.4 大形状 reference 烟测仅为历史记录。原始 120,708,403,200 个菜单标签不能视作有效硬件空间或搜索难度。教学系数存于 `codesign/challenge/cost_v04.json`，与 toy-course 和 toy-analytical 版本不可混用。


## vNext Rust 基线补充规范（2026-09-30，blocking-rf-v0.2）

新增独立 Rust 后端 `rust/vnext-sim/`，不改变既有模型或历史结果。工作负载采用[vNext草案](drafts/transformer_codesign_vnext_cn.md)的M规模；完整P/D均由搬运、MMA、Vector、Reduce原语生成并执行，独立Float64参考全量检查hidden和每层新KV。

当前合同为每SM一个驻留工作组、阻塞指令、wave全局屏障、RF/有限HBM/双向NoC；每wave结束释放RF，跨SM重叠HBM写/读必须跨wave建立顺序。Reduce显式申请RF scratch，Vector逐有限宽度组执行，DMA源暂存和返回端口均有限。Cache/SH、多组驻留、异步重叠及完整ISA评分未实现，未知硬件字段直接拒绝。时序、成本和保守假设见[Rust规范](../rust/vnext-sim/README.md)，不能将这个子集的周期作为完整草案周期。

输出使用新目录，记录模型/源码/配置/输出hash；`estimate`不做数值与初始化检查，`check`运行完整参考。功率窗口使用有界环形差分；逐周期推进用于验证事件跳转等价，手算访存与独立能量oracle提供局部模型对照。此阶段没有正式分数、最优性或课程难度结论。


## vNext Rust v0.3 审计补充（2026-10-01）

阻塞 RF 子集升级为 `vnext-blocking-rf-v0.3`：冷重置清空HBM/分配/计时；执行数值错误使机器失效，重置后方可再执行；宿主分配前验证容量，归约非有限结果拒绝。跨SM依赖以实际元素集合判断，允许同line互不重叠的strided读写；只读tensor免建冲突元数据，输入校验保留。硬件运行期间只读。成本系数不变，完整M有效基线的周期/能耗/输出须逐字段回归。细节、性能和限制见[审计记录](experiments/vnext_rust_audit_20261001_cn.md)。


## vNext v0.4 试解与数值契约补充（2026-10-01）

矩形M/N/K policy、Vector FMA、计费packing和GEMV split-K接入完整M生成器。FMA读旧dst并按4pJ/FMA计费；split-K的部分和HBM写读与合并显式执行。每wave仍≤16384指令，RF工作集先校验。临时HBM副本在完成wave后按逆分配顺序回收，峰值另报；回收会改变后续地址和通道分布。

CLI默认fixture v2 `attention_stress`，在legacy基础上将Q/K投影和历史K乘4，拒绝已复现的均匀attention错误输出；legacy保留历史复验。单次check只验证一个profile，不等同正式多profile评分。ISA内FP32顺序固定，程序跨指令可用split-K等重排并受最终容差约束。完整P/D与X试解、源码快照、资源观测及未决项见[简报](experiments/vnext_codesign_readiness_20261001_cn.md)。硬件成本及100AU/26W/34W不变，不根据受限阻塞模型压低正式功率预算。


## vNext v0.5：结构变量与建模框架（2026-10-01）

policy增加head_group（1..32，默认1）和persistent_keys（默认false）。分组将独立head的QK、softmax、AV按阶段共同分配到SM，保持wave屏障；持久化转置K在HBM保存额外副本，首次历史转换、每步追加及规范K输出均执行原语并计容量/流量/功率。无免费预格式化输入或异步能力。gemm_many每批最多32个独立job，跨job输出到输入依赖拒绝，临时副本在全部使用完成后逆序释放。原硬件价格和时序规则不变。

课程目标是可运行的agent建模闭环：发现结构及变量、生成约束/成本模型、产生可执行程序、用预测误差修正模型，并在公开规则的新实例迁移。无需保证建模比经验搜索更强。应分别评估同一任务的结构竞争和不同任务的优势区间，参数标签或面积Pareto不代替性能主目标上的多样性。原始强试解、条件下界与尚未覆盖范围见[结构多样性报告](experiments/vnext_structural_diversity_20261001_cn.md)；完整SH/Cache/异步及正式安全IR入口仍未实现。


## vNext v0.6：付费SH与可选TC直供（2026-10-01）

阻塞执行子集升级为`vnext-blocking-sh-v0.6`，新增sh_kib、sh_banks、sh_tc_bw及HBM↔SH、SH↔RF、B从SH读取的MMA。沿用草案的容量、面积和活动单价，完整面积进入基准功率。SH每wave重新初始化，每SM私有，RF/SH之间的数据搬运和部分和暂存必须显式执行；仍无Cache、多工作组或指令级异步。局部流水、HBM返回接收预约、接口时序及语法以[Rust规范](../rust/vnext-sim/README.md)为准，不能混同完整草案仲裁模型。

新程序按K块推进，使用SH中的B panel服务多个输出行块，显式暂存跨K块部分和；可用付费接口免去B的RF暂存。仅加SH可能变慢，较大复用组也可能降低并行度。完整M和公开长度迁移已出现RF与SH路线的竞争及赢家反转，证据见[SH试解报告](experiments/vnext_shared_reuse_20261001_cn.md)。静态成本±25%再计费只改变面积及关联基准功率，不是重新选硬件或完整成本重优化。旧结果目录/hash保持不变。


## Blocking-SH 首发规范（2026-10-01，static-sh-v1）

首发范围以[vNext最终契约](vnext_challenge_release_cn.md)为准，计时保持vnext-blocking-sh-v0.6，crate v0.7新增静态提交/评分接口。原完整草案中的Cache、多组与异步延后，不再作为这个明确缩小范围版本的发布承诺；完整草案验收仍未完成。

学生提交固定hardware/shape的prefill/decode NDJSON。评测器生成输入，source只允许绑定一次，未来decode输入在前一步hidden与全部新KV通过后释放；alloc只能获得未初始化空间，计算/搬运必须由原语执行。提交不得包含数值fixture，也不会被编译或作为宿主插件加载。离线export是方便修改的参考生成器，任意其他生成器可产生相同公开IR。外部程序与原生基线的数值/所有资源报告有逐字段对照。

主赛固定M，双seed×双profile×P/D完整核验后计几何平均性能指数，参考周期冻结，1000不封顶。数值测试非任意输入证明，教师必须私有seed受信复算相同program hash，公开日志不得泄露私有seed。方法评价要求测前预测、搜索空间判断、修正与消融；不以调用MILP或胜过经验法为合格条件。

JSON行/文件、累计工作量/指令、live tensor和HBM上限在执行前或公开边界检查；不额外限制单wave工作量，以免把合法SH复用强行拆成清空局部存储的wave。Linux外层4GiB地址空间/600秒墙钟与CPU防护，具体原始证据、独立试解与未获证明结论见[验收](experiments/vnext_release_acceptance_20261001_cn.md)。


## vNext v0.8 多实例研究规范（2026-10-01）

新增独立`vnext-explore-v0.8`构建：五项workload、共享参数batch、独立请求attention、时间优先KV及层scratch付费回收；数学语义/输出容差保留首发。TC按PE与边界计价，宽阵列必须受RF/bank/接口供数限制，RF/SH增加容量相关延迟。具体菜单、成本公式和宿主预算见[研究契约](drafts/vnext_workload_hardware_v08_cn.md)。默认构建保留v0.6机器时序，explore拒绝首发静态评分契约。

实践采用完整FP32执行与独立f64参考，CPU/内存双预算调度独立进程，参考逐行并行不改变归约顺序。20项完整校验与15项结构路线测试、负例、失败轮次和源码快照见[评估记录](experiments/vnext_explore_evaluation_20261001_cn.md)。当前是可信生成器研究入口，batch静态提交、正式评分参考及恶意复杂程序宿主边界仍待验收。


### v0.8 资源边界补充（2026-10-01）

fixture只分配当前场景可见的张量，以计数跳跃保留被省略张量之后的随机流。Prefill不分配history KV/未来decode输入，Decode不分配prompt；该修复不改变数学或成本语义。八路W-D4L、超长wave与低效事务压力通过，OOM和wall timeout后队列继续运行；详见[极端报告](experiments/vnext_extreme_stress_20261001_cn.md)。macOS未执行Linux同等地址空间限制，研究wrapper也不等同任意宿主代码沙箱。


## vNext 并发扩展 v0.9（2026-10-02）

独立模型`vnext-concurrent-v0.9`与静态协议`vnext-static-v09`恢复多TC、K并行、专用归约、SH端口、DMA队列/引擎、Cache、多播和工作组驻留。23项硬件及参考生成器策略、五workload、成本与事件时序以`vnext_v09_author_delivery_cn.md`为完整新契约。500MHz、100AU、动态100/10000周期功率窗34/26W；多单元共享端口并计活动，显式配额与等待决定合法并发。Cache固定256 MSHR并支付每槽面积，避免32槽/250周期造成额外吞吐封顶。

学生离线生成五个静态JSONL，评测器不运行其宿主代码；同硬件、固定shape、按step释放输入、完整hidden/KV和私有seed重评。参考周期为187689274/374856358/27068433/42358913/70439292（W-P/A-P/D1/D16/D4L），分数为1000倍加权加速比几何均值；两P各1/4，三D各1/6。模型/源码hash须随报告保存，旧版参考与分数不混用。Linux进程级CPU/内存/墙钟约束保证失败隔离，模拟HBM容量不代表宿主RSS。硬件为教学假设，无RTL校准或全局最优结论。


### 2026-10-02：独立题目在线 attention 预算实验

[实验记录](experiments/online_attention_budget_20261002_cn.md)复现了局部wave指令预算排除容量合法在线attention的问题。独立Rust `long-waves`实验feature放宽程序表达上限，保持硬件成本/时序与现有MILP约束不变；正式v0.9协议仍保持原规则。完整五项Transformer回归前不作为发布验收完成。面积仅增加1 AU=0.25 mm²展示标尺，无成本语义变化。


### Phase Two compact 竞争元数据修复（2026-10-02）

模型`phase-two-compact-v2`将跨组HBM竞争表中的同组连续/重复访问合并，单组跳过跨组表；执行指令、能量和周期不合并。数学上保留各张量/组/读写种类的精确地址集合，其跨组写读/写写交集不变。多组最多保留262144区间，属于宿主工程上限。DMA/SH-RF源目的形状须相同，目的行连续且互不重叠；建模时不得假设免费reshape/scatter。回归须覆盖重复写超过旧上限可通过、跨组冲突仍拒绝、跨步读空隙精确保留。详见[紧凑程序契约](phase_two_compact_contract_cn.md)。原成本系数与MILP核心不变。


## Ventus 源码事件模型补充规范（2026-10-06）

Ventus 快模型接入完整 Transformer 的目标为 GPU 数据路径的时序覆盖，执行器不计算张量数值。图层提供形状、依赖和布局，kernel/可实现的软件模板提供指令、寄存器、地址、lane mask、warp/block 与同步组织；地址和控制相关整数状态仍须保留。数值 reference、预训练权重和文本生成不作为接入前置。配置变化须重新生成时序流，不能固定一次 trace 后只改峰值吞吐。验证以工作量/访问/生命周期检查、路径与背压覆盖、冻结预测后的 RTL 周期对照为主；历史数值验证作为已有程序证据保留。当前 v5 支持范围不因该目标声明扩大。

独立后端 `codesign/ventus` 当前使用版本 `ventus-source-events-v6`，保留既有解析、命令、挑战和 Rust 成本版本。输入包括 29 个硬件字段、3 个外存目标字段，以及带寄存器、地址和依赖的固定控制程序。硬件覆盖后校验；模型与 RTL 参数解绑状态分别输出。尺寸与行为规则来源、性能模拟器/MIP 边界见[主文档](../analysis/ventus_flow_20261006/report_cn.md)。

独立事件执行器从源码阶段与资源预约求周期；有限菜单 MILP 使用条件事件依赖及数据存储/乘法器预算。缓存状态和服务顺序按候选展开，尚无全尺寸的因子化联合求解。模型不计算数值；`program.packed_gemm` 同时生成受限 Ventus ISA 与对应 IR，独立 dense GEMM 参考核验 RTL 输出。预算不等于物理面积。decoded-body 不含主机启动、复位清零及完整取指控制。`cycles` 等待包装器写响应，`outputs.visible` 表示外存写入，LSU 本地确认和 host-finish 不能替代输出可见时刻。

新结果必须冻结模型 SHA256、输入和 RTL 二进制/库版本，写入新目录；`verify` 和准确性脚本的 `--verify` 只读复验，不重新求解覆盖旧解。v2 的 40 次短程序 RTL 与源码快照保留。v3 增加 14 个非零单 warp GEMM 配置，其中 8 个先冻结预测再运行 RTL；复位清零完成、cache 冷态下，计算窗口平均/最大绝对误差 0.72%/3.68%，输出可见窗口为 0.68%/3.58%。有限软件菜单选择的输出周期在 RTL 从 652 降至 348；重复输入 panel 的合法复用是该收益的前提。分散 LDS、立即复位启动、混合多 warp 及全主机窗口仍未完成建模或验证；RF bank 的第二种配置见下述追加对照。源规则修正与旧预测同时保留，不能把事后修正描述成原始盲测。详细接口与数学形式见[实现记录](../analysis/ventus_flow_20261006/search_model/details_cn.md)。

独立 v4 扩展 `operators.fused_operator`，生成 GEMM+bias+ReLU、两层 FFN 与 residual FFN 的实际指令和 IR；跨层 Tensor 布局转换经 LDS/全局内存搬运，计入地址计算和全部访存。`fmax` 来自 FCMP 两级寄存器，执行延迟 2 周期；collector 与写回另计。13 个新程序的输入、模型哈希和预测均先冻结再运行原 RTL，其中 7 项追加配置；数值输出逐位正确，输出可见周期平均/最大绝对误差 0.072%/0.189%，算术完成窗口最大 0.196%，各计算阶段最大偏差 3 周期。五组 FFN 两路径菜单的 MIP/枚举/RTL 排序一致。旧 v3 源码快照与结果保留，14 项 GEMM 预测在 v4 不变；旧分散 LDS 约 3% 偏差仍存在。softmax、完整 attention 与多 warp 融合未验收。

v4 参数审查明确：29+3 是配置字段数，默认硬件复杂算子的误差不代表全参数空间的准确性。每次改变 Tensor/warp 形状须按同一数学任务重新生成时序指令与地址，核对 FLOP/访存及布局；通用 GEMM timing lowering 支持，真实 FFN emitter 仍固定默认形状。日常参数评估无需编译 RTL；RF/LDS 原语和 GEMM 工作量守恒通过无 RTL 的机制检查，固定调度、coalescer 饱和模板与 cache 背压仍限制可靠搜索范围。


v4 增加真实 RF bank 4→8 的硬件对照，模型源码未变，6 个程序的指令/数据与默认配置相同，预测先冻结。RF/collector 子树由 Chisel 重新生成并接回原整芯片；两处写回 bank 编号从固定 2 位改为 `log2Ceil(num_bank)`，原硬件保留。RF 冲突 GEMM 的输出周期从 380 降至 364，预测与 RTL 均减少 16；另五项变化量均为 0。全部数值逐位正确，绝对输出误差最大 3.085%，由原有分散 LDS 误差贡献；不据此验收其它 28 个硬件字段或任意 bank 配置。构建/观测失败批次排除，正式结果与只读复验见[跨配置证据](../analysis/ventus_flow_20261006/search_model/details_cn.md#rf-bank-48-的真实硬件对照)。


追加模块级跨尺寸验证：6 种 `vTCexe` 形状共 768 条指令，无背压执行延迟 8–14 周期、II=1，与源码公式完全吻合；输出背压测试数值/顺序通过，其延迟变化尚未由 v4 的完整队列机制表达。保持 32 lane，局部解绑 LDS 为 8/16/32 bank，40 个读写事务的轮数及返回时刻全部吻合；128 KiB/16 KiB 模块只测试低地址，不验收容量压力或驻留。模块证据与整芯片证据分开声明。v4 的访存预设顺序与 CTA cohort 释放曾有可复现结构反例，v5 修复及剩余边界见下文；全维并发搜索尚未验收。详见[v5 修正与边界](../analysis/ventus_flow_20261006/report_cn.md#v5-修正了什么仍缺什么)。


v5 将解码流改为按就绪状态在线推进，维护 finite collector、弹性计算流水、一项 LSU 输入缓冲、每 warp/SM 在途占用；load 在实际写回后释放 LSU 槽。CTA 驻留资源按 block 单独释放，不等待全部 SM 完成。IR 的 barrier 是一个 block 集体 fence，等待其 IR 前缀退休并阻止后继；尚未转译硬件逐 warp barrier arrival。RF 固定优先级和有限 cache 仍有近似，不能将这些抽象扩写为完整 RTL。

v5 新增 12 次整芯片非零 GEMM 对照（2/4/8 warp × 8/32 TC 指令 × RF 4/8 bank），全部输出逐位正确、逐 warp 实际指令流吻合；窗口是首条 collector 到最后 TC 写回，不含输出 epilogue。2/4 warp 最大误差 2.78%，8 warp 低估 7.12%–16.12%；增加 24 条 TC 时模型/RTL 均增加 384 周期。后者不能替代绝对周期准确性。取指与 CTA 供给未模拟，8 warp 的首条 collector arrival 相差最多 112 周期，保留为反例。弹性 TC 控制逐项匹配 6 形状/12 模式的模块 RTL，包括首尾输出、输入停顿和延迟范围。旧 13 个 FFN/epilogue 重用 RTL 的 v5 回归为 0.041%/0.186% 平均/最大输出误差，明确标为事后复核。

v5 菜单 DAG 记录在线执行选定的服务顺序；MILP 只选择有限候选，不能优化任意发射顺序。条件边改为 `t_v-t_u≥d*y`，未选候选的时钟强制为零；上界用编译图最早执行的最大时刻加一，避免绝对 service-clock guards 的粗求和导致数值误差。24 候选的独立枚举与 MIP 同选 238 周期，日常模拟无需编译 RTL。保留 v4 完整源码、v5 预测时源码及旧收据；后续 MIP 数值修复和来源提取说明改变不影响已冻结的执行预测，复验逐文件检查差异。[v5 证据与复验](../analysis/ventus_flow_20261006/search_model/details_cn.md#v5在线执行与并发对照)。

### Ventus 粗粒度综合成本 v1（2026-10-06）

独立成本包 `codesign/ventus_costs/` 使用 `ventus-synthesis-cost-v1`，与周期执行器分离。统一 ASAP7 7.5T RVT TT 库映射，预算向量为 **Liberty 原始逻辑面积与独立存储位数**；存储叶模块黑盒化，保留容量、组织和实例数，面积不包含其宏、译码和外围。组成基线保留 I-cache、tag、队列、CTA、控制与互连，避免只累加可变算子后漏掉固定开销。ABC 的 1000 ps 目标不作为共同频率可行性证明，时序、宏面积与能耗返回未建模。

查询支持实采的 RF 4/8 bank、六种 Tensor 形状和四种 LDS bank/容量组织；组合通过实采组件差分估计，SM 1–8 使用复制估计并保留默认双 SM 的共享控制/互连。RF 容量、collector、端口、cache/MSHR/LSU 等其它尺寸改变返回 `unsupported`，不得以零成本进入搜索。形状与 bank 解绑状态随结果返回；单模块可生成不证明完整 GPU 的任意组合已实现。

有限候选选择变量 `y_h` 可使用 `mip_coefficients()` 返回的面积/位数系数施加独立预算；`optimize_with_cost()` 在现有恰选一个候选的菜单中先按相同预算过滤，再调用事件 MILP。日常查表无需综合，周期和旧结果语义不变。原始报告、参数覆盖、复验及实验见[成本说明](../analysis/ventus_flow_20261006/cost_model/report_cn.md)。


### Ventus v6：共享浮点与整图模板（2026-10-06）

v6 按 FMA.scala/FPU.scala 将 FADD/FMA 接到共享加法流水，FCMP 与转换路径共享 FPU 输出；4 个冻结后新增的 1/2 warp 实际程序最大计算误差 1.508%，单次 RTL 18–20 秒。新增 `lower_transformer` 与 `transformer`/`verify-transformer`，缩小 FP32 GPT-2 型 2 层 S=16/64 + 两步 decode 时序图完整运行。mask、Tensor padding、持久 KV、私有 LDS 归约和跨 dispatch cache 状态明确进入输入；软件采用有界 tile dispatch 与写 drain/已写行失效，批大小改变程序调度。摘要与详细 DAG 模式使用同一资源递推并有对照回归。exp/Newton/tanh 是未验收精度/ISA 绑定的软件指令模板，完整模型运行不构成整网 RTL 或数值正确性证据。

宿主执行器按测量减少重复就绪扫描、事件对象与历史日历，S=64 同程序配对为 36.10→30.83 秒、周期/指令/计数一致；最终模板 S=16/64 为 9.38/31.97 秒。完整 GPT-2 形状已接入，30 秒执行预算中止，整网 `cycles=null`；仅完成全图工作量统计，不报告完整性能或默认采用层周期乘法。资源字段保持兼容，新增 mask/variant 可选，旧版本和目录保留。范围、源码、路径覆盖及复验见[v6 实验报告](../analysis/ventus_flow_20261006/performance-v6/report_cn.md)。


### Ventus LayerNorm 独立补测（2026-10-06）

v6执行器保持不变，新增4个真实单warp LayerNorm ISA 程序，D32/D64、非均匀与常量输入，包含LDS butterfly、均值/方差、整数seed/4次rsqrt Newton与gamma/beta。有效预测在RTL前冻结，计算/输出可见及23个阶段误差均为0，输出逐位正确。独立机器码解码核对每条实际地址与IR，并对照Float64函数；失败的有符号向量立即数/减法编码批次保留且排除。软件组织与旧整网部分lane归约模板不同，尚未接回整网或验收多warp与全网络准确性。[原始证据与复验](../analysis/ventus_flow_20261006/layernorm_rtl_20261006/report_cn.md)。


### Ventus v7 混合计算/访存与LayerNorm软件绑定（2026-10-06）

`ventus-source-events-v7`在32 lane、宽度为32倍数时，从同一描述生成LayerNorm机器指令与性能IR，计入常量、地址、FMA复制、LDS butterfly和4次Newton；其余形状显式保留未验证模板。每block私有scratch为512字节。五项冻结完整RTL程序覆盖Tensor驻留/重复load/stream/组冲突再访问及GEMM写出后原地LayerNorm，最大计算误差3.04%，输出可见误差2.99%；不外推为整网误差界。独立模型需保留请求返回、容量和计算访存重叠，不能逐算子用拟合延迟替代。整网S16/S64 +2 decode新预测333660/1054599周期，官方软件与完整网络RTL尚未验收。详见[v7报告](../analysis/ventus_flow_20261006/performance-v7/report_cn.md)。


2026-10-07快速扩展RTL：保持v7机制模型不变，6项冻结真实ISA覆盖独立softmax、GEMM→LayerNorm→GELU→softmax数据依赖链和2/4warp流式/组冲突访存。448个输出字逐位一致，最大计算误差4.08%、可见误差4.00%，总RTL墙钟161.25秒。exp/倒数为本轮明确实现，与旧整网非线性模板不同；完整attention、KV和官方软件仍待对齐，不宣称整网误差界。详见[快速扩展报告](../analysis/ventus_flow_20261006/quick_complete_20261006/report_cn.md)。
