#!/bin/bash
cd ~/binance

echo "🧹 Cleaning queues before start..."
python manage_queue.py clear
python -c "from storage.scheduled_post_queue import ScheduledPostQueue; ScheduledPostQueue().clear()"

echo "🚀 Starting pipeline..."
python main.py pipeline
