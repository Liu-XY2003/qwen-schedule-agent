#!/usr/bin/env bash
# 安装并启用日程助手的 systemd 用户服务
set -u

echo "===== 0. 前置检查 ====="
echo "  Linger : $(loginctl show-user friend 2>/dev/null | grep -i linger)"
echo "  user manager: $(systemctl --user is-system-running 2>&1)"
echo "  端口 18080 是否空闲: $(ss -ltn 2>/dev/null | grep -q ':18080 ' && echo '被占用!' || echo '空闲')"
echo "  端口 8800  是否空闲: $(ss -ltn 2>/dev/null | grep -q ':8800 ' && echo '被占用!' || echo '空闲')"
echo "  GPU:"
nvidia-smi --query-gpu=index,memory.free --format=csv,noheader | sed 's/^/    /'

echo
echo "===== 1. 停掉手工 nohup 的旧进程 ====="
pkill -f "llama-server -m" 2>/dev/null && echo "  已停 llama-server" || echo "  无"
pkill -f "uvicorn app:app" 2>/dev/null && echo "  已停 app" || echo "  无"
sleep 2

echo
echo "===== 2. 安装 unit 文件 ====="
mkdir -p ~/.config/systemd/user
cp /tmp/sched-llama.service ~/.config/systemd/user/
cp /tmp/sched-app.service   ~/.config/systemd/user/
ls -la ~/.config/systemd/user/

echo
echo "===== 3. 校验 unit 语法 ====="
systemctl --user daemon-reload
for u in sched-llama sched-app; do
  echo "--- $u ---"
  systemd-analyze --user verify ~/.config/systemd/user/$u.service 2>&1 | head -5 || true
done

echo
echo "===== 4. 启用 ====="
systemctl --user enable sched-llama.service sched-app.service 2>&1
echo "  is-enabled:"
for u in sched-llama sched-app; do
  printf "    %-14s %s\n" "$u" "$(systemctl --user is-enabled $u.service 2>&1)"
done

echo
echo "===== 5. 启动 ====="
systemctl --user start sched-llama.service
echo "  等 llama-server 就绪..."
for i in $(seq 1 60); do
  sleep 2
  if curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:18080/health 2>/dev/null | grep -q 200; then
    echo "  llama-server ready ($((i*2))s)"; break
  fi
done
systemctl --user start sched-app.service
for i in $(seq 1 30); do
  sleep 2
  if curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8800/api/health 2>/dev/null | grep -q 200; then
    echo "  app ready ($((i*2))s)"; break
  fi
done

echo
echo "===== 6. 状态 ====="
systemctl --user status sched-llama.service --no-pager 2>&1 | head -8
echo
systemctl --user status sched-app.service --no-pager 2>&1 | head -8

echo
echo "===== 7. 健康检查 ====="
curl -s --max-time 8 http://127.0.0.1:8800/api/health; echo
