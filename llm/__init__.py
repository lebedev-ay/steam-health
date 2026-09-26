"""LLM-разметка отзывов аспектами со знаком. Решения и цифры исследования - docs/llm/exploration.md."""

import sys
from pathlib import Path

# collector/ не пакет: его модули (db, change_points) подключаются по пути один раз на весь llm
sys.path.insert(0, str(Path(__file__).parent.parent / "collector"))
