# Ventus 通用性能模拟器与 Transformer 接入任务 prompt

在 `${ORIGINAL_PROJECT_ROOT}` 扩展现有 Ventus 快性能模型，接入完整 Transformer 的 prefill 和 decode，并验证 GPU 各数据路径的时序。直接实现、运行测试并交付结果。

> 模型只预测性能，不计算张量数值。Transformer 用于驱动计算、供数、通信、访存、同步和控制路径。预训练权重、文本生成和整网数值 reference 不作为接入前置条件。

## 已有实现和阅读入口

遵循 AGENTS.md，依次阅读 README、docs/workload_to_system_codesign_practice_cn.md、docs/requirements_cn.md，再读 analysis/ventus_flow_20261006/report_cn.md 和 search_model/details_cn.md。

现有代码为 codesign/ventus/，当前版本 ventus-source-events-v5。Hardware 支持 29 个硬件字段加 3 个外存字段；ir.py 不携带数值张量，online.py 维护就绪指令、collector、寄存器依赖、弹性计算流水、LSU 槽与逐 block 释放，timing.py 处理 LDS 与缓存事务。

已有单 warp GEMM/FFN、RF 4/8 bank、Tensor/LDS 模块和多 warp GEMM 证据。8 warp GEMM 仍低估 7.12%–16.12%；CTA/取指供给、完整 cache 状态、逐 warp barrier、部分指令和 lane mask 尚有缺口。读取原始证据确定边界，不能把小程序误差外推到完整 Transformer。当前普通 fadd/fmax/fma 的模型组织也应核对真实执行单元连接，避免把共享路径误建成独立资源。

RTL 在 `${OWNER_UPSTREAM_CHECKOUT}`，Linux SSH 别名 ${REMOTE_HOST}，已有整芯片与模块 runner 可复用。官方软件参考：https://github.com/THU-DSP-LAB/ventus-env 和 https://github.com/THU-DSP-LAB/ventus-pytorch 。核对代码版本和精度，不能由 PyTorch fork 的低精度声明推断当前锁定 RTL 的实现。

## 时序输入与 GPU 机制

将模型分成可复用的 GPU 执行机制和软件时序生成两部分。输入至少表达执行路径/指令子类、源目的寄存器、地址与活动 lane、warp/block、驻留需求、控制流和同步；输出周期、访存事务、资源占用、停顿及分阶段时刻。保留影响地址和控制的整数状态；固定形状可符号展开，数据相关索引/分支由显式元数据或有依据的范围描述。

PyTorch 图只提供形状与语义依赖。软件前端须从官方 kernel、编译输出或可实现的指令模板生成实际供数和访存组织。softmax、LayerNorm、GELU 展开为真实归约、通信、浮点与访问路径；不增加随意设定的“算子延迟”。不支持的路径须明确报错或标明范围，不能统一归为廉价 vector 指令。除法等次要的输入相关延迟可以提供源码支持的范围，但需说明对总周期的影响。

优先补齐 Tensor 与普通浮点竞争、RF/collector/WB、跨 lane 通信、同步、LSU/LDS、L1/L2 请求返回及有限队列、CTA/取指供给。从源码状态和连接建立机制，RTL 测量用于核验；不用 profiling 拟合一个端到端修正系数。

实现跨 kernel 和 decode step 的状态衔接。张量地址、KV 容量、缓存以及未完成事务按实际启动、同步和失效策略处理；不默认每个算子冷启动，也不默认权重永久留在缓存。改变硬件或软件后重新生成指令、依赖、地址和工作集，一次固定 trace 不能替代参数化生成。

## 完整 Transformer 工作负载

先接入缩小的完整 FP32 GPT-2 型计算图：2 层、D=64、4 heads、FFN=256，prefill 长度 16/64，以及对应上下文之后的单 token decode 和多步 KV 更新。包含 embedding/位置编码、归一化、QKV、causal attention、输出投影、残差、GELU/FFN 和最终输出路径。固定模型结构、输入索引和地址即可，无需执行张量算术。

然后接入从官方配置核验的完整 GPT-2 形状，保持同一套通用执行机制。正确处理 decode 的窄矩阵、尾块、活动 lane 与硬件实际执行的 padding；同时报告有效工作量与发出的工作量。未支持精度不自动降成 FP32 后声称对照同一官方程序。

逐路径记录是否实际触发请求、返回、容量压力与背压。Transformer 未覆盖的路径用针对性小程序补测；完整网络运行成功不能单独证明全 GPU 路径准确。

## 速度与验证

先测量整网宿主时间、峰值内存、事件/指令数量，再优化模拟器。避免为每个候选保存整网完整 DAG；可按需保留摘要或调试轨迹，使用事件跳转、流式展开和经核验的循环模板。压缩必须保持资源、依赖与跨算子缓存状态，小规模应能与详细模式对照；不能直接用 FLOP/峰值或层数乘独立 block 周期替代执行。

核验工作量守恒、地址覆盖、寄存器依赖、容量、生命周期、mask 与同步，防止少发指令被误认为加速。这些是时序输入检查，不要求整网数值执行器。

先冻结预测，再做有限 RTL 对照：缺失路径小程序、参数压力、组合 kernel、一个 block 或缩小整网。默认与 RF8 现有二进制可复用；新增机制或硬件需要相应生成与核验。覆盖混合计算/访存、缓存溢出、读写返回、2/4/8 warp 和跨 kernel 状态，保留旧反例。统一周期起止与初始状态，分别检查绝对误差、变化量和排序；误差没解决时限制声明范围。

## 接口与交付

复用 Hardware 字段和单位。提供 lower_transformer(spec, hardware, software) 与时序执行入口，输出共享配置、程序/地址描述、周期、阶段与资源计数、状态策略、模拟模式和未支持项。区分有效计算与发出计算、请求字节与实际事务字节、读写 bank 服务、忙闲时间，明确各计数的单位及聚合范围。可调整既有 API，但保持旧结果兼容。硬件合法性、源码绑定和参数变化的支持程度显式输出。活动计数供独立成本模块估计能耗，执行器不负责给资源购买价格。

交付可运行的完整 Transformer 时序 case、单命令执行和只读复验、完整形状的速度/内存测量、路径覆盖表、冻结预测与 RTL 对照，以及简洁中文结果。明确哪些只是模型贯通、哪些有真实周期证据。

保留 v5 源码与实验，不覆盖历史目录；新机制升级版本并更新实践规范、推导、验收与 brief。不要修改 frontend。运行必要回归，最后执行 ruff check、ruff format --check、pytest。可以修复发现的问题，持续推进到可运行结果，不停在任务规划。
