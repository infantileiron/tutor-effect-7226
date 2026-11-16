# 课程辅导效果检验 · Tutor Effect

知行职教教研组用真实的两组成绩评估晚间小组辅导效果，贯通成绩复核、辅导方案、后台统计检验、结论签核和结果导出。

## 业务场景
知行职教有城东、城西、滨江、高新 4 个教学点。原流程由教学点导出成绩表，分析员复制进工作簿计算，再将截图发给负责人。三类痛点是：排除缺考时容易丢失口径、方案与结果脱节、签核结论没有当时的样本证据。上游是教学点期末成绩；本应用替代手工核对与计算；下游由教研负责人决定是否扩大辅导试点。

四个业务模块：**成绩样本**支持筛选、录入和修订；**辅导分组**登记研究范围和排除规则；**检验工作台**提交后台任务并查看失败原因与历史结果；**教研结论**起草解释、负责人签核并下载包括原始样本快照的 JSON 报告。业务数据均在 PostgreSQL 中持久化，统计由 Python worker 计算。

另有**随机试验**模块：把名单与随机依据在抽签前封存，按教学点分层随机分组，满足整批辅导名额且层内两组人数差尽量小；揭晓前隐藏分组，揭晓后公开种子、任何人可独立复算，且没有重抽入口。成绩修订与转组不影响封存分组：检验按封存分组聚合原名单内学员的当前成绩，分别统计转组、缺考、失访，缺失成绩按 0–100 分插补给出组均差上下界，完整样本差另列。

## 启动
```sh
cp .env.example .env
docker compose up -d --build
# 可选：手动幂等 seed
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18202 。API http://localhost:19202/docs 。数据库端口 17702。停止并清空演示数据：`docker compose down -v --remove-orphans`。Compose 顶层 name 保证中文父目录也能运行。

|角色|账号|密码|权限|
|---|---|---|---|
|教研负责人 admin|admin@demo.local|Demo123!|全部编辑、统计、结论签核发布、审计|
|教研分析员 analyst|analyst@demo.local|Demo123!|成绩/方案编辑、检验、未签核结论起草；不能签核或改已签核结论|
|教学点观察员 viewer|viewer@demo.local|Demo123!|只读台账、方案、报告及导出；不能发起计算|

JWT 有效期 8 小时；角色由服务器读取数据库，不信任客户端显示。密码使用随机盐 PBKDF2-SHA256 180000 次，登录不保存明文密码。

## 一天的工作剧本
1. 08:50 观察员打开 `ZX-2026-001` 学员记录，核对缺考标记。
2. 09:00 分析员查看 160 名学员，按城东教学点筛选。
3. 09:10 录入 `ZX-2026-161`，学员161，城东，小组辅导组，82.5 分。
4. 09:20 将缺考学员标记为缺考并清空成绩，避免把零分当缺失。
5. 09:30 新建 `2026秋季 · 城东晚间辅导` 方案，选城东并排除缺考。
6. 09:40 提交后台检验；界面自动更新排队、完成或失败状态。
7. 10:00 查看两组均分、95% 区间、p 值、Cohen d 和排除数，起草后续随机试验建议。
8. 10:10 负责人签核结论；分析员不能修改已签核报告。
9. 10:20 观察员下载 `tutor-effect-report-<id>.json`，复核当时样本快照和 SHA-256。
10. 10:30 分析员在「随机试验」勾选 160 名学员、设定整批辅导名额 80，封存名单并抽签；页面显示承诺哈希与分层名额表，分组仍保密。
11. 10:40 负责人确认后揭晓：种子公开，分层分组可独立复算；之后学员转组、缺考、退学（删除记为失访）都按封存分组统计。

## 算法与口径
输入是方案教学点内两组 0–100 分成绩。空成绩永远排除；开启排除缺考时再排除 absent=true 的成绩。显示总选中数和排除数。有效样本每组至少 2 条；两组方差都为零时任务失败且保留可读原因。

以干预组减对照组定义 Δ。Welch t = Δ / sqrt(s1²/n1+s0²/n0)，自由度使用 Welch-Satterthwaite 公式；双侧 p 值和 95% 区间通过 SciPy t 分布计算。Cohen d 使用两组自由度加权 pooled 标准差，描述效应大小，与 Welch 方差假设相互独立。显著性 α 固定为 0.05。观察性分组不能直接做因果断言。

seed 使用 Random(20261115)：160 名学员，4 教学点、各 80 人两组、7 条缺考记录；初始方案为 `2026秋季 · 晚间小组辅导`，初始报告为便于演示的真实计算结果。seed 以 email/code/title 自然键查重，已存在对象不更新，重跑不覆盖用户修改。报告保存计算样本快照与校验码；后续成绩修订不会改旧报告。演示批次 `2026秋季 · 随机试验批次A` 封存全部 160 人、名额 80 并已揭晓；其封存分组来自随机抽签，与现行观察性分组自然不同，差异即计为转组。

## 随机试验口径
创建批次即封存：名单快照（学号/姓名/教学点）、整批辅导名额、随机种子（`secrets.token_hex(16)`）与承诺哈希一次写入，状态为待抽签。抽签算法 `stratified-sha256-v1`：按教学点分层，每层名额先对半、再按"离对半差最小"贪心调整至整批名额恰好满足（层内两组人数差在名额约束下尽量小）；层内学员按 `sha256(seed:学号)` 十六进制升序排名，取前 t 名进辅导组。承诺哈希为算法、种子、名额与封存名单 canonical JSON 的 SHA-256。

待抽签期间接口不返回种子与分组；揭晓是 `UPDATE ... WHERE status='pending'` 的原子翻转，并发请求与重试得到同一结果，系统不提供重抽入口。揭晓后公开种子，页面与导出的 JSON 含分层名额表与分组，任何人可用 SHA-256 独立复算核对（服务端同时给出复算校验）。

批次检验为意向性（ITT）口径：按封存分组聚合原名单内学员的当前成绩。转组 = 当前分组与封存分组不同；缺考 = absent 标记；失访 = 成绩缺失且非缺考（含记录已删除）。缺失成绩（缺考+失访）按 0 与 100 分两种极端插补，给出组均差（辅导−对照）的理论上下界；只用有效成绩的完整样本差单独列出。名单变化不混入已封存批次：新学员不进名单，删除学员记为失访。

## 技术与结构
|层|技术|
|---|---|
|前端|原生 HTML/CSS/ES Modules、Nginx 1.27，无构建依赖|
|后端|Python 3.11、FastAPI 0.115.6、SQLAlchemy 2.0.36|
|统计|SciPy 1.14.1|
|数据与队列|PostgreSQL 16、Redis 7，独立 Python worker|
|认证|PyJWT 2.10.1、PBKDF2|

`frontend/src/api` 负责请求，`stores` 管业务状态，`pages` 分四页，`components/common` 复用结果、表格、状态和通知，`hooks` 封装表单/轮询，`utils` 做转义/下载。`backend/src/models` 定义表，`schemas` 验证，`services` 处理业务与算法，`routes` 提供接口，`controllers` 序列化，`middlewares` 处理审计和全局错误。`backend/migrations/001_initial.sql` 是初始结构，`002_trials.sql` 是随机试验批次表；启动使用 metadata.create_all，后续字段迁移需人工管理。

共享枚举位置：角色 ROLES、分组 GROUPS、报告状态 REPORT_STATUSES、批次状态 TRIAL_STATUSES 与抽签算法 TRIAL_ALGORITHM 在 `backend/src/constants/enums.py`；前端对应 `frontend/src/constants/enums.js` 的 ROLES、GROUPS、STATUS、TRIAL_STATUS。API输入的 group 枚举同时在 `backend/src/schemas/business.py` 校验。

## Docker 与环境变量
恰好五服务：frontend/backend/worker/db/redis，各有健康检查。backend 和 worker 依赖健康 DB/Redis，frontend 依赖 backend；worker 依赖 backend 初始化完成。数据库、Redis AOF、报告产物预留共享卷分别命名。worker 真正从 Redis 唤醒并处理数据库待执行任务，每 2 秒更新心跳。Redis 任务通知丢失仍会扫描数据库待执行任务。计算结果权威存于数据库，shared reports 卷供未来文件归档；当前 JSON 按快照直接导出。

`.env.example` 列出 COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、POSTGRES_PASSWORD、JWT_SECRET、SEED_DEMO、NETWORK_SUBNET（默认 10.253.103.0/24）。所有变量均可覆盖；默认是本地演示配置，外部部署前需更换密码和 JWT_SECRET。`.env` 已忽略。每次最多允许 10 个待执行任务，HTTP 429 提示等待。

## 本地开发
后端在 Python3.11 虚拟环境运行 `pip install -r backend/requirements.txt`，设置 DATABASE_URL、REDIS_URL、JWT_SECRET，进入 backend 后运行 `uvicorn src.main:app --reload` 和另一个终端 `python -m src.worker`。前端无打包步骤，可直接由 Nginx 提供静态文件并代理 /api/。

## 已知范围
不含 CSV 批量导入或多重比较校正；成绩可逐条录入/修订/删除。教学点为自由文本，前端方案选项来自现有成绩。初始报告为同步真实计算的演示快照，新提交报告全部走异步 worker。批次检验给出组均差与缺失上下界，不做显著性推断；显著性检验仍在观察性检验工作台。外网字体不可用时使用本地 serif 回退。进程中断在 running 状态的任务需管理员在数据库重置为 queued；当前小型版本未提供任务取消/自动回收。审计列表只给管理员，最多最近 100 条。

## 验证
`backend/scripts/verify_trials.py` 端到端验证随机试验：奇数分层名额、整批名额恰好满足、待抽签隐藏分组、并发揭晓与重试一致、独立复算分组与承诺哈希、转组/缺考/失访分别统计、缺失成绩上下界与完整样本差、名单变化不混入已封存批次。脚本自建学员与批次，可重复运行：
```sh
docker compose exec -T backend python -m scripts.verify_trials
```

License: MIT（见 LICENSE）。真实验收证据在批次根 `test-artifacts/gb-3103/`，源码目录不含截图或测试报告。
