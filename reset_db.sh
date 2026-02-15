#!/bin/bash
# 一键清空 TrendPulse 数据库所有数据（保留表结构）

echo "========================================"
echo "TrendPulse 数据库清空脚本"
echo "========================================"

DB_URL="postgresql://dengyijie@localhost:5432/trendpulse"

read -p "确认清空所有数据？此操作不可恢复！(y/N): " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "已取消"
    exit 0
fi

echo "正在清空数据..."

psql "$DB_URL" -c "
TRUNCATE TABLE alerts, opinions, analysis_results, raw_posts, collection_tasks, subscriptions CASCADE;
"

if [ $? -eq 0 ]; then
    echo "✓ 数据库已清空"
else
    echo "✗ 清空失败，请检查数据库连接"
    exit 1
fi
