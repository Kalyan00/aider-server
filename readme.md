# Через uv (рекомендуется — сам найдёт нужный Python)
uv tool install git+https://github.com/Kalyan00/aider-server

# Или через pip
pip install git+https://github.com/Kalyan00/aider-server

# Запуск
aider-server


# Установить локально в режиме разработки (изменения в main.py применяются сразу)
pip install -e .
# или
uv tool install .