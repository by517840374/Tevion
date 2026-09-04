"""测试环境兼容配置。

CI 和本地调用方使用标准的 DATABASE_URL / TEST_DATABASE_URL；现有 API
代码保留 TEVION_* 变量以避免改变生产配置，因此只在测试进程启动时映射。
"""

import os

os.environ.setdefault("TEVION_DB_URL", os.environ.get("DATABASE_URL", ""))
os.environ.setdefault("TEVION_TEST_DB_URL", os.environ.get("TEST_DATABASE_URL", ""))

# 空值表示未配置，保留测试模块原有的本地默认 URL 行为。
if not os.environ["TEVION_DB_URL"]:
    os.environ.pop("TEVION_DB_URL")
if not os.environ["TEVION_TEST_DB_URL"]:
    os.environ.pop("TEVION_TEST_DB_URL")
