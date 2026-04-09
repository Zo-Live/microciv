# MicroCiv Phase 1 History

本文档整理阶段一从规则冻结到最小可用产品完成的实际实现记录。

## 前置准备

在正式进入 `project.md` 第 17 节前，先完成了以下基础工作：

1. 把阶段一的冻结规格补进 `project.md`，量化了默认参数、地图生成阈值、资源归属、河流修路成本、Records 口径和 Baseline AI 策略。
2. 把确认后的项目结构写进 `README.md`。
3. 补齐工程配置：
   - `pyproject.toml`
   - `.gitignore`
   - `main.py`
4. 创建目录骨架：
   - `src/microciv/game`
   - `src/microciv/ai`
   - `src/microciv/tui`
   - `src/microciv/records`
   - `src/microciv/utils`
   - `tests`
5. 确认项目测试环境使用 `./.venv/bin/python`。

## 17.2 第一阶段：固定领域模型与常量

完成内容：

1. 在 `src/microciv/constants.py` 中集中冻结阶段一常量和静态表。
2. 在 `src/microciv/game/enums.py` 中补齐核心枚举。
3. 在 `src/microciv/game/models.py` 中实现：
   - `GameConfig`
   - `GameState`
   - `ResourcePool`
   - `BuildingCounts`
   - `City`
   - `Road`
   - `Network`
   - `Stats`
4. 在 `src/microciv/utils/hexgrid.py` 中实现六边形坐标工具：
   - 合法格判断
   - 距离
   - 邻接
   - 稳定排序
   - 地图坐标枚举

阶段结果：

1. 领域层的基础数值、枚举和数据结构固定下来。
2. 后续地图生成、结算、AI、Records 都有了统一底座。

验证结果：

1. 新增 `tests/test_hexgrid.py`
2. 新增 `tests/test_models.py`
3. 连同 smoke test 共 `16 passed`

## 17.3 第二阶段：地图生成与复现

完成内容：

1. 在 `src/microciv/game/mapgen.py` 中实现 `MapGenerator` 和 `GeneratedMap`。
2. 生成流程覆盖：
   - 区域种子选择
   - 多源 BFS 分区
   - 主地形分配
   - 次级斑块
   - 地形平滑
   - 河流生成
   - 河邻荒地修补
   - 平原保底
   - 质量检查与一次局部修补
3. 河流搜索改成 A* 风格路径搜索，避免 Hard 地图卡死。

阶段结果：

1. 同 seed、同配置可复现相同初始地图。
2. `Normal` / `Hard` 的地形和河流分布已经按冻结规格分化。

验证结果：

1. 新增 `tests/test_mapgen.py`
2. 总测试数达到 `20 passed`

## 17.4 第三阶段：网络、资源归属与结算核心

完成内容：

1. 在 `src/microciv/game/networks.py` 中实现：
   - 城市网络重算
   - 并网
   - passable 坐标到网络的映射
2. 在 `src/microciv/game/resources.py` 中实现：
   - 资源格归属重算
   - 河流双资源拆分归属
   - 网络级缺粮停工快照
   - 地形产出
   - 建筑产出
   - 食物消耗
   - 覆盖收益
   - 河上修路额外扣费
3. 在 `src/microciv/game/scoring.py` 中实现即时评分。
4. 把 `tech_count` 明确为“全图去重后的已解锁科技数”，并同步写回 `project.md`。

阶段结果：

1. 资源归属、网络共享、停工逻辑和评分口径闭合。
2. 河流相关特殊规则已经接入逻辑层。

验证结果：

1. 新增 `tests/test_networks.py`
2. 新增 `tests/test_resources.py`
3. 新增 `tests/test_scoring.py`
4. 总测试数达到 `28 passed`

## 17.5 第四阶段：动作系统与游戏引擎

完成内容：

1. 在 `src/microciv/game/actions.py` 中实现五类动作：
   - `build_city`
   - `build_road`
   - `build_building`
   - `research_tech`
   - `skip`
2. 实现动作合法性校验，包括：
   - 地形与占用检查
   - 道路连通检查
   - 河上修路资源检查
   - 建筑科技前置
   - 建筑数量上限
   - 科技已研究/科技点不足检查
3. 在 `src/microciv/game/engine.py` 中实现完整流程：
   - 执行动作
   - 并网
   - 重算资源归属
   - 结算资源
   - 刷新分数
   - 推进回合或进入终局
4. 接入阶段一即时生效规则：
   - 新城当回合参与产出
   - 新路当回合连通网络
   - 新建筑当回合产出
   - 新科技只解锁权限，不直接给资源

阶段结果：

1. 失败动作不会推进回合。
2. 第 `T` 回合成功结算后直接终局，不出现 `T+1`。

验证结果：

1. 新增 `tests/test_engine.py`
2. 对齐冻结规格后总测试数达到 `35 passed`

## 17.6 第五阶段：Records 与导出

完成内容：

1. 在 `src/microciv/records/models.py` 中定义：
   - 完整 `RecordEntry`
   - `RecordDatabase`
   - 终局地图快照
   - 城市快照
   - 道路快照
   - 网络快照
   - 固定 CSV 字段顺序
2. 在 `src/microciv/records/store.py` 中实现：
   - `data/records.json` 读写
   - 终局校验
   - FIFO 裁剪
   - 原子写入
3. 在 `src/microciv/records/export.py` 中实现：
   - CSV 导出
   - 固定文件名格式 `records-YYYYMMDD-HHMMSS.csv`
4. 在 `src/microciv/records/__init__.py` 中整理对外导出。

阶段结果：

1. 完整终局记录可本地持久化。
2. Records 页和后续终局查看所需的数据结构已经具备。

验证结果：

1. 新增 `tests/test_records.py`
2. 总测试数达到 `39 passed`

## 17.7 第六阶段：Baseline 与 Random Policy

完成内容：

1. 在 `src/microciv/game/actions.py` 中补了稳定顺序的 `list_legal_actions(...)`。
2. 在 `src/microciv/ai/policy.py` 中实现：
   - 合法动作获取
   - 深拷贝单步模拟
3. 在 `src/microciv/ai/random_policy.py` 中实现带 seed 的随机策略。
4. 在 `src/microciv/ai/baseline.py` 中实现阶段一 Baseline：
   - 粮食危险网络判定
   - 危险连网修路优先
   - 建城评分
   - 科技优先级
   - 建筑缺口优先级
   - 固定 tie-break

阶段结果：

1. Baseline 在任意合法状态都能返回合法动作。
2. Baseline 在固定 seed 集上打赢 Random 策略。

验证结果：

1. 新增 `tests/test_ai.py`
2. 完整对局对比覆盖固定 `30` 个 seed
3. 总测试数达到 `43 passed`

## 17.8 第七阶段：最小可用 TUI

完成内容：

1. 在 `src/microciv/tui/app.py` 中搭建 Textual 应用壳。
2. 实现最小页面流程：
   - 主菜单 `menu.py`
   - 地图设置 `setup.py`
   - 游戏主界面 `game.py`
   - 终局界面 `final.py`
   - Records 页面 `records.py`
3. 实现地图控件与基础展示：
   - `widgets/map_grid.py`
   - `presenters/game_session.py`
   - `presenters/status.py`
   - `renderers/map.py`
4. 接入：
   - Play 模式
   - Autoplay Baseline `Normal`
   - Autoplay Baseline `Speed`
   - 终局自动写 Records
   - Records 浏览与导出
5. 更新 `README.md`，把仓库状态从“启动前”改成“已完成阶段一核心实现”。

阶段结果：

1. 已可从主菜单跑到终局并返回。
2. Play 与 Autoplay 都能完整跑通。
3. Records 可查看、可导出。

验证结果：

1. 新增 `tests/test_tui.py`
2. 总测试数达到 `46 passed`

## 17.9 第八阶段：视觉增强与收尾

完成内容：

1. 在 `src/microciv/tui/renderers/logo.py` 和 `src/microciv/tui/widgets/logo.py` 中实现稳定的 ASCII LOGO。
2. 把 LOGO 和统一视觉风格接到：
   - 主菜单
   - 设置页
   - 终局页
   - Records 页
3. 在 `src/microciv/tui/app.py` 中统一应用级配色和按钮样式。
4. 优化：
   - 地图格颜色和选中态
   - 右侧状态面板提示文案
   - 页面标题与卡片边框
5. 在 `GameScreen` 中对 Autoplay 关闭手动操作按钮，只保留状态浏览和返回。
6. 修正视觉增强后带来的布局问题，保证 headless 测试下页面仍稳定可点。

阶段结果：

1. 页面外观明显强化，但未改变逻辑层行为。
2. 终端尺寸较小的情况下仍可完成主流程测试。

验证结果：

1. 新增 `tests/test_logo.py`
2. 全量测试达到 `47 passed`

## 当前状态

截至 17.9：

1. 阶段一逻辑层、地图生成、结算、AI、Records、最小 TUI、视觉增强均已完成。
2. 当前版本可直接启动并手动测试。
3. 全量测试通过：`47 passed`
