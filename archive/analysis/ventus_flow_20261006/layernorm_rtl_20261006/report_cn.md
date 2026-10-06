# LayerNorm 的真实 ISA / RTL 时序测试

更新日期：2026-10-06。模型版本仍为 `ventus-source-events-v6`；本轮没有修改执行器、原 Transformer 时序模板或成本语义。

**结论：4 个新生成的具体单 warp FP32 LayerNorm 程序，计算、输出可见以及全部分阶段周期与冻结预测完全一致；RTL 输出与 FP32 指令参考逐位一致。**这给独立性能执行器增加了 LayerNorm 路径的真实证据，尚不能把小 Transformer 整网误差定为 0。

## 测试对象

测试 D=32，以及 D=64 的两份非均匀输入和一份常量输入。均包含真实输入/参数 load、均值与平方和归约、`E[x²]-E[x]²+epsilon`、整数位 seed、4 次倒平方根 Newton 迭代、归一化、逐元素 gamma/beta 与最终 store；epsilon=1e-5。每项处理一行、一 warp，32 lane。

归约使用全 lane 的 LDS butterfly：每轮 store 当前向量，再按 `(lane+distance)%32` gather，distance=16/8/4/2/1，所有 lane 最终拥有归约值。该软件组织与旧整网 `row_reduce` 的部分 lane 二叉树/同地址广播不同。ISA emitter 实际计入常量 materialization、地址指令、FMA 破坏式目的寄存器所需的 copy；没有把算子名称转成固定延迟。

倒平方根使用明确的正确递推：先计算 `half_variance=0.5*variance`，再重复 `y=y*(1.5-half_variance*y*y)`。参考生成器用宿主 `fmaf` 得到 FP32 融合结果；独立 `isa_reference.py` 解码真实 words，执行其寄存器与访存语义，逐条核对实际地址与 IR，输出必须与参考一致。另用 Float64 直接均值/方差/平方根 LayerNorm 检查整体函数，最大绝对误差小于 2e-7。执行器仍不计算张量数值；上述数值检查是测试夹具。

## 冻结预测与 RTL 结果

有效输入和预测为 `probes-c/`。RTL 运行前保存全部 words、IR、输入哈希、模型/生成器哈希和逐阶段预测。复用已有 RF4 RTL 二进制与 observer，没有编译新硬件。每次硬上限 180 秒，实际单次 22.60–23.37 秒，四项共 92.17 秒。

初始状态为 SRAM 清零完成、cold cache、launch gate=512。计算窗口为第一 collector admission 到最后 affine 写回；输出窗口另取最后一条输出行的实际外存写入。主机派发、I-cache、CTA、ENDPRG 收尾不进入所比较的 decoded-body 窗口。

| 输入 | 指令数（含 ENDPRG） | 计算预测 / RTL | 输出可见预测 / RTL | Float64 最大绝对误差 |
|---|---:|---:|---:|---:|
| D32，非均匀 seed1 | 284 | 1297 / 1297 | 1331 / 1331 | 1.98e-7 |
| D64，非均匀 seed2 | 323 | 1508 / 1508 | 1548 / 1548 | 7.76e-8 |
| D64，非均匀 seed3 | 323 | 1508 / 1508 | 1548 / 1548 | 9.64e-8 |
| D64，常量输入 | 323 | 1508 / 1508 | 1548 / 1548 | 0 |

23 个阶段观测全部相差 0 周期：D32 的 sum/squares/variance/rsqrt/affine 为 481/920/995/1171/1297；D64 为 538/977/1052/1228/1354/1508。每项实际 collector 的完整 PC/word 序列与 emitter 一致，输出行各写一次，所有输出逐位正确，没有 RTL 地址警告。`accuracy.json` 保存 provenance、输入/trace/summary 哈希、各阶段误差和数值检查。

## 排除的失败与修正

1. `probes/` 首次准备把归约末尾 store 当成写回观测端点，冻结前失败，没有运行 RTL；保留目录。观测端点改为归约的最后一次实际 FADD WB。
2. `probes-b/` 进行了两项无效 RTL，单次 21.01/22.64 秒：向量 VI 立即数 16/31 是有符号 5 位值，组合使用产生低于 LDS 区间的地址；其余任务随后停止。真实 ISA 的减法顺序也需要显式按 `vs2-vs1` 编码。修正为 scalar register 提供 rotation/mask，核对整数/浮点减法顺序后重新生成 `probes-c/`，先冻结再运行。原文件、代码和日志均保留在 `generate-failed-b.py`、`failed-rf4-v6b/`、`failed-b-run.log`；无效输出没有纳入时序误差统计。

新增独立解码回归覆盖原失败的有符号立即数组合，以及交换浮点减法操作数的负例。单独把 rotation16 改成 -16、同时保持正确 modulo32 mask，会得到同一轮转；负例必须同时重现错误 mask。回归按实际 ISA 语义检查，避免把无影响的变更误当成错误。

## 对小 Transformer 准确性的意义

这次证明了：**当软件输入是这类已核对的真实 LayerNorm 指令流时，v6 执行器能准确预测所测单 warp 程序的 RF、浮点、LDS 与访存组合时序。**结果限定在这四个程序、默认硬件、上述窗口与初始状态；没有依实测拟合周期常数。

原 Transformer 的 LayerNorm 仍使用不同的抽象指令模板，实际常量/ISA 寄存器分配没有绑定到本次二进制。不能把这四项 0% 误差直接赋给旧整网 LayerNorm，更不能直接修订整网的 325,936/1,036,796 周期准确性声明。

后续把已验证软件组织参数化接入整网时，需重新生成整网预测、检查工作量与地址覆盖，并保留旧版本。softmax/GELU、混合 kernel 的缓存/同步、2/4/8 warp LayerNorm、完整 block 与两层模型的 RTL 仍待核验。当前仍没有小 Transformer 的整网误差区间。

## 只读复验

```bash
PYTHONPATH=. .venv/bin/python analysis/ventus_flow_20261006/layernorm_rtl_20261006/check.py --verify
.venv/bin/pytest -q tests/test_ventus_layernorm_isa.py
```

复验重建 ISA 程序、独立解码、核对密集参考、重算冻结周期，再检查保存的实际 RTL PC/word、数值、二进制/observer 身份及证据哈希；不调用 solver、不重新运行 RTL、不写原结果。旧 v6 整网与局部实验保持不变。

## 代码与回归检查

`ruff check codesign tests`、`ruff format --check codesign tests` 均通过，实验工具的 Ruff 检查和格式检查也通过。新增 ISA 回归 6 项全部通过；保存证据的 `check.py --verify` 通过。

完整 `pytest -q` 用时 190.45 秒，553 项通过、7 项失败。7 项均属于 `tests/test_ventus_costs.py`，原因是工作区缺少 `codesign/ventus_costs/table_v1.json`；本轮没有修改成本表或该模块。日志保存在 `pytest-final.log`，未把完整回归记录为通过。
