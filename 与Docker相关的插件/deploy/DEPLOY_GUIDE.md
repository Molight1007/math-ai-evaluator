# 优化版书生 AI · 数学智能体评测器 — Docker 部署指南

## 前置条件

| 依赖 | 最低版本 | 安装方式 |
|------|---------|---------|
| Docker | 24.0+ | `curl -fsSL https://get.docker.com \| sh` |
| Docker Compose | v2.20+ | Docker Desktop 自带，或 `apt install docker-compose-plugin` |

验证安装：

```bash
docker --version          # >= 24.0
docker compose version    # 应输出 Compose 版本
```

---

## 首次部署（3 步）

### 1. 克隆项目

```bash
git clone <你的仓库地址> math-evaluator
cd math-evaluator
```

### 2. 配置 API 密钥（必填）

在项目根目录创建 `.env` 文件：

```bash
LEAN_KEY=你的Lean密钥
ARK_API_KEY=你的方舟API密钥
```

> `.env` 已加入 `.gitignore`，不会提交到仓库。

### 3. 启动服务

```bash
docker compose up -d
```

首次构建约 2~3 分钟（下载镜像 & 安装 Python 依赖）。完成后访问 `http://你的服务器IP` 即可看到评估器界面。

---

## 日常更新

一行命令：

```bash
bash deploy/update.sh
```

或手动执行：

```bash
git pull
docker compose up -d --build
```

`--build` 确保依赖或代码变更后重建镜像；已有容器会被无缝替换。

---

## 常用运维命令

| 操作 | 命令 |
|------|------|
| 查看运行状态 | `docker compose ps` |
| 查看后端日志 | `docker compose logs -f web` |
| 查看 nginx 日志 | `docker compose logs -f nginx` |
| 重启服务 | `docker compose restart` |
| 停止服务 | `docker compose down` |
| 彻底清理（含数据卷） | `docker compose down -v` |

---

## 目录与数据持久化

- **用户数据库**（`users.db`）：存储在 Docker 命名卷 `persist_data` 中，重建容器不会丢失
- **题库**（`题库/*.db`）：同上
- **评测结果**（`测试结果/`）：挂载到宿主机 `./测试结果/`，可直接在服务器上查看输出文件

> 执行 `docker compose down -v` 会删除命名卷，**仅在你确定要重置所有数据时使用**。

---

## 架构说明

```
Browser ──→ :80 ──→ nginx ──┬── /          → 前端静态页面
                             └── /api/*     → uvicorn (FastAPI:8000)
                                               ├── 评测引擎 (测试工具/*)
                                               ├── 题库 (题库/*.db)
                                               └── 用户管理 (users.db)
```

- **web**：Python 3.10 + FastAPI，处理 API 请求与评测逻辑
- **nginx**：Alpine 轻量镜像，负责前端静态文件服务 + API 反向代理
- 两个容器通过 Docker 内部网络通信，`web:8000` 不暴露到公网

---

## 常见问题

### Q: 磁盘空间不足？

```bash
# 清理无用的 Docker 资源
docker system prune -a

# 查看占用
docker system df
```

### Q: 如何备份数据？

```bash
# 备份 users.db 和题库
docker compose exec web tar czf /app/data/backup.tar.gz -C /app/data .
docker compose cp web:/app/data/backup.tar.gz ./backup.tar.gz
```

### Q: 如何回滚？

```bash
git log --oneline          # 找到目标 commit
git checkout <commit-id>
docker compose up -d --build
```
