# 从 Transformer workload 到 MILP：逐步推导

版本 v0.10，2026-09-24；独立 Ventus 补充：2026-10-06。第 1–16 节解释默认解析后端，第 17 节为串行 region 命令后端，第18节保留初轮难度标定，第19节为固定输入联合空间的活动能耗与全局界，第20节说明可编程挑战的两场景评分与有限程序族最优性范围。本文解释当前实现如何从数学函数、可用硬件和部署预算形成一个可求解问题。它与 [实践规范](workload_to_system_codesign_practice_cn.md) 配套；后者规定流程和实验口径，本文解释每一层为什么必要。

阅读时先记住：**语义定义答案应是什么，生成器列出合法做法，MILP 选择资源与时序，验证器检查得到的方案。**

## 1. 起点：输入的是函数和环境

### 1.1 Workload 只规定必须完成的计算

当前 Transformer 使用：

\[
N_1=LN(X),\quad [Q,K,V]=N_1W_{qkv}
\]
\[
P=softmax(QK^T/\sqrt{d_h}+mask),\quad Z=X+(PV)W_o
\]
\[
N_2=LN(Z),\quad U=N_2W_1+b_1,\quad H=GELU(U),\quad Y=Z+HW_2+b_2.
\]

LN 的 affine 参数、epsilon、GELU 版本、mask 与 dtype 在配置中固定。当前 B=1、S=32、D=128、4 heads、FFN=512。

这些公式尚未决定使用多少矩阵单元、是否保存完整 H，也未决定第一层 FFN 是否逐行块交给第二层。

### 1.2 环境规定可以使用什么

硬件契约给出 Matrix、SIMD、SFU、epilogue、SRAM、HBM 的能力和数量范围，单位面积/功耗、带宽、启动开销及本地存储。部署契约给出总面积/功耗上限和优化目标。

例如：允许 1–4 个 Matrix engine，不等于事先选择 4 个；允许最多 20 个 SRAM bank，不等于内存免费。

### 1.3 从 shape 推出工作量和字节数

FP32 tensor 的大小为：

\[
bytes(v)=4\prod_i shape_i(v).
\]

MatMul 的 MAC 数为 `batch × M × N × K`，一个 MAC 表示一次乘加。

| 计算 | 当前实例的 MAC 数 |
|---|---:|
| QKV，32×128 乘 128×384 | 1,572,864 |
| QKᵀ，4 个 32×32 乘 32×32 | 131,072 |
| PV | 131,072 |
| 输出 projection | 524,288 |
| FFN up | 2,097,152 |
| FFN down | 2,097,152 |
| 合计 | 6,553,600 |

例如 Wqkv 是 196,608 bytes；W1、W2 各 262,144 bytes。它们初始在 HBM，必须有加载任务。不能只计算 MAC 数而把这些移动省略。

## 2. Typed DAG 保留语义，不固定 kernel 边界

`workload.py` 生成包含 14 个算子的图。每条边带 tensor 名称、shape、dtype；每个 tensor 有唯一来源。图的拓扑顺序表达数学依赖。

对 FFN 中的一段：

> up(MatMul) → bias1(Add) → gelu(GELU)

可以分别执行，也可以选择 `up+bias1` 或 `up+bias1+gelu`。三个语义节点始终存在，用来表达要求；最终执行任务可以覆盖一个或多个节点。

选中融合后，要重新看 **region 的外部输入输出**：

- 输入：region 读取但未在内部生产的 tensor。
- 输出：region 生产且仍被外部消费者或最终输出读取的 tensor。
- 内部 tensor：其所有使用都在 region 内部，可以用内部缓冲实现。

例子：融合 `res1+ln2` 后，Z 仍被最后的 res2 读取，所以 Z 必须保留为外部输出。只保留 N2 会使最终 residual 失去输入。

## 3. Tile view：从一个 MatMul 得到可执行分解

对 \(C=AB\)，候选模板将索引区间划分为 I、J、K：

\[
C[I,J]=\sum_{K_q}A[I,K_q]B[K_q,J].
\]

当前使用同一个 tile size 划分三条轴。尾块通过缩短区间处理；每个 C tile 的 accumulator 初始化为零，依次处理升序 K 块，再写出结果。

合法性依赖以下事实：

1. 输出 I×J 区域完整覆盖且不重叠。
2. 每个输出区域的 K 分块完整覆盖归约轴，不漏项、不重复。
3. Bias/GELU 等作用在完整归约后的值上。
4. 本地输入 tile 与 accumulator 适配已定义的 primitive 容量。

因此，`GELU(partial_1)+GELU(partial_2)` 不允许替代 `GELU(partial_1+partial_2)`。浮点分块会改变归约细节，必须按固定数值契约比较，不能宣称逐 bit 等价。

这些检查在生成和执行验证阶段完成。MILP 不通过一个 coverage 方程自动证明 GEMM 的代数语义。

## 4. 为什么先生成 catalogue

如果直接让时间随可变 engine 数变化：

\[
T=\frac{W}{n_{matrix}\rho},
\]

就出现变量的倒数。当前方法先选定一个候选的 tile、engine group 和执行方式，算出它的常量时间；MILP 再决定选哪个候选。

### 4.1 一个 choice 包含什么

`Choice` 对应：region、covered nodes、输入输出、实现类型、tile、engines、stages、temporary bytes、traffic、规则证据。

`Stage` 对应：相对开始 offset、持续 duration、各资源数量、未取整 raw_us。一个 candidate 可以包含多个内部重叠 stage。

内部模板是由 shape/规则生成的，不是针对某次答案写死的 schedule。它仍然限定了搜索空间：MILP 无法自行发明未生成的内部流水。

### 4.2 当前矩阵成本如何计算

设一个候选用 tile size b、g 个矩阵单元。当前简化的 SRAM 访问估计为：

\[
Q_S=4B\left(\left\lceil\frac Nb\right\rceil MK+
\left\lceil\frac Mb\right\rceil KN+MN\right).
\]

它表达 A 按输出列块重复读取、B 按输出行块重复读取，以及输出写入。它假设输出 tile 的 partial sum 在本地完成，不是硬件计数器测量。

历史 v0 的 toy tile 效率为 \(\eta_b=\min(0.75+b/128,1)\)。Matrix 候选的未取整耗时为：

\[
\tau=t_{launch}+\max\left(\frac{BMNK}{g\rho_{matrix}\eta_b},\frac{Q_S}{\beta_S}\right).
\]

v1 保留上述流量与效率假设，但先按 batch、I、J 顺序将完整输出 tile 分给当前累计 MAC 最少的抽象 engine（相同负载时取较小编号）。每个输出 tile 的 K 归约留在同一 engine。令第 e 个 engine 的 MAC 数为 W_e，则：

\[
T_c=\frac{\max_e W_e}{\rho_{matrix}\eta_b},\qquad T_s=Q_S/\beta_S.
\]

默认 `compute_memory_overlap=max` 时，\(\tau=t_{launch}+\max(T_c,T_s)\)；敏感性配置 `sum` 时为 \(\tau=t_{launch}+T_c+T_s\)。例如只有一个输出 tile 时，配置两个 engine 不会把计算服务时间减半。分工和服务分解在建模前冻结，MILP 仍使用常量 duration；这只是一份阶段内部抽象分工，不保证 bank/端口/物理互连可实现。

v1 对融合 epilogue 的一个行块（r 行、N 列）计 \(Q_{epi}=2rN\times4+Q_{bias}\)，其中每个 bias 参数向量每行块从 SRAM 读取一遍。专用 epilogue 使用显式吞吐参数；流水末尾的 SIMD bias 使用 SIMD 吞吐。专用单元默认零启动成本仍是待校准假设。Residual+LN 沿用串行子操作减一次启动开销的模型。

SIMD MatMul 则使用配置 SIMD ops rate 的一半作为 MAC rate。阶段时长转换为：

\[
d=\max(1,\lceil\tau/\Delta\rceil).
\]

这里的 ceil、除法与 max 都在构建 MILP 之前计算；进入 MILP 后，d 和资源曲线全部为常数。

### 4.3 一个默认参数的实际例子

QKV 选 tile=32、2 Matrix engines：

- MAC 数 1,572,864，计算服务时间为 12 µs。
- 上式得到 SRAM 流量 442,368 bytes，单带宽单位的服务时间为 13.5 µs。
- 启动开销 1 µs，所以 raw_us=14.5。
- tick=2 µs，持续时间为 8 ticks，即 16 µs。

加载 Wqkv 时，2 个 HBM channel 的总速率与 1 个 SRAM 带宽单位相同，都是 32,768 bytes/µs。传输 196,608 bytes 加 1 µs 启动，共 7 µs，向上取整为 4 ticks，即 8 µs。

这说明“使用更多 Matrix”不一定继续提速，读取服务也可能限制候选。

### 4.4 搬运只算一次

源 tensor 的 HBM→SRAM 移动是独立 DMA choice。计算候选只计其 SRAM 内部访问。最终 Y 的 SRAM→HBM 是 writeback choice。

不能在独立 DMA 已经完成后，又给同一计算候选加一遍相同的 HBM 等待。内部行缓冲的读写仍需计入 SRAM 流量。

## 5. 表达内部流水：相对资源曲线

若 stage p 的 offset 为 o、时长为 d、对资源 h 的需求为 u，则该候选在相对时刻 δ 的占用为：

\[
U_{rch}(\delta)=\sum_{p\in stages(r,c)}u_{ph}\,\mathbf 1[o_p\le\delta<o_p+d_p].
\]

区间以外取零。这是一组已知整数，不是变量乘变量。

例如，FFN 流水候选中，第一层处理行块 1 时，第二层可以消费行块 0。如果两阶段各需 1 个 Matrix，此时曲线就是 2；若硬件只配置 1 个 Matrix，这个候选不能在该硬件上执行。

缓冲模板同时保证：第 b 块使用的槽位，必须等第 b−2 块结束后复用。当前内部 temporary bytes 在整个 region 活动区间保守预留，尚未逐 stage 缩短分配区间。

因此，fusion、流水和硬件数量确实耦合：候选不仅改变总时间，也改变不同阶段的计算并发、内存与通信需求。

## 6. 定义 MILP 的集合和变量

| 符号 | 含义 |
|---|---|
| V | 原始语义节点 |
| R | 候选 region；额外包含 source load 与 writeback region |
| Cᵣ | region r 的合法实现候选 |
| h | 硬件资源类型 |
| v | tensor |
| T_max | 有限调度 horizon，tick 数 |
| Δ | 一个 tick 对应的 µs |
| dᵣ꜀ | 候选持续 tick 数 |

变量：

\[
x_{rct}\in\{0,1\},\qquad n_h\in\mathbb Z_{\ge0},\qquad M\in\mathbb Z_{\ge0}.
\]

- x=1 表示 region r 使用 choice c，从 tick t 启动。
- n 是配置的硬件数量。
- M 是 writeback 完成的 makespan。

只生成满足 \(t+d_{rc}\le T_{max}\) 的启动变量。

另定义 region 选择与时间：

\[
y_r=\sum_{c,t}x_{rct},\quad
s_r=\sum_{c,t}t x_{rct},\quad
f_r=\sum_{c,t}(t+d_{rc})x_{rct}.
\]

约束 \(0\le y_r\le1\)。代码把 y、s、f 作为辅助连续变量并用等式连接；因为 x 为二元且至多选一个，它们自然得到选择/整数时点。未选 region 的 y、s、f 都为零。

## 7. 第一组约束：实现完整计算

对每个语义节点 a：

\[
\sum_{r:a\in covered(r)}y_r=1.
\]

它表示节点被恰好一个 region 实现。

对于 up→bias→gelu，可以选择三个单节点 region，也可以选择一个融合 region；不能既选全融合又选其中的独立 bias。

每个 source load 和最终 writeback 不覆盖语义节点，它们单独满足 \(y_r=1\)。

这里 exact cover 作用在稳定的语义节点集合上。不同 tile 切分放在 choice 内部，因此不会把两个不同粒度的 tile 图节点误当成同一个覆盖集合。

## 8. 第二组约束：选择可部署的硬件

\[
\underline n_h\le n_h\le\overline n_h
\]
\[
A_0+\sum_h A_h n_h\le A_{max}
\]
\[
P_0+\sum_h P_h n_h\le P_{max}.
\]

n 为整数。A/P 都是常量系数，所以这些约束线性。

专用 epilogue 的成本按实际硬件实例计一次。多个串行 kernel 可以复用它；多个同时运行的阶段需要满足下面的容量约束。

P 表示配置功耗，尚无动态 energy 目标。若未来加入 static energy，\(P(n)\times M\) 是变量乘积，必须明确采用离散配置、有效线性化或外部评价，不能直接写进当前 MILP。

## 9. 第三组约束：只有数据就绪才能执行

定义 \(\mathcal P(v)\) 为所有可能将 tensor v 作为外部输出的 region；source tensor 的 producer 是对应 load。令：

\[
F_v=\sum_{p\in\mathcal P(v)}f_p.
\]

在当前合法覆盖与端口规则下，最多一个这样的 producer 被选，其他 f 为零。

对所有需要外部输入 v 的 consumer region r：

\[
F_v\le s_r+T_{max}(1-y_r).
\]

若 r 被选，右边就是 sᵣ，必须等 producer 完成；若 r 未选，约束被放松到 horizon 上界，不会让未执行的分支阻塞真实调度。

这是相较“固定 16 task DAG”的关键变化：**fusion 改变外部边，需要按选中 region 激活依赖。** 原语义边若变为内部边，就由候选模板保证，不能再强行要求完整原算子彼此等待。

v0 的外部输入位置固定为 SRAM。因此没有额外 placement binary 或 route 选择变量。若未来加入多个位置，就必须增加位置相容性、显式 copy 和目的缓冲约束，不能仅在文档里声称已支持 placement。

## 10. 第四组约束：同一时刻不能超用资源

对资源 h、全局 tick τ：

\[
\sum_{r,c,t}U_{rch}(\tau-t)x_{rct}\le n_h.
\]

每个被选候选的资源曲线随启动时间平移，再叠加。它同时表达：

- Matrix、SIMD、SFU、epilogue 的并行容量。
- HBM channel 的带宽与传输并发占用。
- SRAM 带宽单位的并发占用。

例如 DMA 占 2 HBM、1 SRAM，计算占 2 Matrix、1 SRAM，二者可重叠需要至少 2 个 HBM、2 个 Matrix 和 2 个 SRAM 带宽单位。

资源是否存在已经由每个活跃 tick 的不等式保证，单独的 hardware-existence 不等式在这里是冗余的。所有阶段时长必须为正，且整个候选不能越过 horizon。

参考报告的“两个 transfer 同时超出 HBM 数量就不能重叠”，正是这组约束的常量曲线特例。

## 11. 第五组约束：SRAM 存得下，而且不能过早释放

只有带宽限制还不够。预取的权重即使 DMA 已结束，在计算读取它之前仍占字节容量。

### 11.1 累计启动与完成

对 region r、时点 τ 定义：

\[
B_{r\tau}=\sum_{c,t:t\le\tau}x_{rct},\qquad
E_{r\tau}=\sum_{c,t:t+d_{rc}\le\tau}x_{rct}.
\]

B 表示已经启动，E 表示已经完成。代码用递推等式构建稀疏矩阵，例如：

\[
B_{r\tau}-B_{r,\tau-1}=\sum_c x_{rc\tau},
\]

完成变量同理，只在相应结束 tick 加上对应 x；初始累计值为零。

### 11.2 tensor 何时占空间

当前策略：producer 一启动就为输出分配完整空间，最后一个 consumer 完成后释放。

分配指示：

\[
A_{v\tau}=\sum_{p\in\mathcal P(v)}B_{p\tau}.
\]

对于消费 v 的 region r，尚未完成的指示为：

\[
O_{r\tau}=y_r-E_{r\tau}.
\]

令 \(\mathcal C(v)\) 是所有可能外部消费 v 的 region，Rᵥτ 为驻留状态。需要表达：已经分配，并且至少一个被选 consumer 尚未完成。线性写法是：

\[
0\le R_{v\tau}\le1,\qquad R_{v\tau}\le A_{v\tau},
\]
\[
R_{v\tau}\le\sum_{r\in\mathcal C(v)}O_{r\tau},
\]
\[
R_{v\tau}\ge A_{v\tau}+O_{r\tau}-1
\quad\forall r\in\mathcal C(v).
\]

为什么成立：未分配时 R≤0；所有 consumer 都完成时 R≤0；已经分配且还有一个 consumer 未完成时，对应下界要求 R≥1。其余情况下上下界一致。因此 x 为整数时，R 即使声明为连续变量也被强制为 0/1。

内部融合 tensor 没有外部 producer/consumer，不建立完整驻留副本，由该候选的 temporary bytes 负责。

### 11.3 字节容量

设候选 temporary bytes 为 bᵣ꜀，SRAM 每 bank 容量为 Cₛ：

\[
\sum_v bytes(v)R_{v\tau}
+\sum_{r,c,t:t\le\tau<t+d_{rc}}b_{rc}x_{rct}
\le n_S C_S.
\]

同一个 nₛ 同时约束第 10 节的带宽单位和这里的字节数。增加 bank 可能解决其中一个瓶颈，也可能两个都解决；仅看 bank count 无法分辨原因，必须导出两条占用曲线。

这比参考实验报告的抽象 SRAM 占用更严格。参考报告明确没有检查 persistent tensor 的 bytes/lifetime，不能借它的 verifier 通过来替代本项目的这组检查。

## 12. 第六组：目标、horizon 和最优性范围

最终输出必须写回：

\[
M\ge f_{writeback},\qquad \min M.
\]

时间单位是 tick，报告 µs 时乘 Δ。

### 12.1 用可行方案确定安全 horizon

先通过串行和 list scheduling 得到经检查的可行调度，设其完成时间为 H。最优 latency 必定≤H，所以删除结束晚于 H 的启动变量不会丢失更好的 latency 解。

若没有可行初始调度，代码要求显式 horizon；若用户给的 horizon 比可行方案更短，则记录为人为限制。有限窗口内 infeasible 不能自动推导“所有时间长度都不可行”。

### 12.2 求解器到底报告什么

- incumbent：当前找到的最好可行目标，是最优值的上界。
- dual bound：最小化问题的下界。
- gap：两者尚未闭合的差距，按求解器口径报告。
- status：optimal、time limit、infeasible 等终止原因。

对整数 tick 目标，若 incumbent M 与有效下界向上取整后的值一致，可以确认该有限模型内 latency 最优。实现保留数值容差；这是浮点 MILP 求解证据，不是形式化证明证书。

只有此后才固定 M，再优化面积，并独立记录第二阶段的状态与 gap。latency 最优不自动意味着面积 tie-break 也最优。

参考报告采用 `1000M+A`：在其 M 为整数且面积变动范围小于 1000 的条件下，能保证 latency 优先。我们的分阶段方式不需要依赖这个固定权重界限。

### 12.3 多目标如何进入

预算扫描为每个 A_max 解一次同样的 MILP，收集 (L,A)。每一次仍然线性。稀疏预算点得到有限非支配集合；若有未闭合 gap，不能称为完整精确 Pareto frontier。

## 13. 一个可以手算的最小例子

考虑 X 经 A、B 得到 Y，必须 load/writeback。假设以下候选已经合法化：

| 候选 | 覆盖 | 时长 |
|---|---|---:|
| load X | 固定输入任务 | 1 tick |
| A | A | 2 ticks |
| B | B | 2 ticks |
| AB | A、B | 3 ticks |
| writeback | 固定输出任务 | 1 tick |

假设资源与内存足够，A→B 是严格数据依赖。

覆盖约束为 \(y_A+y_{AB}=1\)、\(y_B+y_{AB}=1\)。

- 选独立 A、B：load 0–1，A 1–3，B 3–5，writeback 5–6，M=6。
- 选 AB：load 0–1，AB 1–4，writeback 4–5，M=5。

前后必须串行，没有第三条更短路径，所以这个有限例子的最优值是 5。测试实际枚举合法启动组合，再与 MILP 比较；它验证了 covering、启动选择、依赖和目标的组合。

复杂 Transformer 的区别是多了重叠、可选硬件、多个消费者和内存约束。核心变量与逻辑保持相同，但不能再仅靠手算串行长度确定最优值。

## 14. MILP 之外的阶段也属于方法

| 阶段 | 输入 → 输出 | 责任与边界 |
|---|---|---|
| 配置校验 | YAML/覆盖参数 → 合法契约 | 拒绝无效单位、shape、资源范围、求解参数 |
| 语义前端 | workload → typed DAG | 固定“算什么”，不预先指定 schedule |
| 候选生成 | DAG＋规则＋硬件 → catalogue | 检查索引/接口前提，计算局部非线性成本 |
| warm start | catalogue＋预算 → 可行调度 | 给上界与起点，不宣布最优 |
| MILP | 有限实例 → hardware＋schedule＋bound | 联合组合与条件约束 |
| 独立 verifier | 冻结实例＋导出解 → 检查报告 | 不复用模型 row，从解重建资源/生命周期 |
| 数值执行 | 所选结构＋测试输入 → 输出/误差/轨迹 | 实际 tile 计算；测试证据范围有限 |
| 事件重放 | stages＋schedule → 事件 | 当前验证内部一致性，不是额外物理校准 |
| 实验比较 | 多个冻结 run → 对照报告 | 控制变量，解释选择变化，不隐去失败点 |
| 高保真反馈 | RTL/测量 → 成本或约束修订 | 尚未接入；必须新版本重新求解 |

正确性信任边界也由此明确：trusted primitive 的数学函数与规则是先验；catalogue 成本是可被校准推翻的假设；MILP builder、求解结果和生成执行都需要检查。独立 verifier 可以发现编码/调度错误，但无法验证模型中完全没有描述的物理效应。

## 15. 如何解释当前结果

历史运行得到 104 µs，可行下界为 50 µs，gap=51.92%；该 incumbent 来自 warm start。它说明链路可以产生并检查一个方案，尚未证明 solver 找到了最佳结构。

也不能直接拿它与参考报告的 57/64 µs 比较：workload 大小、dtype、吞吐、tick、SRAM 容量语义和候选空间均不同。

一个合理的后续结论应当包含：固定了哪些输入；只改变了哪个约束；选中的 region/tile/hardware 如何变化；具体哪些 tick 的资源或内存发生瓶颈；该结论的 gap 和校准边界是什么。

## 16. 公式到代码的对应关系

| 推导内容 | 实现入口 |
|---|---|
| 数学 workload、shape、参数 tensor | `workload.transformer_graph` |
| 图与候选类型 | `ir.Graph/Tensor/Node/Choice/Stage` |
| region 端口、tile/融合、阶段成本 | `catalogue.ports/generate`、`costs.matrix_cost/vector_cost/epilogue_cost` |
| 可行上界与启发式初始解 | `warmstart.serial_incumbent/greedy_incumbent` |
| y/s/f、covering、conditional dependency | `model.solve` 前半部分 |
| resource curves、B/E/R、SRAM capacity | `model.solve` 中间部分 |
| 稀疏 row 与 HiGHS 接口 | `solver.SparseMilpMatrix` |
| latency/area 两阶段与状态 | `model.solve` 后半部分 |
| 独立重建与事件 | `verify.inspect_schedule/verify/simulate` |
| tile 数值与覆盖 | `execution.tiled_matmul/check_tile_trace/execute` |
| 冻结和只读复验 | `artifacts.read_snapshot/reverify` |

本文描述当前实现。新增 placement、任意流水或新数值语义时，应同时修改相应推导、代码、verifier 和验收要求。

## 17. 快速命令后端：串行 region 下的紧凑 MILP

该后端由 `--executable` 进入，原时间索引模型保持原义。候选只含独立算子与 MatMul+Bias，Matrix 使用 tile 16/32 和 1/2 个 engine。region 内有具体 engine 队列和单 SRAM 服务端口；region 末尾 WAIT 全部完成。因此，任意合法拓扑顺序的总延迟均为所选 region 延迟之和，无需优化其开始时间。

令候选选择为 \(x_c\in\{0,1\}\)，Matrix 数量为 \(n_M\in\{1,2\}\)，候选要求 \(e_c\) 个 Matrix，覆盖节点集合 \(V_c\)，孤立执行周期为常量 \(d_c\)。模型为：

\[
\min L=\sum_c d_c x_c,\qquad
\sum_{c:v\in V_c}x_c=1\quad\forall v.
\]
\[
e_c x_c\le n_M,\quad
A_{fixed}+a_M n_M\le A_{budget},\quad
P_{fixed}+p_M n_M\le P_{budget}.
\]

每个源 DMA 与最终写回候选强制选中。固定存储、SIMD、SFU、HBM 和控制成本计入 fixed 项。声明的 SRAM 地址空间完整预分配，在求解前/独立验证中检查容量；Matrix 输入 panel 与输出缓冲容量在候选生成时检查。固定局部融合规则保留外部端口，exact cover 后由拓扑排序生成串行执行次序，独立 checker 重查覆盖、就绪和硬件/预算。严格证明 latency 最优后，再固定 \(L\) 最小化 Matrix 面积。

这里消去时序变量依赖“region 不重叠、服务确定、边界完成”的限制，不能将同一简化直接用于任意并发模型。命令内部的 SRAM 仲裁仍由事件模拟器求得，它在有限候选预处理阶段产生常量 \(d_c\)。

初始估计为 \(d_c^{(0)}=\max_r B_{cr}\)，其中 \(B_{cr}\) 是该 region 在 engine 或共享服务 \(r\) 上的忙碌周期总量；它忽略不同服务间的依赖等待，作为理想重叠估计。反馈后的 \(d_c^{(1)}\) 使用该 region 事件执行的完成周期。阶段服务本身按整数吞吐取整，计算命令读、计算、写串行，多个 engine 的请求按固定策略争用共享端口。全程序执行只消费汇编、target、地址表和初始内存，不读取 MILP 的 \(d_c\) 或开始时刻。

在同一确定服务模型下，串行程序有 \(L_{sim}=\sum_{c:x_c=1}d_c^{(1)}\)。反馈后一致说明生成与组合路径符合这些假设；面积/频率/吞吐仍需 RTL、综合或测量证据。默认 52 个候选对应 52 个二进制变量加 1 个 Matrix 数量变量；首阶段 60 条约束。该小模型的最优性只涵盖受限空间，不能外推为旧 91 候选空间或一般硬件的最优设计。

## 18. 难度标定的辅助下界与领域简化（实验工具）

2026-09-23 新增独立实验脚本，默认建模、成本版本与 CLI 行为保持不变。实验方法和原始数据入口见[课程难度标定](experiments/course_difficulty_20260923_cn.md)。目标是区分可行解搜索困难与时间索引松弛过弱，不能仅用变量数量或限时 gap 决定问题难度。

### 18.1 依赖与资源工作量松弛

`scripts/difficulty_bound.py` 保留原冻结候选的 exact cover、硬件数量、面积/配置功耗预算、region 开始/结束与条件依赖；删除逐 tick 并发和完整 tensor 生命周期约束。每个候选仍检查自身资源峰值不超过硬件数量、temporary 不超过 SRAM 容量。

令 \(x_c\) 为候选选择、\(d_c\) 为时长、\(s_r,f_r,y_r\) 为 region 开始、结束和激活变量，则：

\[
f_r=s_r+\sum_{c\in r}d_cx_c,\quad 0\le s_r\le Hy_r,\quad f_r\le C.
\]

当前图契约排除无用节点与 source，合法候选的外部输出沿依赖链通向 writeback，故所选 region 均在 makespan \(C\) 前完成。\(H\) 来自已通过原 verifier 的可行上界，保留 \(C\le H\) 不排除原最优解。

资源 \(q\) 的工作量为 \(W_q=\sum_c x_c\sum_{j\in c} d_j u_{jq}\)。任何原合法调度都满足占用积分 \(W_q\le n_q C\)。用 one-hot \(z_{qk}\) 表示 \(n_q=k\)，得到必要线性约束：

\[
W_q-kC\le Hn_q^{max}(1-z_{qk}),\qquad
\sum_k z_{qk}=1,\quad n_q=\sum_k kz_{qk}.
\]

未选中的 \(k\) 由 \(W_q\le Hn_q^{max}\) 安全放松；\(k=0\) 选中时禁止资源工作。因此每个原合法调度都可投影到该松弛，其 **dual bound** 是原有限菜单的有效下界；松弛 primal 仍可能同时超用资源，不能作为可执行方案。测试对小图合法调度穷举投影、融合/尾块/零资源及穷举最优值交叉检查。

`scripts/difficulty_assisted.py` 可将这一独立下界作为 \(C\ge LB\) 加回原时间索引模型；也可复用已验证的完整候选空间 incumbent，缩短由可行上界确定的 horizon。两者不改变允许的最优设计，新增约束与 warm 来源单独保存。辅助下界计算、程序验证与后续求解的开销需分别计入。

### 18.2 缩小可行空间与质量口径

`scripts/difficulty_reduction.py` 的候选过滤或延迟预取调度族属于启发式限制。其可行结果在原完整 catalogue 下重新验证并执行；受限求解器的下界只适用于子空间，不能充当原问题下界。延迟预取利用“尽早加载可能增加驻留，挤占用于计算资源的面积预算”的结构知识，枚举少量计算数量、HBM 并发、融合和预取窗口；随机窗口对照共享同一个调度生成器。

认证 gap 定义为 \((U-LB)/U\)。相对最优延迟的最坏超额是 \((U-LB)/LB\)，两者不得混用。经验差距 \((U-U_{best})/U_{best}\) 只相对于本轮最好已知可行值。大的认证 gap 不证明存在相同比例的真实收益，随机策略使用同一领域调度族也不能作为完全无领域知识的对照。


## 19. 固定输入联合空间的能效评分与全局界

独立 `toy-course-v1` 不改变前述默认 MILP。固定输入、固定活动单价，逐档开放候选菜单。设硬件为 cluster 数 C、阵列 R×Q、本地 L KiB、累加器 K KiB、共享 S KiB、bank B、通道 D、向量宽 V：

\[
A=0.6+C(0.25+0.0055RQ+0.003L+0.004K)+0.002S+0.06B+0.12D+0.02V+0.15.
\]

计算活动由矩形循环计数，尾块按实际阵列激活补齐；输入缓存约束 `4*(m*k+k*n)*(2 if double_buffer else 1)≤1024L`，累加器约束 `4*m*n≤1024K`。每算子的共享流量包含 tile 引起的重读，WS 包含 K 分块部分和写回；本地流量单独计费。确定的 stage 调度同时约束资源、数据依赖和完整 tensor 驻留。

\[
E(h,p)=\sum_a n_a(h,p)e_a + 0.025A(h)T(h,p),\qquad
J(h,p)=\frac{128/T}{A(E/T)}=\frac{128}{AE}.
\]

E以焦耳、T以秒统一；实现中 `uJ` 与 `us` 配套转换。时间虽然在分式中消去，仍通过泄漏能耗和1000µs截止时间影响目标。单算子使用更快实现未必使面积与全系统能量乘积更小。

**全空间有效界。** 必须MAC计数29360128，强制外存922112 bytes；只计两者产生的动态能量下界115.743744 µJ。对每个硬件，取计算/外存工作量的时间下界并计泄漏，可得粗 `E_L(h)` 和 `U(h)=128/(A(h)E_L(h))`。更紧的界逐GEMM枚举允许的矩形tile，用平均 cluster 负载放松实际最大负载，保留量化时长、动态流量和每算子 `E_dynamic+P_leak*T` 的最小值；图中14个计算节点成依赖链，因此这些计算时长下界可相加。再计首个layernorm必需DMA和最后writeback，放松其余端口竞争、预取与全局存储。对所允许的融合给予最大可能的启动折扣，得到安全乐观界。

整tensor attention 在softmax时同时需要 scores/P/V/X，共655360 bytes。这是v1有限程序族的必要条件。共享1MiB时，完整up+bias+GELU融合的必要驻留1116160 bytes也不满足，不能给这类硬件虚假的融合启动折扣。完整11664个硬件逐一计算上界后，最大为120261.9471171623；独立可行方案为120261.94711716232，在浮点容差内闭合。证书和冻结hash见[固定输入报告](experiments/course_fixed_space_20260923_cn.md)。这是有限程序族与toy成本下的数值最优证据，无自由汇编或物理PPA保证。

局部最小值只用于构造乐观界或启发式提案，不能直接声称快/省能量的tile全局支配另一tile；持续时间变化仍可能影响预取及驻留。安全硬件剪枝需要 `U(h)≤J_incumbent`。扩展为分块驻留、head/行流水后，旧640KiB必要条件和整图串行下界不再通用，必须重新推导。


### 19.1 分块族的界与驻留约束变化

v2把attention按head group、FFN按row展开成新的DAG，原14节点串行链假设失效。QKV一次生产完整的Q/K/V各组视图，投影等待所有Context组；res2等待所有FFN行输出。各chunk读写字节按真实shape重算；每row reload权重时，外存下界随重复加载增加，绝不能继续只收取一次权重成本。

必要共享容量降为512KiB（完整QKV阶段X/N1/Wqkv/QKV总和）。保留全部dense MAC及至少一次原始source搬运，可得通用粗界；对全部允许硬件取最大值258374.6671，远松于一个已知可行值，暂不据此声称真实可提升幅度。代码见 `codesign/course_v2_bounds.py`。更紧界需从新任务DAG和实际engine需求重新推导，任何局部Pareto删减都须区分安全界与启发式候选缩减。


v3原型允许每matrix chunk占用g个cluster（g≤物理C）并行，故不能再把所有matrix时长直接相加。必要资源界改为 `T≥sum(g_i*t_i)/C`，并须与依赖路径、端口和存储约束结合。实现保留完整物理面积与泄漏，逻辑配额不降低配置成本；当前仅验证嵌套与并发行为，未将这个工作量式冒充紧最优证书。


### 19.2 v2分块族的强界与认证

对每个硬件h及分块组合π=(head_group,ffn_rows,weight_mode)，完整枚举各matrix chunk的合法矩形tile，取得动态能量e_k及平均cluster负载导出的时长下界d_k。所有matrix任务占满物理clusters，因此 `T≥Σd_k+G`，G包含LN1/res1/LN2/res2、首尾DMA、单组/单行及reload gate强制串行的间隙。reload的每行W2及除首行外W1搬运均不能与矩阵任务重叠，必须计入G；首次W1允许预取，不能这样相加。

另外由首Scores→全部Softmax→末Apply、首Up→全部bias/GELU→末Down/bias，以及DMA/SIMD总工作，得到与tile选择松弛相容的 `T≥B`。设F为非矩阵活动能量下界（完整计实际重载，合法可能的融合仅扣启动能耗），对任意λ∈[0,P_leak]：

\[
E\ge F+\lambda G+(P_{leak}-\lambda)B+\sum_k\min_{p_k}(e_k(p_k)+\lambda d_k(p_k)).
\]

取所有局部折线交点λ的最大值为E_L，最后对全部(h,π)取最大 `U=128/(A_h E_L*10^{-6})`（此处E_L以µJ计）。容量、面积及必要延迟违反才用于安全剪枝；局部能量/时长前沿仅构造放松界，没有删除原程序。

完整v2强界8.89秒得到U=132347.551309；独立验证领域方案J=129355.455690，J/U=97.7392%。未闭合gap=(U−J)/U=2.2608%，可提升分数的上限U/J−1=2.3131%，不表示存在同等实际增益。证书 `results/course-v2-certificate-20260923-v1/certificate.json` hash联结原预算检查点、强界和再次验证的见证。v3不满足所有matrix串行假设，不能使用本节强界。

## 20. 可编程挑战与 MILP 最优性范围

[挑战 v0.6](programmable_transformer_codesign_challenge_cn.md)用四层 M1/P1 与 M1/D1 两场景共同检查低级汇编、独立数值答案与事件评分。两份[完整基础指令例程](../examples/challenge/README.md)由低级指令写出 hidden/KV；修正后的 `pipeline-global-events-v2` 明确跨组重叠 HBM RAW/WAR/WAW 须由 `WAIT/BARRIER/STEP.COMMIT` 建立 happens-before，文本交错不提供此关系。[release_v06_r3 冻结基线](../examples/challenge/release_v06_r3/baseline_manifest.json)的 P1/D1 周期为 $79{,}210{,}901$ / $41{,}235{,}284$；新受信隐藏报告已签发 v2 模型分数 1000.0，本轮功能、评分和资源验收已完成；完整报告只读复算按用户要求提前停止；旧 v1 的分数不能转作 v2 结论。旧串行 M1/P1 的 $112{,}452{,}822$ 周期、旧 Cache=0 实验流水的 $79{,}210{,}901$ 周期，以及旧[全局事件 v1 发布记录](experiments/challenge_two_case_release_evidence_20260924_cn.md)均保留原模型口径。正式分数在两场景正确性、面积、功率和各自延迟门槛全部通过后，使用冻结基线 $T^0_s$ 与提交周期 $T_s$ 计算 $1000\sqrt{(T^0_{P1}/T_{P1})(T^0_{D1}/T_{D1})}$。硬件菜单的原始标签数是条件取值的乘积：

\[
8(1+6\cdot3\cdot3)(8+16+32+64)\cdot3(1+6\cdot4\cdot2)\cdot3^4\cdot2\cdot4\cdot4\cdot6
=120708403200.
\]

该式没有编码面积、动态功率、事件延迟或软件合法性，不能作为有效解数量。若对一个明确定义的 tile/工作组/同步程序族建立局部 MILP，其最优值或 gap 仅适用于该程序族；放开所有合法汇编后，只有已验证可行程序提供已知成绩，除非另行证明对所有汇编成立的上界。当前资源验证覆盖有限实例，不能从面积公式、历史试行周期或菜单标签数推导整个硬件空间的性能与课程搜索难度结论。


## vNext Rust 阻塞模型的服务与窗口推导（2026-09-30）

本节仅适用于 `vnext-blocking-rf-v0.2`，无新增MILP最优性结论。参数单价沿用vNext-draft-0.5，硬件固定 `c=1,r=0,S_h=C=B_t=0,d=1,z=4`，其余菜单经校验后代入面积式。基准功率为 `0.025 A + 0.15 h`。

HBM请求占用有限credit，经过上行传输和6周期传播、250周期等待、2周期64B服务、下行传输和6周期传播，再等待RF/通知完成才释放。读请求8B/返回64B，写72B/通知8B；部分写同样收费64B HBM。无争用单64B读取在该阻塞合同下为 `1+6+(1+6)+(250+2)+(1+6)+(1+2)+1=277` 周期，末项为全局wave屏障。请求生成和返回共享有限带宽，不能将总字节除以峰值当作完整周期。提前预约credit相对完整草案更保守。

设每周期动态能量为e(t) pJ，窗口W的动态能量为 `E_W(t)=Σ e(u), u∈[t-W,t)`，功率为 `P_base+E_W(t)/(2000W)` W。对常速区间 `[a,b)` 的能量E，其速率 `r=E/(b-a)`；窗口能量斜率在 `a,b,a+W,b+W` 分别变化 `+r,-r,-r,+r`。事件存入固定环形差分；在整数周期边界更新并取最大，运行后延伸W个空闲周期，覆盖尾窗。环容量65536大于本ISA最长指令活动前视(<40000)加最大窗口10000。

RF服务按实际字节和带宽计整周期、尾周期独立收费，服务后再加2周期。TC各物理块串行读acc、启动供数、`K+p+q−2`计算、写acc，K内每周期一个输入组，外部RF读取与物理补齐FMA分别计费。Vector与归约按有限组读/算/写；归约中间量显式占RF scratch。该阻塞语义不模拟完整草案的双上下文/异步重叠，不能据此宣称对更开放程序空间成立的性能界。

事件跳转仅跨越无状态变化的区间；NoC轮转仅在实际服务时变化。32组与逐周期模式的差分检查验证这项实现优化；两者共用资源规则，独立正确性证据仍依赖手算与独立能量/数值参考。


## vNext v0.3 访问与失败语义（2026-10-01）

对于一行 strided read，实际元素集合为 A={b+i·s | 0≤i<n}；跨SM的连续写区间 W=[l,u) 与该行冲突当且仅当 A∩W≠∅，不能用 A 的包围区间替代。实现合并每SM写区间，并在区间数与元素数中选择较小一侧检查；无需展开全地址历史。只读tensor不存在RAW/WAR/WAW冲突，可免建这类元数据。连续访问仍使用排序扫描。

执行数值失败后有效状态V=false，后续wave拒绝且power_pass=false；reset清空HBM、分配及计时并恢复V=true。合法程序的硬件单价、时序公式及功率公式不变。该项为Rust阻塞子集运行语义，不修改MILP最优性结论；见[审计记录](experiments/vnext_rust_audit_20261001_cn.md)。


## vNext v0.4：程序结构的可解释取舍（2026-10-01）

输出驻留GEMM块RF需求为4(mn+mk+kn)字节；完整K累加时，其输入与最终输出的有效HBM量约4(mK+Kn+mn)字节（C初始为0）。调小k增加启动及RF accumulator读取/回写次数，不自动改变上述有效输入量；实际64B事务另由布局和批次取整确定。split-K增加可分配SM的任务数，同时产生分区部分和的显式HBM写读、归约与屏障。packing先付转置副本的读写成本，再比较后续事务节省；没有免费布局变换。

这些是有前提的局部工作量模型，不能替代全程序竞争调度或原空间最优性证明。ISA内运算顺序确定，跨指令的合法重排以误差契约检验。已测宽/窄阵列在P/D和面积/能耗上有取舍，但完整存储层次和异步流水缺失，不能宣称软硬件全空间已标定，见[简报](experiments/vnext_codesign_readiness_20261001_cn.md)。


## vNext v0.5：发现变量与重建成本模型（2026-10-01）

独立head分组增加可供SM分配的任务，可能替代部分split-K并行度；原串行head程序上有利的split-K取值不能无条件迁移。K的长期转置副本成本为首次转换、每步追加、额外HBM容量与所有后续读取；收益来自免除重复转换及访问布局改善。仅扩大K分块时，有效矩阵输入量不必减少，收益可来自较少DMA启动和accumulator访问，不能混同复用收益。

在固定阻塞RF硬件、传统稠密FP32投影且无压缩/代数表示改写的前提下，令F=L(4D²+2DF_ffn)、W=4F、C=SM(pq+V)、R=SM×RF_bytes、B=32h。赠予所有RF跨step存权重和TC/Vector同时峰值能力，忽略其他操作及竞争，得到LB_P=max(PF/C,W/B)、LB_D=max(GF/C,[W+(G−1)max(0,W−R)]/B)。这是有条件的乐观放松，不是实际周期预测或任意程序/完整Cache模型的最优性证书。

本轮模型用于解释新变量和候选取舍，未实现MILP求解对照；不能把测后配置表做成one-hot选择就宣称发现了结构约束。课程建模证据应含测前预测、变量/反馈消融及迁移。量化结果与推导边界见[结构试解报告](experiments/vnext_structural_diversity_20261001_cn.md)。


## vNext v0.6：存储分工、复用与可行分块（2026-10-01）

普通RF/RF矩阵路径的局部工作集为4(mn+mk+kn)；B直供SH后RF为4(mn+mk)，SH预留4(kn+r·mn)，r为每任务输出行块数。后者包含一个B panel和所有部分和，跨K块的部分和SH读写、首次Fill、最终HBM输出必须计费。K块变大减少启动与accumulator访问，r增加另外减少B的外存加载次数，不能用同一个带宽折扣替代。可分配SM的任务数随r增长下降，尾行和head之间的任务合并须共同考虑。

SH bank=word%b，每个16元素服务批次按各bank不同字计读服务（同字广播），写按实际字计；最大bank服务轮数给出批次服务时间，固定6周期返回延迟另计。SH→TC路径受接口B_t约束，A/C仍占RF；当前单TC阻塞模型中每步B≤16个连续字，bank无内部冲突，服务间隔ceil(4n_valid/B_t)。显式多级流水和端口计费见[Rust规范](../rust/vnext-sim/README.md)。

完整M的SH直供与RF路线、短/长prompt反转支持把存储分工、分块、任务粒度一起建模；尚无MILP方法对照或全空间最优性结论。v0.5仅RF容量的条件下界不可原样作为含SH/Cache任意程序空间的证书。实验范围、手算与负对照见[SH报告](experiments/vnext_shared_reuse_20261001_cn.md)。


## Blocking-SH首发：程序空间与验证边界（2026-10-01）

首发静态IR不要求程序来自既有Builder或policy。建模可自行选择实现族、局部候选、资源需求、存储生命周期与分解方式，再生成任意合法wave原语流；同一硬件承担P/D两个场景。工作量/容量公式只对所推导的实现族有效，不能把某个生成器的合法性筛选或最优界外推为全部静态程序的证书。

资源有效界、经验周期预测与可执行方案分别保存。课程要求可验证的空间判断及测前预测，不要求一次性建立完整MILP，也不要求建模必胜经验搜索。独立试解使用容量式与控制实验，改善已知SH方案；更强候选可以推翻旧候选之间的竞争结论，因此多样性证据须随更强对照更新。

正式性能指数为1000 sqrt[(14,227,707/T_P)(9,938,724/T_D)]，仅在完整M、多fixture数值与面积/功率/执行预算均通过后计算，无封顶。输入source唯一绑定和逐step commit属于可观察程序语义；预制答案不会因为存在Fill就合法，须在未知fixture完整复验。有限测试仍不证明语义对所有输入成立。

Host-work保护计MMA的mnk及其他原语的逻辑元素数，不能当作性能下界或目标。曾拟250M/wave的门槛错误排除合法SH四/八行块复用，已撤除，保留ISA指令限与场景50B累计work及进程上限。约束变化属于首发接口修正，未改v0.6周期/能耗成本，完整程序回归见[最终验收](experiments/vnext_release_acceptance_20261001_cn.md)。


## vNext v0.8：batch与阵列供数的新增建模关系（2026-10-01）

FP32主要权重为`4L(4D²+2DF)` bytes，初始KV为`8LBTD` bytes。共享权重的decode投影理想权重算术强度为B/4 FMA/byte，KV随BT增长；该式未计其他流量，不能直接作整体性能预测。五项实例用相同KV总量但不同B/T隔离复用与矩阵形状的作用。

TC边界成本加入p+q；RF供数间隔为`ceil(4(mm+nn)/B_RF)`，SH直供为RF、bank、接口三个服务间隔的最大值，首个计算必须等待两支路就绪。容量、分块、形状与带宽因此形成耦合约束，不能只用pq峰值除FMA数。大容量的访问延迟与局部工作集约束独立于全芯片总容量；数值和时间假设见[v0.8契约](drafts/vnext_workload_hardware_v08_cn.md)。仅允许菜单不证明路线可行或最优，本轮结构对照不替代全空间界。


## vNext v0.9 的建模接口（2026-10-02）

并发扩展把每SM TC数c、K并行kp、专用归约数、SH读端口、DMA引擎/描述符深度、驻留槽g以及全局Cache/多播纳入离散选择，完整成本在新版交付契约。面积按购买资源求和；同一SM的驻留组满足sum(RF quota)<=RF与sum(SH quota)<=SH、count<=g。更多引擎只扩展引擎占用的可重叠区间，RF/SH/NoC/HBM累计服务预算仍共享；异步依赖以token与wait约束禁止RAW/WAR/WAW。

可先将分块和布局枚举为候选，再用容量/资源区间、加权五实例延迟选择MILP/CP或分解方案。理想外存并发界为信用槽数×64B/信用生命周期；256个Cache MSHR覆盖约273周期冷读，最终冷流还受64B/cycle共享lookup/fill端口限制。128pending/SM把SM数量与外存并发耦合。此类界只在明示假设下排除方案；Cache命中、bank冲突、排队、功率窗需真实静态程序回放校验，不应使用经验除以引擎数替代服务。

例：D16的M16/N64/K112需39KiB RF/组，两个组不能同驻64KiB；K80约29KiB/组可行。这个容量判断用于改软件分块，也能比较加RF与改TC的机会成本。解析约束帮助缩小域，但不证明所用模板覆盖全部程序，也不保证求解器胜过经验搜索。


### 2026-10-02：独立题目在线 attention 预算实验

[实验记录](experiments/online_attention_budget_20261002_cn.md)复现了局部wave指令预算排除容量合法在线attention的问题。独立Rust `long-waves`实验feature放宽程序表达上限，保持硬件成本/时序与现有MILP约束不变；正式v0.9协议仍保持原规则。完整五项Transformer回归前不作为发布验收完成。面积仅增加1 AU=0.25 mm²展示标尺，无成本语义变化。


### Phase Two compact 竞争元数据修复（2026-10-02）

模型`phase-two-compact-v2`将跨组HBM竞争表中的同组连续/重复访问合并，单组跳过跨组表；执行指令、能量和周期不合并。数学上保留各张量/组/读写种类的精确地址集合，其跨组写读/写写交集不变。多组最多保留262144区间，属于宿主工程上限。DMA/SH-RF源目的形状须相同，目的行连续且互不重叠；建模时不得假设免费reshape/scatter。回归须覆盖重复写超过旧上限可通过、跨组冲突仍拒绝、跨步读空隙精确保留。详见[紧凑程序契约](phase_two_compact_contract_cn.md)。原成本系数与MILP核心不变。


## Ventus 事件约束与性能执行器的分工（2026-10-06）

Ventus 时序输入不携带张量数值。Transformer 对应的程序族可记为 `P(shape, layout, hardware, software, control)`；其操作字段包含执行路径、寄存器依赖、地址、活动 lane 与同步关系。性能为该程序在资源机制下的执行时间，不能直接将 softmax/GELU 名称设成自由延迟变量。省去数值计算不消除数据相关地址和控制，因此 control 输入必须明示；硬件/软件选择变化后须重建程序及访问。整网接入的核验对象是工作量、访问和状态转换与周期，当前执行器尚未实现上述完整输入范围。

当前独立版本 `ventus-source-events-v5` 按就绪状态在线执行给定程序，再将依赖、bank 服务、Tensor 流水和访存事务编译为 DAG。边 `(u,v,d)` 定义 `t_v ≥ t_u+d`；执行器独立求最早完成时间。尺寸、程序模板与预算由优化器选择，执行规则不能作为任意可缩短的等待变量。

v3 对 LDS 写请求的端口占用加入一个额外周期，并让地址计算器在最后一个分组获准后释放；后续有序 LDS load 不附加整个 store 返回的依赖。全局写 miss 的本地确认、L2 MSHR 的 Get、后续转发写与响应分别计时；Get 对纯写 miss 不更新目录。定义 `T_visible=max(t_external_write_accept)`、`T_drained=max(t_protocol_write_response,t_program_done)`，不得用本地确认替代二者。RTL 对照从首条 collector admission 起，初始条件为 SRAM 清零结束且 cache 为空；复位剩余等待与主机启动未进入该公式。分散 LDS 的部分响应和交错仍近似，验证误差按独立窗口报告。

当前每个有限候选 j 有二元变量 y_j，sum(y_j)=1。v5 条件事件约束为 `0 ≤ t_jv ≤ H y_j`、`t_jv-t_ju ≥ d*y_j`、`T ≥ t_j,end`；资源预算为 `sum(y_j resource_j) ≤ budget`，目标 min T。H 取各编译 DAG 独立最早执行的最大事件时刻加一，包含非终点事件；该上界包含可实现的最早解。未选候选的全部时钟为零，故 `d*y_j` 条件边与原大 M 条件边具有相同整数语义，减少绝对 clock guards 带来的数值问题。独立最长路径重放与完整菜单枚举检查最优目标，verifier 不接触 solver 约束对象。

该实现已固定候选内的 cache 结果与服务顺序，尚未将全部硬件字段因子化进同一个可组合 MILP。MIP 若允许改变布局、生命周期或顺序，命中和资源占用也必须相应约束；不能给命中变量任意取值，或假定硬件能执行任意最优 warp 发射序列。详见[边界与推导](../analysis/ventus_flow_20261006/search_model/details_cn.md#mip-编码与适用边界)。源码信息用于建模，RTL 测量用于核验；有限菜单下的最优性与真实硬件时序准确性分别声明。

v4 加入向量 FP32 max：FCMP 两个寄存器给出执行边延迟 2，供数、RAW/WAW 与 WB 约束仍单独作用。FFN 的第一层 4×4 输出经实际 scatter store 与第二层 4×8 gather load 转换布局；地址分组和 memory hierarchy 根据这些指令计算，不能把阶段之间的 reshape 视为零成本。算术完成目标由最后一个 bias/residual 的 WB 定义，不能继续用最后一个 Tensor WB 替代。两路径有限菜单仍优化协议完成目标 `T_drained`；RTL 分别核验各阶段和 `T_visible`，五组选择排序一致。模型没有因此获得自由合成 FFN 调度或全硬件变量的能力。

硬件形状与指令展开须耦合。对整除的 M×N×K GEMM，`N_TC=(M/tensor_m)(N/tensor_k)(K/tensor_n)`，每条为 `2*tensor_m*tensor_n*tensor_k` FLOP，乘积保持 `2MNK`。改变形状时须重新生成依赖和地址，不能在旧事件图上只缩短 TC 延迟；否则会把少做计算误认为优化收益。此守恒仅核对工作量，正确布局、资源等待及非默认硬件时序仍需独立检查。


RF bank 变化的约束来自操作数的 `register_index mod rf_banks` 映射和每 bank 服务端口。v5/v9/v1 在 4 bank 中需要三轮，在 8 bank 中需要两轮；16 条依赖 Tensor 指令对应 16 周期差值。冻结 v4 模型预测后，修改 RF/collector 的真实 RTL 验证了这一差值；另外五个程序的变化量为 0，均吻合。此对照检验参数对资源等待的影响，没有扩大有限菜单 MILP 的表达能力，也没有证明 LDS/cache 的全部状态约束准确；同批分散 LDS 的绝对输出误差仍为 12 周期。


追加 Tensor 形状的模块 RTL 验证支持 `L_TC=2+2log₂(tensor_n)+2+2` 和无背压 II=1，6 个合法三维形状全部吻合；LDS 局部解绑后，每 bank 单服务端口的轮数 `max_b count_b` 与 8/16/32 bank 的 40 个读写返回窗口吻合。原语时序不保证组合后的有限队列与调度准确。v4 DAG 按 IR 顺序固定 LSU 请求先后、按 cohort 释放 block，曾构造未来请求挡住先就绪请求、空闲 SM 等待整批完成的结构反例。若要直接搜索容量、并发槽和调度变量，须先将实际到达、分配/释放和队列背压转译为状态机制，再决定哪些状态能因子化为 MILP 约束；当前有限菜单最优性不解决这些模型偏差。


v5 对这些反例加入实际服务状态：warp 当前指令须满足 RAW/WAW 与已退休依赖；collector 从接收到发射一直占用；LSU 输入缓冲、地址路径及已写回的在途槽决定访存进入顺序；每 block 结束后独立释放 SM 资源。对弹性计算级 i，`R_i = empty_i ∨ R_(i+1)`，尾级的 R 由写回仲裁决定；R_i 成立时才把上一拍的 token 移到该级。各 stage transfer 与释放 blocker 被记录为事件边，另有确定的 service-clock guard 表达该次在线服务选择。当前图不允许 MILP 重选这一顺序；若把时刻或顺序开放为变量，须同步编码 ready/valid、仲裁、到达和容量状态，不能删除 clock guard 后直接当作已验证优化模型。

TC 六形状/12 控制模式的背压逐项吻合。新增 2/4/8 warp GEMM 的稳态增加量正确，2/4 warp 绝对计算误差最大 2.78%，8 warp 仍低估 7.12%–16.12%。因此 ready-aware decoded stream 不等于完整前端供给：CTA 派发、I-cache、instruction buffer 和 cache 内部返回状态仍需要转译。这一事实同时限制模拟器泛化与 MILP 物理结论，有限菜单的求解最优性不消除该偏差。

### Ventus 综合成本的菜单预算（2026-10-06）

独立成本版本 `ventus-synthesis-cost-v1` 给每个已覆盖硬件候选 `h` 提供逻辑面积 `A_h`（Liberty 原始单位）与存储位数 `B_h`。对恰选一个候选的变量施加

\[
\sum_h y_h=1,\qquad \sum_h A_h y_h\le A_{max},\qquad \sum_h B_h y_h\le B_{max}.
\]

`A_h` 使用共享固定逻辑与独立单 SM 的综合结果组成双 SM 基线；每 SM 用实采面积加 RF、Tensor、LDS 组件的综合差分。默认总成本也属于组成估计，完整集成综合未完成。`B_h` 从生成 RTL 的存储叶实例递归计数，包括 tag、I-cache 与队列。两种单位独立约束，不合成 mm²。SM 数的线性复制和跨组件组合均为估计，共享控制/互连扩容仍未覆盖；未知尺寸没有 `A_h=0` 的回退。恰选一个候选时，先删除超过任一预算的候选与上述预算约束等价。

该方法为已采样的有限硬件菜单提供成本系数，不构成29维自由尺寸的全参数面积公式，也不改变事件图的执行规则。[实现及证据](../analysis/ventus_flow_20261006/cost_model/report_cn.md)。


### Ventus v6 的共享路径、尾块与状态边界（2026-10-06）

令直接加法请求队列为 Q_add，FMA 乘法结果队列为 Q_mul。每周期共享加法器只能从其中一个可用队列取一项；Q_mul 优先。FPU 输出再在加法/乘法结果、比较与转换之间仲裁，再参与 RF/WB 竞争。v6 在线机制按上述连接产生事件，不能分别给 fadd/fma 设置互不相关的独立服务资源。有限菜单 MIP 继续复用固定服务事件，未开放仲裁选择。

Transformer 的 GEMM 时序 lowering 对输出行/列和归约维分别向 Tensor 三维取整。发出条数为 `ceil(M/tensor_m)*ceil(N/tensor_k)*ceil(K/tensor_n)`，有效 FLOP 为 `2*M*N*K`，发出 FLOP 为条数乘硬件每条 FLOP；不足元素由零 panel 供给，store 仅覆盖有效 lane。有效计算不能替代真实 padding 的资源收费。

跨软件 dispatch 的事件时间在所有请求/写 drain 后重新以局部零点记录，保留 read-only cache tag 与替换状态，写行在全部 SM/L2 失效；总周期为这些明确串行的 dispatch 周期之和。这一和式来自软件 fence 契约，不能用于省略任意并发 kernel 的跨批竞争。summary 仅省去 DAG 存储，两种模式均执行同一服务递推；整网预算中止时仅有前缀周期，无整网延迟。非线性模板数值、CTA/I-cache/flush FSM 和完整 GPT-2 周期仍待核验，见[v6 证据](../analysis/ventus_flow_20261006/performance-v6/report_cn.md)。


### Ventus 时序输入与机器码对应补验（2026-10-06）

4项具体LayerNorm的ISA解码、数值与周期对照说明，固定服务图可信度还依赖生成指令的语义、实际地址与操作数对应。VI立即数须按有符号5位解释，减法按实际`vs2-vs1`编码；只验证IR地址合法，无法排除机器码执行了另一地址流。先冻结预测，再独立解码words、核对访存与密集函数，最后比较逐阶段RTL，是本次证据链。新LDS butterfly与rsqrt软件组织尚未替换旧整网模板，局部事件吻合不改变有限菜单或整网准确性范围。[测试证据](../analysis/ventus_flow_20261006/layernorm_rtl_20261006/report_cn.md)。


### Ventus v7 指令组织与混合访存证据（2026-10-06）

LayerNorm的整数地址、常量装载、破坏式FMA复制、全lane LDS归约与Newton迭代均形成显式操作/依赖；32倍数宽度采用机器指令/IR配对前端，每block占用512字节LDS。代价和周期随软件组织重新生成，旧解与旧v6周期保留。缓存命中/未命中、事务返回与执行流水的交织由机制模型决定，不把算子归约为计算周期加固定内存罚时。五项完整RTL程序的局部周期与内存策略排序证据见[v7报告](../analysis/ventus_flow_20261006/performance-v7/report_cn.md)；组冲突仍多预测2条外存读，派发/取指/flush抽象不构成统一RTL等价约束。不得据局部误差声明Transformer或联合求解硬件的误差界。
