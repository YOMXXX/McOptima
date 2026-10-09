# workbuddy.md - WorkBuddy 开发上下文记录

> 本文件记录 McOptima 项目使用腾讯 WorkBuddy 智能体开发的过程上下文，用于「2026 麦当劳程序员创意开发大赛」WorkBuddy 专项奖励核验（规则要求：真实使用 WorkBuddy 开发 + 提交本文件）。

## 项目信息

- **项目**: McOptima（麦门最优解引擎）
- **开发时间**: 2026-10-09 19:44 起（大赛 Day 1）
- **开发工具**: 腾讯 WorkBuddy（Agent 模式，全程人机协作）
- **MCP**: 麦当劳中国官方 MCP Server（https://mcp.mcd.cn，35 tools）

## 开发过程时间线

### Phase 0：情报与接入（10-09 19:44 - 21:30）

1. **赛事调研**：WorkBuddy 抓取了微信推文 + GitHub 官方仓库（M-China/mcd-developer-innovation-challenge）+ 活动规则全文 + 麦当劳 MCP 仓库 README + Day1 排行榜，产出《McOptima整体作战方案.md》（排名规则=Star数、必交文件清单、16天执行计划、传播策略）。
2. **MCP 接入**：用户提供 MCP Token 后，WorkBuddy 完成：
   - `~/.workbuddy/mcp.json` 写入 mcd-mcp server 配置（Streamable HTTP + Bearer Token）
   - Token 存入 `~/.zshenv` 环境变量 `MCD_MCP_TOKEN`
   - curl 直连验证 initialize/tools-list 全通

### Phase 1：核心开发（10-09 21:36 - 22:00）

3. **数据链路打通**（WorkBuddy 执行的关键调试，含失败重试）：
   - `tools/list` 发现 35 个工具（比官方 README 多出 `query-promotions`）
   - `query-meal-detail` 参数踩坑：第一次用 `mealCode` 报 400「code不得为空白」，读 schema 后改为 `code` ✅
   - `calculate-price` 踩坑：items 字段是 `productCode` 不是 `code`；价格单位是**分** ✅
   - 营养数据 158 项行式 CSV 解析；菜单 111 餐品 / 14 分类
4. **求解器开发与 4 个真 bug 修复**（全部有失败→诊断→修复过程）：
   - **Bug 1**：0/1 背包「原地更新+指针回溯」会重复拾取同一物品（6 个圆筒冰淇淋案例）→ 重写为逐层 choice 表回溯
   - **Bug 2**：热量粒度 `int(kcal/10)` 向下取整导致解超热量上限（811>800）→ 改 `ceil` 保守取整 + 精确值二次校验安全网
   - **Bug 3**：三维 DP（蛋白维）初始表 p>0 层应为 -inf 却初始化为 0，导致蛋白约束失效（24g<25g）→ 修复初始化
   - **Bug 4**：测试用例本身边界错误（预算 ¥5 时圆筒 ¥5 可买，有解）→ 修正测试
5. **端到端验证**：
   - 8 个单元测试全过（tests/test_solver.py）
   - 真实数据三场景验证（人民广场店 1450713）：预算吃爽/增肌/控卡
   - **官方验价闭环**：本地求解总价 ¥25.9 vs calculate-price 官方 ¥25.90，偏差 0.00

### Phase 1.5：全功能补完（10-09 22:02 - 22:30）

6. **CLI 工具**（cli.py）：五模式（feast/muscle/light/night/sub）+ 城市地标自动解析门店 + 券积分报告附加
7. **平替换算器**（substitute.py）：巨无霸 → 脆汁鸡+玉米杯，省 132kcal
8. **券与积分规划**（coupon_planner.py）：门店券解析 + 积分保值建议 + 抽奖期望值算法
9. **分享卡生成器**（card_generator.py）：零依赖 SVG 对比卡（1080×1350 竖版，红黑配色，省¥47/少236kcal 徽章）
10. **GitHub Pages 演示页**（demo/）：JS 版同算法求解器（Node 验证 45ms 出解，与 Python 结果一致）+ 脱敏数据集（86 餐品）
11. **工程化**：MIT LICENSE + CI workflow（pytest + 必交文件检查 + Token 泄露守卫）+ README 双语

## 使用的 WorkBuddy 能力

- Agent 模式文件读写（项目全部代码由 WorkBuddy 编写）
- Bash 工具执行 curl/Python/git 调试（含 MCP 协议级调试）
- WebFetch/WebSearch 赛事情报调研
- 任务管理工具跟踪 16 项任务
- 与用户多轮交互确认 Token、方案、执行节奏

## 数据与安全声明

- MCP Token 仅存于环境变量与 WorkBuddy 本地配置，**未出现在任何项目文件**（已用 grep 全量自检）
- demo/menu_data.json 为脱敏聚合数据（餐品名/价格/营养，无用户个人信息）
- 交易类工具（create-order 等）在本项目 Skill 中有双确认安全设计，开发过程中未实际下单
