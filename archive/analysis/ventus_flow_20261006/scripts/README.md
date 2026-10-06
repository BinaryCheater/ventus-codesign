# ${REMOTE_HOST} 复验入口

脚本针对已盘点的`${REMOTE_USER}@${REMOTE_HOST}`工具路径，复用旧RTL构建。新机器需先移植环境脚本和基线路径。复验使用新的`VENTUS_FLOW_ROOT`；默认目录已有结果，prepare会拒绝覆盖。

在项目根目录执行，以下例子采用新的`${REMOTE_STORAGE_ROOT}/ventus-flow-recheck-20261006`：

```bash
ssh ${REMOTE_HOST} 'VENTUS_FLOW_ROOT=${REMOTE_STORAGE_ROOT}/ventus-flow-recheck-20261006 bash -s' < analysis/ventus_flow_20261006/scripts/remote_prepare.sh
scp analysis/ventus_flow_20261006/scripts/inspect_anchor.py analysis/ventus_flow_20261006/evidence/cyclesim-test-driver.patch ${REMOTE_HOST}:${REMOTE_STORAGE_ROOT}/ventus-flow-recheck-20261006/
ssh ${REMOTE_HOST} 'VENTUS_FLOW_ROOT=${REMOTE_STORAGE_ROOT}/ventus-flow-recheck-20261006 bash -s' < analysis/ventus_flow_20261006/scripts/remote_anchor.sh
ssh ${REMOTE_HOST} 'VENTUS_FLOW_ROOT=${REMOTE_STORAGE_ROOT}/ventus-flow-recheck-20261006 bash -s' < analysis/ventus_flow_20261006/scripts/remote_build_cyclesim.sh
ssh ${REMOTE_HOST} 'VENTUS_FLOW_ROOT=${REMOTE_STORAGE_ROOT}/ventus-flow-recheck-20261006 bash -s' < analysis/ventus_flow_20261006/scripts/remote_run_cyclesim.sh
ssh ${REMOTE_HOST} 'VENTUS_FLOW_ROOT=${REMOTE_STORAGE_ROOT}/ventus-flow-recheck-20261006 VENTUS_TIMING_DDR=0 VENTUS_CYCLESIM_CASE_DIR=${REMOTE_STORAGE_ROOT}/ventus-flow-recheck-20261006/evidence/cyclesim-vecadd-ddr-off bash -s' < analysis/ventus_flow_20261006/scripts/remote_run_cyclesim.sh
ssh ${REMOTE_HOST} 'VENTUS_FLOW_ROOT=${REMOTE_STORAGE_ROOT}/ventus-flow-recheck-20261006 bash -s' < analysis/ventus_flow_20261006/scripts/remote_synthesis.sh
```

build脚本构建用户目录依赖，固定系统fmt9和已有spdlog1.12；`ccache`名称对应显式的透传wrapper，不提供编译缓存。周期模型的测试driver补丁只增加输出验证和外存时序开关。

Mac局部RTL复验：

```bash
verilator --cc --exe --build -j 4 --top-module ScalarALU --Mdir /tmp/ventus-alu-native-recheck-20261006 analysis/ventus_flow_20261006/evidence/ScalarALU.v "$PWD/analysis/ventus_flow_20261006/scripts/alu_native.cpp"
/tmp/ventus-alu-native-recheck-20261006/VScalarALU
```

本轮成功产物在主文档及`evidence/`中。批次中的除零、180秒超时、首次Liberty合并缺表模板、等价检查脚本先删除gold模块、yaml头文件路径和fmt冲突的失败日志保留在服务器原目录；各次修正未覆盖旧日志。修正后的复验命令已写入以上脚本，尚未从全新目录再次重建全部依赖。
