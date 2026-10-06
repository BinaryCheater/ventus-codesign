# Ventus 性能模型完整字段清单

日期：2026-10-03；计数口径与边界见 [report_cn.md](report_cn.md)。

P=源码具名；H=固定结构/策略；C=待校准时序；D=派生；E=外部参数族；W=软件输入族；X=排除。P 不保证任意值受整机支持。

每一行按同结构模板计数。字段族可能包含多个子值；动态状态不算设计自由度。

## 核心

### 组织与驻留（10行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V001 `sm_count` | SM 数量 | P 源码具名 | 2 | 全局并行与内存争用 | [ventus/src/top/parameters.scala:7](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L7) |
| V002 `cluster_count` | cluster 数量 | P 源码具名 | 1 | SM 分组和互连扇入；num_sm 必须可整除 | [ventus/src/top/parameters.scala:27](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L27) |
| V003 `warp_slots` | 每 SM 驻留 warp 槽 | P 源码具名 | 8 | 隐藏延迟；当前同时绑定多项资源 | [ventus/src/top/parameters.scala:8](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L8) |
| V004 `warp_threads` | 逻辑 warp 宽度 | P 源码具名 | 32 | 线程打包、掩码和协同粒度；更改需软件一致 | [ventus/src/top/parameters.scala:9](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L9) |
| V005 `block_slots` | 每 SM 驻留 WG 槽 | P 源码具名 | 8 | block 并发上限；须不超过 warp 数 | [ventus/src/top/parameters.scala:53](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L53) |
| V006 `warps_per_block_limit` | 每 WG warp 上限 | P 源码具名 | num_warp=8 | 当前绑定 warp_slots，可解耦候选 | [ventus/src/top/parameters.scala:55](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L55) |
| V007 `vgpr_vector_slots` | 每 SM 向量寄存器槽 | P 源码具名 | 128*num_warp=1024 | 每槽含 num_thread 个32位元素；绑定 warp 数 | [ventus/src/top/parameters.scala:20](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L20) |
| V008 `sgpr_scalar_slots` | 每 SM 标量寄存器槽 | P 源码具名 | 256*num_warp=2048 | 寄存器驻留限制；绑定 warp 数 | [ventus/src/top/parameters.scala:21](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L21) |
| V009 `lds_rows` | 共享内存行数 | P 源码具名 | 1024 | LDS 容量与 occupancy；容量还取决于行宽 | [ventus/src/top/parameters.scala:93](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L93) |
| V010 `mmu_enable` | MMU 启用 | P 源码具名 | false | 决定是否启用 TLB/PTW 整条路径 | [ventus/src/top/parameters.scala:15](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L15) |

### CTA 分配与回收（17行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V011 `pending_wg_depth` | 待分配 WG 表深度 | P 源码具名 | 8 | 提交吸收与分配器背压 | [ventus/src/top/parameters.scala:191](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L191) |
| V012 `resource_result_count` | 每资源表保留空洞数 | P 源码具名 | 2 | 候选空闲段摘要；精细分配仍需扫描 | [ventus/src/top/parameters.scala:194](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L194) |
| V013 `cu_scan_width` | 每周期检查 SM 数 | H 固定结构/策略 | 1 | 可参数化检查并行度，涉及 FSM 改造 | [ventus/src/cta/allocator.scala:124](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/allocator.scala#L124) |
| V014 `cu_preference` | SM 选择策略 | H 固定结构/策略 | 从上次分配 SM 的后继开始 | 影响负载分配和 cache locality | [ventus/src/cta/allocator.scala:224](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/allocator.scala#L224) |
| V015 `resource_allocation_policy` | 资源空洞选择规则 | H 固定结构/策略 | best fit空洞 | 选满足WG大小的最小段；必须保留碎片化 | [ventus/src/cta/resource_table.scala:305](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L305) |
| V016 `resource_handler_group` | 一组 handler 管理 SM 数 | P 源码具名 | 1 | 增加共享度改变资源表服务瓶颈 | [ventus/src/cta/resource_table.scala:620](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L620) |
| V017 `resource_scan_pipeline` | 资源表扫描流水 | C 待校准时序 | 指针、取数、空洞计算排序 | 保留逐段处理与填排空；总延迟依活跃 WG | [ventus/src/cta/resource_table.scala:468](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L468) |
| V018 `alloc_dealloc_priority` | 分配和回收优先级 | H 固定结构/策略 | 可抢占扫描；分配优先 | 不同请求竞争改变分配可见时刻 | [ventus/src/cta/resource_table.scala:141](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L141) |
| V019 `slot_dealloc_queue` | 资源槽回收队列深度 | H 固定结构/策略 | 2 | 回收背压 | [ventus/src/cta/resource_table.scala:769](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L769) |
| V020 `baseaddr_queue` | LDS/SGPR/VGPR 基址队列深度族 | H 固定结构/策略 | 各1，pipe和flow开启 | 三条同结构队列作为一个模板字段 | [ventus/src/cta/resource_table.scala:853](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/resource_table.scala#L853) |
| V021 `cta_dispatch_queue` | CTA 到 SM 分发队列深度 | H 固定结构/策略 | 2 | block 分配与逐 warp 派发的解耦 | [ventus/src/cta/cu_interface.scala:46](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/cu_interface.scala#L46) |
| V022 `warp_dispatch_width` | CTA splitter 派发宽度 | H 固定结构/策略 | 每次1个 warp | block 启动服务，不可假设全 warp 同周期就绪 | [ventus/src/cta/cu_interface.scala:71](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/cu_interface.scala#L71) |
| V023 `warp_slot_policy` | SM 内空闲 warp 槽选择 | H 固定结构/策略 | 低位优先 | 硬件 warp ID 改变 RF bank 与取指优先级 | [ventus/src/pipeline/CTA2warp.scala:59](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/CTA2warp.scala#L59) |
| V024 `warp_done_queue` | warp 完成回报 FIFO 深度 | H 固定结构/策略 | 16 | 隐藏的硬编码队列，回收路径仍要求 ready | [ventus/src/pipeline/CTA2warp.scala:73](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/CTA2warp.scala#L73) |
| V025 `completion_arbitration` | 跨 SM 完成回报仲裁 | H 固定结构/策略 | round robin | 完成吞吐与资源回收时刻 | [ventus/src/cta/cu_interface.scala:154](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/cu_interface.scala#L154) |
| V026 `completion_service` | 完成与回收 FSM | C 待校准时序 | GET_WF→UPDATE→必要时 DEALLOC | 每个 warp 回报占用服务周期；不简化为0 | [ventus/src/cta/cu_interface.scala:230](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/cu_interface.scala#L230) |
| V027 `wg_buffer_policy` | WG 表入队及候选选择 | H 固定结构/策略 | RRPriorityEncoder | 队列竞争与公平性；空位分配也用 RR | [ventus/src/cta/wg_buffer.scala:73](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/cta/wg_buffer.scala#L73) |

### 取指与指令分发（13行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V028 `fetch_words` | 每次取指指令数 | P 源码具名 | 2 | 要求2的幂；决定包宽，不等同每 warp 双发射 | [ventus/src/top/parameters.scala:38](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L38) |
| V029 `ibuffer_packets` | 每 warp 指令包 FIFO 深度 | P 源码具名 | 2包 | 每包 num_fetch 条；另有 SlowDown 寄存器 | [ventus/src/top/parameters.scala:45](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L45) |
| V030 `fetch_requests` | 每 SM 取指请求宽度 | H 固定结构/策略 | 1 | 一条 ICache 请求通道 | [ventus/src/pipeline/warp_schedule.scala:187](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/warp_schedule.scala#L187) |
| V031 `fetch_warp_policy` | 取指 warp 选择 | H 固定结构/策略 | 就绪 warp 中低 ID 优先 | 反向循环赋值导致低 ID 覆盖；与发射 RR 区别明显 | [ventus/src/pipeline/warp_schedule.scala:185](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/warp_schedule.scala#L185) |
| V032 `fetch_eligibility` | 取指准入规则 | H 固定结构/策略 | active 且 ibuffer ready | 取指可前推，不直接用 scoreboard_busy 门控 | [ventus/src/pipeline/warp_schedule.scala:184](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/warp_schedule.scala#L184) |
| V033 `packet_unpack_width` | 每 warp 指令包拆分宽度 | H 固定结构/策略 | 每次1条 | 限制同 warp 分发顺序 | [ventus/src/pipeline/ibuffer.scala:149](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L149) |
| V034 `packet_unpack_storage` | 拆包暂存容量 | H 固定结构/策略 | 每 warp 1包 | 须与指令 FIFO 一起考虑可缓存指令数 | [ventus/src/pipeline/ibuffer.scala:147](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L147) |
| V035 `scalar_dispatch_width` | 到 collector 的标量分发宽度 | H 固定结构/策略 | 1 | 可与另一 warp 的向量分发并行 | [ventus/src/pipeline/ibuffer.scala:64](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L64) |
| V036 `vector_dispatch_width` | 到 collector 的向量类分发宽度 | H 固定结构/策略 | 1 | 向量类含访存、FP、SFU、TC 和 MUL | [ventus/src/pipeline/ibuffer.scala:65](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L65) |
| V037 `scalar_dispatch_policy` | 标量 warp 分发策略 | H 固定结构/策略 | round robin | 选择就绪 warp | [ventus/src/pipeline/ibuffer.scala:64](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L64) |
| V038 `vector_dispatch_policy` | 向量 warp 分发策略 | H 固定结构/策略 | round robin | 与标量类独立仲裁 | [ventus/src/pipeline/ibuffer.scala:65](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L65) |
| V039 `instruction_class_routing` | 指令类别到 X/V 路由 | H 固定结构/策略 | mem/fp/mul/sfu/tc 归 V | 标量 load/FP 也会争用向量类资源 | [ventus/src/pipeline/ibuffer.scala:70](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/ibuffer.scala#L70) |
| V040 `branch_flush_scope` | 分支重定向丢弃范围 | H 固定结构/策略 | 对应 warp 指令与取指流水 | 回收错误路径取指，影响分支代价 | [ventus/src/pipeline/pipe.scala:193](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L193) |

### 依赖控制与 SIMT（14行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V041 `scoreboard_entries` | 每 warp 逻辑寄存器依赖表大小 | P 源码具名 | 256，来自5+3位 | 架构索引空间；不等于物理 RF 容量 | [ventus/src/pipeline/scoreboard.scala:102](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/scoreboard.scala#L102) |
| V042 `raw_waw_interlock` | RAW/WAW 依赖规则 | H 固定结构/策略 | 目的 busy 到 WB 才清除 | 相同 opcode 流量但依赖链不同，周期不同 | [ventus/src/pipeline/scoreboard.scala:129](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/scoreboard.scala#L129) |
| V043 `collector_tokens` | 每 warp X/V collector 在途令牌 | H 固定结构/策略 | X和V各1 | 限制单 warp 指令提前进入 collector | [ventus/src/pipeline/scoreboard.scala:105](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/scoreboard.scala#L105) |
| V044 `branch_interlock` | 分支和 barrier 的 warp 互锁 | H 固定结构/策略 | 1个 busy 标志 | 顺序与控制依赖 | [ventus/src/pipeline/scoreboard.scala:113](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/scoreboard.scala#L113) |
| V045 `fence_interlock` | fence 阻塞范围 | H 固定结构/策略 | 对应 warp 后续访存 | 必须等待访存响应，不能只加固定开销 | [ventus/src/pipeline/scoreboard.scala:133](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/scoreboard.scala#L133) |
| V046 `scoreboard_release` | 依赖清除时点 | H 固定结构/策略 | WB fire/collector out/控制完成 | 同周期清除与读取规则需保留，边界周期待比对 | [ventus/src/pipeline/scoreboard.scala:110](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/scoreboard.scala#L110) |
| V047 `simt_stack_depth` | 每 warp SIMT 栈深度 | P 源码具名 | num_thread=32 | 当前绑定逻辑线程数；合法嵌套限制 | [ventus/src/pipeline/pipe.scala:129](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L129) |
| V048 `divergent_path_policy` | 分歧路径先后顺序 | H 固定结构/策略 | 优先活动线程较少路径 | 相等时偏 else；需要掩码和真实控制流 | [ventus/src/pipeline/branch_join.scala:145](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/branch_join.scala#L145) |
| V049 `branch_control_queue` | 分支控制 FIFO 深度与 flow | H 固定结构/策略 | 1，flow=true | 控制与 compare 结果配对 | [ventus/src/pipeline/branch_join.scala:84](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/branch_join.scala#L84) |
| V050 `reconvergence_pc_queue` | 汇合 PC FIFO 深度与 flow | H 固定结构/策略 | 1，flow=true | 与分支控制队列耦合 | [ventus/src/pipeline/branch_join.scala:86](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/branch_join.scala#L86) |
| V051 `redirect_queue` | 重定向结果 FIFO 深度与 flow | H 固定结构/策略 | 1，flow=true | 控制背压 | [ventus/src/pipeline/branch_join.scala:88](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/branch_join.scala#L88) |
| V052 `barrier_release_rule` | WG barrier 到达和释放规则 | H 固定结构/策略 | 等待 WG 预期 warp 全到齐 | 影响同步停顿；不可用常数替代到达时差 | [ventus/src/pipeline/warp_schedule.scala:139](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/warp_schedule.scala#L139) |
| V053 `endprg_flush_rule` | WG 完成后的 DCache 维护触发 | H 固定结构/策略 | WG 全部 warp 结束触发 invalidate | 必须声明性能终点是否包含最终内存可见 | [ventus/src/pipeline/warp_schedule.scala:167](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/warp_schedule.scala#L167) |
| V054 `control_response_priority` | 分支与 warp 控制响应优先级 | H 固定结构/策略 | branch 优先，flushCache 会阻塞 | 同步、控制指令竞争 | [ventus/src/pipeline/warp_schedule.scala:52](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/warp_schedule.scala#L52) |

### RF 与 Operand Collector（21行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V055 `rf_banks` | SGPR/VGPR bank 数 | P 源码具名 | 共用4 | 容量相同但 bank 映射不同会影响供数 | [ventus/src/top/parameters.scala:18](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L18) |
| V056 `collector_count` | collector 单元数 | P 源码具名 | num_warp=8 | 绑定 warp 数；可独立选择需 RTL 改造 | [ventus/src/top/parameters.scala:19](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L19) |
| V057 `rf_bank_mapping` | RF bank 映射 | H 固定结构/策略 | (warp_id+reg_idx) mod banks | 影响多源冲突；bank 宽度部分代码写死2位 | [ventus/src/pipeline/operandCollector.scala:581](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L581) |
| V058 `sgpr_read_ports` | SGPR 每 bank 读端口数 | H 固定结构/策略 | 1 | 四 bank 共最多四个标量读请求 | [ventus/src/pipeline/regfile.scala:25](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L25) |
| V059 `vgpr_read_ports` | VGPR 每 bank 向量读端口数 | H 固定结构/策略 | 1 | 每次读取一个 warp 向量槽 | [ventus/src/pipeline/regfile.scala:58](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L58) |
| V060 `sgpr_write_ports` | SGPR 每 bank 写端口数 | H 固定结构/策略 | 1 | 还受全局标量 WB 每周期1条限制 | [ventus/src/pipeline/regfile.scala:28](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L28) |
| V061 `vgpr_write_ports` | VGPR 每 bank 向量写端口数 | H 固定结构/策略 | 1 | 掩码写入；还受向量 WB 限制 | [ventus/src/pipeline/regfile.scala:64](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L64) |
| V062 `rf_read_latency` | RF 同步读延迟 | C 待校准时序 | 1周期 SRAM 读 | collector 返回路径另有协议开销 | [ventus/src/pipeline/regfile.scala:53](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L53) |
| V063 `rf_read_write_bypass` | RF 同址读写旁路 | H 固定结构/策略 | RegNext匹配后旁路 | 不应给同址读写额外 stall | [ventus/src/pipeline/regfile.scala:22](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L22) |
| V064 `rf_vector_mask_write` | VGPR 写掩码粒度 | H 固定结构/策略 | 每 lane 一个32位元素 | 尾 warp/分歧保留旧元素 | [ventus/src/pipeline/regfile.scala:62](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/regfile.scala#L62) |
| V065 `collector_source_slots` | collector 请求槽数量 | H 固定结构/策略 | 3源+mask共4槽 | 源数量影响 bank 供数需求 | [ventus/src/pipeline/operandCollector.scala:67](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L67) |
| V066 `collector_allocation_policy` | 空 collector 选择与 X/V 优先级 | H 固定结构/策略 | 低位空槽；默认V优先 | num_warp=1 时 X/V 每周期轮流优先 | [ventus/src/pipeline/operandCollector.scala:461](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L461) |
| V067 `rf_read_arbitration` | 每 bank RF 读仲裁 | H 固定结构/策略 | round robin | 所有 collector 源一起争用 | [ventus/src/pipeline/operandCollector.scala:340](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L340) |
| V068 `collector_ready_rule` | collector 完成条件 | H 固定结构/策略 | 所有要求的源均已收齐 | 须保留指令级源需求；不能统一3次读 | [ventus/src/pipeline/operandCollector.scala:85](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L85) |
| V069 `collector_output_width` | collector 到执行 X/V 宽度 | H 固定结构/策略 | 各1 | 与前端两类分发构成相同两条流 | [ventus/src/pipeline/operandCollector.scala:630](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L630) |
| V070 `collector_output_policy` | 收齐源的 collector 选择 | H 固定结构/策略 | X/V 独立RR | 源读取和发射可能乱序，执行仍受 scoreboard | [ventus/src/pipeline/operandCollector.scala:650](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/operandCollector.scala#L650) |
| V071 `scalar_wb_width` | 标量写回通道数 | H 固定结构/策略 | 1 | 聚合各执行单元；不是每个 bank 独立写回 | [ventus/src/pipeline/writeback.scala:47](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L47) |
| V072 `vector_wb_width` | 向量写回通道数 | H 固定结构/策略 | 1 | 整数、FP、LSU、TC 竞争 | [ventus/src/pipeline/writeback.scala:46](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L46) |
| V073 `scalar_wb_priority` | 标量执行结果写回策略 | H 固定结构/策略 | 固定输入优先级 | 以 pipe 的输入连接顺序为准 | [ventus/src/pipeline/writeback.scala:60](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L60) |
| V074 `vector_wb_priority` | 向量执行结果写回策略 | H 固定结构/策略 | 固定输入优先级 | 不能套用 RR | [ventus/src/pipeline/writeback.scala:61](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L61) |
| V075 `wb_input_storage` | WB 聚合器输入暂存深度族 | H 固定结构/策略 | 全部0 | 实际缓冲在 FU 结果队列，禁止重复计算 | [ventus/src/pipeline/writeback.scala:53](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/writeback.scala#L53) |

### 整数与浮点执行（34行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V076 `scalar_alu_instances` | 标量 ALU 数量 | H 固定结构/策略 | 1 | 标量整数服务 | [ventus/src/pipeline/pipe.scala:76](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L76) |
| V077 `vector_alu_lanes` | 向量 ALU 物理 lane 数 | P 源码具名 | num_lane=num_thread=32 | 与 FPU/MUL 共用 num_lane，独立 lane 数需解耦 | [ventus/src/pipeline/pipe.scala:77](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L77) |
| V078 `vector_mul_lanes` | 向量 MUL 物理 lane 数 | P 源码具名 | num_lane=32 | 当前与 ALU/FPU 绑定 | [ventus/src/pipeline/pipe.scala:81](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L81) |
| V079 `vector_fpu_lanes` | 向量 FPU 物理 lane 数 | P 源码具名 | num_lane=32 | lane 时分支路存在；需 softThread 可整除 hardThread | [ventus/src/pipeline/pipe.scala:78](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L78) |
| V080 `execution_route_queue` | collector 到 Issue 缓冲深度族 | H 固定结构/策略 | 0，直接连线 | 目的 FU 背压直接传回 | [ventus/src/pipeline/issue.scala:54](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/issue.scala#L54) |
| V081 `scalar_alu_result_queue` | 标量 ALU 结果 FIFO | H 固定结构/策略 | 1，pipe=true | WB 竞争回压 | [ventus/src/pipeline/execution.scala:37](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L37) |
| V082 `scalar_branch_result_queue` | 标量分支结果 FIFO | H 固定结构/策略 | 1，pipe=true | 分支重定向可与普通结果竞争 | [ventus/src/pipeline/execution.scala:38](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L38) |
| V083 `vector_alu_result_queue` | 向量 ALU 结果 FIFO | H 固定结构/策略 | 1，pipe=true | FU 可接收与 WB 延迟不同 | [ventus/src/pipeline/execution.scala:504](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L504) |
| V084 `vector_compare_result_queue` | 向量比较到 SIMT FIFO | H 固定结构/策略 | 1，pipe=true | SIMT 背压 | [ventus/src/pipeline/execution.scala:422](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L422) |
| V085 `mul_pipe_latency` | 整数乘法内部流水延迟 | P 源码具名 | 2 | 局部流水值；全路径还包含 FU/WB 队列 | [ventus/src/pipeline/Multiplier.scala:152](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/Multiplier.scala#L152) |
| V086 `mul_result_queue` | 乘法 X/V 结果 FIFO 深度族 | H 固定结构/策略 | 各1，pipe=true | 结果输出解耦 | [ventus/src/pipeline/execution.scala:190](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L190) |
| V087 `lane_serialization` | 逻辑 warp 到物理 lane 时分方式 | H 固定结构/策略 | 按连续 lane 组发送并重组 | 当前32/32无需时分；减少 lane 时必须计填排空 | [ventus/src/pipeline/execution.scala:227](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L227) |
| V088 `fpu_subunit_sharing` | 单 lane 浮点单元组成与共享 | H 固定结构/策略 | FMA/CMP/MV/FPToInt/IntToFP | 每 lane 内多个子单元共享输入/输出通道 | [dependencies/fpuv2/src/main/scala/FPU.scala:15](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FPU.scala#L15) |
| V089 `fpu_output_priority` | FPU 五类子单元输出策略 | H 固定结构/策略 | 固定优先级 | 不同 FP 指令混合吞吐不能仅看峰值 | [dependencies/fpuv2/src/main/scala/FPU.scala:39](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FPU.scala#L39) |
| V090 `fp_mul_pipe_latency` | FP 乘法局部流水深度 | P 源码具名 | 2 | 不包含 FMA 内队列 | [dependencies/fpuv2/src/main/scala/FMA.scala:34](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L34) |
| V091 `fp_add_pipe_latency` | FP 加法局部流水深度 | P 源码具名 | 1 | FADD/FMA 共享加法流水 | [dependencies/fpuv2/src/main/scala/FMA.scala:74](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L74) |
| V092 `fma_add_arbitration` | FMA 中共享 add 选择 | H 固定结构/策略 | mul返回的 FMA 优先于独立add | ADD/FMA 混合竞争 | [dependencies/fpuv2/src/main/scala/FMA.scala:133](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L133) |
| V093 `fma_control_queue` | 共享 add 两路控制队列模板 | H 固定结构/策略 | 各1，pipe=true | 控制与数据队列必须配对 | [dependencies/fpuv2/src/main/scala/FMA.scala:134](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L134) |
| V094 `fma_direct_add_queue` | 独立 ADD 数据 FIFO | H 固定结构/策略 | 1，pipe=true | 共享 add 排队 | [dependencies/fpuv2/src/main/scala/FMA.scala:145](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L145) |
| V095 `fma_mul_to_add_queue` | MUL 到 ADD 数据 FIFO | H 固定结构/策略 | 1，pipe=true | FMA 内部生产消费依赖 | [dependencies/fpuv2/src/main/scala/FMA.scala:152](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L152) |
| V096 `fma_output_queue` | FMA 的 mul/add 输出 FIFO 模板 | H 固定结构/策略 | 各1，pipe=true | FMA 内输出竞争 | [dependencies/fpuv2/src/main/scala/FMA.scala:167](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L167) |
| V097 `fma_output_priority` | FMA 内 add/mul 输出优先级 | H 固定结构/策略 | add/FMA 优先于mul | 影响持续混合指令 | [dependencies/fpuv2/src/main/scala/FMA.scala:178](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FMA.scala#L178) |
| V098 `fp_cmp_latency` | 浮点比较局部流水延迟 | P 源码具名 | 2 | 与转换同数值也保留独立操作族 | [dependencies/fpuv2/src/main/scala/FCMP.scala:11](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FCMP.scala#L11) |
| V099 `fp_move_latency` | 浮点搬移局部流水延迟 | P 源码具名 | 2 | 实际执行路径为 FPU 子模块 | [dependencies/fpuv2/src/main/scala/FPMV.scala:11](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FPMV.scala#L11) |
| V100 `fp_to_int_latency` | 浮点转整数局部延迟 | P 源码具名 | 2 | 转换类时序 | [dependencies/fpuv2/src/main/scala/FPToInt.scala:12](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/FPToInt.scala#L12) |
| V101 `int_to_fp_latency` | 整数转浮点局部延迟 | P 源码具名 | 2 | 转换类时序 | [dependencies/fpuv2/src/main/scala/IntToFP.scala:11](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/IntToFP.scala#L11) |
| V102 `sfu_units` | 每 SM SFU lane 数 | P 源码具名 | max(num_thread/4,1)=8 | 与 warp_width 绑定；每 lane 有整数除法和 FP div/sqrt | [ventus/src/top/parameters.scala:91](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L91) |
| V103 `sfu_input_queue` | SFU 指令暂存 FIFO | H 固定结构/策略 | 1 | 默认整个 SFU 逐指令处理 | [ventus/src/pipeline/execution.scala:818](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L818) |
| V104 `sfu_output_queue` | SFU X/V 结果 FIFO 模板 | H 固定结构/策略 | 各1，pipe=true | SFU 与 WB 竞争 | [ventus/src/pipeline/execution.scala:813](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L813) |
| V105 `sfu_mask_group_policy` | SFU 分组及空组跳过规则 | H 固定结构/策略 | 优先低位活动组；每组num_sfu条 | 按掩码组数计服务；组内慢 lane 可拖全组 | [ventus/src/pipeline/execution.scala:828](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L828) |
| V106 `sfu_group_completion` | SFU 组完成与 lane 同步 | H 固定结构/策略 | 等待整组输出 valid | 操作数相关慢 lane 与掩码填充有影响 | [ventus/src/pipeline/execution.scala:849](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L849) |
| V107 `int_div_latency_function` | 整数除法迭代与特殊值规则 | C 待校准时序 | 依前导零差/除零/溢出变化 | 需要值或延迟类别输入，不能一个固定delay | [ventus/src/pipeline/IntDivMod.scala:46](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/IntDivMod.scala#L46) |
| V108 `fp_div_sqrt_latency_function` | FP div/sqrt 迭代与特殊值规则 | C 待校准时序 | 28位 recurrence + prepare/round | 特殊值捷径和正常路径需 FSM/微基准确认 | [ventus/src/pipeline/FloatDivSqrt.scala:34](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/FloatDivSqrt.scala#L34) |
| V109 `sfu_initiation_rule` | SFU 新指令准入规则 | H 固定结构/策略 | 等待当前指令 finish并消费 | SFU 内部延迟与整个 warp II 不同 | [ventus/src/pipeline/execution.scala:897](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L897) |

### Tensor Core（11行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V110 `tc_instances` | 每 SM Tensor Core 数 | H 固定结构/策略 | 1 | 可改造为多个独立资源 | [ventus/src/pipeline/pipe.scala:82](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L82) |
| V111 `matrix_output_m` | TC 输出矩阵第一轴 | P 源码具名 | DimM=4 | 默认和 num_thread 绑定 | [ventus/src/top/parameters.scala:124](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L124) |
| V112 `matrix_output_n` | TC 输出矩阵第二轴 | P 源码具名 | 代码DimK=4 | 代码 DimK 是输出轴，数学上记N，避免维度误读 | [dependencies/fpuv2/src/main/scala/Tensor.scala:213](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L213) |
| V113 `matrix_reduction_k` | TC 点积归约轴 | P 源码具名 | 代码DimN=8 | 代码 DimN 是归约轴，数学上记K | [dependencies/fpuv2/src/main/scala/Tensor.scala:214](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L214) |
| V114 `matrix_lane_layout` | TC 碎片寄存器布局 | H 固定结构/策略 | A[m*DimN+n]、B[k*DimN+n]、C[m*DimK+k] | 决定编译器数据重排和供数 | [dependencies/fpuv2/src/main/scala/Tensor.scala:215](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L215) |
| V115 `matrix_arithmetic` | TC 计算与舍入结构 | H 固定结构/策略 | FP32 mul→平衡add tree→add C | 逐节点舍入；与单指令全融合语义需区分 | [dependencies/fpuv2/src/main/scala/Tensor.scala:161](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L161) |
| V116 `tc_mul_latency` | TC 每乘法节点流水延迟 | P 源码具名 | 2 | primitive 时序字段 | [dependencies/fpuv2/src/main/scala/Tensor.scala:14](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L14) |
| V117 `reduction_add_latency` | TC 每树加法节点流水延迟 | P 源码具名 | 2 | 按log2(归约轴) 层累计；源中该类latency=2 | [dependencies/fpuv2/src/main/scala/Tensor.scala:11](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L11) |
| V118 `tc_dot_output_queue` | 每 TC dot-product 输出 FIFO | H 固定结构/策略 | 1，pipe=true | 同模板，按M*N复制但只计一个字段 | [dependencies/fpuv2/src/main/scala/Tensor.scala:173](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L173) |
| V119 `tc_warp_output_queue` | TC wrapper 向量输出 FIFO | H 固定结构/策略 | 1，pipe=true | TC 与其它执行单元竞争 VGPR WB | [ventus/src/pipeline/execution.scala:124](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/execution.scala#L124) |
| V120 `matrix_accept_rule` | TC 输入与输出背压 | H 固定结构/策略 | head dot 控制，整阵列同 valid/ready | 吞吐受数据供给与 WB 共同约束 | [dependencies/fpuv2/src/main/scala/Tensor.scala:209](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L209) |

### LSU 与合并返回（17行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V121 `lsu_input_queue` | LSU 指令 FIFO 深度 | H 固定结构/策略 | 1，pipe=true | 访存发射缓冲 | [ventus/src/pipeline/LSU.scala:551](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L551) |
| V122 `lsu_instruction_entries` | LSU 在途 warp 指令记录数 | P 源码具名 | num_warp=8 | 合并分段返回，不等于 DCache miss MSHR | [ventus/src/top/parameters.scala:69](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L69) |
| V123 `lsu_per_warp_credit` | 每 warp 在途访存上限 | P 源码具名 | 4 | ShiftBoard credit；与总LSU entries共同限制 | [ventus/src/top/parameters.scala:67](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L67) |
| V124 `lsu_address_width` | 地址计算/发起通道数量 | H 固定结构/策略 | 1条 AddrCalculate FSM | 每条向量访存分多笔 line 请求 | [ventus/src/pipeline/LSU.scala:554](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L554) |
| V125 `lsu_address_modes` | 地址生成模式 | H 固定结构/策略 | unit stride/stride/index/private swizzle | 对合并与外存局部性影响显著 | [ventus/src/pipeline/LSU.scala:153](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L153) |
| V126 `lsu_coalescing_granularity` | 全局访存合并粒度 | P 源码具名 | 128 B line | 绑定 DCache_BlockWords；不能把warp load直接计一笔 | [ventus/src/pipeline/LSU.scala:173](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L173) |
| V127 `lsu_line_selection` | 合并时下一 line 选择 | H 固定结构/策略 | 最低活动 lane 所在 line | 影响多 line 请求的顺序 | [ventus/src/pipeline/LSU.scala:169](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L169) |
| V128 `lsu_request_serialization` | 多 line 请求拆分发出规则 | H 固定结构/策略 | 逐 line 清除已发掩码 | 由 FSM 逐笔服务，II 需微基准，不预设1 | [ventus/src/pipeline/LSU.scala:283](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L283) |
| V129 `lsu_shared_routing` | 全局与 LDS 路由判定 | H 固定结构/策略 | 活动 lane 都落在 LDS 才选shared | 混合地址不能任意逐 lane 分别路由 | [ventus/src/pipeline/LSU.scala:164](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L164) |
| V130 `lsu_byte_masks` | byte/half/word 访问掩码粒度 | H 固定结构/策略 | 1/2/4 byte | 影响合并字节与写回掩码 | [ventus/src/pipeline/LSU.scala:183](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L183) |
| V131 `lsu_response_priority` | DCache/LDS 返回仲裁 | H 固定结构/策略 | DCache固定优先 | LDS与global同时返回时争用 | [ventus/src/pipeline/LSU.scala:560](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L560) |
| V132 `lsu_response_accumulation` | 分段返回聚合规则 | H 固定结构/策略 | 收齐原指令活动掩码才可 WB | 不同 line 的最慢响应决定完成 | [ventus/src/pipeline/MSHR.scala:37](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/MSHR.scala#L37) |
| V133 `lsu_entry_selection` | 在途槽分配和完成选择 | H 固定结构/策略 | 低位优先 | 返回/再分配次序 | [ventus/src/pipeline/MSHR.scala:38](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/MSHR.scala#L38) |
| V134 `lsu_mshr_update_conflict` | LSU 表同时分配和返回更新 | H 固定结构/策略 | 返回优先；新分配延至s_add | 合并表服务本身会产生瓶颈 | [ventus/src/pipeline/MSHR.scala:50](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/MSHR.scala#L50) |
| V135 `lsu_return_service` | LSU 表到 WB 的 FSM 服务 | C 待校准时序 | idle/add/out，out 时才能释放 | 表数再大也不保证每周期完整指令完成 | [ventus/src/pipeline/MSHR.scala:106](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/MSHR.scala#L106) |
| V136 `lsu_fence_rule` | LSU fence 完成条件 | H 固定结构/策略 | 相应warp全部在途请求完成 | fence效果由credit与响应时序决定 | [ventus/src/pipeline/LSU.scala:572](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L572) |
| V137 `lsu_flush_priority` | LSU cache维护和新访存优先 | H 固定结构/策略 | idle 时优先处理flush_dcache；实际opcode为invalidate | WG结束flush与普通访存竞争 | [ventus/src/pipeline/LSU.scala:371](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L371) |

### L1 指令缓存（12行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V138 `icache_sets` | ICache set 数 | P 源码具名 | dcache_NSets=256 | MyConfig 默认同 DCache；局部构造参数可改 | [ventus/src/L1Cache/ICache/ICacheParameters.scala:21](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheParameters.scala#L21) |
| V139 `icache_ways` | ICache ways | P 源码具名 | dcache_NWays=2 | 当前默认绑定 DCache | [ventus/src/L1Cache/ICache/ICacheParameters.scala:22](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheParameters.scala#L22) |
| V140 `icache_line_bytes` | ICache line 大小 | P 源码具名 | DCache_BlockWords*4=128 B | line 属性继承共用基类 | [ventus/src/L1Cache/ICache/ICache.scala:85](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICache.scala#L85) |
| V141 `icache_mshr_entries` | ICache primary MSHR | P 源码具名 | 4 | 独立 miss line 数 | [ventus/src/L1Cache/ICache/ICacheParameters.scala:24](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheParameters.scala#L24) |
| V142 `icache_mshr_targets` | ICache 每 miss 合并目标数 | P 源码具名 | 4 | 同 line 多warp miss 合并 | [ventus/src/L1Cache/ICache/ICacheParameters.scala:25](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheParameters.scala#L25) |
| V143 `icache_response_queue` | ICache 下层返回 FIFO | H 固定结构/策略 | 2，pipe=true | refill吸收与背压 | [ventus/src/L1Cache/ICache/ICache.scala:99](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICache.scala#L99) |
| V144 `icache_hit_latency` | ICache 命中核心路径 | C 待校准时序 | req fire 到 st2 response | 静态推断2级；全路径仍有拆包开销 | [ventus/src/L1Cache/ICache/ICache.scala:201](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICache.scala#L201) |
| V145 `icache_ports` | ICache 数据存储端口组织 | H 固定结构/策略 | 同步1R1W，双端口 | 读命中可与refill写并存；同址规则需保持 | [ventus/src/L1Cache/ICache/ICache.scala:90](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICache.scala#L90) |
| V146 `icache_replacement` | ICache 替换策略 | H 固定结构/策略 | 全局循环one-hot victim | 替换状态不按set独立，不能替成通用LRU | [ventus/src/L1Cache/L1TagAccess.scala:516](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/L1TagAccess.scala#L516) |
| V147 `icache_miss_replay` | ICache miss/replay 规则 | H 固定结构/策略 | 返回miss status，refill后重取 | miss等待不能只加一次固定delay | [ventus/src/L1Cache/ICache/ICache.scala:220](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICache.scala#L220) |
| V148 `icache_replay_hazard` | 同warp近邻miss冲突窗口 | H 固定结构/策略 | 检查前2/3级 warp与miss | 影响取指密集及 miss 模式 | [ventus/src/L1Cache/ICache/ICache.scala:276](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICache.scala#L276) |
| V149 `icache_refill_target_service` | 同line miss目标返送顺序 | H 固定结构/策略 | 一次返送一个 target | subentry>1仍有逐个服务 | [ventus/src/L1Cache/ICache/ICacheMSHR.scala:175](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheMSHR.scala#L175) |

### L1 数据缓存（23行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V150 `dcache_sets` | DCache set 数 | P 源码具名 | 256 | cache locality与容量 | [ventus/src/top/parameters.scala:71](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L71) |
| V151 `cache_ways` | DCache ways | P 源码具名 | 2 | 冲突miss与 tag探测 | [ventus/src/top/parameters.scala:73](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L73) |
| V152 `cache_line_words` | DCache line words | P 源码具名 | 32即128 B | 影响合并；其它多个结构引用该值 | [ventus/src/top/parameters.scala:75](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L75) |
| V153 `cache_mshr_entries` | DCache primary MSHR | P 源码具名 | 4 | 独立miss并发 | [ventus/src/top/parameters.scala:88](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L88) |
| V154 `cache_mshr_targets` | DCache 每 miss 次级目标 | P 源码具名 | 2 | 同line miss合并能力 | [ventus/src/top/parameters.scala:90](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L90) |
| V155 `cache_write_status_entries` | DCache WSHR 数 | P 源码具名 | 4 | 写miss/写回在途追踪 | [ventus/src/top/parameters.scala:76](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L76) |
| V156 `cache_request_queue` | DCache core request FIFO | H 固定结构/策略 | 1，pipe=true，flow=false | lookup 准入与流水寄存 | [ventus/src/L1Cache/DCache/DCache.scala:188](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L188) |
| V157 `cache_response_queue` | DCache core response FIFO | H 固定结构/策略 | NLanes=32，非pipe/flow | 当前绑定warp线程数 | [ventus/src/L1Cache/DCache/DCache.scala:190](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L190) |
| V158 `cache_refill_queue` | DCache 下层响应 FIFO | H 固定结构/策略 | 2，非pipe/flow | 命中与refill竞争 | [ventus/src/L1Cache/DCache/DCache.scala:194](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L194) |
| V159 `cache_outgoing_queue` | DCache 下层请求 FIFO | H 固定结构/策略 | 8，非pipe/flow | miss、dirty替换、flush共享 | [ventus/src/L1Cache/DCache/DCache.scala:198](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L198) |
| V160 `cache_internal_elasticity` | DCache 内部1槽暂存模板 | H 固定结构/策略 | control/readHit/st2/data均1 | 作为同结构族，不逐个临时寄存器扩张计数 | [ventus/src/L1Cache/DCache/DCache.scala:232](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L232) |
| V161 `cache_hit_service` | DCache hit流水与响应服务 | C 待校准时序 | tag探测→data→coreRsp队列 | 准确边界周期及背压需要RTL确认 | [ventus/src/L1Cache/DCache/DCache.scala:249](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L249) |
| V162 `cache_store_hit_policy` | DCache store hit策略 | H 固定结构/策略 | 本地更新并标脏，后续写回 | 当前RTL含dirty mask，早期写穿通文档过时 | [ventus/src/L1Cache/DCache/DCache.scala:315](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L315) |
| V163 `cache_store_miss_policy` | DCache store miss策略 | H 固定结构/策略 | PutPartial下传，不经读分配 | 区分hit和miss写策略 | [ventus/src/L1Cache/DCache/DCache.scala:358](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L358) |
| V164 `cache_replacement_policy` | DCache victim 选择 | H 固定结构/策略 | 有限accessCount时间戳规则 | 接近LRU意图但有1000次counter循环，模型须按源码 | [ventus/src/L1Cache/L1TagAccess.scala:77](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/L1TagAccess.scala#L77) |
| V165 `cache_dirty_granularity` | DCache dirty记录粒度 | H 固定结构/策略 | 每cacheline字节掩码 | 脏流量取决于写覆盖字节 | [ventus/src/L1Cache/L1TagAccess.scala:209](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/L1TagAccess.scala#L209) |
| V166 `cache_data_bank_layout` | DCache data array组织 | H 固定结构/策略 | 每line word独立字节掩码SRAM | 实际按BlockWords实例化，勿把NBanks别名当物理组织 | [ventus/src/L1Cache/DCache/DCache.scala:637](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L637) |
| V167 `cache_data_ports` | DCache data array端口 | H 固定结构/策略 | 同步1R1W双端口 | refill写与writehit的实际mux优先级需保留 | [ventus/src/L1Cache/DCache/DCache.scala:644](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L644) |
| V168 `cache_downstream_priority` | DCache 下层请求策略 | H 固定结构/策略 | dirty victim→普通miss→flush | 三个固定优先输入 | [ventus/src/L1Cache/DCache/DCache.scala:785](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L785) |
| V169 `cache_lookup_refill_conflict` | tag探测与分配写冲突规则 | H 固定结构/策略 | probe遇allocate则阻塞 | 命中与refill并发不总为满吞吐 | [ventus/src/L1Cache/DCache/DCache.scala:623](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L623) |
| V170 `cache_write_miss_interlock` | 写miss与已有miss互锁 | H 固定结构/策略 | inflightreadwritemiss等状态阻塞 | MSHR增加不能消除所有阻塞 | [ventus/src/L1Cache/DCache/DCache.scala:210](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L210) |
| V171 `cache_sameword_merge` | 同word字节写合并规则 | H 固定结构/策略 | genDataMapSameWord重映射 | 字节覆盖与冲突影响实际请求数 | [ventus/src/L1Cache/DCache/DCache.scala:201](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L201) |
| V172 `cache_flush_rule` | DCache flush/invalidate排空条件 | H 固定结构/策略 | dirty扫描、WSHR与L2确认 | kernel尾部代价由dirty状态决定 | [ventus/src/L1Cache/DCache/DCache.scala:207](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/DCache/DCache.scala#L207) |

### 共享内存 LDS（10行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V173 `lds_line_words` | LDS 每行word数 | P 源码具名 | DCache_BlockWords=32 | 与cacheline共用定义；按当前地址切片约束 | [ventus/src/top/parameters.scala:95](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L95) |
| V174 `lds_banks` | LDS bank 数 | P 源码具名 | NLanes=num_thread=32 | 显式TODO解耦；和线程数绑定 | [ventus/src/L1Cache/ShareMem/ShareMemParameters.scala:40](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMemParameters.scala#L40) |
| V175 `lds_bank_address_map` | LDS bank地址映射 | H 固定结构/策略 | word地址低位 | stride与布局决定冲突 | [ventus/src/L1Cache/ShareMem/ShareMemParameters.scala:48](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMemParameters.scala#L48) |
| V176 `lds_bank_ports` | LDS 每bank端口 | H 固定结构/策略 | 1R1W双端口 | 与bank冲突仲裁和写占用准入耦合 | [ventus/src/L1Cache/ShareMem/ShareMem.scala:152](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMem.scala#L152) |
| V177 `lds_read_latency` | LDS data读时序 | C 待校准时序 | 同步读+st1/st2响应路径 | 准确请求到响应周期需验证 | [ventus/src/L1Cache/ShareMem/ShareMem.scala:128](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMem.scala#L128) |
| V178 `lds_response_queue` | LDS 返回 FIFO | H 固定结构/策略 | num_thread=32，pipe=true | warp_width绑定返回缓冲 | [ventus/src/L1Cache/ShareMem/ShareMem.scala:72](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMem.scala#L72) |
| V179 `lds_conflict_policy` | 每bank多个lane仲裁 | H 固定结构/策略 | 低位lane优先；余者逐轮服务 | 要按实际地址/掩码计算冲突，非平均系数 | [ventus/src/L1Cache/ShareMem/BankConflictArbiter.scala:164](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/BankConflictArbiter.scala#L164) |
| V180 `lds_same_address_merge` | LDS 同地址广播合并 | H 固定结构/策略 | 不合并 | 32 lane同word读也排队，不能套用NVIDIA广播假设 | [ventus/src/L1Cache/ShareMem/BankConflictArbiter.scala:184](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/BankConflictArbiter.scala#L184) |
| V181 `lds_access_overlap` | LDS 新请求与重放/写重叠 | H 固定结构/策略 | 冲突重放及st1写阻塞新请求 | 1R1W能力不等于每周期一条向量指令 | [ventus/src/L1Cache/ShareMem/ShareMem.scala:194](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMem.scala#L194) |
| V182 `lds_byte_write` | LDS 写掩码和旁路 | H 固定结构/策略 | 字节掩码；bypassWrite=true | 影响同址读写语义；保持精确访问粒度 | [ventus/src/L1Cache/ShareMem/ShareMem.scala:153](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ShareMem/ShareMem.scala#L153) |

### L2 缓存与服务（24行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V183 `l2_slices` | L2 slice 数 | P 源码具名 | 1 | 并行共享内存服务端点 | [ventus/src/top/parameters.scala:132](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L132) |
| V184 `l2_sets` | 每slice L2 set 数 | P 源码具名 | 64 | 容量与L2索引 | [ventus/src/top/parameters.scala:99](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L99) |
| V185 `l2_ways` | L2 associativity | P 源码具名 | 16 | 冲突miss；victim取低wayBits，变更须合法 | [ventus/src/top/parameters.scala:101](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L101) |
| V186 `l2_line_bytes` | L2 line 大小 | P 源码具名 | DCache_BlockWords*4=128 B | 当前绑定L1大小 | [ventus/src/top/parameters.scala:103](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L103) |
| V187 `l2_beat_bytes` | L2内外接口beat大小 | P 源码具名 | 等于line=128 B | 局部声明可设置，但实际多个路径依赖单beat | [ventus/src/top/parameters.scala:113](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L113) |
| V188 `l2_write_bytes` | L2存储更新粒度 | P 源码具名 | 1 B | mask和data子bank组织 | [ventus/src/top/parameters.scala:105](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L105) |
| V189 `l2_sizing_mem_cycles` | L2资源配额的memory cycles参数 | P 源码具名 | 32 | 只用于MSHR/secondary/put尺寸，绝非真实DDR延迟 | [ventus/src/top/parameters.scala:107](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L107) |
| V190 `l2_mshr_entries` | L2 MSHR 数 | D 派生 | max(dirReg?3:2,ceil(memCycles/blockBeats))=32 | 由资源配额导出；不能当独立upstream参数 | [ventus/src/L2cache/Parameters.scala:164](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L164) |
| V191 `l2_secondary_entries` | L2 secondary共享entry池 | D 派生 | max(mshrs,memCycles-mshrs)=32 | ListBuffer全局pool，非每MSHR32项 | [ventus/src/L2cache/Parameters.scala:165](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L165) |
| V192 `l2_put_lists` | L2写数据list数 | D 派生 | memCycles=32 | 写数据追踪，绑定memory sizing | [ventus/src/L2cache/Parameters.scala:166](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L166) |
| V193 `l2_put_beats` | L2写数据beat池大小 | D 派生 | max(2*blockBeats,memCycles)=32 | 统一beat池，非list数乘beat数 | [ventus/src/L2cache/Parameters.scala:167](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L167) |
| V194 `l2_mshr_policy` | L2 MSHR服务选择 | H 固定结构/策略 | round robin filter | directory、sourceA和sourceD多资源竞争 | [ventus/src/L2cache/Scheduler.scala:103](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Scheduler.scala#L103) |
| V195 `l2_merge_semantics` | L2同set请求合并/排队规则 | H 固定结构/策略 | ListBuffer关联到MSHR列表 | 必须检查MSHR/queued请求具体状态，非纯miss率模型 | [ventus/src/L2cache/Scheduler.scala:89](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Scheduler.scala#L89) |
| V196 `l2_writeback_queue` | L2 dirty下传FIFO | H 固定结构/策略 | 8，pipe=true | dirty victim与普通miss解耦 | [ventus/src/L2cache/Scheduler.scala:125](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Scheduler.scala#L125) |
| V197 `l2_writeback_priority` | L2下层A通道优先级 | H 固定结构/策略 | write_buffer优先 | 写回占用带宽并延迟读miss | [ventus/src/L2cache/Scheduler.scala:143](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Scheduler.scala#L143) |
| V198 `l2_replacement` | L2实际victim策略 | H 固定结构/策略 | 16位LFSR低wayBits | 配置字符串plru未接入实际victim逻辑 | [ventus/src/L2cache/Directory_test.scala:227](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Directory_test.scala#L227) |
| V199 `l2_replacement_sequence` | L2 LFSR种子和推进规则 | H 固定结构/策略 | reset=0；result.fire推进 | 同策略不同序列也影响冲突trace，可固定为校准常量 | [ventus/src/L2cache/Directory_test.scala:219](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Directory_test.scala#L219) |
| V200 `l2_directory_ports` | L2 directory存储端口 | H 固定结构/策略 | 1R1W，sync、hold、bypass | lookup/refill同set竞争与旁路 | [ventus/src/L2cache/Directory_test.scala:103](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Directory_test.scala#L103) |
| V201 `l2_directory_service` | L2 directory查询和冲突协议 | C 待校准时序 | 同步读+结果保持/冲突处理 | 命中延迟不能只由capacity推得 | [ventus/src/L2cache/Directory_test.scala:229](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Directory_test.scala#L229) |
| V202 `l2_data_ports` | L2 data array端口 | H 固定结构/策略 | 1R1W、同步读 | 单共享访问端口，byte banks不提供独立128路请求 | [ventus/src/L2cache/BankedStore.scala:92](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/BankedStore.scala#L92) |
| V203 `l2_refill_store_priority` | L2 refill和store数据写优先级 | H 固定结构/策略 | sinkD优先于sourceD写 | refill吞吐与store hit相互竞争 | [ventus/src/L2cache/BankedStore.scala:109](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/BankedStore.scala#L109) |
| V204 `l2_source_d_service` | L2 hit/miss/dirty返回服务FSM | C 待校准时序 | 8状态路径，依请求类型 | hit与dirty miss服务时间分开，精确边界待校准 | [ventus/src/L2cache/SourceD.scala:68](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/SourceD.scala#L68) |
| V205 `l2_flush_service` | L2 flush/invalidate协议 | H 固定结构/策略 | 排空putbuffer；invalidate还待MSHR空 | 跨SM共享缓存状态影响尾部flush | [ventus/src/L2cache/Scheduler.scala:154](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Scheduler.scala#L154) |
| V206 `l2_input_buffer` | L2 A通道输入buffer模板 | P 源码具名 | BufferParams.none | 仅实际消费的innerBuf.a纳入 | [ventus/src/L2cache/SinkA.scala:48](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/SinkA.scala#L48) |

### 互连与争用（7行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V207 `l1_to_l2_policy` | SM内I/D下层请求仲裁 | H 固定结构/策略 | 固定优先级 | 输入连接顺序须纳入模型 | [ventus/src/L1Cache/L1Cache2L2Arbiter.scala:32](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/L1Cache2L2Arbiter.scala#L32) |
| V208 `sm_to_cluster_policy` | SM到cluster仲裁 | H 固定结构/策略 | 固定优先级 | 改变sm数量改变争用 | [ventus/src/top/GPGPU_top.scala:529](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L529) |
| V209 `sm_to_cluster_queue` | cluster入口请求FIFO | H 固定结构/策略 | 2 | 有限缓冲与背压 | [ventus/src/top/GPGPU_top.scala:530](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L530) |
| V210 `cluster_to_l2_policy` | cluster到L2仲裁 | H 固定结构/策略 | 固定优先级 | 多个cluster共L2端点 | [ventus/src/top/GPGPU_top.scala:610](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L610) |
| V211 `l2_slice_address_map` | L2 slice地址映射 | H 固定结构/策略 | offset→set→slice→tag | 多slice地址条带布局 | [ventus/src/L2cache/Parameters.scala:222](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L222) |
| V212 `l2_to_cluster_response_policy` | L2到cluster返回仲裁 | H 固定结构/策略 | 固定优先级 | 各slice响应争用返程通道 | [ventus/src/top/GPGPU_top.scala:590](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L590) |
| V213 `interconnect_beat_service` | 互连每通道服务宽度 | H 固定结构/策略 | 每次一个128B beat | 当前为分层仲裁互连；无路由器、VC或mesh模型 | [ventus/src/top/GPGPU_top.scala:550](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L550) |

## 可选 MMU

### 可选 MMU（14行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V214 `virtual_page_offset_bits` | 基本page offset位数 | P 源码具名 | 12即4 KiB | 固定ISA和地址翻译契约时应冻结 | [ventus/src/mmu/PTW.scala:24](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/PTW.scala#L24) |
| V215 `page_table_levels` | 页表层数 | P 源码具名 | SV32=2 | superpage路径与walk流量 | [ventus/src/mmu/PTW.scala:27](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/PTW.scala#L27) |
| V216 `asid_bits` | ASID位数 | P 源码具名 | 16 | 上下文隔离，不随active kernel数重复展开 | [ventus/src/mmu/PTW.scala:20](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/PTW.scala#L20) |
| V217 `l1_tlb_entries` | 每I/D L1 TLB ways | P 源码具名 | 8 | top实际实例传入；不要用unused trait nWays重复计数 | [ventus/src/top/parameters.scala:134](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L134) |
| V218 `l1_tlb_service` | L1 TLB lookup/miss等待规则 | C 待校准时序 | L1TLB FSM | 仅MMU路径；命中延迟待边界核对 | [ventus/src/mmu/L1TLB.scala:121](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/L1TLB.scala#L121) |
| V219 `l2_tlb_sets` | 共享L2 TLB set数 | P 源码具名 | 16合计 | 跨bank总数 | [ventus/src/mmu/L2TLB.scala:10](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/L2TLB.scala#L10) |
| V220 `l2_tlb_ways` | L2 TLB ways | P 源码具名 | 4 | 翻译冲突 | [ventus/src/mmu/L2TLB.scala:11](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/L2TLB.scala#L11) |
| V221 `l2_tlb_banks` | L2 TLB bank数 | P 源码具名 | 2 | translation并行 | [ventus/src/mmu/L2TLB.scala:13](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/L2TLB.scala#L13) |
| V222 `l2_tlb_sectors` | 每L2 TLB项sector数 | P 源码具名 | L2 line words=32 | 绑定cacheline；可覆盖相邻VPN | [ventus/src/mmu/L2TLB.scala:12](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/L2TLB.scala#L12) |
| V223 `l2_tlb_service` | L2 TLB miss/walk/refill服务 | C 待校准时序 | bank内FSM和sector fill | 精确延迟/并发需校准 | [ventus/src/mmu/L2TLB.scala:216](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/L2TLB.scala#L216) |
| V224 `ptw_parallelism` | 页表遍历器并行度 | P 源码具名 | 按TLB banks实例 | 每bank一条walk状态；与nBanks绑定 | [ventus/src/mmu/PTW.scala:159](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/PTW.scala#L159) |
| V225 `ptw_memory_sharing` | PTW与普通L2请求仲裁 | H 固定结构/策略 | 固定优先级 | page miss抢占实际内存服务 | [ventus/src/top/GPGPU_top.scala:272](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L272) |
| V226 `asid_lookup_entries` | ASID到PTBR表项 | H 固定结构/策略 | 8 | top中硬编码 | [ventus/src/top/GPGPU_top.scala:226](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L226) |
| V227 `asid_invalidation` | ASID替换及失效范围 | H 固定结构/策略 | fill更新时传播flush_tlb | 多kernel迁移和TLB冷状态 | [ventus/src/mmu/AsidLookup.scala:17](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/mmu/AsidLookup.scala#L17) |

## 可选 AXI

### 可选 AXI 包装（7行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V228 `axi_data_bits` | AXI data位宽 | P 源码具名 | 64 | 硬件包装，默认cached Verilator走另一接口 | [ventus/src/top/GPGPU_top.scala:117](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_top.scala#L117) |
| V229 `axi_read_line_buffer` | AXI读返回暂存容量 | H 固定结构/策略 | 1个line | 允许的完成缓冲，不能据此声称只有1个已发读地址 | [ventus/src/axi/AXI4Adapter.scala:55](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/axi/AXI4Adapter.scala#L55) |
| V230 `axi_write_line_buffer` | AXI写数据暂存容量 | H 固定结构/策略 | 1个line | burst序列化 | [ventus/src/axi/AXI4Adapter.scala:59](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/axi/AXI4Adapter.scala#L59) |
| V231 `axi_burst_mode` | AXI突发模式与长度 | H 固定结构/策略 | INCR；line/beat-1 | 长度为派生量；改变line和beat需验证adapter | [ventus/src/axi/AXI4Adapter.scala:71](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/axi/AXI4Adapter.scala#L71) |
| V232 `axi_read_write_admission` | AXI读写请求准入耦合 | H 固定结构/策略 | AR/AW ready和buffer忙共同门控 | 不能把读写当两个完全独立满速通道 | [ventus/src/axi/AXI4Adapter.scala:173](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/axi/AXI4Adapter.scala#L173) |
| V233 `axi_response_priority` | AXI B/R返回选择 | H 固定结构/策略 | B优先于读line完成 | 下游ready协议需检查 | [ventus/src/axi/AXI4Adapter.scala:167](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/axi/AXI4Adapter.scala#L167) |
| V234 `axi_max_outstanding` | AXI允许的在途与ID匹配约束 | C 待校准时序 | 单读拼包缓冲，地址接收需另外审计 | 当前单读拼包结构的合法traffic与吞吐需验证 | [ventus/src/axi/AXI4Adapter.scala:57](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/axi/AXI4Adapter.scala#L57) |

## 仿真边界/外部系统

### 仿真边界与外存（15行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V235 `wrapper_request_stages` | RTLsim请求wrapper流水级 | H 固定结构/策略 | 2 | 必须注明比较周期是否包含wrapper | [ventus/src/top/GPGPU_SimWrapper.scala:101](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_SimWrapper.scala#L101) |
| V236 `wrapper_response_stages` | RTLsim响应wrapper流水级 | H 固定结构/策略 | 2 | RTLSim测试边界，不是GPU核心结构 | [ventus/src/top/GPGPU_SimWrapper.scala:102](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/GPGPU_SimWrapper.scala#L102) |
| V237 `sim_ddr_delay` | 当前RTLSim伪DDR延迟设置 | P 源码具名 | DELAY_DDR=2 | 是wrapper delay设置，不含完整DRAM时序 | [ventus/src/top/Mem_SimWrapper.scala:22](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V238 `sim_lds_delay` | MemSim LDS地址区delay设置 | P 源码具名 | DELAY_LDS=0 | shared通常走片上专用路径；只描述该wrapper规则 | [ventus/src/top/Mem_SimWrapper.scala:22](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V239 `sim_response_entries` | MemSim外存响应槽数 | H 固定结构/策略 | 5 | 有限在途credit | [ventus/src/top/Mem_SimWrapper.scala:24](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L24) |
| V240 `sim_response_selection` | MemSim已到期响应仲裁 | H 固定结构/策略 | 低槽位优先 | 延迟到期及slot占用影响返回 | [ventus/src/top/Mem_SimWrapper.scala:73](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L73) |
| V241 `core_clock_hz` | 核心实际频率 | E 外部参数族 | 未提供物理校准值 | 周期转秒必需；不能从RTL常数直接得到 | [ventus/src/top/Mem_SimWrapper.scala:22](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V242 `memory_channels` | DRAM channel及子通道数 | E 外部参数族 | 当前RTLsim未建模 | 需要目标板/DRAM模型证据；不能由L2 slice数推出 | [ventus/src/top/Mem_SimWrapper.scala:22](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V243 `dram_bank_geometry` | DRAM rank/bank/row组织 | E 外部参数族 | 未提取 | 若用DRAM状态模型需拆为多个字段 | [ventus/src/top/Mem_SimWrapper.scala:22](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V244 `memory_address_mapping` | DRAM地址映射规则 | E 外部参数族 | 未提取 | 影响row locality与bank冲突 | [ventus/src/top/Mem_SimWrapper.scala:22](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V245 `dram_command_timing` | DRAM时序参数族 | E 外部参数族 | tRCD/tRP/tRAS/tCCD/tRRD/tFAW/tRFC等未提取 | 族字段需按所选DDR规格展开，暂不声称一个独立变量 | [ventus/src/top/Mem_SimWrapper.scala:22](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V246 `memory_bus_service` | 实际内存bus宽度速率 | E 外部参数族 | 未校准 | 带宽和burst传输周期 | [ventus/src/top/Mem_SimWrapper.scala:22](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V247 `memory_controller_policy` | 内存控制器排队和仲裁策略族 | E 外部参数族 | 未提取 | 读写队列、row policy、读写切换需进一步展开 | [ventus/src/top/Mem_SimWrapper.scala:22](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V248 `refresh_policy` | DRAM刷新规则 | E 外部参数族 | 当前RTLsim无模型 | 长kernel下可能改变尾延迟 | [ventus/src/top/Mem_SimWrapper.scala:22](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/Mem_SimWrapper.scala#L22) |
| V249 `host_launch_completion` | host启动和完成固定开销 | E 外部参数族 | 未测量 | 定义kernel设备周期/端到端时间时分开计费 | [sim-verilator/kernel.hpp:17](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/sim-verilator/kernel.hpp#L17) |

## 软件共同设计

### 软件输入与共同设计（12行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V250 `wg_grid_shape` | workgroup grid形状 | W 软件输入族 | kernel_size[3] | 三轴值来自程序；不计硬件自由度 | [sim-verilator/kernel.hpp:38](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/sim-verilator/kernel.hpp#L38) |
| V251 `threads_per_warp_active` | 逻辑warp活动线程数 | W 软件输入族 | wf_size | 尾warp掩码 | [sim-verilator/kernel.hpp:41](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/sim-verilator/kernel.hpp#L41) |
| V252 `warps_per_workgroup` | 每workgroup warp数 | W 软件输入族 | wg_size | block软件选择与occupancy约束 | [sim-verilator/kernel.hpp:40](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/sim-verilator/kernel.hpp#L40) |
| V253 `kernel_vgpr_usage` | 每warp VGPR用量 | W 软件输入族 | vgprUsage | 决定资源驻留与spill tradeoff | [sim-verilator/kernel.hpp:46](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/sim-verilator/kernel.hpp#L46) |
| V254 `kernel_sgpr_usage` | 每warp SGPR用量 | W 软件输入族 | sgprUsage | block分配用总量 | [sim-verilator/kernel.hpp:45](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/sim-verilator/kernel.hpp#L45) |
| V255 `kernel_lds_usage` | 每WG LDS用量 | W 软件输入族 | ldsSize | shared tiling与驻留耦合 | [sim-verilator/kernel.hpp:42](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/sim-verilator/kernel.hpp#L42) |
| V256 `kernel_private_usage` | 每thread private用量 | W 软件输入族 | pdsSize | private/swizzle访存与spill | [sim-verilator/kernel.hpp:51](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/sim-verilator/kernel.hpp#L51) |
| V257 `instruction_trace` | 指令序列及寄存器读写依赖 | W 软件输入族 | 编译产物/动态执行 | 仅opcode频率不足，依赖链必须来自程序 | [ventus/src/pipeline/pipe.scala:57](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/pipe.scala#L57) |
| V258 `lane_address_trace` | 各lane实际地址与访问掩码 | W 软件输入族 | 动态输入 | cache、coalescing、bank conflict可由此计算 | [ventus/src/pipeline/LSU.scala:173](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/LSU.scala#L173) |
| V259 `branch_mask_trace` | 分支结果及活动lane掩码 | W 软件输入族 | 动态输入 | 路径顺序和SFU服务取决于掩码 | [ventus/src/pipeline/branch_join.scala:143](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/branch_join.scala#L143) |
| V260 `matrix_tile_layout` | GEMM分块及fragment布局 | W 软件输入族 | 软件选择 | 供数流量、RF占用、TC利用率 | [dependencies/fpuv2/src/main/scala/Tensor.scala:215](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L215) |
| V261 `barrier_placement` | 同步指令位置 | W 软件输入族 | 软件选择 | 消除或增加barrier改变依赖和停顿 | [ventus/src/pipeline/warp_schedule.scala:136](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/pipeline/warp_schedule.scala#L136) |

## 派生与排除

### 派生量与非维度（17行）

| ID / key | 字段 | 类型 | 源码基线 / 规则 | 性能影响与耦合 | 证据 |
|---|---|---|---|---|---|
| V262 `sm_per_cluster` | 每cluster SM数 | D 派生 | num_sm/num_cluster=2 | 无需独立设计变量 | [ventus/src/top/parameters.scala:29](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L29) |
| V263 `vgpr_bytes` | 每SM VGPR容量 | D 派生 | 1024*32*4=131072 B | 向量槽乘warp宽度；勿当作1024个32bit总计 | [ventus/src/top/parameters.scala:20](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L20) |
| V264 `sgpr_bytes` | 每SM SGPR容量 | D 派生 | 2048*4=8192 B | 容量和slot不重复计数 | [ventus/src/top/parameters.scala:21](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L21) |
| V265 `lds_bytes` | 每SM LDS容量 | D 派生 | 1024*32*4=131072 B | 来自行数和行宽；不重复计独立轴 | [ventus/src/top/parameters.scala:97](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L97) |
| V266 `icache_bytes` | 每SM ICache容量 | D 派生 | 256*2*128=65536 B | 来自sets/ways/line | [ventus/src/L1Cache/ICache/ICacheParameters.scala:21](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L1Cache/ICache/ICacheParameters.scala#L21) |
| V267 `cache_bytes` | 每SM DCache容量 | D 派生 | 256*2*128=65536 B | 来自sets/ways/line | [ventus/src/top/parameters.scala:71](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L71) |
| V268 `l2_bytes` | 每L2 slice容量 | D 派生 | 64*16*128=131072 B | 来自sets/ways/line；total还乘slice数 | [ventus/src/top/parameters.scala:99](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L99) |
| V269 `tc_parallel_multipliers` | TC乘法节点数量 | D 派生 | 4*8*4=128 | 输出16个dot，每dot8个乘法；来自矩阵轴 | [dependencies/fpuv2/src/main/scala/Tensor.scala:203](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L203) |
| V270 `tc_dot_pipeline` | TC点积内部流水理论深度 | D 派生 | 2+2*log2(8)+2=10 | 还未包含dot输出FIFO和wrapper FIFO，不作整条指令delay | [dependencies/fpuv2/src/main/scala/Tensor.scala:161](https://github.com/liuxd17thu/fpuv2/blob/7ea30df00f9353f2e8645b32665b13f9b3f69e6d/src/main/scala/Tensor.scala#L161) |
| V271 `nominal_issue_parameter` | 顶层num_issue | X 排除 | 1 | 当前pipe用Issue各一，num_issue只在未接入IssueV2使用 | [ventus/src/top/parameters.scala:43](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L43) |
| V272 `legacy_ibuffer_parameter` | 顶层num_ibuffer | X 排除 | 2 | 当前用InstrBufferV2/size_ibuffer；legacy instbuffer未接入 | [ventus/src/top/parameters.scala:63](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L63) |
| V273 `legacy_icache_buffer_parameter` | 顶层num_icachebuf | X 排除 | 1 | 未见当前核心实例消耗 | [ventus/src/top/parameters.scala:59](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L59) |
| V274 `l2_port_factor` | L2 portFactor | X 排除 | 2 | 当前BankedStore未用其生成端口；不可当实际吞吐控制旋钮 | [ventus/src/top/parameters.scala:109](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L109) |
| V275 `l2_replacement_string` | L2 replacement字符串 | X 排除 | plru | actual Directory_test用LFSR；名义参数无实际policy效果 | [ventus/src/L2cache/Parameters.scala:32](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L32) |
| V276 `l2_outer_buffer_template` | L2 outerBuf全通道模板 | X 排除 | full | 本lite实现未按完整A/B/C/D/E通道消费，禁止展开15个自由度 | [ventus/src/L2cache/Parameters.scala:126](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/L2cache/Parameters.scala#L126) |
| V277 `isa_data_width` | ISA数据/指令/地址基本位宽 | X 排除 | 当前RV32/FP32/32bit指令 | 固定ISA契约下冻结；不拆多个宽度凑维度 | [ventus/src/top/parameters.scala:47](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L47) |
| V278 `logging_debug_flags` | debug、GVM、计数输出 | X 排除 | 源码配置 | 影响仿真开销/实现形式但非设备架构性能自由度 | [ventus/src/top/parameters.scala:11](https://github.com/THU-DSP-LAB/ventus-gpgpu/blob/681172541a8a34ffb43c483a19c075acbc11a4eb/ventus/src/top/parameters.scala#L11) |
