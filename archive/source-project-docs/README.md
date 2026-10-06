# Break Layer

从 Transformer 的数学语义生成合法 tile/region 候选，用 MILP 联合选择计算实现、硬件数量和静态调度，再独立检查调度与数值结果。

当前已具备 **解析优化原型与命令模拟器闭环**：完整 Transformer 可生成汇编、执行访存和计算、统计模型周期并反馈成本。尚未完成完整 Pareto 实验或 RTL/综合校准。已有前端单独维护；后端通过结果 JSON 提供数据。

## 文档入口

首次了解项目或准备研究分享，请先读 [Project Brief](docs/project_brief_cn.md)：以“将硬件结构与配套软件结构编码为 MILP 联合求解”为主线，按 12 页 slides 讲解研究问题、变量与约束、软硬件生成架构、技术贡献及研究路线。

建议按以下顺序阅读：

1. [实验实践文档](docs/workload_to_system_codesign_practice_cn.md)：当前权威实施规范，说明 workload、硬件级别、流程、实验和边界；已直接替换最初的实施草案。
2. [从 workload 到 MILP 的推导](docs/workload_to_milp_derivation_cn.md)：通过具体张量和时间线，从问题分析推导变量与约束，包含求解前后阶段。
3. [需求与验收清单](docs/requirements_cn.md)：稳定编号、当前状态、通过条件和工程要求。
4. [总体设计](docs/workload_to_system_codesign_v2_cn.md)：长期目标与方法；具体 v0 范围以实践文档为准。
5. [初次运行记录](docs/experiments/prototype_20260922_cn.md)：历史结果、已知局限及其证据来源。
6. [外部参考说明](docs/references/README.md)：原始 Transformer spec 与新提供的实验报告，及其与本项目的区别。
7. [研究与工程路线图](docs/roadmap_cn.md)：带摘要的后续方向，覆盖语义综合与验证、ASIC/FPGA 元件数据、全局优化、可执行软硬件与自动化闭环。
8. [可执行 MVP 方案](docs/executable_mvp_plan_cn.md)：汇编输入、硬件模拟器与成本反馈已实现；说明受限范围和后续 RTL/综合入口。
9. [课程难度简要建议](docs/experiments/course_difficulty_recommendation_20260923_cn.md)：变量菜单、固定输入阶梯、180/600秒收敛及选型边界。
10. [固定输入联合空间标定](docs/experiments/course_fixed_space_20260923_cn.md)：固定Transformer，逐档增加硬件与软件菜单，比较随机/通用/领域搜索，并用全局界检验是否真正困难。
11. [课程研究难度标定](docs/experiments/course_difficulty_20260923_cn.md)：逐档开放自由度，比较 20 秒、3 分钟、10 分钟预算；区分直接求解、领域简化、原空间下界与经验质量。
12. [可编程 Transformer 挑战](docs/programmable_transformer_codesign_challenge_cn.md)：四层 M1/P1 与 M1/D1 的[完整例程和 v2 冻结基线](examples/challenge/README.md)可运行；修正跨组 HBM 依赖与 `STEP.COMMIT` 后，当前 `pipeline-global-events-v2` 的受信隐藏报告已签发模型分数 1000.0；本轮功能、评分和资源验收已完成；完整报告只读复算按用户要求提前停止。[验收规则](docs/challenge_release_acceptance_cn.md)规定功能、计时、资源展示和复验；[旧 v1 发布记录](docs/experiments/challenge_two_case_release_evidence_20260924_cn.md)与[早期实施记录](docs/experiments/challenge_implementation_20260924_cn.md)保留历史口径。正式分数须由受信私有输入与报告签名签发，公开 `grade` 只给实验分数。
13. [Gemmini 三层验证方案](docs/experiments/gemmini_codesign_experiment_design_20260925_cn.md)：把开源参数化加速器作为 NPU 系统，在固定资源向量预算内以冻结 GEMM 检验联合选择。[首轮 CCI 八项配对诊断](docs/experiments/gemmini_cci_g0_g1_20260927_cn.md)发现主要收益来自软件消除零 bias；[搜索空间审计](docs/experiments/gemmini_search_space_and_model_20260927_cn.md)列出参数自由度与模型缺口。[后续 28 项采样搜索](docs/experiments/gemmini_measured_search_v1_20260927_cn.md)用 10 个锚点建立周期模型、18 个留出点验证，选中并 RTL 实测 tile4 + `3×10×16` 为 35,947 周期，比同轮强官方映射快 0.64%；WS-only 保持周期并显著降低 Mesh 逻辑代理，物理面积和时钟尚未测。[G0 整数功能记录](docs/experiments/gemmini_g0_smoke_host_comparison_20260925_cn.md)保留为历史 Spike 功能证据。

14. [Ventus 性能模型与 MIP 边界](analysis/ventus_flow_20261006/report_cn.md)：从开源 RTL 建立参数化时序模型、核验 Tensor/存储路径，并说明独立性能执行器和有限候选 MIP 的分工。 粗粒度综合预算见[成本模型](analysis/ventus_flow_20261006/cost_model/report_cn.md)，采用逻辑面积与存储位数独立预算。[v6 整图接入](analysis/ventus_flow_20261006/performance-v6/report_cn.md)新增共享浮点竞争、缩小 GPT-2 型 prefill/decode 与有预算的摘要执行；完整 GPT-2 周期运行仍未完成。

原 [实验准备度评审](docs/experiment_readiness_review_cn.md) 保留为历史记录，不再作为待办或当前设计规范。

新版题目设计讨论见 [vNext 存储层次与资源平衡草案](docs/drafts/transformer_codesign_vnext_cn.md)及[独立审查记录](docs/drafts/transformer_codesign_vnext_review_cn.md)。草案尚未实现或发布，不改变现行模型、验收状态或历史成绩。

## 安装和运行

在项目根目录使用 Python 3.12+：

```bash
uv sync --extra dev
uv run break-layer --time-limit 60
uv run break-layer --fusion none --area 14 --out results/separate-area14-v1
```

不指定 `--out` 时创建带时间戳的新目录。指定目录必须为空；历史结果不会被覆盖。`--time-limit` 是每个优化阶段的限时：先优化 latency，证明其最优后才进入 area tie-break。

默认输入是 [specs/transformer.yaml](specs/transformer.yaml)：batch=1、S=32、D=128、4 heads、FFN=512、FP32 causal prefill。每次求解固定 shape；可以修改配置后重新生成候选。

```bash
# 只读复验已保存的原始结果；不会重新生成 catalogue 或调用 solver。
uv run break-layer --verify results/default

# 只有在需要研究人为限定的时间范围时才显式设 horizon。
uv run break-layer --horizon 60 --out results/horizon60-v1

# 已有扫描入口：三种 fusion 模式 × 两个面积预算。
uv run break-layer --sweep --out results/sweep-v1
```

扫描入口可执行不代表已有 Pareto 研究结论。无可行解的运行退出码为 2；必须进一步查看 solver status 和 horizon 范围，区分模型不可行与限时未找到解。

## 可执行 toy 闭环

```bash
# 新建实验：初始服务估计 → 求解/汇编/执行 → region 周期反馈 → 再求解/执行。
uv run break-layer --executable --area 20 --out results/my-command-run
# 直接运行保存的汇编；执行器不读取 solution 的预测时刻。
uv run break-layer --execute-program results/my-command-run/feedback
# 核对冻结哈希、方案与汇编对应关系，并只读执行；不重新求解。
uv run break-layer --verify results/my-command-run/feedback
```

服务参数见 [command_target.json](specs/command_target.json)，也可通过 `--target` 指定。默认固定 2 MiB SRAM、单共享服务端口和单 DMA，Matrix 在 1/2 个之间选择；region 串行，region 内按 engine 队列并行。支持独立算子与 MatMul+Bias；旧配置中的 pipeline 模式在该专用入口收敛为 local，显式 `--fusion pipeline` 拒绝。原解析入口和旧结果保持原语义。

[首次命令实验](docs/experiments/command_mvp_20260923_cn.md)中，预算 16/20 分别得到 192,864/130,936 个模拟周期，两套完整输出与停顿检查通过。吞吐、面积、功耗和 100 MHz 时钟均为声明假设；本轮未执行 RTL 或提取工艺参数。

## 后端结构

| 模块 | 单一职责 |
|---|---|
| `config.py` | 输入契约与 CLI 覆盖后的校验 |
| `workload.py` / `ir.py` | Transformer 前端 / 图、张量与候选结构 |
| `catalogue.py` / `costs.py` | 参数化分解、融合、流水模板与版本化成本审计 |
| `warmstart.py` | 确定性初始调度与可行上界，不声称最优 |
| `model.py` / `solver.py` | 约束建模 / 稀疏矩阵与 HiGHS 接口 |
| `verify.py` | 独立调度检查与资源事件重放 |
| `execution.py` | FP32 tile 执行、Float64 reference 与索引覆盖检查 |
| `experiment.py` / `artifacts.py` | 实验流程 / 不覆盖的结果快照与离线复验 |
| `machine.py` | 命令汇编解析、具体内存、engine 队列、共享端口与事件周期执行 |
| `command_codegen.py` / `command_verify.py` | 受限候选与汇编生成 / 独立方案和输出检查 |
| `executable.py` | 串行 region MILP、成本反馈、命令实验与只读复验 |
| `cli.py` | 命令行入口 |

`frontend/` 的代码、依赖、静态数据与构建由前端任务负责。本轮后端整理没有修改该目录，也没有同步或重新生成前端数据。

## 质量检查

```bash
uv run ruff check codesign tests
uv run ruff format --check codesign tests
uv run pytest -q
```

当前全套 461 项测试通过，覆盖解析与命令闭环、课程空间及可编程挑战，包括非法输入、尾块/归约覆盖、融合数值、资源/生命周期、快照复验、独立逐周期资源检查和评分边界。日常测试不依赖限时 Transformer 必须达到 optimal。

## 结果与声明边界

`results/<run>/` 保存 config、instance、manifest、solution、verification、functional、simulation、summary 和 `output.npy`；新运行另存 `cost_audit.json`。默认成本已升级为 `toy-analytical-v1`，补充融合参数读取、SIMD 成本修正与抽象 engine 分工；仍无物理映射和硬件校准。JSON 的既有字段保持兼容；新增字段说明见 [实践文档](docs/workload_to_system_codesign_practice_cn.md#9-结果接口与复现)。非有限统计值写成 `null`。

历史 `results/default` 为 **104 µs 的可行方案，60 秒结束时 gap=51.92%**。该方案由 warm start 提供，不能称为 MILP 最优解或 MILP 独立收益。数值与独立调度检查通过。硬件成本是 toy model，事件重放使用同一局部成本，均不代表实测芯片性能。

下一阶段继续改善建模与收敛、推进受控 HBM/fusion/面积实验，已有命令后端为下一阶段的 MatMul+Bias RTL 锚点提供汇编、输入和对照轨迹；硬件库与综合数据就绪后接入参数校准。


## vNext Rust 基线（2026-09-30）

[运行与编程说明](rust/vnext-sim/README.md)提供完整 M prefill/decode、独立 Float64 全量参考、通用原语 JSON 与流式 Rust 生成器。模型为单独版本 `vnext-blocking-rf-v0.2`：多 SM 共享有限 HBM/NoC，SM 内阻塞执行；SH、Cache 和异步重叠尚未实现，不能代替完整 vNext 或现行评分器。基线实测与边界见[实验记录](docs/experiments/vnext_rust_baseline_20260930_cn.md)。


vNext后续试解见[准备度简报](docs/experiments/vnext_codesign_readiness_20261001_cn.md)：Rust v0.4新增矩形分块、计费布局转换、Vector FMA及split-K；发现并修复均匀attention能通过旧fixture的数值漏洞，完成M多方案与X压力实验。当前仍为阻塞RF子集，完整SH/Cache/异步未验收，未签发新题正式成绩。


### vNext结构试解更新（2026-10-01）

[结构多样性报告](docs/experiments/vnext_structural_diversity_20261001_cn.md)扩展了head分组与跨步K布局，得到三条SM/TC/RF分配不同、完整M综合时延相差约1.5%的已测候选。教学目标是让agent发现变量并形成可检验、可迁移的模型，不承诺建模必胜搜索；完整SH/Cache/异步与更广软件结构尚待验证。运行入口及限制见[Rust v0.5规范](rust/vnext-sim/README.md)。


### vNext付费SH试解（2026-10-01）

Rust v0.6增加显式SH、bank冲突/广播、有限局部搬运流水和SH B直供TC。新程序以局部权重复用和部分和存储换取更少HBM访问，完整M优于上轮已测最佳约3%；短/长prompt迁移时RF与SH路线出现赢家反转。单价及100AU/26W/34W不变，Cache、多工作组与异步仍待实现。过程与范围见[SH试解报告](docs/experiments/vnext_shared_reuse_20261001_cn.md)。


## Blocking-SH 首发交付（2026-10-01）

新版采用独立的[完整首发契约](docs/vnext_challenge_release_cn.md)，范围为显式RF/SH、共享HBM/NoC和阻塞wave；Cache/异步完整草案保留为后续研究。Rust v0.7增加不执行学生宿主代码的静态JSONL提交入口、受控输入释放、逐步hidden/KV检查和多fixture评分。学生可自写整个原语程序，既有policy不是搜索空间边界。[运行手册](docs/vnext_release_runbook_cn.md)、[最终验收与独立试解结论](docs/experiments/vnext_release_acceptance_20261001_cn.md)给出可复现交付、实际性能及明确限制；旧挑战成绩不变。


## vNext v0.8 多实例研究评估（2026-10-01）

[扩展workload/硬件契约](docs/drafts/vnext_workload_hardware_v08_cn.md)与[完整评估报告](docs/experiments/vnext_explore_evaluation_20261001_cn.md)提供两类模型、五项batch/长上下文实例、瘦长TC与深RF/SH的供数和成本规则。`--features explore`构建独立研究模型，明确禁止套用冻结首发评分。Spark完整20次数值/功率检查约128秒；同版本四worker较串行加速2.68倍，有限试解已出现场景取舍，不代表已知全局最优。


## vNext 极端压力与隔离试题（2026-10-01）

[出题人交付文档](docs/vnext_author_delivery_cn.md)汇总所有变量、成本、设计目的和实验证据；[压力报告](docs/experiments/vnext_extreme_stress_20261001_cn.md)记录满wave、低效DMA、SH冲突、八路大实例并发以及OOM/超时恢复。Prefill无用KV分配已修复，五项完整输出hash与模拟报告不变。`scripts/vnext/package_tryout.py NEW_DIRECTORY`创建可独立本地试跑的源码/题面/配置副本；仍为可信生成器研究入口，不接受正式学生提交。


## vNext v0.9 并发教学机器（2026-10-02）

[新版完整题目](docs/vnext_v09_author_delivery_cn.md)给出23项硬件变量、全部成本/延迟、五个固定workload、异步与多驻留组、Cache/多播及静态提交规则。Rust `--features concurrent` 与 `vnext-static-v09` 独立于旧版；五项同硬件、全输出验证后按冻结参考加权计分。`scripts/vnext/package_v09.py`交付可独立试跑的源码、配置和证据；网页仅局域网预览，无生产部署。
