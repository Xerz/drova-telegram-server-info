@echo off

set TELEGRAM_BOT_TOKEN=REPLACE-TO-YOUR-TELEGRAM-BOT-TOKEN

echo module ERRORS install commands:
echo No module named 'telegram' = pip install python-telegram-bot==13.15
echo No module named 'requests' = pip install requests
echo No module named 'geoip2' = pip install geoip2

python.exe bot.py

pause