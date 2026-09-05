# 数据库迁移策略

Tevion 的 PostgreSQL schema 由 Alembic migrations 管理，`Base.metadata.create_all()` 不再作为部署或升级机制。

## 空库

对没有业务表的 clean database 执行：

```bash
cd apps/api
TEVION_DB_URL=postgresql+psycopg://.../tevion .venv/bin/alembic upgrade head
.venv/bin/alembic check
```

`upgrade head` 会从 baseline `78cc1e16a72a` 依次应用当前 migration 链，创建全部业务表和 `alembic_version`。当前 head 为 `5ab7c9d1e2f3`：generation idempotency/recovery 字段已纳入迁移链，`generation_runs.user_id` 明确保持 nullable，以兼容历史 generation run。后续 schema 变更必须创建新的 revision，不修改已应用的历史 revision。

## 已有历史数据

本 baseline 是对当前 ORM schema 的可审计快照，不是数据迁移脚本。对已经由旧版本 `Base.metadata.create_all()` 创建、但尚无 `alembic_version` 的数据库：

1. 先在备份或 staging 数据库核对表、列、约束与 baseline 一致；
2. 确认一致后执行 `alembic stamp 78cc1e16a72a`，只记录版本，不删除或重建业务表；
3. 再执行 `alembic check`，确认 ORM 与迁移没有 drift；
4. 后续使用 `alembic upgrade head` 应用新的 revision。

禁止在未核对的生产数据库上直接执行 `upgrade head`，也禁止为“初始化”删除 schema 或覆盖生产数据。如果历史 schema 与 baseline 不一致，应先编写一次明确的数据/结构迁移并在备份副本验证，不能用 `stamp` 掩盖差异。

## 测试隔离

migration harness 只允许连接数据库名为 `tevion_test` 的 PostgreSQL URL。每个测试在 `public` schema 中建立 clean database 状态，测试结束后清理该测试 schema；不会连接或清理 `tevion` 生产/开发数据库。PostgreSQL 不可用时，migration tests 会 skip，并报告启动 `docker compose up -d db`。

验证命令：

```bash
TEVION_TEST_DB_URL=postgresql+psycopg://.../tevion_test \
  .venv/bin/python -m pytest tests/test_migrations.py -q
```

测试覆盖 clean upgrade、最终 revision 和 `alembic check` 无 drift。
