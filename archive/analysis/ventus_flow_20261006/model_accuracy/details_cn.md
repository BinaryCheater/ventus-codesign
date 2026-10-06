# Ventus模型测试详情

日期：2026-10-06。面向阅读的结论在[主文档](../report_cn.md)，这里保存测试定义、逐项结果和复现入口。

## 版本与计时

官方环境固定为`7e9790708d58ebf697d74fa8dadbaafa1232ca1d`，其中RTL为`f5853809f114192b99657e7021d1e50dfe961fe1`，SystemC模型为`335ba24d2c7763c87e8c9bfe889c9074763a32f7`。旧编译对应`681172541a8a34ffb43c483a19c075acbc11a4eb`；两个RTL提交只有三个文档文件变化，硬件与构建输入相同，子模块也一致，因此复用已有二进制。生成RTL、参数、库与测试driver的SHA256见[provenance](evidence/accuracy-provenance.json)。

所有测试在${REMOTE_HOST}原生运行。SystemC库的数据通路、调度、时序与资源参数未改动，哈希与之前构建相同；新driver从官方main.cpp生成，关闭DDR，并在kernel回调中读回输出、打印完成时刻。旧driver与旧结果保留。RTL使用原driver，快照间隔设置为大于总仿真时长，避免其`--snapshot 0`除零问题。

RTL半周期5个时间单位，完整周期10；SystemC时钟周期10ns。RTL区间从首个host WG请求被接受到最后WG返回，SystemC从首warp被SM接收到kernel全部WG完成。两个起点的内部层次不同，逐项绝对差异不能直接解释为同起点的严格周期误差。固定程序模板的长度增量及操作数变化用于消除固定启动偏移。

RTL在kernel完成后额外推进10,000次半周期step，让cache invalidate收尾，再从外存读回结果；这部分drain不计入表中kernel区间。SystemC在销毁虚拟地址空间前读回。输出正确证明指定输出符合预期，不是全状态等价证明。日志和输出范围都保留。

## 测试定义

加法、除法和读取的主体长度分别为16、64、192条。计算微程序为1个WG、1个warp、32个线程，32位数据；向量计算读回全部32个lane，标量程序读回最终标量存储。程序无循环和分支，直接编码官方ISA，保证主体指令不会被编译器消除。

标量加法每条读取并更新x1，向量加法每条更新v1，FP32加法对v1反复加1.0，整数除法对v1反复除以标量1；后继计算具有结果依赖。重复读取使用相同地址和相同目标寄存器，最终存储该值。读取微程序反映WAW、LSU与cache路径的综合行为。

初始化向量改用`vxor.vv`，不修改SystemC库。单独保留`vmv.v.i`探针：SystemC能解码它，但执行单元缺少对应分支并assert；同一二进制在RTL输出正确。负例的退出码为-6。

vecadd使用官方预编译指令，只改变驱动metadata中的grid，分别运行1、4、8个WG，检查32、128、256个输出；compiled hardware metadata保持原值。两个资源测试复用8-WG的完全相同指令和输入，只改变资源预留：VGPR每warp64→256，或LDS每WG4KiB→96KiB。两者均在RTL声明容量内。检查全部256个有效输出。

操作数测试采用相同数量、顺序和长度的指令，固定16条向量除法；只改变LUI/ADDI初始化常数，使被除数为1或`0x7fffffff`，除数为1。两边都检查32个输出。

## 逐项结果

单位为上述记录区间中的周期。

| 程序 | RTL | SystemC关闭DDR | 功能结果 |
|---|---:|---:|---|
| scalar_add-16 | 161 | 113 | 两边输出正确 |
| scalar_add-64 | 401 | 401 | 两边输出正确 |
| scalar_add-192 | 1,041 | 1,169 | 两边输出正确 |
| vector_add-16 | 174 | 167 | 两边输出正确 |
| vector_add-64 | 414 | 551 | 两边输出正确 |
| vector_add-192 | 1,054 | 1,575 | 两边输出正确 |
| vector_fadd-16 | 211 | 207 | 两边输出正确 |
| vector_fadd-64 | 547 | 687 | 两边输出正确 |
| vector_fadd-192 | 1,443 | 1,967 | 两边输出正确 |
| vector_div-16 | 505 | 194 | 两边输出正确 |
| vector_div-64 | 1,753 | 626 | 两边输出正确 |
| vector_div-192 | 5,081 | 1,778 | 两边输出正确 |
| repeat_load-16 | 434 | 96 | 两边输出正确 |
| repeat_load-64 | 962 | 336 | 两边输出正确 |
| repeat_load-192 | 2,370 | 976 | 两边输出正确 |
| vecadd-wg1 | 1,076 | 564 | 两边输出正确 |
| vecadd-wg4 | 8,839 | 681 | 两边输出正确 |
| vecadd-wg8 | 26,178 | 1,356 | 两边输出正确 |
| vecadd-vgpr256 | 26,887 | 1,356 | 两边输出正确 |
| vecadd-lds96k | 26,887 | 1,356 | 两边输出正确 |
| vmv-i-probe | 171 | 断言退出 | RTL输出正确，SystemC失败 |
| div-1-by-1 | 511 | 199 | 两边输出正确 |
| div-maxint-by-1 | 2,431 | 199 | 两边输出正确 |

计算与读取微程序、vmv探针和操作数测试没有RTL内存错误日志。所有vecadd及资源预留测试都保留一次未分配`0x80003000`读取警告，与旧基线相同。因此完整vecadd结果用于暴露默认路径差异，不单独用它归因cache或分配的全部耗时；无该警告的微程序也已显示时序不一致。

这些是固定默认硬件的测试，没有覆盖全部ISA、全部硬件配置或长期kernel。并行运行过部分RTL与SystemC任务，墙钟不作为稳定速度基准。

## 源码依据

以下均为锁定提交的实际代码。源码提取结果见[source_rules.json](evidence/source_rules.json)；它是部分建模输入，没有完成完整性能执行器，也不把记录条数当作设计变量数。

- [SystemC参数](https://github.com/THU-DSP-LAB/ventus-gpgpu-cpp-simulator/blob/335ba24d2c7763c87e8c9bfe889c9074763a32f7/src/parameters.h)：2个subcore×4个warp、每warp256个逻辑寄存器、LDS为0x10000000；部分cache尺寸常数用于地址分解。
- [SystemC CTA分配](https://github.com/THU-DSP-LAB/ventus-gpgpu-cpp-simulator/blob/335ba24d2c7763c87e8c9bfe889c9074763a32f7/src/CTA_Scheduler.cpp#L95)：检查warp、block和LDS，未检查SGPR/VGPR池；同周期派发WG的各warp还留有时序TODO。
- [SystemC取指](https://github.com/THU-DSP-LAB/ventus-gpgpu-cpp-simulator/blob/335ba24d2c7763c87e8c9bfe889c9074763a32f7/src/sm/subcore.cpp#L298)：通过MMU复制4字节指令，没有RTL的I-cache请求路径。
- [SystemC内存连接](https://github.com/THU-DSP-LAB/ventus-gpgpu-cpp-simulator/blob/335ba24d2c7763c87e8c9bfe889c9074763a32f7/src/top_gpgpu.cpp)：SM接口直接绑定Ramulator request。[Ramulator包装层](https://github.com/THU-DSP-LAB/ventus-gpgpu-cpp-simulator/blob/335ba24d2c7763c87e8c9bfe889c9074763a32f7/src/ramulator.cpp#L39)直接读写底层内存，关DDR立即回调，cache flush/invalidate请求直接释放；没有经过对应I/D/L2缓存。
- [SystemC LSU及LDS](https://github.com/THU-DSP-LAB/ventus-gpgpu-cpp-simulator/blob/335ba24d2c7763c87e8c9bfe889c9074763a32f7/src/sm/exec_lsu.cpp#L15)：LSU额外1周期，LDS读写固定2周期；sharedMem_request循环访问数组，未实现RTL的BankConflictArbiter。
- [SystemC SFU](https://github.com/THU-DSP-LAB/ventus-gpgpu-cpp-simulator/blob/335ba24d2c7763c87e8c9bfe889c9074763a32f7/src/sm/exec_sfu.cpp#L23)、[VALU](https://github.com/THU-DSP-LAB/ventus-gpgpu-cpp-simulator/blob/335ba24d2c7763c87e8c9bfe889c9074763a32f7/src/sm/exec_valu.cpp)、[VFPU](https://github.com/THU-DSP-LAB/ventus-gpgpu-cpp-simulator/blob/335ba24d2c7763c87e8c9bfe889c9074763a32f7/src/sm/exec_vfpu.cpp)：采用各自固定a_delay/b_delay；SFU未复现8-lane分组与除法数据相关迭代，VALU缺少vmv对应的计算分支。
- [RTL参数](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/f5853809f114192b99657e7021d1e50dfe961fe1/ventus/src/top/parameters.scala)、[实际执行例化](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/f5853809f114192b99657e7021d1e50dfe961fe1/ventus/src/pipeline/pipe.scala)：num_sfu=8、num_thread=32、VGPR池1024行、LDS128KiB；执行宽度、共享路径和资源池均影响建模。
- [RTL SFU分组](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/f5853809f114192b99657e7021d1e50dfe961fe1/ventus/src/pipeline/execution.scala#L806)、[整数除法器](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/f5853809f114192b99657e7021d1e50dfe961fe1/ventus/src/pipeline/IntDivMod.scala)：按活动组串行处理，迭代数由前导零数决定；两个正整数操作数测试都进入正常计算路径。
- [RTL资源表](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/f5853809f114192b99657e7021d1e50dfe961fe1/ventus/src/cta/resource_table.scala)、[RF映射与仲裁](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/f5853809f114192b99657e7021d1e50dfe961fe1/ventus/src/pipeline/operandCollector.scala)、[LDS冲突处理](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/f5853809f114192b99657e7021d1e50dfe961fe1/ventus/src/L1Cache/ShareMem/BankConflictArbiter.scala)：资源池、分配状态与bank规则需要保留。现有LDS仲裁不合并同地址读，不能按其它GPU的广播规则建模。

## 源码推导的核对

这里只预测操作数变化造成的差值，不从kernel总耗时拟合SFU延迟。32位正整数的前导零数：1为31，0x7fffffff为1。源码iter表达式给出1和31次迭代。每条满warp向量指令执行4组，16条依赖链不能相互重叠，因此增量为16×4×30=1920周期。固定的预处理、恢复、供数、写回和取指结构在这两个程序中相同。

RTL实际差值2431−511=1920；SystemC差值199−199=0。[summarize.py](scripts/summarize.py)独立计算源码公式，再核对保存结果。该公式未进行参数拟合；本轮没有将它登记为测量前冻结的盲测预测，不能据此宣称完整模型已经具备泛化准确率。

## 文件与复现

[evidence/summary.json](evidence/summary.json)聚合23组配对结果，并检查两个后端输入哈希相同。每组的stdout、stderr与summary保存在`evidence/accuracy-pairs`、`accuracy-resources`、`accuracy-negative`、`accuracy-operands`。输入保存在`evidence/accuracy-cases-v2`、`accuracy-resources`、`accuracy-negative`及`operand-inputs`；部分资源与负例输入和日志在同名目录中合并保存，文件名不同。服务端原始目录都保留在`${REMOTE_FLOW_ROOT}`。

读取现有结果重新核算，使用只读模式：

```bash
uv run python analysis/ventus_flow_20261006/model_accuracy/scripts/summarize.py \
  analysis/ventus_flow_20261006/model_accuracy/evidence \
  analysis/ventus_flow_20261006/evidence/rtl-parameters.json --verify
uv run python analysis/ventus_flow_20261006/model_accuracy/scripts/extract_source_rules.py \
  ${OWNER_UPSTREAM_CHECKOUT} \
  analysis/ventus_flow_20261006/model_accuracy/evidence/source_rules.json --verify
```

实际运行入口为[generate_cases.py](scripts/generate_cases.py)、[build_test_driver.py](scripts/build_test_driver.py)、[run_pairs.py](scripts/run_pairs.py)、[generate_resources.py](scripts/generate_resources.py)、[generate_operands.py](scripts/generate_operands.py)。它们依赖已有的固定版本RTL和SystemC构建；新运行使用新目录，mkdir拒绝覆盖旧结果。首次准备路径见[原构建说明](../scripts/README.md)。测试driver的最终源码保存在[evidence/cyclesim_observation_driver.cpp](evidence/cyclesim_observation_driver.cpp)。

本轮后端Ruff检查通过，项目464项pytest通过；实验脚本也通过Ruff与只读汇总核对。新增内容没有改变Break Layer求解器或现行评分语义。
