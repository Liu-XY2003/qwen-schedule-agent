#!/usr/bin/env bash
cd ~/sched-lora || exit 1
pkill -u friend -f "uvicorn app:app" 2>/dev/null
sleep 1
nohup ~/ft-env/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8800 \
      > ~/sched-lora/app.log 2>&1 < /dev/null &
echo "launched pid=$!"
for i in $(seq 1 40); do
  sleep 3
  code=$(curl -s -o /tmp/h.json -w '%{http_code}' --max-time 5 http://127.0.0.1:8800/api/health 2>/dev/null)
  if [ "$code" = "200" ]; then
    echo "ready after $((i*3))s"
    cat /tmp/h.json
    echo
    exit 0
  fi
done
echo "未能就绪, 日志:"
tail -30 ~/sched-lora/app.log
exit 1
