# GlueKettle-01 · 骨巷熬胶坊

一排熬锅作业台。登录后是横向锅位，点锅登记煮胶峰值并改状态。前端是原生 JS，没有 React/Vue/Svelte。

## 技术栈

| 层 | 技术 |
| --- | --- |
| Web API | Starlette 路由表（不是 FastAPI Depends） |
| 结构 | SQLModel 实体 + `domain.py` 门槛 |
| 数据 | SQLModel / SQLAlchemy · psycopg2 · PostgreSQL 15 |
| 前端 | 原生 ES Module · Vite 仅打包 |
| 部署 | Docker Compose |

## 路径与端口

- 前端：http://localhost:4790
- API：http://localhost:8790
- PostgreSQL：localhost:6190

## 演示账号

`admin` / `123456`（管理员，可撤印、改印人），`worker` / `123456`、`worker2` / `123456`（操作工，只能给自己加印）

## 业务规则

锅不可标「已出胶」，除非同时满足：

1. 最近一次煮胶峰值 **≥ 90℃**；
2. 该锅**未撤回押印名单去重后至少两名不同印人**——空名单、单人、两人同名（去重后仍一人）一律挡住。

规则在 `backend/app/domain.py`。登记峰值、改成冷锅/熬煮中完全不碰押印。

押印：操作工只能给自己加印（请求体里的印人被忽略，强制取登录人）；撤印、改名归管理员。
两名主管几乎同时抢交两套「已满两人」的集合时，`stamp_books.kettle_id` 唯一约束 + 行锁兜底，
库里只保留一套（一套 200、另一套 409）。

## 押印台

顶栏在「锅位作业台」与「押印台」两个独立专页之间切换。押印台按锅筛选名单，支持加印、撤印、改印人（管理员）。

## 主要接口

- `GET  /api/kettles/{id}/stamps` 按锅列名单（含已撤回/已封账）
- `POST /api/kettles/{id}/stamps` 自己加印
- `POST /api/stamps/{id}/withdraw` 管理员撤印
- `PATCH /api/stamps/{id}` 管理员改印人 / 撤回 / 恢复
- `POST /api/kettles/{id}/status`（`drawn`）行锁内校验并封存唯一一套


## 快速启动

```bash
cd GlueKettle/GlueKettle-01
docker compose up --build
```
