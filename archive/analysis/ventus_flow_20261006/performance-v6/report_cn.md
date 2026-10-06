# Ventus v6：浮点竞争与 Transformer 时序接入

更新日期：2026-10-06。版本：`ventus-source-events-v6`。本轮保持旧结果、v5 源码与预测，不修改 frontend。

## 已完成的改动与边界

`lower_transformer(spec, hardware, software)` 生成 FP32 GPT-2 型完整图、持久地址与按需指令批。缩小配置为 2 层、D=64、4 heads、FFN=256、词表 128；S=16/64 的 prefill 都接两步单 token decode。包含 token/位置 embedding、两次 LayerNorm、QKV 与 bias、KV append、causal attention、输出投影/残差、tanh GELU/FFN、最终归一化与完整 logits。权重/输入只携带形状、地址和固定 token 索引，执行器不计算张量数值。

完整 GPT-2 配置来自[官方发布配置](https://huggingface.co/openai-community/gpt2/blob/main/config.json)，保存为 `gpt2-official-config.json`：12 层、D=768、12 heads、FFN=3072、词表 50257、位置容量 1024。官方 [Ventus 环境](https://github.com/THU-DSP-LAB/ventus-env)和 [PyTorch fork](https://github.com/THU-DSP-LAB/ventus-pytorch)作为软件参考入口；本轮没有把其编译产物接成整网二进制，也没有根据低精度声明更改锁定的 FP32 RTL 路径。

> 本轮完成的是缩小整图的时序模板贯通，以及混合浮点路径的有限 RTL 核验。精确常量绑定、非线性近似数值精度、正式编译输出对应关系、完整 GPT-2 的完整周期执行、完整网络 RTL 对照仍未验收。

## 从源码修正 FPU 连接

`dependencies/fpuv2/src/main/scala/FMA.scala` 中，FMA 的两级乘法流水与直接 FADD 各经单项队列进入同一加法器；乘法侧具有优先级，加法器之后有单项输出队列。`FPU.scala` 的 ScalarFPU 把 FMA、FCMP、转换路径接到同一个优先级输出仲裁。

v6 将原先独立的 fadd/fma 完整流水拆成：FADD 输入队列 1 级、FMA 乘法/队列 3 级、共用加法/输出 2 级；无竞争延迟仍为 3/5 周期。FCMP 保持 2 级，与普通浮点共用输出；Tensor 独立计算并竞争 RF/WB。新增转换路径 ftoi/itof 采用源码 2 级延迟。规则来源和 SHA256 保存在 `source-rules.json`；转换路径未单独做新 RTL 测量。

4 个新程序在 RTL 之前冻结 words、输入和预测，复用 RF4 二进制与 observer，runner 单次硬上限 180 秒、串行执行；实际每项 18.48–19.69 秒，总计约 76.2 秒。窗口均为第一 collector admission 到所有 warp 的最后建模算术 WB，排除 CSR/地址 epilogue 与主机收尾。

| 程序 | 预测周期 | RTL 周期 | 相对误差 |
|---|---:|---:|---:|
| FMA + FADD + FCMP + Tensor，1 warp | 287 | 287 | 0 |
| FMA，1 warp | 191 | 191 | 0 |
| 混合路径，2 warp | 305 | 306 | −0.327% |
| FMA，2 warp | 196 | 199 | −1.508% |

全部 warp 的 collector PC/word 流与真实 words 一致。原 Python 参考把负数乘零的结果保存为 `-0`；实际指令从 `+0` 进行 RNE 融合累加，结果为 `+0`。原冻结参考和原 runner 的 `output_matches=false` 均保留；修正收据逐项记录 5/10 个零符号修正，其余输出逐位一致。这一差异来自参考的零符号规则，计算周期预测没有修改。新收据为 `mixed-accuracy-final.json`，保留 trace/input hash；冻结后执行器只有宿主优化与非线性模板修正，四个原始 compute 预测未改变。旧 8 warp 的 7.12%–16.12% 低估仍保留，不能由此验收完整 GPU 或全参数准确性。

## 状态、尾块与非线性模板

每批为明确的软件 dispatch，所有请求与写返回 drain 后再进入下一批。保留读缓存 tag、有限替换与 L2 LFSR；全 SM/L2 的已写行在 fence 后失效，read-only 权重不固定驻留。该策略是声明的软件一致性契约，尚未转译硬件 flush/失效扫描的 FSM 周期。`dispatch_tiles` 改变软件同步与并行组织，不能把它当成无影响的日志压缩参数。

Tensor 按配置重新分块，尾部不足的行/列/归约维显式读取零 panel，TC 发出的完整工作量独立计数；有效输出 lane 才发出 store。普通指令的 `active_lanes` 保留真实 lane 编号，Tensor mask 明确拒绝。KV 为每层持久的 `[prefill+decode_steps,D]` K/V 地址，decode 只写新增行；QKV/各 head 通过带 stride 的 view 访问，没有免费物理转置。

LayerNorm 与 softmax 使用显式 LDS 二叉树与 lane-0 重读，按真实 bank 服务计费；softmax 的指数临时值也放在私有 LDS，避免把全局 store 的本地确认误当成中间值已经可读。causal 后缀明确写零。exp 展开为 range reduction、转换、Horner FMA 与指数构造；reciprocal/rsqrt 展开整数 seed 与 Newton 路径，GELU 使用 tanh 的 exp/reciprocal 组织。这些是声明的软件模板，近似精度、特殊值和 ISA 寄存器分配尚未核验，不能声称等价执行官方 GPT-2 数值程序。

## 宿主性能与预算

摘要模式沿用在线执行与资源递推，省去 DAG 名称/入边；每次只保留有界指令批和必要状态。详细模式保留 DAG 并做独立最长路径重放。回归核对两者的周期、指令、计数、字节与逐阶段结果一致。剖析发现 collect/ready_edges、事件 node、RF/WB 预约与 Python 对象操作占据主要开销。优化包含提前筛执行路径、等待 writer 完成的唤醒索引、空流水事件跳转、slots token、直接时间递推和已过期资源日历清理。

同一 S=64 软件和非线性模板的配对实验 `python-ab.json`：优化前 **36.10 s**、第一轮优化后 **30.83 s**，约 **1.17×**；周期均为 1,035,342，指令、事件和全部计数一致。该配对使用当时模板；后来加入浮点减法子类与显式 softmax 减法，最终周期不同，不能与旧配对混称同一输入。

| 最终运行 | 完成状态 | 周期 | 指令 | 宿主秒 | 进程峰值 RSS |
|---|---|---:|---:|---:|---:|
| 小模型 S=16 + 2 decode | 完成 | 325,936 | 272,606 | 9.38 | 42.27 MiB |
| 小模型 S=64 + 2 decode | 完成 | 1,036,796 | 950,022 | 31.97 | 42.55 MiB |
| GPT-2 S=16 + 1 decode | 30 秒预算中止 | `null` | 已执行 802,456 | 30.08 | 56.78 MiB |

S=64 累计约 1,455 万事件，但峰值批次仅约 4.3 万事件；程序不保存整网完整 DAG。RSS 是独立 CLI 进程的高水位，包含前端，不代表 GPU 存储或所有合法配置的上界。GPT-2 全图有效/发出 Tensor 工作量为 4,210,152,960 / 4,954,054,656 FLOP，19,351,776 条 TC；这些来自形状统计，**不能提供完整网络性能周期**。已分配地址字节为 511,622,788，性能模型不实际分配这些数值张量。

S=64 仍处数十秒级；完整 GPT-2 的展开量远大于缩小模型，本轮按预算停止。后续优先把通用在线调度、RF 日历、共享 FPU 和 cache 状态迁入 Rust，保持 Python 前端及配置接口；应以详细事件/跨 kernel 状态对照验收。现阶段没有 Rust 版本或未经测量的加速承诺。

## 路径覆盖

| 路径 | 本轮触发/检查 | 证据限制 |
|---|---|---|
| Tensor/FADD/FMA/FCMP、RF、collector、WB | 整图模板与 4 个新 RTL 程序；共享加法仲裁回归 | RTL 仅上述 1/2 warp 程序 |
| ftoi/itof | exp 模板与计数触发，源码延迟 | 无新增转换 RTL |
| LDS 读写/bank/归约 | LN/softmax/私有 scratch、尾 lane、服务计数 | coalescer/混合部分返回仍近似 |
| L1/L2/外存/LSU | request/return、替换和有限在途机制；跨 dispatch tag 保留、写失效回归 | 无新 cache 溢出/组合返回 RTL |
| KV 生命周期/跨 kernel | 全地址覆盖、每步 append、矩阵 stride、写 fence | 软件策略声明；非硬件 flush FSM |
| CTA/I-cache/逐 warp barrier/SFU div-sqrt | 明确未覆盖或未完整转译 | decoded-body 周期排除，不增加任意算子延迟 |

## 运行与只读复验

```bash
.venv/bin/python -m codesign.ventus transformer --prefill 16 --decode-steps 2 --budget 60 --out NEW_DIRECTORY
.venv/bin/python -m codesign.ventus verify-transformer --out analysis/ventus_flow_20261006/performance-v6/small-s16-final
.venv/bin/python -m codesign.ventus verify-transformer --out analysis/ventus_flow_20261006/performance-v6/small-s64-final2
.venv/bin/python -m codesign.ventus verify-transformer --out analysis/ventus_flow_20261006/performance-v6/gpt2-census
.venv/bin/python analysis/ventus_flow_20261006/performance-v6/check_mixed.py --verify
```

`--input` 可提供 `spec/hardware/software` JSON 覆盖，覆盖后校验；`--mode detailed` 保留批次 DAG，`--mode census` 仅统计图。新目录独占创建；只读复验不调用 solver、不写结果。预算中止结果没有整网周期，完整周期复验明确拒绝。v5 在 `model-v5/` 保存；早期 v6 的源码与结果在 `model-v6a/`、`model-v6b/` 分别保留，当前最终结果与源码哈希对应。

## 最终检查

- `ruff check codesign tests`、`ruff format --check codesign tests` 通过，实验工具的基础 Ruff 与格式检查通过。
- `pytest -q tests/test_ventus.py tests/test_ventus_transformer.py`：**83 项通过，12.64 秒**；包含 20 项整图/状态/尾块/预算/只读复验回归。
- 最终 `pytest -q`：**547 项通过，7 项失败，184.54 秒**。七项均为同时在工作区开发的 `tests/test_ventus_costs.py` 读取缺失的 `codesign/ventus_costs/table_v1.json`，详见 `final-pytest.log`；没有补造成本表、跳过测试或改写其它任务的成本语义。本轮相关测试全部通过，不能宣称全套通过。
- S=16、S=64 与 GPT-2 census 的最终收据已只读复验；四个 RTL 原始预测由最终模型重算仍一致，PC/word、数值和 trace/input hash 核对通过。预算中止 GPT-2 保留其前缀结果，没有完整周期复验声明。
- 当前源码冻结在 `model-final/codesign/ventus/`；`model-v6a` 对应 `small-s64`，`model-v6b` 对应 `small-s64-final`，各自 hash 与对应历史收据吻合。所有实验目录保留。


### 后续 LayerNorm RTL 补测（2026-10-06）

[独立测试记录](../layernorm_rtl_20261006/report_cn.md)增加4个真实单 warp FP32 LayerNorm ISA 程序，D32/D64 两种宽度，包含非均匀与常量输入、LDS butterfly、bit seed/4次Newton和affine。运行前冻结；计算、输出可见及23个阶段周期全部吻合，输出逐位正确，相对Float64最大绝对误差1.98e-7。该具体软件组织与本文整网模板不同，本轮未修改整网预测或执行器，不能把局部0%外推为完整Transformer准确性。
