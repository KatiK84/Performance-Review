#!/bin/zsh
cd "/Users/katja/Documents/New project/Performance Review"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt >/dev/null 2>&1

echo "Запуск приложения Performance Review..."
echo "Когда увидите 'Running on http://127.0.0.1:5000' — откройте браузер по адресу:"
echo "http://127.0.0.1:5000"
echo ""
echo "Для остановки: нажмите Ctrl + C в этом окне."

auto_open() {
  sleep 2
  open "http://127.0.0.1:5000"
}
auto_open &

python3 backend/app.py
