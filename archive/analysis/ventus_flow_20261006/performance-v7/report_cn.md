# v7：Transformer LayerNorm 接入与混合计算/访存核验

日期：2026-10-06。模型版本：`ventus-source-events-v7`。目标按用户要求采用整体周期与趋势的近似预测，优先检验计算/访存交织、缓存复用和组合路径。原 v6 结果和源码不覆盖。

## 实际交付

新增 `codesign/ventus/layernorm.py`，从同一参数化描述生成真实机器指令与时序 IR，不执行张量数值。32 lane、宽度为32倍数的 Transformer LayerNorm 改为已测 butterfly 程序：真实常量装载、地址、破坏式FMA复制、两个LDS归约、正确half-variance和4次Newton迭代、gamma/beta与store。D32/D64与原独立RTL夹具的机器字、指令依赖完全一致。每个block明确分配512字节私有LDS，实际整网输入/参数/输出地址随形状重定位。

其他宽度或lane数量保留旧模板，结果描述显式标为 `legacy-masked-template-unvalidated`。更大宽度、地址重定位后的多block程序与不同硬件仍属外推；整网尚未生成并运行统一完整ISA，softmax/GELU仍待同样绑定。当前声明为可运行的完整图性能输入，不能据局部测试给整网误差保证。

## 混合计算与memory hierarchy

先冻结预测、输入哈希和源码，再复用完整RF4 `VentusRTL`，每次上限180秒，无新RTL编译。四项均完成相同32条Tensor指令（8192发出FLOP），改变寄存器驻留和内存复用组织。地址装载指令数量随布局变化，模型实际计入，不声称全部ISA工作量相同。

`conflict-return` 使用8对输入panel、32KiB步长，四遍读取，集中到少数L1/L2组。它检验组冲突与重新访问，逻辑工作集仅2KiB；不是总缓存容量溢出实验。`stream`读取32对新panel。`reload`反复读取同一对panel；`resident`仅第一次加载、之后留在寄存器。

| 程序 | 计算预测 / RTL | 计算误差 | 输出可见预测 / RTL | 外存读行数：模型 / RTL |
|---|---:|---:|---:|---:|
| resident | 578 / 578 | 0% | 606 / 606 | 3 / 3 |
| reload | 1601 / 1601 | 0% | 1629 / 1629 | 3 / 3 |
| stream | 2438 / 2440 | -0.082% | 2466 / 2468 | 65 / 65 |
| conflict-return | 2002 / 1943 | +3.037% | 2030 / 1971 | 35 / 33 |
| GEMM → 原地LayerNorm | 1888 / 1888 | 0% | 1910 / 1924 | 6 / 6 |

全部数值输出逐位正确、完整collector PC/word序列吻合、无RTL地址警告。四种内存组织排序相同，最大计算偏差3.04%、输出可见偏差2.99%。这五项证据限定在单warp、冻结硬件和窗口，不是整网误差界或硬件配置通用误差界。

最后一项在一个程序中计算Tensor GEMM、写出全局结果、从该地址读取LayerNorm输入并原地写回；没有把两项独立冷启动周期相加。LayerNorm独立数值参考与Float64最大绝对误差7.00e-8。最终物理写回比模型晚14周期（0.728%），该路径仍保留flush/可见性抽象差异。

单次RTL20.44–26.54秒，五项合计119.05秒。墙钟不包含编译。模型比较窗口从首collector开始；派发、I-cache和主机启动不在此误差统计中。

冲突项的外存读取仍多预测2行，L2替换模型包含全局LFSR但未驱动实际I-cache流量，不能宣布替换状态完全准确。没有依据此次实测修改延迟常数或增加端到端修正系数。真实跨kernel启动/flush、容量溢出、2/4/8 warp和官方软件对齐仍是后续重点。

## 整网运行与速度

| 完整模板图 | 模型周期 | 发出指令 | 宿主秒 | 进程峰值MiB |
|---|---:|---:|---:|---:|
| 2层 D64 H4 FFN256，S16 +2 decode | 333660 | 285328 | 8.69 | 42.50 |
| 同结构，S64 +2 decode | 1054599 | 996929 | 30.05 | 42.59 |

旧v6为325936/1036796周期；新结果反映实际LayerNorm组织及额外软件指令，不能将周期增加解释为硬件性能退化。输出receipt记录版本/源码哈希/软件组织与地址分配；支持只读复验。

S16 profiling发现106.7M次函数调用，`collect`累计6.83秒、writebacks3.45秒、advance2.99秒（含profiling开销）。执行器改为每轮按SM/路径分组就绪流、复用collector编号并跳过空流水线。无需减少发出的工作量，优化前后的S16周期、指令、计数、阶段时刻必须相同。保留 `model-before-optimization/` 和 `model-final/`。S64仍约30秒，后续更大形状需要进一步优化，Rust执行核心是可选方向；本轮未实现Rust版本。

模型敏感性实验（一层、D64、S4 +1 decode）使用相同47567条指令：默认67316周期；外存延迟从2改100后190785；L1 sets从256改4后97203。它检查供数条件确实影响整网，未对这些改变配置运行RTL；对应receipt显式保留硬件变化与绑定限制，不是硬件实测。

## 验证与复验

生产LayerNorm接入、原Transformer与独立ISA相关33项回归通过。最终 `ruff check codesign tests`、`ruff format --check codesign tests` 通过，完整 `pytest -q` 为568通过、用时182.83秒；日志 `pytest-final.log`。成本表现已由并行维护任务补齐，本轮未修改该模块。

`check.py`检查冻结输入、生成器快照、硬件身份、每条实际PC/word、数值输出、周期与实际外存读行数，再核对优化后的执行器与预冻结预测一致。`combined_probe_frozen.py`保留RTL前生成器原文；当前生成器只调整import位置以满足Ruff，未改生成语义。旧v6 LayerNorm通过冻结包复验，避免拿新版本哈希复验旧模型。

```bash
.venv/bin/python -m codesign.ventus transformer --out results/ventus-v7-new --prefill 16 --budget 90
.venv/bin/python -m codesign.ventus verify-transformer --out analysis/ventus_flow_20261006/performance-v7/small-s16-final
.venv/bin/python -m codesign.ventus verify-transformer --out analysis/ventus_flow_20261006/performance-v7/small-s64-final
PYTHONPATH=. .venv/bin/python analysis/ventus_flow_20261006/performance-v7/check.py --verify
.venv/bin/python analysis/ventus_flow_20261006/performance-v7/replay_v6_layernorm.py
```

完整Transformer的RTL误差仍未测。v7提高了软件输入真实性并补上混合访存/组合路径证据，适合继续做近似分析；官方编译软件与整网可靠性尚未验收。

优化前未插桩S16样本为9.23秒，优化后保存样本8.69秒；这是单次宿主测量，不能作为稳定加速率保证。两份结果的周期、指令、事件、请求字节、全部计数、逐阶段时刻和工作量普查完全一致。S16/S64最终结果均已通过只读复验，旧v6 LayerNorm也通过冻结源包复验。
