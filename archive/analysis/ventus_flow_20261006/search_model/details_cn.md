# Ventus 源码事件模型实现与验证

日期：2026-10-06。当前模型版本 `ventus-source-events-v5`。面向阅读的结论在[主文档](../report_cn.md)。

## 代码和来源

独立包为 [`codesign/ventus`](../../../codesign/ventus)。它引用项目的稀疏 MILP 矩阵工具，未改变既有 Transformer、课程或 Rust 模型的计分语义。

| 文件 | 职责 |
|---|---|
| `config.py` | 硬件尺寸、合法性、数据存储/乘法器预算、现有 RTL 绑定检查 |
| `ir.py` | 显式指令、寄存器、地址和依赖；每 block/warp 的资源需求 |
| `timing.py` | 资源日历、cache/外存事务抽象与事件图入口 |
| `online.py` | 就绪指令、collector/LSU 状态、逐 block 分配释放与服务顺序 |
| `elastic.py` | 源码 valid/ready 弹性寄存器流水 |
| `coalescer.py` | 执行 AddrCalculate/MSHR 控制，导出整行 LDS 的饱和服务模板 |
| `graph.py` | 独立最长路径重放；不读取求解器约束对象 |
| `workloads.py` | 依赖链与较大 GEMM 的时序展开 |
| `operators.py` | 生成融合 GEMM、两层 FFN、residual FFN，显式转换跨层 Tensor 布局 |
| `program.py` | 同时生成 4×4 输出的 FP32 GEMM 可执行 ISA、IR、输入和独立输出参考 |
| `mip.py` | 有限候选选择、条件事件时序、资源预算、求解状态与解复核 |
| `source.py` | 检查固定源码家族的表达式和规则位置，记录 commit、文件 SHA256 |
| `__main__.py` | 源码提取、JSON 模拟/搜索、冻结示例与只读复验 |

来源为 RTL `681172541a8a34ffb43c483a19c075acbc11a4eb` 及其 FPU 子模块。对应官方环境锁定的 `f585380` 与之硬件相同，差异只在文档。源文件、行号、关键表达式与哈希见 [`source-v3.json`](source-v3.json)。提取器检查明确的源码锚点和默认值，尚非通用 Scala 求值或自动状态机翻译器。

当前源码规则见 `source-rules-v5.json`，新增验证见 `online-accuracy-v5b.json`，当前快照在 `model-v5/`。v4 来源 `source-events-v4.json`、算子结果 `operators-combined-v4.json` 和代码 `model-v4/` 均保留；v3 代码归档在 `model-v3/`，可执行程序结果见 `accuracy-v3.json`，预测冻结在 `kernel-holdout-v3/pre_run_predictions.json`。v2 源码保存在 `model-v2/`，对应 `source-v3.json`、`demo-v2/experiment.json` 和 `accuracy-v2.json`。v1 源码与结果仍保存在 `model-v1/` 等原目录。旧实验必须用对应版本复验。

## 时序原语

时间单位是 GPU 周期；预约使用 `[start, finish)`。数值 payload 不进入模型，地址、依赖和活动 lane 必须明确提供。支持 scalar/vector integer、FADD、FMAX、FMA、Tensor、32 位 load/store，以及显式集体 barrier；不支持的种类拒绝。没有任意 ISA 解码、动态分支或完整程序求值。

### Tensor 和寄存器

默认 FP32 Tensor：乘法 2 周期，归约树的每层加法 2 周期，C 累加 2 周期，两个非 flow 输出队列各 1 周期：

\[
L_{TC}=2+2\log_2 N+2+1+1=12\quad(N=8).
\]

流水可每周期接收一次。一个 warp 的下一条有依赖指令需要写回后的下一周期解除 scoreboard，再经过 collector。不同 bank 的供数/collector 是 3 周期；同 bank 三次读增加 2 周期。因此连续依赖的周期分别为 16 和 18。

映射为 `(hardware_warp_id + register_index) % rf_banks`。标量与向量的 bank 资源分开；相同地址的重复操作数仍按读请求计数。RF 写端口与对应写回端口在同一周期联合预约。时间日历允许较早就绪的计算结果先于尚未返回的旧 load 写回，避免按建图顺序错误占住写回端口。

### LDS 和 LSU

地址以 32 位字表示。每条访存按缓存行分组；同一行的每 bank 活动 lane 数决定服务轮数：

\[
R=\max_b\left\lceil\frac{\#\{lane:\ bank(addr_{lane})=b\}}{ports_b}\right\rceil.
\]

RTL 的 `BankConflictArbiter` 不合并同地址 lane。LSU 请求前 3 个阶段、最后一轮后的同步读取/响应 3 个阶段、coalescer 1 个阶段，加上依赖和 collector，给出连续读取周期 `R+10`。默认 1/2/4/32 轮分别为 11/12/14/42 周期。

跨行请求按行顺序发出；LDS 写分组按 `R+1` 占用服务端口，其它路径按读服务和资源约束预约，地址生成器在最后一次分组获准后释放。总在途和每 warp 在途分别检查。当前没有完整重现每个阶段的 ready/valid 背压。跨行加串行等待是一种明确的事务抽象，不能用单行测试代替散射/并发验证。

v2 补充 coalescer 控制吞吐。`MSHRv2` 在 `s_idle` 接受地址登记与返回；同时出现时进入 `s_add`，再进入 `s_out`。`s_out` 使用 `complete.bitSet(valid_entry, false)` 判定是否继续，`valid_entry` 是首个空闲槽，通常不同于正在输出的槽，因此最后一个输出后还可能留在该状态一周期。

`coalescer.py` 将上述状态与 `AddrCalculate` 的 idle/save/shared 连接，提供持续整行 LDS 请求和源码的三阶段返回，直接执行控制状态。默认 8 槽饱和输出间隔为 4 周期；登记、响应和输出共享这一服务限制。事件模型增加对应吞吐预约，保留单指令 `R+10` 的依赖延迟。4/8 warp 高负载因此受共享服务限制。

该模板省略数值和逐 lane 数据，只表达受控整行返回的持续服务。混合全局/LDS、部分返回及 WB 背压的在线控制尚未完整转译；4 周期不能当作所有 load 的裸延迟。其它槽数也由控制执行得到，尚未用不同 RTL 尺寸验证。

### 全局存储

状态包括每 SM 的有限 L1、共享有限 L2、未完成的 fill、合并目标、MSHR、写记录和外存通道预约。读 miss 进入下级，写 miss 按源码采用不分配 L1 的转发路径。写 hit 标记 dirty，驱逐和最终 drain 产生写事务。v3 已转译写 miss 的本地确认、Get 与转发路径；L2 写 hit、dirty drain 与完整背压仍需对应验证。

首次全局测试发现了冷路径漏算的阶段。修正依据为：

| 路径 | 源码依据 | 修正 |
|---|---|---|
| L1 发出 miss | `DCache.scala` 的 `memReq_Q` | 1 个非 flow 队列阶段 |
| SM → cluster | `GPGPU_top.scala` 的 `memReqBuf` | 1 个队列阶段 |
| L2 → 测试外存及返回 | `GPGPU_SimWrapper.scala` 的 `pipe_a/pipe_d` | 各 2 个寄存阶段 |
| 下级返回到 L2 输出 | `SinkD.scala`、`MSHR.scala`、`SourceD.scala` | SinkD 1、MSHR 1、SourceD stage4 1；原先漏最后 1 |
| L1 返回 | `memRsp_Q`、`L1MSHR.missRspOut_st1`、`coreRsp_st2`、`coreRsp_Q` | 共 4 个阶段；原先少计 1 |

外存默认 `DELAY_DDR=2`，响应在接受后 3 个时钟边沿可用；外加连接流水。它是测试 memory wrapper，不是 DRAM 时序模型。

L2 的 `l2cache_memCycles=32` **用于推导 MSHR/缓冲容量，不能当作真实 miss 延迟**。默认 blockBytes=beatBytes=128，因此 blockBeats=1，MSHR 为 `max(2,ceil(32/1))=32`。

L2 `Directory_test.scala` 实际选用全局 16 位 LFSR 的低 way 位。模型已按此规则更新，包括数据 hit；未纳入 I-cache 和 flush 的目录访问，因此共享状态仍与完整 RTL 有差异。L1 目前采用 LRU 事务近似，尚未模拟源码时间戳 1000 次回绕、probe 重试及所有分配细节。

### block 和服务顺序

驻留上界取 block 槽、warp 槽、VGPR、SGPR 和 LDS 容量约束的最小值。block 按批次分配到 SM，批次内使用固定交错顺序。此处未实现 RTL 的连续空闲段分配、碎片、逐个回收后补发或完整 ready-aware 仲裁。

barrier 是输入中给定的一次 block 集体事件，依赖之前全部参与操作。它不接受任意部分到达模式。改变调度和访存布局要生成新的合法模板，不能只修改几个事件时间。

## MIP 编码与适用边界

候选 `j` 提供硬件与程序，源码规则编译为有限 DAG。边 `(u,v,d)` 表示 `t_v ≥ t_u+d`。二元选择 `y_j` 满足 `Σ y_j=1`；`H` 为各图逐点最大入边延迟之和的最大值加 1，是安全上界。

每个候选的事件时钟使用：

\[
0\le t_{j,v}\le Hy_j,\qquad
t_{j,v}-t_{j,u}\ge d-H(1-y_j),
\]
\[
T\ge t_{j,end}-H(1-y_j),\qquad
\sum_j y_j resource_j\le budget,\qquad \min T.
\]

非选中图的时钟为 0，选中图启用全部依赖和资源预约边。时钟用连续变量即可：整数边延迟的 DAG 最早完成时间是整数。独立执行器求最长路径，复核选中方案的周期和预算；有限示例还枚举全部候选检查目标。

**服务顺序和 cache 结果在候选建图阶段已展开。**MILP 不在求解中执行 cache 状态机，也不自由优化每次 miss、仲裁或发射。建图会执行源码转译的状态规则，这与读取 RTL profiling 耗时无关；但对大设计空间逐候选展开会产生组合爆炸。

当前 v3 的 24 候选示例产生 24 个选择变量、29,611 个总列与 79,756 个约束；v2 原记录的 26,995 列 / 72,146 约束保留在旧实验。最优性限于对应菜单与事件模型。需要大自由度联合建模时，应将尺寸档位、程序结构、映射和局部顺序分解为变量，条件启用其原语与容量约束。这个版本尚未实现该分解。

性能模拟器可以比 MIP 更详细；两者不同抽象时，要分别标注预测、可行性及最优性的对象。若模拟器发现某个 MILP 顺序硬件无法执行，可以加合法性约束或排除该结构；时间偏差则应修正缺失的原语和资源依赖。只有经过准确性核验的模型和声明设计空间，才支持性能或排序结论。

预算 `storage_bytes` 计入 VGPR/SGPR 数据、LDS、L1 数据及 L2 数据；不包括标签、I-cache、队列、端口外围和控制逻辑。`tensor_multipliers` 是算术阵列数量指标。两者没有换算为面积；当前增加端口未得到物理成本，须限制菜单并经综合确认后才能作真实成本优化。

## 独立 RTL 对照（v2 历史证据）

运行服务器为 ${REMOTE_HOST}；根目录 `${REMOTE_FLOW_ROOT}`。RTL 二进制来自旧原生构建，SHA256：`8cf5b29a0bf9e225ccb821d3801c7067df438e24a70d2c7c7aaec02a67106f33`。未修改 RTL、仿真驱动或硬件尺寸。本轮不需要重新综合 GPU。

程序手工编码 pinned ISA，主体无分支，不会被编译器优化掉。每次输出读取 32 个字。Tensor/LDS 使用已初始化的零并检查输出零；全局测试读取原 fixture，数值不作为模型输入，仅核对运行完成、输出可读和错误日志。零 Tensor 测试验证的是时序，未验证非零矩阵的数值。

计时为首个 block dispatch 至 kernel finish，日志时间单位除以 10。driver 结束后额外 drain 的 10,000 次半周期步不进入 kernel 周期。新模型只预测 decoded-body；因此主体长度增量是本轮主要准确性对象。

| 家族 | n=16 RTL | n=32 RTL | n=64 RTL | n=192 RTL |
|---|---:|---:|---:|---:|
| Tensor，不同 RF bank | 349 | — | 1117 | 3165 |
| Tensor，同 RF bank | 371 | — | 1235 | — |
| LDS 1 轮 | 300 | — | 828 | — |
| LDS 2 轮 | 315 | — | 891 | — |
| LDS 4 轮 | 345 | — | 1017 | — |
| LDS 32 轮 | 788 | — | 2804 | — |
| 全局，同一行 | 446 | 622 | 974 | — |
| 全局，128 B 步长 | 691 | 1141 | 2041 | — |
| 全局，256 B 步长 | 691 | 1141 | 2041 | — |

13 个 Tensor/LDS 程序首次预测见 [`probes-v1/pre_run_predictions.json`](probes-v1/pre_run_predictions.json)，运行见 [`rtl-probes-v3/results.json`](rtl-probes-v3/results.json)。此前服务器两次失败目录分别保留动态库加载错误与日志 UTF8 解码错误；成功运行修复了环境变量和读取脚本，硬件未改变。日志 kernel trace 的非 UTF8 名称字节按 replacement 解码；计时和输出字段仍可明确解析。

最初 4 个全局程序的运行前预测与观测见 [`memory-probes-v1/pre_run_predictions.json`](memory-probes-v1/pre_run_predictions.json)、[`rtl-memory-v1/results.json`](rtl-memory-v1/results.json)。16→64 的原始预测为 warm 576、cold 1008，RTL 为 528、1350。修正前结果保留，不能把修正后的预测声称为这四个程序的盲测。

修正后的预测再冻结到 [`memory-holdout-v1/pre_run_predictions.json`](memory-holdout-v1/pre_run_predictions.json)，随后运行 9 次：重复 4 个旧程序检查可复现性，新增 n=32 两项及 256 B 步长三项，共 5 个新程序。见 [`rtl-memory-holdout-v1/results.json`](rtl-memory-holdout-v1/results.json)。warm 的两段长度增量精确；cold 的 16→32、32→64 分别预测 448/896，RTL 为 450/900，均低约 0.44%。剩余小偏差尚未分离到具体控制阶段，未添加经验修正。

新增 8 项 2/8 warp 程序，预测见 [`multiwarp-probes-v1/pre_run_predictions.json`](multiwarp-probes-v1/pre_run_predictions.json)，观测见 [`rtl-multiwarp-v1/results.json`](rtl-multiwarp-v1/results.json)。Tensor 两种并发度和 2 warp LDS 的增量吻合；v1 的 8 warp LDS 预测 1152，RTL 为 1536，暴露了 coalescer 控制吞吐遗漏。v2 的 1536 是修正后结果，未声称是该组原始盲测。

修正后冻结 [`multiwarp-holdout-v2/pre_run_predictions.json`](multiwarp-holdout-v2/pre_run_predictions.json)，新增 4 warp 的 16/32/64 条三项及 8 warp 的 32 条一项，另复验两项旧 8 warp 程序。结果见 [`rtl-multiwarp-holdout-v2/results.json`](rtl-multiwarp-holdout-v2/results.json)。4 warp 两段增量为 256/512，8 warp 为 512/1024，模型与 RTL 精确一致。

| 程序 | n=16 RTL | n=32 RTL | n=64 RTL |
|---|---:|---:|---:|
| Tensor，2 warp | 355 | — | 1123 |
| Tensor，8 warp | 418 | — | 1186 |
| LDS，2 warp | 291 | — | 819 |
| LDS，4 warp | 393 | 649 | 1161 |
| LDS，8 warp | 686 | 1198 | 2222 |

最终 23 组增量比较、40 次运行、34 种输入与代码哈希冻结于 [`accuracy-v2.json`](accuracy-v2.json)。结果涵盖默认硬件、受控 1/2/4/8 warp；未验证缓存溢出、随机替换的长期效果、任意混合并发、其它真实硬件或全 kernel 绝对计时。

## 运行入口

在项目根目录，Mac 原生可运行：

```bash
uv run python -m codesign.ventus extract --rtl-root ${OWNER_UPSTREAM_CHECKOUT} --out /tmp/ventus-source-new.json
uv run python -m codesign.ventus demo --out /tmp/ventus-demo-new
uv run python -m codesign.ventus verify --out /tmp/ventus-demo-new
```

输出文件与目录必须不存在。现有冻结实验只读复验：

```bash
uv run python -c 'import sys; sys.path.insert(0,"analysis/ventus_flow_20261006/search_model/model-v2"); from codesign.ventus.__main__ import main; main()' verify --out analysis/ventus_flow_20261006/search_model/demo-v2
uv run python -c 'import sys,runpy; sys.path.insert(0,"analysis/ventus_flow_20261006/search_model/scripts"); sys.path.insert(0,"analysis/ventus_flow_20261006/search_model/model-v2"); runpy.run_path("analysis/ventus_flow_20261006/search_model/scripts/check_accuracy.py",run_name="__main__")' --root analysis/ventus_flow_20261006/search_model --out analysis/ventus_flow_20261006/search_model/accuracy-v2.json --verify
```

v1 结果可使用保存的 v1 源码只读复验：

```bash
uv run python -c 'import sys; sys.path.insert(0,"analysis/ventus_flow_20261006/search_model/model-v1"); from codesign.ventus.__main__ import main; main()' verify --out analysis/ventus_flow_20261006/search_model/demo-v1
uv run python -c 'import sys,runpy; sys.path.insert(0,"analysis/ventus_flow_20261006/search_model/model-v1"); runpy.run_path("analysis/ventus_flow_20261006/search_model/model-v1/check_accuracy.py",run_name="__main__")' --root analysis/ventus_flow_20261006/search_model --out analysis/ventus_flow_20261006/search_model/accuracy-v1.json --verify
```

JSON 输入支持覆盖部分硬件字段；覆盖后校验。模拟输入形如：

```json
{
  "hardware": {"rf_banks": 4},
  "workload": {
    "warps_per_block": 1,
    "vgpr_per_warp": 64,
    "sgpr_per_warp": 64,
    "lds_per_block": 0,
    "operations": [
      {"name": "mma", "kind": "tensor", "sources": ["v1", "v2", "v3"], "destination": "v1"}
    ]
  }
}
```

保存为输入文件后运行 `uv run python -m codesign.ventus simulate --input INPUT.json --out NEW.json`。load/store 加 `addresses`，每个活动 lane 一个 32 位对齐地址；可用 `dependencies` 加明确的跨操作先后关系。

搜索 JSON 使用 `candidates` 数组，每项包含 `name/hardware/workload`，另加 `budgets`（`storage_bytes`、`tensor_multipliers`）及可选 `time_limit`。运行 `uv run python -m codesign.ventus search --input MENU.json --out NEW.json`。硬件违反现有 RTL 绑定的字段会在结果中明确列出。

Python 接口提供 `Hardware.with_changes`、`workloads.gemm`、`timing.simulate`、`mip.optimize`。GEMM 的 M/N/K、warp 分工、B 转置、LDS padding 和是否走共享内存可独立构造，再组合硬件配置；必须明确哪些组合已做 RTL 验证。

## 当前需要继续修正的机制

修正来源优先级为实际 RTL 路径、源代码连接、独立 RTL 验证。下一批影响搜索可信度的机制是 ready-aware 多 warp 服务顺序、真实 CTA 分配/释放、L1 时间戳与重试、完整写协议与 cache 背压。输入应增加针对性短程序，随后检查更大 GEMM、多 warp 程序和 RF bank 之外的硬件配置。现有小误差无需作为放弃建模的理由，也不足以省略这些验证。

综合/STA 的实物成本反馈与软件生成仍各自独立；正确模型周期不能证明频率或面积，合法事件图不能证明生成程序数值正确。

## v3可执行 GEMM 验证

### 程序、初始条件与时间窗口

`program.packed_gemm` 每个 warp 计算 4×4 输出，32 个 lane 分别打包 4×8 的 A 和转置打包的 B。K=8×steps，A/B 的每个 panel 重复；输入是含正负数的小整数 FP32，CPU 通过完整 A@B 独立算参考。这个输入结构使 resident 方案合法地把每个 panel 的 load 提到循环外。没有把该复用假定用于一般不重复的矩阵。

每个案例包含真实地址生成、全部输入搬运、Tensor 累加与输出 store。四种策略为 stream（不同地址的冷 panel）、reload（每次重读同一地址）、resident（保留在 RF）与 shared（全局→LDS→RF）。RF 冲突通过真实寄存器编号改动；LDS 间隔 4/8/16 B 改动分组与请求交错。除了计时，核验实际执行 PC/指令序列以及 32 个输出字的 FP32 位模式。没有经过 OpenCL/LLVM 编译器，使用受限 ISA emitter。

初始状态：原 RTL 复位、所有 cache 为空、SRAM 清零完成。观测 shim 仅把外部 host_req 的有效信号在第 512 周期前压低；没有预先执行 kernel 或设置 DUT 内部状态。原 driver 与 RTL shared library 不变，具体二进制、生成头文件、dut.v、parameters.json 与 shim 的哈希见 [provenance](kernel-provenance-v3.json)。

计时起点为第一条 collector admission，不使用测量偏移量校准模型。两个终点分别为最终 Tensor WB、最终输出地址的外存 write acceptance。模型的 `outputs.visible` 对应后者；`cycles` 还等待写响应，通常多 5 周期，不能把该字段直接拿来比较外存可见周期。RTL host-finish 在当前路径上可能早于 store 外存写入，因此只把它作为另一项观测值保存。首条指令之前的启动与冷 I-cache 请求不在这些跨度内；窗口中后续取指等待仍计入 RTL 观测。

### 结果

| 配置 | 用途 | 计算模型 / RTL | 误差 | 输出可见模型 / RTL | 误差 |
|---|---|---:|---:|---:|---:|
| resident-16-rf0-lds1 | 定位用 | 320 / 320 | +0.000% | 348 / 348 | +0.000% |
| resident-16-rf1-lds1 | 定位用 | 352 / 352 | +0.000% | 380 / 380 | +0.000% |
| shared-4-rf0-lds1 | 定位用 | 304 / 304 | +0.000% | 332 / 332 | +0.000% |
| shared-4-rf0-lds4 | 定位用 | 373 / 361 | +3.324% | 401 / 389 | +3.085% |
| stream-16-rf0-lds1 | 定位用 | 624 / 624 | +0.000% | 652 / 652 | +0.000% |
| stream-4-rf0-lds1 | 定位用 | 192 / 192 | +0.000% | 220 / 220 | +0.000% |
| reload-12-rf0-lds1 | 新增验证 | 289 / 289 | +0.000% | 317 / 317 | +0.000% |
| resident-24-rf1-lds1 | 新增验证 | 496 / 496 | +0.000% | 524 / 524 | +0.000% |
| resident-7-rf0-lds1 | 新增验证 | 176 / 176 | +0.000% | 204 / 204 | +0.000% |
| shared-12-rf0-lds4 | 新增验证 | 957 / 923 | +3.684% | 985 / 951 | +3.575% |
| shared-7-rf0-lds1 | 新增验证 | 472 / 472 | +0.000% | 500 / 500 | +0.000% |
| shared-7-rf0-lds2 | 新增验证 | 508 / 494 | +2.834% | 536 / 522 | +2.682% |
| stream-24-rf0-lds1 | 新增验证 | 912 / 914 | -0.219% | 940 / 942 | -0.212% |
| stream-7-rf0-lds1 | 新增验证 | 300 / 300 | +0.000% | 328 / 328 | +0.000% |

14 项输出全部逐位一致。计算平均绝对误差 0.719%、最大 3.684%；输出可见平均 0.682%、最大 3.575%。8 项新增验证的预测文件保存了模型 SHA256，check 脚本拒绝模型变更或预测改变；这些结果没有回填延迟系数。Mac 原生评估 14 项约 21 ms，涵盖 24–134 条程序指令；只是该规模的运行时间，不能外推任意程序规模。

### 修正与保留的反例

1. `addi x7,x0,128` 仍需读标量 RF 中的 x0；原 IR 漏了这一操作数，流式程序少计 2 周期。LUI 和 VID 无 RF 操作数。
2. [SharedMemory](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMem.scala#L204) 的 `coreReq.ready` 要求 `!coreReqisValidWrite_st1`，写请求使下一周期无法接收。地址计算器等最后一次分组请求获准后才释放。原 GEMM IR 给后续 load 添加整个 store 返回的依赖，实际有序 LSU/LDS 并不需要这项同步，已删除。
3. [L2 MSHR](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/MSHR.scala#L97) 在 allocate 后发出的 opcode 固定为 Get，纯写 miss 的目录更新则被 `request.opcode===Get` 禁止；[SourceD](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/SourceD.scala#L217) 再转发写。原抽象直接发外存写，漏了前面的读取，已分开建模本地确认、写可见与协议完成。

分散 LDS 仍高估 2.83–3.68%，偏差出现在部分返回和读写交错中，不能把饱和整行服务模板当作完整 coalescer。最长 stream 还低估 2 周期，与尚未完整转译的取指/背压边界相关；尚未证明该 2 周期偏差的唯一原因。L2 写 hit、dirty eviction、MSHR 满、L1/L2 容量压力与混合多 warp 没有由这组实验验证。

立即复位启动的原始证据保存在 `evidence/kernel-trace-v3b`。例如 stream-4 的计算为 321 周期，清零完成后为 192；resident-16 为 453 与 320。原因来自 [dirty-mask SRAM](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/L1TagAccess.scala#L209) 的 `shouldReset=true` 和 [SRAMTemplate](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/SRAMTemplate/SRAMTemplate.scala#L113) 的逐 set 清零；当前模型不处理复位剩余时间。首次立即启动的数值输出仍正确，但周期不能用稳态模型直接预测。旧缺少真实内部信号观测的尝试保留在服务器 `kernel-probes-v3`、`kernel-trace-v3`，不纳入上述验证统计。

### 可执行软件搜索与复验

同一 K=128 输入和默认硬件，三项菜单是 stream、resident 和同 RF bank 的 resident。MILP 选择 resident；模型协议完成目标 353，物理输出可见时刻 348。RTL 对这三个方案的输出跨度是 652、348、380，独立枚举与 RTL 最优者均一致。相对 stream，物理输出减少 46.626%；主机 dispatch→finish 的 RTL 值另为 669 与 365，减少 45.441%，但模型没有预测该主机窗口。这里只验证有限软件菜单，没有验证硬件修改收益或一般 GEMM 的复用收益。

只读复验，不运行 solver，不覆盖文件：

```bash
PYTHONPATH=analysis/ventus_flow_20261006/search_model/model-v3:. uv run python analysis/ventus_flow_20261006/search_model/model-v3/check_kernels.py --root analysis/ventus_flow_20261006/search_model --out analysis/ventus_flow_20261006/search_model/accuracy-v3.json --verify
```

重新生成新程序可调用 `program.packed_gemm(...).write(new_directory, upstream_vecadd_fixture)`，运行 RTL 用 `scripts/run_kernels.py ROOT NEW_RESULT SOURCE_DIRECTORY`。shim 编译固定使用原 debug library 的 Verilator 头文件，`LD_PRELOAD`、`VENTUS_TRACE_PATH` 与第 512 周期的外部启动延迟由 runner 设置。重新运行必须另取新结果名，不覆盖历史。v3 修改后的纯时序 24 项示例保存在 `demo-v3`，不计入 14 个真实 kernel 的统计。

最终验证：`ruff check codesign tests`、`ruff format --check codesign tests` 与 `pytest -q` 通过（509 项，175.03 s）；v2 历史增量与菜单、v3 混合 kernel 和菜单均通过只读复验。

## v4融合算子与两层 FFN

### 实现和来源

`codesign/ventus/operators.py` 直接生成实际 Ventus 指令及带 PC 的时序 IR。GEMM epilogue 为 `ReLU(XW+b)`；FFN 为 `ReLU(XW₁+b₁)W₂+b₂`，residual 版本再加独立 residual 矩阵。batch=4，D=8/16/24/32，H=8/16，输出宽度 4。独立 dense reference 使用完整矩阵归约；各输入、权重和偏置按索引与 seed 生成，不复用此前 GEMM 的重复 panel 假设。数据为可精确表示的小整数 FP32，激活中包含正值与零值。

TC 输出的 4×4 数据位于前 16 个 lane，后 16 个为零。scatter 地址把这些 lane 写成带行跨度的中间矩阵；额外零 lane 写入四个额外行，与有效数据不重叠。下一层 gather 地址读取真实四行的八个元素，构成 TC 的 4×8 A 输入。没有用未实现的 register gather，也没有把布局转换隐藏在一个免费 reshape 中。中间矩阵在 LDS 或全局 B buffer 的空闲区域，两个路径使用相同数值与数学语义。全局路径没有重新发起 host kernel；这两条都为同一 kernel 内的实际搬运。

v4 新增 `fmax` 原语，来自 `dependencies/fpuv2/src/main/scala/FCMP.scala` 的 `override def latency = 2`；VFMAX decode 选择该 FCMP 路径，ScalarFPU/VectorFPU 直接接输出仲裁，没有 FMA 分支中的结果 FIFO。collector 和 RF/WB 仍单独计时。规则与源码哈希见 [source-events-v4.json](source-events-v4.json)。没有根据 RTL 总耗时调低延迟。v3 代码在 `model-v3/` 冻结；[旧 GEMM 回归](gemm-regression-v4.json)核对全部 14 项预测逐项不变。

### 冻结与核验

首批 6 项的输入和预测在运行前写入 [operators-probes-v4/pre_run_predictions.json](operators-probes-v4/pre_run_predictions.json)。确认第一批数值与时序后，没有改动模型代码，另生成 7 项 [operators-holdout-v4/pre_run_predictions.json](operators-holdout-v4/pre_run_predictions.json)，再运行 RTL。两个批次的模型 SHA256 完全一致。初始条件与 v3 相同：reset 完成、冷 cache、host_req 在周期 512 后允许启动。原二进制和 RTL library 没有改动。

`check_operators.py` 验证输入哈希、driver/library 哈希记录、实际 PC/指令序列、32 个输出字，以及每个算术阶段的 WB。时序起点为首条 collector admission；终点为最后一个 ReLU、bias 或 residual 的 WB，以及最终 C 地址的外存写入。FFN 不能继续用最后一个 Tensor WB 代表完整算子完成。

| 程序 | 批次 | 最终算术模型 / RTL | 输出可见模型 / RTL | 输出偏差 |
|---|---|---:|---:|---:|
| epilogue-d16-h4-lds-r0-s1 | 首批 | 212 / 212 | 250 / 250 | +0.000% |
| epilogue-d32-h4-lds-r0-s2 | 首批 | 364 / 364 | 402 / 402 | +0.000% |
| ffn-d8-h8-lds-r0-s1 | 首批 | 508 / 509 | 546 / 545 | +0.183% |
| ffn-d8-h8-global-r0-s1 | 首批 | 518 / 519 | 556 / 555 | +0.180% |
| ffn-d16-h16-lds-r1-s1 | 首批 | 1329 / 1329 | 1367 / 1365 | +0.147% |
| ffn-d16-h16-global-r1-s1 | 首批 | 1339 / 1341 | 1377 / 1377 | +0.000% |
| epilogue-d24-h4-lds-r0-s4 | 追加配置 | 288 / 288 | 326 / 326 | +0.000% |
| ffn-d24-h8-lds-r0-s3 | 追加配置 | 812 / 813 | 850 / 849 | +0.118% |
| ffn-d24-h8-global-r0-s3 | 追加配置 | 822 / 823 | 860 / 859 | +0.116% |
| ffn-d8-h16-lds-r1-s2 | 追加配置 | 1025 / 1025 | 1063 / 1061 | +0.189% |
| ffn-d8-h16-global-r1-s2 | 追加配置 | 1035 / 1037 | 1073 / 1073 | +0.000% |
| ffn-d32-h16-lds-r1-s5 | 追加配置 | 1937 / 1939 | 1975 / 1975 | +0.000% |
| ffn-d32-h16-global-r1-s5 | 追加配置 | 1947 / 1949 | 1985 / 1985 | +0.000% |

完整结果见 [operators-combined-v4.json](operators-combined-v4.json)，首批独立收据保存在 [operators-accuracy-v4.json](operators-accuracy-v4.json)。原始 stdout/stderr/trace.csv/summary.json 位于 `evidence/operators-probes-v4/` 与 `evidence/operators-holdout-v4/`。13 项输出逐位一致，输出可见平均/最大绝对误差为 0.07176%/0.18850%，算术完成最大 0.19646%。逐阶段最大偏差 3 周期，不能把部分终点的精确吻合解释为所有内部阶段完全吻合。几处第二层 bias 与收尾的细小偏差尚未完全归因，没有增加补偿常数。

模型单次原生评估全部 13 项约 42 ms；固定程序为 40–344 条指令。仍为单 warp 固定展开的直接 ISA 程序，未通过 LLVM/PoCL 编译完整模型，也不包含 softmax、GELU、完整 attention 或多 warp 融合。地址生成使一些搬运之间留有指令间隔，结果尚不足以保证任意紧密读写交错、容量压力与资源重排都准确；旧分散 LDS 的约 3% 反例仍保留。

### MIP 选择与只读复验

五组相同 FFN 的 LDS/全局路径各组成两项有限菜单。目标仍为协议完成的 `cycles`，对照另外报告物理输出可见时刻。MIP、枚举、RTL 均选择 LDS，RTL 输出可见周期分别为 545/555、849/859、1061/1073、1365/1377、1975/1985。收益为 10–12 周期；没有声称这些固定程序已达到所有软件方案的最优性。五次 MIP 合计约 1.09 s；[搜索收据](operators-search-v4.json)保存解、bound、gap 与双方周期。

以下复验不重新求解，不覆盖结果：

```bash
PYTHONPATH=analysis/ventus_flow_20261006/search_model/model-v4:. .venv/bin/python analysis/ventus_flow_20261006/search_model/model-v4/check_operators.py --root analysis/ventus_flow_20261006/search_model --batches operators-probes-v4 operators-holdout-v4 --out analysis/ventus_flow_20261006/search_model/operators-combined-v4.json --verify
PYTHONPATH=analysis/ventus_flow_20261006/search_model/model-v4:. .venv/bin/python analysis/ventus_flow_20261006/search_model/model-v4/search_operators.py --accuracy analysis/ventus_flow_20261006/search_model/operators-combined-v4.json --out analysis/ventus_flow_20261006/search_model/operators-search-v4.json --verify
```

生成新实验用 `scripts/generate_operators.py --root ROOT --batch NEW_NAME [--holdout]`，必须使用新目录名。脚本先保存程序、配置、模型 SHA256 与预测，再由 `scripts/run_kernels.py ROOT NEW_RESULT SOURCE_DIRECTORY` 运行 Linux 上原 RTL。复现 driver/library 与 trace shim 的身份可交叉核对 v3 provenance 及各 v4 summary 中的 SHA256。

最终 v4 回归：`ruff check codesign tests`、`ruff format --check codesign tests` 通过（99 个 Python 文件）；`pytest -q` 为 518 项通过，175.01 s。13 项算子与五组菜单均已只读复验；归档 v3 的 14 项 GEMM 准确性收据也只读复验通过。

## v4参数变化的机制审查

配置仍为 29 个硬件字段与 3 个外存目标字段，v4 扩展了算子覆盖，没有增加硬件字段。现有维度均参与合法性、资源、事件时序或程序 lowering；参与计算不构成跨配置 RTL 准确性证明。详见[主文档中的参数边界](../report_cn.md#改变量后模拟器能否正确处理)。

`audit_parameters.py` 在不编译/运行 RTL 的条件下检查 RF 供数递推、LDS bank/端口请求计数，以及改变 Tensor 形状后同一 GEMM 的 FLOP 守恒，并保留复用旧 IR 导致工作量改变的反例。它验证所实现抽象的机制一致性，不声称验证全部 32 项或非默认硬件。冻结结果为 [parameter-audit-v4.json](parameter-audit-v4.json)，复验如下：

```bash
PYTHONPATH=analysis/ventus_flow_20261006/search_model/model-v4:. .venv/bin/python analysis/ventus_flow_20261006/search_model/model-v4/audit_parameters.py --out analysis/ventus_flow_20261006/search_model/parameter-audit-v4.json --verify
```

只修改 Tensor 单元数时，当前每 SM 的向量 issue 仍为一条/周期，单 TC 的流水也可每周期接受一条，因此不能期待自动倍增 Tensor 吞吐。要表达更宽发射、独立 operand dispatch 与结果仲裁，需同时建立这些硬件连接的机制。collector/驻留采用固定服务顺序和 cohort 释放；LDS coalescer 为整行饱和模板；cache 状态按建图顺序更新且未完整实现重试。这些都是全维搜索的现存边界。


## RF bank 4→8 的真实硬件对照

### 配置、源码修复与硬件构建

仅改变 `rf_banks` 4→8，其它 31 个模型配置字段保持默认。总 VGPR/SGPR 参数不变，单 bank 深度随 bank 数派生。原 RTL 为 commit `681172541a8a34ffb43c483a19c075acbc11a4eb`，Linux 上 `${REMOTE_PROJECT_ROOT}` 的原源码、`dut.v` 和默认二进制保留。

源码 `operandCollector.scala` 的 `wbVecBankId`/`wbScaBankId` 固定为 `UInt(2.W)`，8 bank 时会截断写回 bank 编号。隔离副本用 `UInt(log2Ceil(num_bank).W)` 修复两处；[补丁](parameter-rtl-v4/rf-bank-width.patch)未改上游目录。默认 4 bank 的位宽仍为 2，新增 8 bank 为 3。这是本次能正确执行新增硬件配置的必要修复，不能直接宣称未经修复的原始参数入口已支持该配置。

本次采用模块组合构建：重新编译参数与 RF/collector 源文件，Chisel 生成 RF 子树，替换原整芯片的 `operandCollector` 并给其依赖模块加独立前缀。共 13 个生成模块，289 个其它模块定义逐字节保留。`pipe` 仅为独立生成时保留的无用输出、调试输入增加终止连接；默认 4 bank 的独立生成也具有完全相同的额外端口，原有端口名称、方向和位宽逐项检查。最后对组合后的完整芯片运行 Verilator。没有完成“全芯片重新 elaboration 后与该组合逐模块等价”的形式证明；此证据属于源码生成子树接入完整芯片的执行对照。

构建工具为 Scala 2.13.12、Chisel 6.4.0、JDK 17、Verilator 5.049。JDK 和 liblz4/libzstd 开发文件安装在任务目录内；FST 运行库要求压缩库链接在对象文件之后。最终硬件目录为服务器 `${REMOTE_FLOW_ROOT}/parameter-rtl-v4/rf-banks8-fixed3/`，整芯片 driver 为 `sim-verilator/build/driver_example/debug/sim-VentusRTL`。[完整来源与二进制哈希](parameter-rtl-v4/complete-subtree-provenance4.json)记录源码、补丁、原/新 RTL、派生参数和 driver/library/observer 身份。

构建步骤分别保存在 `scripts/build_parameter_rtl.py`、`emit_rf_component.py`、`build_rf_subtree.py`、`resume_rf_cpp.py` 与 `link_rf_cpp.py`；它们是本次分步恢复记录，尚未整理为无状态的一键安装器。实际成功路径为 RF 子树生成/组合→补足 task-local 开发头文件→生成 C++ 编译→修正压缩库链接顺序→编译最终 observer。首次全芯片 elaboration 因耗时与发现的位宽缺陷终止；失败目录和日志保留，不作为成功生成证据。

### 预测冻结、正式对照与反例

[parameter-rf8-v4b/pre_run_predictions.json](parameter-rf8-v4b/pre_run_predictions.json)在正式 RTL 时序运行前冻结。六个程序复用默认测试的完全相同指令与数据，重新从当前 `packed_gemm`/`fused_operator` 生成 IR，只向 `Hardware` 覆盖 `rf_banks=8`。模型仍为 v4，代码 SHA256 与默认硬件测试完全一致，未增加延迟补偿或根据新增结果调整规则。

正式运行是 `evidence/parameter-rf8-v4d/`。冷 cache、SRAM 清零完成、外部启动门控到周期 512；时间从首条 collector admission 到最终算术 WB 或 C 输出地址实际外存写入。observer 使用同一硬件二进制的生成头文件；`io_controlX_ready` 被 Verilator 优化为 `Demux.outReady2.orR`，根据生成 trace 的实际表达式观测。collector 全部 PC/指令按序核对，全部 32 个输出字与独立参考一致。

| 程序 | 4 bank：计算 / 输出 RTL | 8 bank：计算模型 / RTL | 8 bank：输出模型 / RTL | 输出变化模型 / RTL |
|---|---:|---:|---:|---:|
| resident-16-rf1-lds1 | 352 / 380 | 336 / 336 | 364 / 364 | −16 / −16 |
| resident-16-rf0-lds1 | 320 / 348 | 320 / 320 | 348 / 348 | 0 / 0 |
| stream-16-rf0-lds1 | 624 / 652 | 624 / 624 | 652 / 652 | 0 / 0 |
| shared-4-rf0-lds4 | 361 / 389 | 373 / 361 | 401 / 389 | 0 / 0 |
| ffn-d16-h16-lds-r1-s1 | 1329 / 1365 | 1329 / 1329 | 1367 / 1365 | 0 / 0 |
| ffn-d16-h16-global-r1-s1 | 1341 / 1377 | 1339 / 1341 | 1377 / 1377 | 0 / 0 |

六项计算/输出变化量都正确。RF 冲突程序的 v5/v9/v1，在 4 bank 中是 1/1/1，在 8 bank 中是 5/1/1；单 bank 单读端口因此从三轮变成两轮，16 条 Tensor 指令总共减少 16 周期。没有新建 8 bank 专用时序常数。

绝对输出周期平均/最大误差为 0.53856%/3.08483%，算术完成最大 3.32410%。最大误差来自既有分散 LDS 的 12 周期高估，模型对该程序仍未完整处理 coalescer 部分返回与交错。FFN 的算术或输出误差最多 2 周期。这次改变 RF bank 没有修复上述误差，也不验证改变 LDS bank、端口、TC 形状、cache 队列和多 warp 调度后的准确性。

### 排除的尝试与只读复验

首个 `parameter-rf8-v4` 冻结目录误用了旧 IR，发现后未运行，保留以说明为何需要按当前源码重新生成；有效冻结为 v4b。随后 `evidence/parameter-rf8-v4b/` 在 observer 链接完成前启动，首批 `LD_PRELOAD` 被忽略，没有完整周期记录，整批排除。`evidence/parameter-rf8-v4c/` 能记录终点但漏记标量 collector admission，因为新 Verilator 的 X.ready 只是未更新的别名字段；完整指令验证未通过，整批排除。修正真实 ready 信号后的 v4d 才纳入时序统计。runner 已加 observer 文件存在检查与缺失 trace/loader 错误拒绝。

[parameter-accuracy-rf8-v4.json](parameter-accuracy-rf8-v4.json)保存配置、前后周期、变化量、误差、baseline 收据及证据哈希。核验器检查模型未变、硬件身份、相同程序/输入、完整实际指令序列、输出数值和默认结果不被改写。

```bash
PYTHONPATH=analysis/ventus_flow_20261006/search_model/model-v4:. .venv/bin/python analysis/ventus_flow_20261006/search_model/model-v4/check_parameter_rtl.py --root analysis/ventus_flow_20261006/search_model --out analysis/ventus_flow_20261006/search_model/parameter-accuracy-rf8-v4.json --verify
```

需要重复 RTL 测试时，使用新结果名：

```bash
ssh ${REMOTE_HOST} 'python3 ${REMOTE_FLOW_ROOT}/run_parameter_kernels-fixed4.py ${REMOTE_FLOW_ROOT} NEW_RESULT_NAME parameter-rf8-v4b'
```

将服务器 `evidence/NEW_RESULT_NAME` 复制到本地相同根目录后，用 `check_parameter_rtl.py --evidence-batch NEW_RESULT_NAME --out NEW_RECEIPT.json` 写新收据。保持当前硬件库和最终 observer 哈希一致；历史结果复验只用 `--verify`。日常模型改 bank 数只需要 JSON 覆盖，不需要运行此 RTL 步骤。

本轮模型回归 518 项通过（176.38 s），相关参数回归 54 项通过；模拟器代码未因 RF8 结果改变。最终 Ruff 与冻结证据复验见运行记录。


## 扩大参数范围：Tensor 与 LDS 模块 RTL

本节追加参数化原语的真实 RTL 运行，模拟器源码保持 v4；[冻结预测](primitive-parameters-v4/pre_run_predictions.json)在组件运行前保存。区别于上一节接入整芯片的 RF8，这一轮单独生成和仿真 `vTCexe` 与 `SharedMemory`，用于核验各尺寸的局部契约，未把新形状或 LDS bank 接入完整 kernel。没有用结果调整任何模型常数。

### Tensor：六种三维形状与背压

沿用 `TensorCoreFP32` 与 `vTCexe` 的现有实现，把 `tc_dim` 从根据线程数选择的固定表开放为三维配置；warp 仍为 32 lane。每个形状运行连续输入 64 条，另运行输入空隙/输出背压 64 条，总计 768 条。每条的 A/B/C 含有不同的小整数 FP32，独立 dense 点积逐 lane 核对，并检查目标寄存器编号顺序、32 个输出字及未使用 lane 为零。

| M×N×K（N 为归约维） | FLOP/指令 | 源码预测 / RTL 无背压延迟 | RTL II | 背压模式实际延迟范围 |
|---|---:|---:|---:|---:|
| 4×8×4 | 256 | 12 / 12 | 1 | 12–22 |
| 4×4×4 | 128 | 10 / 10 | 1 | 10–19 |
| 2×16×2 | 128 | 14 / 14 | 1 | 14–27 |
| 8×4×4 | 256 | 10 / 10 | 1 | 10–19 |
| 2×4×2 | 32 | 10 / 10 | 1 | 10–19 |
| 4×2×4 | 64 | 8 / 8 | 1 | 8–16 |

无背压时，v4 的 `2+2log₂(N)+2+2` 公式与真实入/出握手全部吻合。M/K 改变阵列数量、打包与每条工作量，归约树深度由 N 决定。输出背压模式每 11 周期只允许前 6 周期接收，输入同时留空隙；768 条数值与顺序全部正确，受到输入阻塞的周期数和延迟范围也保存。

背压运行核验了硬件数据/控制完整性，未宣称 v4 预测了表中背压周期。当时 v4 模型只有执行延迟和结果资源预约，未完整实现有限队列逐级传播。因此这个结果支持三维原语参数化，同时揭示需要在线流水/队列机制；不支持“任意 TC 单元数或写回带宽都已准确”。本轮各指令工作量随硬件形状不同，未作为同一完整 GEMM 的端到端加速比较。

### LDS：bank/lane 解绑与服务轮数

原 `NBanks=NLanes`，`BankConflictArbiter`/`DataCrossbar` 中有等尺寸假定：活动 lane 的循环以 NBanks 为上界，同一个选择信号同时作为两种方向的 crossbar 选择。局部补丁把读/写选择拆开，write crossbar 为 lane→bank，read 为 bank→lane，活动 lane 循环使用 NLanes；保留单 bank 单服务、固定 lane 优先级和原流水级数。参数层增加独立 bank 数入口。补丁、原始源码、修改后的源码和完整生成 RTL 均在 [primitive-parameters-v4](primitive-parameters-v4/)。

保持 32 lane，分别生成 32/16/8 bank 的 128 KiB 模块，以及 16 bank 的 16 KiB 模块。每个模块运行 stride=1/2/4/8/32 五类地址，每类先写后读，共 40 个事务。地址在同一 128 B 行内，按 `(lane*stride)%32` 选择字；高 stride 包含同地址访问，源硬件不合并这些 lane。写入值按物理字地址生成，读回逐活动 lane 验证；每一轮的响应 mask 不重叠且总共覆盖 32 lane。

| bank 数 | stride=1/2/4/8/32 的服务轮数 | 最后返回距请求握手的周期 |
|---|---|---|
| 32 | 1 / 2 / 4 / 8 / 32 | 3 / 4 / 6 / 10 / 34 |
| 16 | 2 / 4 / 8 / 16 / 32 | 4 / 6 / 10 / 18 / 34 |
| 8 | 4 / 8 / 16 / 32 / 32 | 6 / 10 / 18 / 34 / 34 |

40 项的读写首响应均为 3 周期，末响应为 `rounds+2`，服务轮数与源码/模型的 bank 请求计数逐项一致。16 KiB 与 128 KiB 的低地址结果相同；仅证明尺寸生成和这个地址范围的读写，未验证容量压力、最后一个 set、block 驻留或地址重分配，也未包含 LSU coalescer/MSHR 的混合返回。本节结果不消除整芯片分散 LDS 的 12 周期误差。

### 来源、结果与复验

生成/构建脚本为 `scripts/test_parameter_primitives.py`，使用同一上游编译 classpath，隔离编译四份源码与 emit helper，通过 JVM 属性选择尺寸。每个组件由 Verilator 5.049 原生 C++ 仿真；保留生成 RTL、harness、build.log、run.log、result.json、RTL 和二进制哈希。首个准备步骤因原文件未复制而失败，`prepare-failed0.log` 保留；有效组件生成与执行全部成功。脚本在新任务目录执行，不覆盖历史。

[参数原语准确性收据](parameter-primitives-accuracy-v4.json)记录冻结模型哈希、源码和补丁哈希、各形状及各读写窗口，已验证时序差值全部为 0。原始 `results.json` 同时记录每个仿真二进制身份。只读复验：

```bash
PYTHONPATH=analysis/ventus_flow_20261006/search_model/model-v4:. .venv/bin/python analysis/ventus_flow_20261006/search_model/model-v4/check_parameter_primitives.py --root analysis/ventus_flow_20261006/search_model/primitive-parameters-v4 --out analysis/ventus_flow_20261006/search_model/parameter-primitives-accuracy-v4.json --verify
```

### 并发与缓存层的结构反例

[parameter-counterexamples-v4.json](parameter-counterexamples-v4.json)保存两个小程序的 IR、各配置、完整关键事件和模型哈希，属于模型机制反例，没有新 RTL 周期观测。

1. **早就绪请求被未来请求挡住。**warp 0 的十条依赖 TC 后才发出 slowA；warp 1 的 fastB 无此依赖。v4 按 IR 处理 slowA 在先，记录其 address.release=167；随后 fastB 虽 issue=54，address 仍被前述资源历史强制推迟到 167。slowA 自身 issue=163，这项顺序约束没有由在线请求到达建立。缩小为 L1 单 set 后，1/2 way 又得到不同的替换与完成时刻，但两者都带着同一个 113 周期人为等待。要验证 way/MSHR/LSU 尺寸的性能，须先按实际发射和请求到达维护状态。
2. **空闲 SM 等待整批 block。**三个独立 block 的 Tensor 链长度为 100/1/100，每 SM 只允许一个 block。模型在 1/2/3 SM 下给出 3213/3198/1599 周期。2 SM 时短 block 在 15 已结束，第三个 block 第一条仍在 1599 才允许进入；cohort.done 造成等待。源码 [allocator.scala](source_evidence/allocator.scala)逐 CU 检查资源，CU interface/resource table 按完成 WG 释放，没有全 SM cohort barrier。因此这些模型数字不能直接用于 SM/驻留资源的物理优化。

这两项用于定位需要补足的调度机制，不能把 113 或 1599 描述为实测 RTL 误差，也没有为它们拟合补偿。复验如下：

```bash
PYTHONPATH=analysis/ventus_flow_20261006/search_model/model-v4:. .venv/bin/python analysis/ventus_flow_20261006/search_model/model-v4/check_parameter_counterexamples.py --input analysis/ventus_flow_20261006/search_model/parameter-counterexamples-v4.json
```

当前已有跨配置真实证据的硬件字段为 RF bank（整芯片）以及 Tensor M/N/K、LDS bank（模块）。LDS 容量仅有结构/低地址检查。其它端口、collector、驻留、cache 和在途资源字段仍需各自的实现与机制对照；这里没有把配置字段总数当作已验证维度数。MIP 继续是有限菜单接口，不因此获得五个字段的任意组合搜索证明。

最终三类证据（RF8 整芯片、Tensor/LDS 模块、结构反例）均通过只读复验；`ruff check codesign tests`、`ruff format --check codesign tests` 和五份新增/修改测试工具的直接 Ruff 检查通过，相关 `pytest -q tests/test_ventus.py` 为 54 项通过（2.37 s）。本轮此前完整回归为 518 项通过（176.38 s），此后模型包未改变。


## v5：在线执行与并发对照

v4 的完整 Python 包已归档在 `model-v4/codesign/ventus/`，旧收据按上述命令只读复验。当前 v5 包与检查器保存在 `model-v5/`；首次冻结多 warp 预测时的代码另保存在 `model-v5-pre-rtl/`。各文件哈希均保留。模型的 timing 部分在冻结后未变；之后修复 `mip.py` 的数值条件、更新 `source.py` 的来源锚点/说明。核验器逐文件验证这两个非计时差异，并重新计算全部冻结预测，不把事后回归称为原始盲测。

### 在线机制与源码契约

`online.py` 的每个 warp 维护有序解码流。collector 接收必须满足既有 writer 的实际写回、显式依赖、上一指令已发射及 block 已驻留；RF 读取按 `(physical_wid+reg)%banks` 和端口日历预约。collector 到发射前保持占用，标量/向量各一条每周期；原绑定的 instDemux 保留 V 第一空槽、X 第二空槽规则，解绑后的 collector 使用声明的通用分配。实际 RF 仲裁仍近似，部分 FPU 输出内部 mux 未完整转译。

执行器维护单项 LSU 输入缓冲，按当前地址路径与每 warp/SM 占用进入 memory abstraction；loads 实际 WB 后释放在途占用，store 按已有本地确认契约退休。cache 事务仍会提前构造后续预约并更新 tag/fill 记录，有限 MSHR/retry/返回仲裁尚未完全在线；不能把入口的就绪化描述为完整 D-cache/L2 状态翻译。LDS coalescer 的饱和整行模板保留。

每个 block 完成自身全部指令后释放其 warp 和驻留槽，allocator 选择上一 CU 后的可用 CU。译入的是分配/释放原则和整数容量，尚未模拟 CTA scheduler 的 FSM 开销、物理分配碎片、ENDPRG 收尾/scan。IR 中一个 `barrier` 表示 block 集体 fence；等待 IR 前缀退休并阻止后继，尚非逐 warp barrier arrival 模型。

`elastic.py` 对各计算 stage 保存 token/valid；`ready_i = empty_i or ready_(i+1)`，只在 ready 时从上一拍移入；输出受阻会逐级阻塞并限制发射。TC 延迟仍从归约树推导，WB 保留 VALU=0、FPU=1、LSU=2、TC=5 的源优先级。实际移动/写回节点和释放阻塞边组成 DAG，service-clock guards 记录这次在线执行的时刻。最长路径重放因此可复核该服务执行；MIP 不得自由重排这些时刻。新增来源锚点（HasPipelineReg、ibuffer、writeback、allocator、CTA2warp）及 SHA256 见 [source-rules-v5.json](source-rules-v5.json)。

两个保留的 v4 结构反例在 v5 的新事件为：

| 机制 | v4 | v5 |
|---|---|---|
| 快/慢 warp 的访存进入 | fastB issue=54/address=167；slowA issue=163 | fastB issue/address=4；fastA address=32；slowA address=163 |
| 2 SM 长/短/长 block，block 槽=1 | 短 block=15 完成，第三 block=1599 才 collect；总=3198 | 第三 block=15 collect；总=1614 |

1/3 SM 的 block 对照保留 3213/1599 周期。双 warp cache 例的 1/2 way 都为 170 周期，顺序错误修复后不再产生旧的额外 way 收益。以上为源码契约回归，尚无这两个自定义程序的 RTL 百分比结论。

### 六种 Tensor 形状的弹性控制

使用此前模块 RTL 的 6 形状 × 2 模式，共 12 组观测。连续输入 64 条；背压模式为输入 cycle%3!=1，输出 ready=cycle%11<6。v5 核对 accepted/output 数量、严格顺序、首尾输出周期、最小/最大延迟与 input_stalls，全部逐项吻合。数值由保留的 dense FP32 RTL harness 核验，当前 timing 模型不计算数值。模块证据属事后机制复核，没有重新标为未知配置盲测。

| 归约维 N | 无背压延迟 | 背压首 / 尾输出 | 背压延迟范围 | 输入停顿 |
|---|---:|---:|---:|---:|
| 2 | 8 | 11 / 124 | 8–16 | 11 |
| 4 | 10 | 11 / 125 | 10–19 | 10 |
| 8 | 12 | 12 / 132 | 12–22 | 10 |
| 16 | 14 | 14 / 133 | 14–27 | 8 |

### 12 次新增多 warp 数值 RTL

生成器 `scripts/generate_online_probes.py` 从 resident GEMM emitter 取真实 prefix，复制为独立 warp 流；每 warp Tensor 条数 8/32，warp 数 2/4/8。尾部真实 CSRRS 读取 CSR.threadid（warp×32），转换为字节偏移后写自己的 128 B 输出片。独立 FP32 GEMM 参考有正负非零元素；实际缓冲中的每个 warp 输出逐位核对。复用 panel 的合法性来自固定输入，两种 K 表示数学工作量不同，仅用于增量检验，不称为同任务优化收益。

冻结目录为 [online-probes-v5](online-probes-v5/)，包含完整 words、IR、数值参考、输入 SHA、RF4/RF8 的预测与各 warp 终点。运行前冻结后，使用原 RF4 和此前已生成的 RF8 二进制，共 12 次新的整芯片 Verilator 运行；不改 DUT、计算单元或 cache。runner `scripts/run_online_probes.py` 使用配套 observer，gate=512，检查 observer 加载和 trace 存在。原始目录为 `evidence/online-rf4-v5/` 与 `evidence/online-rf8-v5/`。

核验器 `scripts/check_online_v5.py` 检查二进制/库/observer provenance、冻结数值输入、每个 warp 的完整 PC/word 流、唯一最终 Tensor WB 与输出数值。计算窗口从第一 collector admission 到所有 warp 中最后 TC 写回，不含输出 epilogue、host-finish 或物理输出写；与单 warp 的输出可见窗口分开报告。

| warp 数 | 每 warp TC 条数 | 预测 / RTL | 误差 |
|---|---:|---:|---:|
| 2 | 8 / 32 | 197/200；581/584 | -1.50% / -0.51% |
| 4 | 8 / 32 | 210/216；594/600 | -2.78% / -1.00% |
| 8 | 8 / 32 | 255/304；639/688 | -16.12% / -7.12% |

RF4/RF8 对这些不同 bank 操作数程序的结果相同，12 项全部逐位正确。各配置增加 24 TC 的模型/RTL 周期增量均为 384。8 warp 实际首 collector 相对时刻为 0/5/13/28/56/69/104/112，模型从已解码可用流开始，未译入 CTA/I-cache/instruction-buffer 供给；并发模型的绝对时长已有显著反例。具体 49 周期误差如何分配到前端和资源竞争，不能仅凭这些观测确定，也没有拟合一个启动偏移量。

首次下载在服务器运行完成前启动，保存在 `evidence/online-rf{4,8}-v5-partial-copy/`，不参与统计；运行完成后下载到新的正式目录。原文件不覆盖。

### 旧结果复核与有限菜单

v5 对保留的 13 项复杂算子、14 项 GEMM、6 项 RF8 共 33 项做事后回归，旧模型和旧 receipts 只读验证，旧预测不改写。13 项复杂算子的输出可见平均/最大绝对误差为 0.04105%/0.18639%，算术最大 0.19286%；14 GEMM 保留最大输出误差 3.57518%，分散 LDS 的已知偏差未消除。RF8 六项复核同样保留分散 LDS 的 12 周期差值。新回归明细在 [online-accuracy-v5b.json](online-accuracy-v5b.json)。

v5 的绝对 service-clock guards 使旧入边延迟求和上界膨胀，最初 demo 求解的不足周期被独立重放拒绝，目录 `demo-v5/` 留空并保留为失败尝试。修复 `mip.py`：H 取所有候选独立 DAG 最早执行的最大时刻加一；条件边为 `t_v-t_u≥d*y`，未选候选时 clock=0，终点约束 `T≥t_end`。整数语义等价，减少无意义的大系数。该修复改变优化器数值表达，没有改变冻结 timing。

当前 [demo-v5c/experiment.json](demo-v5c/experiment.json) 的 24 候选，39,863 列、108,287 行，最优目标/bound 都为 238，gap=0；独立枚举同选 `h0-w2-b1`，评估约 0.132 s，MIP 约 4.58 s（Mac 本次运行）。只在这个有限菜单与事务模型内声明最优。`demo-v5b/` 是来源说明扩充前的成功运行，保持其原 hash；当前复验用 v5c。

### 当前复验入口

在项目根目录，只读重放新证据和已保存解：

```bash
PYTHONPATH=. .venv/bin/python analysis/ventus_flow_20261006/search_model/scripts/check_online_v5.py --root analysis/ventus_flow_20261006/search_model --out analysis/ventus_flow_20261006/search_model/online-accuracy-v5b.json --verify
PYTHONPATH=. .venv/bin/python -m codesign.ventus verify --out analysis/ventus_flow_20261006/search_model/demo-v5c
```

如需新增 RTL 观测，应使用新 batch/result 名，先运行 generator 保存预测，再同步到 Linux，并调用 `run_online_probes.py ROOT NEW_RESULT SOURCE_BATCH 4` 或 `8`；不覆盖本文结果。日常改尺寸模拟与有限菜单搜索均不需要这个 RTL 步骤。

最终检查：`ruff check codesign tests`、`ruff format --check codesign tests` 通过；三份新测试工具直接 Ruff 检查通过。完整 `pytest -q` **527 项通过，175.51 s**，其中新增相关回归覆盖弹性背压、快慢 warp 请求、独立 block 释放、集体 IR fence、LSU 槽保持，以及 24 项在线菜单的 MIP 数值边界。新证据与旧 v4 算子/RF8/原语/结构证据按各自版本只读复验。
