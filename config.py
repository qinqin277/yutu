"""
配置文件
"""
import os
from dotenv import load_dotenv

load_dotenv(override=True)

# DeepSeek 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()

# TMDB 配置
TMDB_API_TOKEN = os.getenv("TMDB_API_TOKEN", "").strip()

# 微信读书配置
WEREAD_API_BASE = "https://i.weread.qq.com/api/agent/gateway"
WEREAD_SKILL_VERSION = "1.0.4"

# TMDB 配置
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# 默认目标
DEFAULT_ANNUAL_GOAL = 50
DEFAULT_MONTHLY_GOAL = 4
