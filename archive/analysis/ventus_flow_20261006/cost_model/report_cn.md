# Ventus 粗粒度综合成本库

日期：2026-10-06；版本：`ventus-synthesis-cost-v1`。

用于有限候选 MIP 搜索的第一版成本：**同库映射逻辑面积 + 独立存储位数预算**。查询不需要生成 RTL 或重新综合，静态成本不依赖 workload 操作次数。统一目标和全部测量点在 `codesign/ventus_costs/table_v1.json`；历史性能模型和结果保持原语义。

## 使用

```bash
.venv/bin/python -m codesign.ventus_costs
.venv/bin/python -m codesign.ventus_costs --hardware path/to/hardware-overrides.json
```

```python
from codesign.ventus.config import Hardware
from codesign.ventus_costs import evaluate_cost, mip_coefficients, optimize_with_cost

cost = evaluate_cost(Hardware(rf_banks=8))
coefficients = mip_coefficients([Hardware(), Hardware(rf_banks=8)])
# candidates 是既有 codesign.ventus.mip.Candidate 菜单。
# optimize_with_cost(candidates, logic_area_budget=..., memory_bits_budget=...)
```

目标必须与冻结 target 完全相同；非法 Hardware 在覆盖默认值后校验。未采尺寸返回 `unsupported`、空成本与原因，MIP 接口拒绝它们。能耗、存储面积、时序可行性返回 `None`。

## 工艺和估计口径

Linux `${REMOTE_HOST}` 的 Yosys 与 ASAP7 7.5T RVT TT 五份标准单元 Liberty；库标称 0.7 V、25 °C、时间 ps、电容 fF。保留原库 SHA256 和合并 mapper 库 SHA256。直接保留 Yosys `stat -liberty` 面积数值，单位声明 `liberty_area_unit`；没有未经核验的 mm² 换算。ABC 采用 1000 ps 目标，该参数不证明时序满足 1 GHz；首轮没有重新运行 STA、放置或布线。不同存储宏的估计不混入该逻辑面积。

识别生成 RTL 的存储数组叶模块，保留接口并设为 blackbox。按数组宽度×深度×递归实例数单列位数，覆盖 RF、LDS、L1/L2 数据、tag/目录、I-cache、MSHR/list-buffer 和队列的数组实现。黑盒叶内部的读地址寄存器、译码、数据 mux、mask 与存储外围同样没有计入逻辑面积，不能将这份逻辑数值称为完整芯片面积。RF 旁路、collector 保存寄存器、crossbar 和仲裁等叶模块之外的逻辑正常映射；不把大容量 RF/SRAM 展成 DFF 计价。

共享固定部分以 `GPU` 为 top，将两份 SM 作为保留接口的黑盒，排除仿真内存和 host wrapper；CTA、共享互连、L2 的逻辑与数组独立综合/计数。另行实采完整 `SM_wrapper`，包含执行管线、前端、RF/collector、LDS、I-cache/D-cache 和控制，组成默认双 SM 成本。独立 L2 `Scheduler` 及 SM 内组件的层次面积用于组成检查。默认总成本也为组合估计；完整 GPU 综合因资源与时间开销中断，未得到新形状组合的留出集成误差或物理实现误差。

## 实采数值摘要

下表面积均为原始 `liberty_area_unit`，位数包含对应子树的全部黑盒数组；各行是不同层次，不能直接全部相加。

| 测量点 | 逻辑面积 | 黑盒存储位数 |
|---|---:|---:|
| GPU 共享固定部分 | 61,683.81 | 1,160,918 |
| 单 SM 基线 | 317,497.30 | 3,424,026 |
| RF collector：4 / 8 bank | 52,617.92 / 70,858.14 | 均 1,114,112 |
| Tensor：4×8×4 / 4×4×4 | 102,702.32 / 52,517.50 | 0 |
| Tensor：2×16×2 / 8×4×4 | 51,009.92 / 104,663.74 | 0 |
| Tensor：2×4×2 / 4×2×4 | 13,407.81 / 27,136.16 | 0 |
| LDS：32 / 16 / 8 bank，128 KiB | 7,899.52 / 4,381.07 / 2,530.78 | 均 1,082,496 |
| LDS：16 bank，16 KiB | 4,311.32 | 164,992 |
| 独立 L2 | 59,067.74 | 1,153,112 |

默认双 SM 组成估计：逻辑面积 **696,678.41**，黑盒数组 **8,008,970 bit**。RF 4→8 每 SM 增加逻辑面积 18,240.22，声明容量相同。独立 L2 与固定 GPU 内 L2 逻辑面积差约 0.043%，仅作为该层次的局部检查。

## 参数范围与实现状态

| Hardware 字段 | 首版成本查询 | 实现/证据边界 |
|---|---|---|
| `sms` | 1–8 的 SM 复制估计 | 双 SM 实采；共享 CTA/互连保持双 SM 基线，扩容差异未建模 |
| `rf_banks` | 4、8 | 真实 collector 子树；8 bank 需现有 bank 派生位宽补丁 |
| `tensor_m/n/k` | 4×8×4、4×4×4、2×16×2、8×4×4、2×4×2、4×2×4 | 实采 vTCexe 模块，需参数解绑；N 表示归约维 |
| `lds_banks/lds_bytes` | 32/128 KiB、16/128 KiB、8/128 KiB、16/16 KiB | 真实 SharedMemory 子树，需 bank/lane 解绑；bytes=threads×参数 depth×4；每 bank 实际深度=threads×参数 depth/banks |
| `vgpr_slots/sgpr_slots` | 固定 1024/2048 | 原生 bank 深度分别随 bank 数变化；任意容量变化未采 |
| `warps_per_sm/blocks_per_sm/collectors/threads` | 固定 8/8/8/32 | 固定前端、驻留、collector 与 SIMD 结构已计入基线 |
| RF 读/写端口、WB、Tensor 单元数、LDS 端口 | 固定 1 | 多端口/多单元需新增仲裁或复制实现，拒绝未采成本 |
| L1/L2 sets/ways/line、MSHR/subentry/write-entry、LSU 槽 | Hardware 默认值 | tag、队列、控制和数据数组保留；变化配置拒绝 |
| 外存 3 个字段 | 可传入、无 GPU 静态成本变化 | 外部 DRAM、controller/PHY 成本未建模 |

组件可生成与完整组合可实现分别报告。独立模块的解绑不会自动应用于完整 GPU；`rtl_unbinding_required` 及 implementation 字段随查询返回。所有整机组合（含默认双 SM 配置）标记 `estimated`，没有未经采集的外插直线或零成本回退。尚无 RF 容量、cache/MSHR 或多端口的留出点，暂不为这些维度拟合成本。

默认生成 RTL 的 `RegFileBank.io_rsidx/io_rdidx` 为 8 位，bank4 的物理数组为 512×32，每 bank 只有低 256 项能由该端口寻址；bank8 数组为 256×32，其地址端口降为7位。首版按实际声明的数组保留全部位数，查询额外返回 `sgpr_addressability`（bank4 可寻址总1024槽，物理保留2048槽；bank8可寻址总1024槽，物理保留2048槽）。这是生成 RTL 的地址端口检查，未验证 allocator 的全部驻留分配行为；搜索中的可用 SGPR 容量仍须受该实现边界约束。

## MIP 系数

共享固定逻辑和独立 SM 分别实采，组成预算时保留两部分成本。RF、Tensor、LDS 用同采样流程的组件差分替换：

\[
A(h)=A_{shared}+SM(h)\,[A_{SM,base}+\Delta A_{RF}+\Delta A_{TC}+\Delta A_{LDS}].
\]

存储位数按相同组成替换，固定部分包含共享目录和队列；RF bank 4→8 保持总容量，逻辑差分显式计费。bank 的存储宏外围成本仍保留为缺失项，不能理解为改变 bank 免费。未采端口数直接拒绝。面积和位数分别形成 `sum_h A_h*y_h <= area_budget` 与 `sum_h B_h*y_h <= bit_budget`。现有菜单恰选一个候选，预算过滤与这两条线性约束等价。

## 原始采集与只读复验

`cost_model/scripts/collect.py` 针对已核验的 ${REMOTE_HOST} 工具和上游目录，创建全新目录。第一轮使用原生 Verilog 前端，六个 Tensor 样本全部成功并纳入表；RF、LDS 和整机解析局部自动变量失败，后续这些组件使用已安装 slang 前端。原生 Tensor 使用完整逻辑优化流程，其它成功组件使用简化映射；统一库、PVT、面积单位和 ABC 1000 ps 目标，逐点记录 flow。优化遍数与层次上下文差异是组成估计的误差来源，未给出跨形状集成误差保证。失败/中断批次保留，最终模型仅采用成功测量点。执行时源码快照和 script hash 随原始结果保存；格式化后的便利脚本保留相同流程。

SM 的 slang 展开产生 33,343 个模块定义。为控制综合开销，先对具有相同源模块类、相同降级文本和递归等价子定义的模块去重至 205 个定义，保留原实例数；再重新读入、执行 `proc` 并映射。去重记录、降级 RTL 和最终日志随原始结果保留。第一次重新读入未执行 `proc` 的映射存在未降级进程，已排除；采用 `sm-processed` 的零进程最终测量。该步骤是结构文本等价检查，未开展完整形式证明。

需要重新采集 SM 时，在服务器使用新目录：

```bash
python3 dedup_sm.py ${REMOTE_STORAGE_ROOT}/ventus-cost-v1c-20261006/sm-base ${REMOTE_STORAGE_ROOT}/ventus-cost-sm-new
```

服务器成功点、RTL、netlist、库、脚本、日志和报告汇总在 `${REMOTE_STORAGE_ROOT}/ventus-cost-final-v1-20261006`；原始简化流程批次在 `${REMOTE_STORAGE_ROOT}/ventus-cost-v1c-20261006`，共享固定部分在 `${REMOTE_STORAGE_ROOT}/ventus-cost-fixed-v1-20261006`。首轮原始批次（六个有效 Tensor 与其它失败点）在 `${REMOTE_STORAGE_ROOT}/ventus-cost-v1-20261006`；完整层次优化尝试在 `${REMOTE_STORAGE_ROOT}/ventus-cost-v1b-20261006`，因优化遍数耗时主动停止，不参与模型。slang 成功组件使用 proc、常量/死逻辑清理、techmap、dfflibmap 和 ABC 的简化流程，跳过 FSM/share/opt_dff 等优化遍数；Tensor 保留原生完整优化测量，适合粗粒度初筛。本地 `raw/` 保留 manifest、统计、综合脚本、日志与输入逻辑/映射网表，`build_table.py --verify` 只读核验测量点与冻结表：

```bash
.venv/bin/python analysis/ventus_flow_20261006/cost_model/scripts/build_table.py \
  analysis/ventus_flow_20261006/cost_model/raw \
  codesign/ventus_costs/table_v1.json --verify
```

新增搜索实验必须使用新输出目录：

```bash
PYTHONPATH=. .venv/bin/python analysis/ventus_flow_20261006/cost_model/scripts/run_demo.py \
  analysis/ventus_flow_20261006/cost_model/demo-new
```

该例比较相同 GEMM 工作量的 SM/RF 菜单，通过成本预算筛选后运行事件 MILP，再用独立枚举核对模型周期最优值。它说明综合系数可用于搜索；周期来自既有性能模型，不能称为硬件性能实测或全硬件空间最优。

## 已完成验证

15 点冻结表只读复验通过；384 个声明支持的组合查询均返回正成本（只检验查询范围，不代表组合 RTL 已实现）；成本接口的 8 项回归通过。`measurements_v1.csv` 为可直接读取的逐点系数摘要，`model-v1/` 固定本版代码、Hardware 契约与脚本快照。`demo-v1/experiment.json` 保存四个候选的成本、预算、源码 hash、MILP 解与独立枚举。面积预算 397,421.33、存储预算 4,584,944 bit 下，选中 `sm1-rf8`，周期 369；最优性仅覆盖该有限菜单和既有事件时序模型。默认查询快照为 `default_cost_v1_final.json`。早期失败留下的空 `default_cost_v1.json` 不作为结果。

最终工作区检查：`ruff check`、`ruff format --check` 与采集脚本的独立 Ruff 检查全部通过；完整 `pytest` 为 **561 passed，177.83 s**。五份原始 Liberty 与合并 mapper 库 SHA256 核验一致。工作区存在并行任务的既有修改，完整回归数字对应此次执行时的整个工作区。
