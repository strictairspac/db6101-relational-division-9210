# 雁坪地服·行李牵引车放行

在行李车交接前，核对车型的全部必检项目，阻断过期、撤销及缺项车辆。

## 业务流程

1. 交接班台
2. 车型与检证
3. 放行筛查
4. 缺项交接单

PostgreSQL 嵌套 NOT EXISTS 对全套必检证据做关系除法。

上游为雁坪机场地服车辆组的车型检点表与检测仪回执，下游为机坪调度。旧流程使用群消息与纸质签字，容易漏对车型项目、沿用过期报告、忽略同一分钟内补登的不通过结论。

07:25 导入车型表，07:30 整理 YP-1124-早班的 4 辆车，07:40 收取检测回执，07:55 保存交接批次，08:00 后台查询有效证据，08:05 核查停放与缺项，08:10 导出给调度。

按车型找全部必检项目，再找每项最新证据。仅包含复核分钟之前及当分钟，按检测分钟及证据序号降序取首条，通过且失效分钟严格大于复核分钟才有效。车型无必检配置时挂起。默认 YP-T12 放行，其余三辆停放。SQL 在独立的 PostgreSQL 会话暂存表上执行，结果回写交接批次。班内口径按当日分钟表达，不跨日，也不直接下发调度放行指令。

## 启动

```sh
cp -n .env.example .env
docker compose config --quiet
docker compose up -d --build --wait
```

打开 <http://localhost:18250>。OpenAPI 在 <http://localhost:19250/docs>，数据库映射到本机 17750。所有暴露端口只绑定回环地址。Compose 启动 frontend、backend、worker、db、redis，各自通过健康探针检查。数据库、Redis 和共享产物目录各有命名卷；任务状态及导出内容以数据库中的证据为准。

首次启动时幂等载入演示数据。手动载入可运行 `docker compose exec -T backend python -m scripts.seed_demo`。常规停止可用 `docker compose down`。验收环境清理才加 `-v`，它会删除本项目的数据卷。

## 角色与交接

演示账号共用口令 `Demo-DbWorkbench-2026`。

| 登录名 | 角色 | 可执行操作 |
|---|---|---|
| operator | 资料操作员 | 登记业务资料、设置「复核时点（当日分钟）」、提交、查看和下载结果；建立演练场并追加批次 |
| reviewer | 业务复核员 | 查看执行证据、签署单次复核、下载交接单 |
| viewer | 只读观察员 | 查看资料、执行结果及审计，下载证据 |
| outsource | 外包演练员 | 仅访问演练副本：查看代号与放行结果、重跑副本、导出证据 |

选用「YP-1124-早班」对应的演示资料，保存一份复演资料，再以默认参数 480 提交。worker 保存结果摘要、业务明细和 SHA-256。复核员登录后在「缺项交接单」签署。

## 演练副本

外包班组用历史交接批次练习筛查。资料操作员在「演练副本」页从已完成的历史批次建立演练场（场），每场把原车号替换为本场代号：

- 同一场内，同一辆车在所有批次及后续追加批次中都使用同一代号；不同车代号不同。换一场演练会重新生成全部代号。
- 副本保留原批次的复核时点，按该时点重算，每辆车的放行决定与缺项原因必须与原单逐条一致；不一致的批次不会建立。
- 外包账号只能读取演练副本，看不到原资料、原批次编号或原车号；可重跑副本并导出演练证据。
- 每个批次连同批次记录、资料与执行任务在同一事务内落库，齐套后才对同场其他提交可见。追加请求按场串行换取序号，两人同时追加不会重复占号。
- 追加可混合多个历史批次：已办妥的批次返回为「此前已加入」，失败批次列出原因，可对失败部分重试而不重复生成已办妥批次。

演练相关表在 `backend/src/models/drill.py`，服务与接口在 `backend/src/services/drills.py`、`backend/src/routes/drills.py`。演练回归测试在 `backend/tests/test_drills.py`，指向一个一次性 PostgreSQL 库运行：

```sh
pip install -r backend/requirements-dev.txt
DRILL_TEST_DATABASE_URL="postgresql+psycopg://workbench:密码@127.0.0.1:17750/workbench" pytest backend/tests -q
```

## 开发说明

| 部分 | 实现 |
|---|---|
| 前端 | 原生 HTML、CSS、JavaScript ES Modules、Nginx |
| 后端 | Python 3.11、FastAPI、SQLAlchemy、JWT |
| 数据库 | PostgreSQL 16 |
| 后台执行 | Redis 通知、数据库持久任务队列和行锁、Python worker |

从 `backend/src/domain/scenario.py` 修改业务入口和演示口径，运行 `docker compose up -d --build --wait` 查看变更。数据库表结构在 `backend/src/models` 和 `backend/migrations`，输入模型在 `backend/src/schemas`。业务页和请求接口在 `frontend/src/pages`、`frontend/src/api`。资料、执行、复核三个工作流实体各有独立表和 API；场景输入及结果保留在所属资料和批次中。

角色枚举在 `backend/src/constants/roles.py`、`frontend/src/constants/roles.js`，用于服务端访问控制、账号初始化、前端导航与签署。批次状态在 `backend/src/constants/job_state.py`、`frontend/src/constants/states.js`，用于队列、状态 API、状态标记与轮询。登记、提交、完成和签署事件写入审计表。

`COMPOSE_PROJECT_NAME` 设置栈名，`FRONTEND_PORT`、`BACKEND_PORT`、`DB_PORT` 设置端口。通过 `DB_PASSWORD`、`JWT_SECRET`、`DEMO_PASSWORD` 配置本地凭据。设置 `SEED_DEMO=false` 可关闭演示数据载入，此时数据库初始没有演示账号。数据库密码调整后，已有数据卷需在数据库内同步修改用户密码。

## 验收范围

输入为单业务日和临时检证表，放行决定作为演练证据留存。 当前界面用 JSON 编辑业务资料，以 JSON 下载证据。过程和截图保存在批次的 [验收记录](../../test-artifacts/gb-6101/TESTING.md)。

[MIT License](LICENSE)
