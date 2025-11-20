#!/bin/bash
export PYTHONPATH=$PYTHONPATH:.

# Start the Telegram bot in the background
echo "Starting Telegram Bot..."
python public_bot.py &

# Start the Flask app
echo "Starting Flask API..."
exec gunicorn --bind 0.0.0.0:$PORT dashboard.api.app:app
