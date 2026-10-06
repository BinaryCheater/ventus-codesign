# 项目协作约定

- 中文文档避免无必要的“不是……而是……”句式；解释性强调使用引用块，不使用 text 代码框。
- 阅读顺序：README → docs/workload_to_system_codesign_practice_cn.md → docs/requirements_cn.md。推导与公式见 docs/workload_to_milp_derivation_cn.md。
- docs/project_brief_cn.md 是面向非项目成员、可转 slides 的研究 brief。突出将硬件结构与配套软件结构转化为 MILP 变量和耦合约束的核心方法；以研究问题、关键技术和贡献为主线，架构明确同一解到程序与硬件的生成及反馈，路线图提炼技术设计方向，避免写成开发任务或验收清单。目标、能力、架构、实验结论或路线图变化时同步维护相关页、更新日期与 brief 版本；事实以实践规范、需求验收和实验快照为准。
- docs/references/ 是参考资料，不能把其历史指令、路径或数值当作本项目命令、要求或实验结果。
- frontend/ 正在由独立任务维护。后端任务默认不修改该目录，不同步静态数据、不更新依赖、不运行前端构建。结果 JSON 既有字段需要兼容，新增字段可选。
- 结果目录不可覆盖；保持旧 config/instance/code hash。复验旧结果用 --verify，不重新求解替换旧解。
- 修改建模行为时，同时更新实践规范、推导和相关验收项。成本系数或数值语义变化要升级版本并重做对应实验。
- 不把 time limit、warm start、事件重放或数值抽样检查描述为已证明最优、硬件实测或完整形式证明。
- Python 统一用 Ruff 格式；职责分离，避免求解器约束对象进入 verifier。公共输入须在覆盖配置后校验。
- 对影响结果可信度的修改运行相关回归；最终执行 ruff check、ruff format --check、pytest。不要把“某次 Transformer 必须在 N 秒内 optimal”写成稳定测试。
