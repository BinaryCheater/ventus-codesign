# 快速扩展测试：非线性长链与2/4 warp混合访存

日期：2026-10-07；实验开始目录沿用20261006。模型保持 `ventus-source-events-v7`，本轮未改性能执行器或原整网前端。目标是在短预算内扩大到真实ISA非线性、数据依赖和多warp共享访存，判断近似周期及趋势是否可用。

## 结果

6项完整 `VentusRTL` 程序全部正常结束，448个FP32输出字与独立指令参考逐位一致，无地址警告。机器指令序列、warp数、每条访存地址、分配范围和多warp私有输出均核对。预测先冻结，没有按观测结果调整常数或加拟合系数。

| 实际ISA程序 | 每warp指令数（含END） | 计算预测 / RTL | 计算误差 | 输出可见预测 / RTL | 可见误差 |
|---|---:|---:|---:|---:|---:|
| softmax，1 warp | 304 | 1395 / 1395 | 0% | 1429 / 1429 | 0% |
| GEMM → LayerNorm → GELU → softmax | 774 | 3970 / 3971 | -0.025% | 3992 / 4007 | -0.374% |
| stream，2 warp | 424 | 2439 / 2477 | -1.534% | 2482 / 2520 | -1.508% |
| stream，4 warp | 424 | 2607 / 2710 | -3.801% | 2651 / 2752 | -3.670% |
| conflict-return，2 warp | 362 | 2003 / 2008 | -0.249% | 2046 / 2051 | -0.244% |
| conflict-return，4 warp | 362 | 2140 / 2231 | -4.079% | 2184 / 2275 | -4.000% |

指令数以冻结JSON为准，检查脚本会逐warp验证完整PC/word序列。最大绝对计算误差4.08%、输出可见误差4.00%，满足本轮“差不多”的局部测试目标；不能将这个最大值外推为整网误差界。

外存读行数：stream2为66/66、stream4为68/68；conflict2为模型36/RTL34、conflict4为38/36。每行128字节，包含输出写分配读取，排除I-cache读取。缓存组冲突的替换状态仍多预测2行；多warp误差不能全部归于这个差异，CTA/I-cache供给和仲裁仍可能贡献。没有用固定乘数修正。

6项单次22.26–32.27秒，共161.25秒；每次上限180秒，复用冻结二进制/observer，无RTL重编译。程序规模小，工作负载包含多路径；硬件仿真范围仍为完整GPU。

## 覆盖的计算与数据流

独立softmax包含真实max归约、减max、exp、sum归约、倒数和归一化，采用全lane LDS butterfly。长链先运行32条Tensor指令，写全局结果；随后LayerNorm、GELU和softmax从同一地址读取并原地写回。数据真实产生并被后继消费，cache状态保留在同一次运行中；未把独立冷启动周期相加。

exp使用明确的软件实现：将参数缩小16倍、8阶Horner多项式、4次平方。倒数使用整数位seed与4次Newton。GELU实现GPT-2型tanh公式，以exp和倒数展开。测试中所有常量、地址、破坏式FMA复制、max与普通FPU争用、LDS归约和全局load/store都进入时序IR。该实现与旧整网的 `range-reduced-polynomial-v1` 模板不同，本轮验证这些真实程序所驱动的执行机制，没有把它们的误差赋给旧整网模板。

长链的8个阶段观测（含独立softmax）中，归约/方差/倒平方根/LayerNorm affine均0周期偏差，GELU与后续softmax各少预测1周期。独立指令解码器还逐阶段检查Float64函数：LayerNorm最大绝对误差7.00e-8、GELU9.45e-8、softmax4.85e-8。这是所测数据上的数值误差，未证明全输入域精度。

多warp使用CSR.threadid计算独立128字节输出切片，共享只读输入，覆盖共同缓存与请求返回、有限LSU/collector/RF、Tensor与供数交织。2→4 warp时，两种布局的总窗口均增加，预测与RTL变化方向一致；同warp数下stream慢于conflict-return，排序一致。它们是共享输入的并发测试，没有覆盖不同warp独立工作集或多warp barrier。

## 尚未覆盖

长链是一组Transformer关键路径的组合，未包含Q/K/V完整数据组织、causal attention、KV更新、残差和完整FFN维度，不能称为完整Transformer block或整网RTL。仍需实际整网前端绑定这套非线性软件、总缓存容量溢出、不同warp工作集、真实跨kernel同步/flush以及官方软件对齐。旧8 warp GEMM反例保留，本轮没有宣布解决。

本轮可得的判断：v7机制执行器对所测非线性与2/4 warp混合访存，能较好预测周期量级和趋势；整网软件组织误差仍是独立问题。

## 文件与复验

`probes/pre_run_predictions.json`保存模型/生成器哈希、机器字、地址与输入哈希和预冻结周期。`rtl/`保留实际trace、summary、日志；`accuracy.json`保存逐阶段、数值、事务与误差。`isa_check.py`独立解码真实指令，Tensor参考只用于本轮小整数FP32输入，避免将顺序求和当成任意浮点Tensor树的数值等价证明。

```bash
PYTHONPATH=. .venv/bin/python analysis/ventus_flow_20261006/quick_complete_20261006/check.py --verify
.venv/bin/pytest -q tests/test_ventus_quick_complete.py
```

只读复验不重新运行RTL、不重新求解、不写历史结果。新增7项数值/地址回归通过；Ruff检查和格式检查通过。完整项目回归结果记录在 `pytest.log`。

最终完整 `pytest -q`：575项全部通过，188.02秒。最终 `ruff check codesign tests` 与 `ruff format --check codesign tests` 通过；本轮3个实验工具的检查/格式检查通过；冻结RTL证据只读复验通过。所有旧v6/v7结果保留，未修改frontend或成本模块。
