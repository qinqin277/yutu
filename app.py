"""
============================================================
📚 阅途 · Personal Reading Growth Agent
============================================================

功能：
1. 微信读书真实阅读数据
2. 阅读 Dashboard
3. 阅读人格 MBTI（娱乐化）
4. AI 阅读锐评
5. 阅读目标
6. 每日打卡
7. 阅读中断提醒
8. 我的书架
9. 我的划线 / 想法
10. AI 分析笔记
11. AI 锐评想法
12. 阅读成果检验
13. 下一本读什么
14. 电影文化探索
15. 多轮 AI 对话

电影推荐：
- ❤️ 共鸣推荐
- 🌱 越界推荐
- 📖→🎬 从一本书出发
"""

# ============================================================
# 1. Imports
# ============================================================

import os
import asyncio
import json
import re
import random

from datetime import (
    datetime,
    date,
    timedelta
)

from typing import (
    Any,
    Dict,
    List,
    Optional
)

import requests
import httpx
import plotly.graph_objects as go
import streamlit as st

from dotenv import load_dotenv

from langchain.agents import (
    create_agent as lc_create_agent
)

from langchain.chat_models import (
    init_chat_model
)

from langchain_core.tools import (
    tool
)


# ============================================================
# 2. Environment
# ============================================================

load_dotenv(
    override=True
)

DEEPSEEK_API_KEY = os.getenv(
    "DEEPSEEK_API_KEY",
    ""
).strip()

DEEPSEEK_BASE_URL = os.getenv(
    "DEEPSEEK_BASE_URL",
    "https://api.deepseek.com"
).strip()

TMDB_API_TOKEN = os.getenv(
    "TMDB_API_TOKEN",
    ""
).strip()

WEREAD_API_BASE = (
    "https://i.weread.qq.com/api/agent/gateway"
)

WEREAD_SKILL_VERSION = "1.0.4"

TMDB_BASE_URL = (
    "https://api.themoviedb.org/3"
)

TMDB_IMAGE_BASE_URL = (
    "https://image.tmdb.org/t/p/w500"
)


# ============================================================
# 3. Streamlit config
# ============================================================

st.set_page_config(
    page_title="阅途 · Personal Reading Growth Agent",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# 4. CSS
# ============================================================

st.markdown(
    """
    <style>

    .block-container {
        max-width: 1250px;
        padding-top: 2rem;
        padding-bottom: 4rem;
    }

    .hero {
        padding: 2.2rem 2.5rem;
        border-radius: 28px;
        background:
            linear-gradient(
                135deg,
                #f4f0ff 0%,
                #eef7ff 50%,
                #fff5ec 100%
            );
        margin-bottom: 1.5rem;
        border: 1px solid #ececec;
    }

    .hero-title {
        font-size: 2.6rem;
        font-weight: 800;
    }

    .hero-subtitle {
        color: #666;
        font-size: 1rem;
        margin-top: .4rem;
    }

    .movie-reason {
        padding: 1rem;
        background: #f7f7f7;
        border-radius: 15px;
        margin-top: .8rem;
    }

    </style>
    """,
    unsafe_allow_html=True
)


# ============================================================
# 5. Session State
# ============================================================

DEFAULT_STATE = {

    "weread_client":
        None,

    "agent":
        None,

    "is_ready":
        False,

    "shelf":
        {},

    "reading_stats":
        {},

    "notebooks":
        {},

    "profile":
        {},

    "personality":
        {},

    "book_catalog":
        [],

    "note_items":
        [],

    "messages":
        [],

    "annual_goal":
        50,

    "monthly_goal":
        4,

    "checkin_history":
        {},

    "quick_query":
        "",

    "last_refresh":
        None,

    "movie_mode":
        "",

    "movie_results":
        [],

    "movie_page":
        1,

    "movie_seed":
        0,

    "movie_source_book":
        "",

    "selected_note_book":
        "",

    "reading_test_question":
        "",

    "reading_test_answer":
        "",

    "reading_test_feedback":
        ""
}


def initialize_state():

    for key, value in DEFAULT_STATE.items():

        if key not in st.session_state:

            if isinstance(
                value,
                dict
            ):

                st.session_state[key] = dict(
                    value
                )

            elif isinstance(
                value,
                list
            ):

                st.session_state[key] = list(
                    value
                )

            else:

                st.session_state[key] = value


initialize_state()


# ============================================================
# 6. Basic Helpers
# ============================================================

def run_async(coro):
    """执行异步函数。"""
    return asyncio.run(coro)


def safe_int(
    value: Any,
    default: int = 0
) -> int:

    try:
        return int(value)

    except (
        TypeError,
        ValueError
    ):
        return default


def safe_float(
    value: Any,
    default: float = 0
) -> float:

    try:
        return float(value)

    except (
        TypeError,
        ValueError
    ):
        return default


def format_seconds(
    seconds
):

    seconds = max(
        0,
        safe_int(seconds)
    )

    hours = seconds // 3600

    minutes = (
        seconds % 3600
    ) // 60

    if hours:

        return (
            f"{hours}小时"
            f"{minutes}分钟"
        )

    return f"{minutes}分钟"


def timestamp_to_date(
    timestamp
):

    try:

        return datetime.fromtimestamp(
            float(timestamp)
        ).date()

    except (
        TypeError,
        ValueError,
        OSError
    ):

        return None


# ============================================================
# 7. Streak
# ============================================================

def calculate_streak_safe(
    history
):

    if not history:

        return 0

    today = date.today()

    today_key = today.strftime(
        "%Y-%m-%d"
    )

    yesterday = (
        today
        - timedelta(days=1)
    )

    yesterday_key = (
        yesterday.strftime(
            "%Y-%m-%d"
        )
    )

    if history.get(
        today_key,
        False
    ):

        current = today

    elif history.get(
        yesterday_key,
        False
    ):

        current = yesterday

    else:

        return 0

    streak = 0

    while True:

        key = current.strftime(
            "%Y-%m-%d"
        )

        if not history.get(
            key,
            False
        ):

            break

        streak += 1

        current -= timedelta(
            days=1
        )

    return streak


# ============================================================
# 8. Weread Client
# ============================================================

class WereadClient:

    def __init__(
        self,
        api_key
    ):

        if not api_key.strip():

            raise ValueError(
                "微信读书 API Key 不能为空。"
            )

        self.api_key = (
            api_key.strip()
        )

        self.headers = {

            "Authorization":
                f"Bearer {self.api_key}",

            "Content-Type":
                "application/json"
        }


    async def call(
        self,
        api_name,
        params=None
    ):

        payload = {

            "api_name":
                api_name,

            "skill_version":
                WEREAD_SKILL_VERSION
        }

        if params:

            payload.update(
                params
            )

        try:

            async with httpx.AsyncClient(
                timeout=30
            ) as client:

                response = await client.post(

                    WEREAD_API_BASE,

                    headers=self.headers,

                    json=payload
                )

            if response.status_code != 200:

                raise RuntimeError(
                    f"微信读书 API "
                    f"HTTP {response.status_code}: "
                    f"{response.text[:800]}"
                )

            data = response.json()

            if not isinstance(
                data,
                dict
            ):

                raise RuntimeError(
                    "微信读书返回格式异常。"
                )

            return data

        except httpx.RequestError as exc:

            raise RuntimeError(
                f"微信读书网络请求失败：{exc}"
            )


    async def get_shelf(self):

        return await self.call(
            "/shelf/sync"
        )


    async def get_reading_stats(
        self,
        mode="overall"
    ):

        params = {
            "mode":
                mode
        }

        if mode == "overall":

            params["baseTime"] = 0

        return await self.call(
            "/readdata/detail",
            params
        )


    async def get_notebooks(
        self,
        count=200
    ):

        return await self.call(
            "/user/notebooks",
            {
                "count":
                    count
            }
        )


    async def search_books(
        self,
        keyword
    ):

        return await self.call(
            "/store/search",
            {
                "keyword":
                    keyword,

                "count":
                    10,

                "scope":
                    10
            }
        )


    async def get_bookmarks(
        self,
        book_id
    ):

        return await self.call(
            "/book/bookmarklist",
            {
                "bookId":
                    book_id
            }
        )


    async def get_reviews(
        self,
        book_id
    ):

        return await self.call(
            "/review/list/mine",
            {
                "bookid":
                    book_id,

                "count":
                    50
            }
        )


# ============================================================
# 9. Parse Weread
# ============================================================

def parse_shelf(
    data
):

    books = data.get(
        "books",
        []
    )

    albums = data.get(
        "albums",
        []
    )

    mp = data.get(
        "mp"
    )

    if not isinstance(
        books,
        list
    ):

        books = []

    if not isinstance(
        albums,
        list
    ):

        albums = []

    finished = sum(

        1

        for book in books

        if (
            isinstance(
                book,
                dict
            )

            and safe_int(
                book.get(
                    "finishReading",
                    0
                )
            ) == 1
        )
    )

    return {

        "books":
            books,

        "albums":
            albums,

        "mp":
            mp,

        "book_count":
            len(books),

        "album_count":
            len(albums),

        "total_items":
            (
                len(books)
                +
                len(albums)
                +
                (
                    1
                    if mp
                    else 0
                )
            ),

        "finished_books":
            finished,

        "unfinished_books":
            max(
                0,
                len(books) - finished
            )
    }


def parse_stats(
    data
):

    return {

        "total_read_time":
            safe_int(
                data.get(
                    "totalReadTime",
                    0
                )
            ),

        "read_days":
            safe_int(
                data.get(
                    "readDays",
                    0
                )
            ),

        "day_average":
            safe_int(
                data.get(
                    "dayAverageReadTime",
                    0
                )
            ),

        "prefer_category":
            data.get(
                "preferCategory",
                []
            ),

        "read_longest":
            data.get(
                "readLongest",
                []
            )
    }


def parse_notebooks(
    data
):

    notebooks = data.get(
        "notebooks",
        []
    )

    if not isinstance(
        notebooks,
        list
    ):

        notebooks = []

    total_notes = safe_int(
        data.get(
            "totalNoteCount",
            0
        )
    )

    if total_notes == 0:

        for item in notebooks:

            if not isinstance(
                item,
                dict
            ):

                continue

            total_notes += (
                safe_int(
                    item.get(
                        "noteCount",
                        0
                    )
                )
                +
                safe_int(
                    item.get(
                        "reviewCount",
                        0
                    )
                )
            )

    return {

        "notebooks":
            notebooks,

        "total_note_count":
            total_notes
    }


# ============================================================
# 10. Profile
# ============================================================

def build_profile(
    shelf_info,
    stats_info,
    notebook_info
):

    books = shelf_info.get(
        "books",
        []
    )

    categories = {}

    for book in books:

        if not isinstance(
            book,
            dict
        ):

            continue

        category = book.get(
            "category",
            "其他"
        )

        if not category:

            category = "其他"

        categories[
            category
        ] = (
            categories.get(
                category,
                0
            )
            + 1
        )

    total = len(books) or 1

    distribution = {

        key:
            round(
                value
                / total
                * 100,
                1
            )

        for key, value
        in categories.items()
    }

    return {

        "book_count":
            shelf_info.get(
                "book_count",
                0
            ),

        "album_count":
            shelf_info.get(
                "album_count",
                0
            ),

        "total_items":
            shelf_info.get(
                "total_items",
                0
            ),

        "finished_books":
            shelf_info.get(
                "finished_books",
                0
            ),

        "unfinished_books":
            shelf_info.get(
                "unfinished_books",
                0
            ),

        "total_read_time":
            stats_info.get(
                "total_read_time",
                0
            ),

        "read_days":
            stats_info.get(
                "read_days",
                0
            ),

        "day_average":
            stats_info.get(
                "day_average",
                0
            ),

        "total_notes":
            notebook_info.get(
                "total_note_count",
                0
            ),

        "category_distribution":
            distribution
    }


# ============================================================
# 11. Personality
# ============================================================

def calculate_personality(
    profile
):

    books = safe_int(
        profile.get(
            "book_count",
            0
        )
    )

    finished = safe_int(
        profile.get(
            "finished_books",
            0
        )
    )

    notes = safe_int(
        profile.get(
            "total_notes",
            0
        )
    )

    categories = len(
        profile.get(
            "category_distribution",
            {}
        )
    )

    completion = (
        finished / books
        if books
        else 0
    )

    note_density = (
        notes / books
        if books
        else 0
    )

    ei = (
        "E"
        if categories >= 6
        else "I"
    )

    sn = (
        "N"
        if categories >= 7
        else "S"
    )

    tf = (
        "T"
        if note_density >= 1
        else "F"
    )

    jp = (
        "J"
        if completion >= 0.5
        else "P"
    )

    code = (
        ei
        + sn
        + tf
        + jp
    )

    mapping = {

        "INTP": (
            "知识考据型读者",
            "比起读完，你更在意有没有真正想明白。"
        ),

        "INTJ": (
            "知识策展型读者",
            "喜欢把零散的阅读经验整理成自己的体系。"
        ),

        "ENTP": (
            "跨界探索型读者",
            "喜欢让不同领域的观点发生碰撞。"
        ),

        "ENTJ": (
            "目标驱动型读者",
            "阅读通常围绕明确目标展开。"
        ),

        "INFJ": (
            "意义探索型读者",
            "容易从作品中寻找人与世界的深层联系。"
        ),

        "INFP": (
            "精神漫游型读者",
            "容易被文学、情绪和价值问题吸引。"
        ),

        "ENFP": (
            "灵感漫游型读者",
            "兴趣跨度大，经常从一本书跳到另一个世界。"
        ),

        "ENFJ": (
            "共情策展型读者",
            "喜欢从人物、关系和社会环境理解作品。"
        ),

        "ISTJ": (
            "长期主义型读者",
            "重视稳定积累与完成度。"
        ),

        "ISFJ": (
            "沉浸陪伴型读者",
            "喜欢能够长期陪伴自己的作品。"
        ),

        "ISFP": (
            "体验型读者",
            "更加关注作品带来的感受。"
        ),

        "ISTP": (
            "问题解决型读者",
            "喜欢从阅读中寻找具体答案。"
        ),

        "ESTP": (
            "即时探索型读者",
            "兴趣来得快，喜欢迅速进入新的领域。"
        ),

        "ESFP": (
            "感官漫游型读者",
            "容易被生动、有趣的作品吸引。"
        ),

        "ESFJ": (
            "共鸣型读者",
            "容易被人物和人与人的故事打动。"
        ),

        "ESTJ": (
            "高效执行型读者",
            "喜欢有结构地推进阅读。"
        )
    }

    title, description = mapping.get(
        code,
        (
            "探索型读者",
            "正在逐渐形成自己的阅读风格。"
        )
    )

    if note_density >= 2:

        sub = (
            "你不是在读书，你是在给自己的大脑做版本控制。"
        )

    elif completion < 0.3:

        sub = (
            "你的收藏欲目前跑在阅读执行力前面。"
        )

    elif categories >= 8:

        sub = (
            "你的书架像是由多个不同版本的你共同维护的。"
        )

    else:

        sub = (
            "你的阅读口味正在逐渐形成自己的形状。"
        )

    return {

        "code":
            code,

        "title":
            title,

        "description":
            description,

        "sub":
            sub,

        "completion":
            completion,

        "note_density":
            note_density,

        "category_count":
            categories
    }


# ============================================================
# 12. Catalog
# ============================================================

def build_catalog(
    shelf_info
):

    catalog = []

    for book in shelf_info.get(
        "books",
        []
    ):

        if not isinstance(
            book,
            dict
        ):

            continue

        catalog.append({

            "bookId":
                str(
                    book.get(
                        "bookId",
                        ""
                    )
                ),

            "title":
                book.get(
                    "title",
                    "未知"
                ),

            "author":
                book.get(
                    "author",
                    "未知作者"
                ),

            "category":
                book.get(
                    "category",
                    "其他"
                ),

            "cover":
                book.get(
                    "cover",
                    ""
                ),

            "deepLink":
                book.get(
                    "deepLink",
                    ""
                ),

            "finishReading":
                safe_int(
                    book.get(
                        "finishReading",
                        0
                    )
                ),

            "readUpdateTime":
                book.get(
                    "readUpdateTime"
                )
        })

    return catalog


# ============================================================
# 13. Reading Reminder
# ============================================================

def get_reading_reminders(
    catalog
):

    today = date.today()

    reminders = []

    for book in catalog:

        if safe_int(
            book.get(
                "finishReading",
                0
            )
        ) == 1:

            continue

        last = timestamp_to_date(
            book.get(
                "readUpdateTime"
            )
        )

        if not last:

            continue

        days = (
            today - last
        ).days

        if days >= 7:

            reminders.append({

                "title":
                    book.get(
                        "title",
                        "未知"
                    ),

                "days":
                    days
            })

    reminders.sort(
        key=lambda x:
            x["days"],
        reverse=True
    )

    return reminders[:6]


# ============================================================
# 14. DeepSeek
# ============================================================

def get_deepseek_model():

    if not DEEPSEEK_API_KEY:

        raise RuntimeError(
            "没有配置 DEEPSEEK_API_KEY。"
        )

    return init_chat_model(

        model="deepseek-chat",

        model_provider="openai",

        api_key=
            DEEPSEEK_API_KEY,

        base_url=
            DEEPSEEK_BASE_URL
    )


# ============================================================
# 15. Agent Tools
# ============================================================

def create_tools(
    client,
    profile,
    catalog
):

    @tool
    def search_books(
        keyword: str
    ) -> str:
        """
        搜索微信读书书城中的真实书籍。
        """

        try:

            result = run_async(
                client.search_books(
                    keyword
                )
            )

            results = result.get(
                "results",
                []
            )

            if not isinstance(
                results,
                list
            ):

                return (
                    "没有找到相关书籍。"
                )

            output = []

            for item in results[:8]:

                if not isinstance(
                    item,
                    dict
                ):

                    continue

                info = item.get(
                    "bookInfo",
                    item
                )

                if not isinstance(
                    info,
                    dict
                ):

                    continue

                output.append(
                    f"《{info.get('title', '未知')}》"
                    f" - "
                    f"{info.get('author', '未知作者')}"
                )

            return (
                "\n".join(
                    output
                )
                if output
                else "没有找到相关书籍。"
            )

        except Exception as exc:

            return (
                f"搜索失败：{exc}"
            )


    @tool
    def get_reading_profile() -> str:
        """
        获取用户真实阅读数据和阅读画像。
        """

        return json.dumps(
            profile,
            ensure_ascii=False,
            indent=2
        )


    @tool
    def get_unfinished_books() -> str:
        """
        获取用户尚未读完的书籍。
        """

        books = [

            book

            for book in catalog

            if safe_int(
                book.get(
                    "finishReading",
                    0
                )
            ) != 1
        ]

        if not books:

            return (
                "当前没有未读完的电子书。"
            )

        return "\n".join(

            [
                f"《{book['title']}》"
                f" - {book['author']}"

                for book in books[:30]
            ]
        )


    @tool
    def get_recent_books() -> str:
        """
        获取用户最近阅读过的书籍。
        """

        items = []

        for book in catalog:

            d = timestamp_to_date(
                book.get(
                    "readUpdateTime"
                )
            )

            if d:

                items.append({

                    "title":
                        book.get(
                            "title",
                            "未知"
                        ),

                    "date":
                        str(d)
                })

        items.sort(
            key=lambda x:
                x["date"],
            reverse=True
        )

        if not items:

            return (
                "没有足够的最近阅读数据。"
            )

        return "\n".join(

            [
                f"《{x['title']}》"
                f"（{x['date']}）"

                for x in items[:10]
            ]
        )


    return [
        search_books,
        get_reading_profile,
        get_unfinished_books,
        get_recent_books
    ]


# ============================================================
# 16. Agent
# ============================================================

def build_agent(
    client,
    profile,
    catalog,
    personality
):

    model = get_deepseek_model()

    tools = create_tools(
        client,
        profile,
        catalog
    )

    system_prompt = f"""
你是“阅途”，一个个人阅读成长 Agent。

用户阅读人格：
{personality['code']} · {personality['title']}

人格描述：
{personality['description']}

真实阅读数据：
{json.dumps(profile, ensure_ascii=False)}

你的任务：

1. 理解用户阅读习惯。
2. 帮用户决定下一本书。
3. 分析用户的阅读记录。
4. 分析用户提出的观点。
5. 检验用户是否真正读懂一本书。
6. 对用户阅读行为进行幽默、善意的锐评。

工具：

search_books
get_reading_profile
get_unfinished_books
get_recent_books

规则：

- 涉及用户真实数据时优先调用工具。
- 不要编造数据。
- 推荐下一本书时综合用户真实阅读历史。
- 不要机械复制平台推荐。
- 最多推荐3本。
- 推荐要具体。
- 用户要求阅读成果检验时，一次只问一个问题。
- 使用中文。
"""


    return lc_create_agent(

        model=model,

        tools=tools,

        system_prompt=system_prompt
    )


# ============================================================
# 17. AI Note Analysis
# ============================================================

def analyze_note_with_ai(
    title,
    original_text,
    thought=""
):

    model = get_deepseek_model()

    prompt = f"""
请分析用户关于《{title}》的一条阅读记录。

【原文】
{original_text}

【用户想法】
{thought or "无"}

分析：

1. 核心问题。
2. 用户抓住了什么。
3. 理解得好的地方。
4. 可能存在的逻辑问题。
5. 可以继续思考的问题。

不要评价用户本人。
只分析阅读内容。
"""

    result = model.invoke(
        prompt
    )

    return str(
        result.content
    )


# ============================================================
# 18. Reading Test
# ============================================================

def generate_reading_question(
    title
):

    model = get_deepseek_model()

    prompt = f"""
请针对《{title}》提出一个阅读理解问题。

要求：
- 不能只靠背简介回答。
- 需要解释自己的理解。
- 最好触及作品真正的问题。
- 不要太学术。
- 只输出一个问题。
"""

    result = model.invoke(
        prompt
    )

    return str(
        result.content
    )


def evaluate_reading_answer(
    title,
    question,
    answer
):

    model = get_deepseek_model()

    prompt = f"""
用户正在回答《{title}》的阅读理解问题。

问题：
{question}

回答：
{answer}

请评价：

1. 核心理解
2. 文本理解
3. 独立思考
4. 逻辑完整性
5. 可能存在的误读

最后提出下一道问题。

语气自然，不要像考试阅卷。
"""

    result = model.invoke(
        prompt
    )

    return str(
        result.content
    )


# ============================================================
# 19. TMDB API
# ============================================================

def tmdb_get(
    endpoint,
    params=None
):

    if not TMDB_API_TOKEN:

        raise RuntimeError(
            "没有配置 TMDB_API_TOKEN。"
        )

    headers = {

        "Authorization":
            f"Bearer {TMDB_API_TOKEN}",

        "accept":
            "application/json"
    }

    response = requests.get(

        TMDB_BASE_URL + endpoint,

        headers=headers,

        params=params or {},

        timeout=15
    )

    response.raise_for_status()

    return response.json()


def tmdb_search_movie(
    query,
    page=1
):

    data = tmdb_get(

        "/search/movie",

        {
            "query":
                query,

            "language":
                "zh-CN",

            "include_adult":
                "false",

            "page":
                page
        }
    )

    return data.get(
        "results",
        []
    )


def tmdb_discover_movie(
    *,
    genre_id=None,
    original_language=None,
    sort_by="popularity.desc",
    page=1
):

    params = {

        "language":
            "zh-CN",

        "include_adult":
            "false",

        "include_video":
            "false",

        "sort_by":
            sort_by,

        "page":
            page,

        "vote_count.gte":
            100
    }

    if genre_id:

        params[
            "with_genres"
        ] = genre_id

    if original_language:

        params[
            "with_original_language"
        ] = original_language

    data = tmdb_get(

        "/discover/movie",

        params
    )

    return data.get(
        "results",
        []
    )


def enrich_movie(
    movie
):

    poster_path = movie.get(
        "poster_path"
    )

    return {

        "id":
            movie.get(
                "id"
            ),

        "title":
            movie.get(
                "title",
                "未知"
            ),

        "original_title":
            movie.get(
                "original_title",
                ""
            ),

        "release_date":
            movie.get(
                "release_date",
                ""
            ),

        "rating":
            safe_float(
                movie.get(
                    "vote_average",
                    0
                )
            ),

        "vote_count":
            safe_int(
                movie.get(
                    "vote_count",
                    0
                )
            ),

        "overview":
            movie.get(
                "overview",
                "暂无简介"
            ),

        "poster":
            (
                TMDB_IMAGE_BASE_URL
                + poster_path
                if poster_path
                else ""
            )
    }


# ============================================================
# 20. Remove obvious non-mainline titles
# ============================================================

def clean_movie_candidates(
    movies
):

    result = []

    seen = set()

    bad_title_patterns = [

        "inside",

        "behind",

        "making of",

        "science of",

        "the science of",

        "behind the scenes",

        "special",

        "featurette",

        "interview",

        "documentary about"

    ]

    for movie in movies:

        if not isinstance(
            movie,
            dict
        ):

            continue

        movie_id = movie.get(
            "id"
        )

        if not movie_id:

            continue

        if movie_id in seen:

            continue

        seen.add(
            movie_id
        )

        title = str(
            movie.get(
                "title",
                ""
            )
        ).lower()

        original = str(
            movie.get(
                "original_title",
                ""
            )
        ).lower()

        joined = (
            title
            + " "
            + original
        )

        if any(
            pattern in joined
            for pattern in bad_title_patterns
        ):

            continue

        # 只过滤极端冷门的项目，
        # 不再使用过于严格的评分门槛。
        votes = safe_int(
            movie.get(
                "vote_count",
                0
            )
        )

        if votes < 20:

            continue

        result.append(
            enrich_movie(
                movie
            )
        )

    return result


# ============================================================
# 21. Movie Type Inference
# ============================================================

BOOK_CATEGORY_TO_MOVIE = {

    # 中文分类关键词：
    # 对应 TMDB 官方 genre id
    "悬疑":
        "9648",

    "推理":
        "9648",

    "犯罪":
        "80",

    "科幻":
        "878",

    "奇幻":
        "14",

    "爱情":
        "10749",

    "历史":
        "36",

    "战争":
        "10752",

    "动画":
        "16",

    "音乐":
        "10402",

    "恐怖":
        "27",

    "喜剧":
        "35",

    "动作":
        "28",

    "冒险":
        "12",

    "剧情":
        "18"
}


def infer_movie_preferences_from_books(
    catalog,
    profile
):

    categories = list(
        profile.get(
            "category_distribution",
            {}
        ).keys()
    )

    genre_id = None

    # ----------------------------
    # 1. 分类
    # ----------------------------

    for category in categories:

        for keyword, gid in BOOK_CATEGORY_TO_MOVIE.items():

            if keyword in str(
                category
            ):

                genre_id = gid

                break

        if genre_id:

            break

    # ----------------------------
    # 2. 语言/地区
    # ----------------------------

    # 因为书架数据未必直接提供语言，
    # 这里通过书名/作者做轻量判断。
    japanese_hint = False

    for book in catalog[:30]:

        text = (
            str(
                book.get(
                    "title",
                    ""
                )
            )
            +
            str(
                book.get(
                    "author",
                    ""
                )
            )
        )

        jp_words = [
            "村上",
            "东野",
            "東野",
            "伊坂",
            "湊",
            "宫部",
            "宮部",
            "绫辻",
            "綾辻",
            "日本"
        ]

        if any(
            word in text
            for word in jp_words
        ):

            japanese_hint = True

            break

    language = (
        "ja"
        if japanese_hint
        else None
    )

    return {

        "genre_id":
            genre_id,

        "original_language":
            language
    }


# ============================================================
# 22. AI Movie Ranking
# ============================================================

def rank_movies_for_user(
    candidates,
    context,
    mode
):

    if not candidates:

        return []

    model = get_deepseek_model()

    compact = []

    for movie in candidates[:20]:

        compact.append({

            "id":
                movie["id"],

            "title":
                movie["title"],

            "original_title":
                movie["original_title"],

            "year":
                movie["release_date"][:4]
                if movie["release_date"]
                else "",

            "rating":
                movie["rating"],

            "overview":
                movie["overview"][:450]
        })

    prompt = f"""
你是电影推荐系统。

用户背景：
{context}

推荐模式：
{mode}

候选电影：
{json.dumps(compact, ensure_ascii=False)}

请给每部候选电影一个0-100的“用户匹配度”。

匹配度不能只依据评分。

考虑：
- 类型
- 主题
- 氛围
- 用户阅读习惯
- 国家/语言偏好
- 用户当前探索目的

最重要：
即使不是完美匹配，也要尽量给出结果。
不要因为匹配度不高就返回空列表。

只返回JSON：

[
    {{
        "id": 123,
        "score": 87,
        "reason": "为什么适合这个用户"
    }}
]

按score从高到低排序。
最多返回3部。
"""

    result = model.invoke(
        prompt
    )

    text = str(
        result.content
    )

    match = re.search(
        r"\[.*\]",
        text,
        re.S
    )

    if not match:

        return []

    try:

        ranked = json.loads(
            match.group()
        )

        return ranked[:3]

    except json.JSONDecodeError:

        return []


# ============================================================
# 23. Similar Movie Recommendation
# ============================================================

def recommend_similar_movies():

    profile = (
        st.session_state.profile
    )

    catalog = (
        st.session_state.book_catalog
    )

    preferences = (
        infer_movie_preferences_from_books(
            catalog,
            profile
        )
    )

    page = max(
        1,
        st.session_state.movie_page
    )

    candidates = []

    # --------------------------------------------------------
    # 第一层：按类型 + 语言
    # --------------------------------------------------------

    try:

        data = tmdb_discover_movie(

            genre_id=
                preferences.get(
                    "genre_id"
                ),

            original_language=
                preferences.get(
                    "original_language"
                ),

            sort_by=
                "popularity.desc",

            page=
                page
        )

        candidates.extend(
            data
        )

    except Exception:

        pass


    # --------------------------------------------------------
    # 第二层：只有类型
    # --------------------------------------------------------

    if len(candidates) < 6:

        try:

            data = tmdb_discover_movie(

                genre_id=
                    preferences.get(
                        "genre_id"
                    ),

                sort_by=
                    "vote_average.desc",

                page=
                    page
            )

            candidates.extend(
                data
            )

        except Exception:

            pass


    # --------------------------------------------------------
    # 第三层：直接热门片兜底
    # --------------------------------------------------------

    if len(candidates) < 3:

        try:

            data = tmdb_discover_movie(

                sort_by=
                    "popularity.desc",

                page=
                    page
            )

            candidates.extend(
                data
            )

        except Exception:

            pass


    candidates = clean_movie_candidates(
        candidates
    )

    # --------------------------------------------------------
    # 避免重复推荐
    # --------------------------------------------------------

    previous_ids = {

        movie["id"]

        for movie
        in st.session_state.movie_results
    }

    if previous_ids:

        fresh = [

            movie
            for movie
            in candidates

            if movie["id"]
            not in previous_ids
        ]

        if len(fresh) >= 3:

            candidates = fresh


    context = f"""
用户阅读类型：
{json.dumps(
    profile.get(
        "category_distribution",
        {}
    ),
    ensure_ascii=False
)}

阅读人格：
{st.session_state.personality.get(
    "code",
    ""
)}

用户读过的部分书籍：
[
    {", ".join(
        book.get("title", "")
        for book in catalog[:8]
    )}
]
"""

    ranked = rank_movies_for_user(

        candidates,

        context,

        "❤️ 共鸣推荐：主要寻找类型、地区、语言或气质上与用户阅读习惯一致的电影。"
    )

    lookup = {

        movie["id"]:
            movie

        for movie in candidates
    }

    result = []

    for item in ranked:

        movie = lookup.get(
            item.get(
                "id"
            )
        )

        if movie:

            movie["match_score"] = safe_int(
                item.get(
                    "score",
                    70
                )
            )

            movie["reason"] = item.get(
                "reason",
                "与你的阅读类型具有较强共鸣。"
            )

            result.append(
                movie
            )

    # --------------------------------------------------------
    # AI失败也必须给结果
    # --------------------------------------------------------

    if not result:

        fallback = candidates[:3]

        for movie in fallback:

            movie["match_score"] = 65

            movie["reason"] = (
                "这部电影与你的阅读类型存在一定共鸣，"
                "可以作为一次文化探索。"
            )

        return fallback

    return result


# ============================================================
# 24. Explore Movie Recommendation
# ============================================================

def recommend_explore_movies():

    profile = (
        st.session_state.profile
    )

    catalog = (
        st.session_state.book_catalog
    )

    existing_categories = set(

        profile.get(
            "category_distribution",
            {}
        ).keys()
    )

    all_genres = {

        "科幻":
            "878",

        "动画":
            "16",

        "纪录片":
            "99",

        "历史":
            "36",

        "音乐":
            "10402",

        "战争":
            "10752",

        "犯罪":
            "80",

        "悬疑":
            "9648",

        "爱情":
            "10749"
    }

    unfamiliar = [

        name

        for name in all_genres

        if name not in existing_categories
    ]

    if not unfamiliar:

        unfamiliar = [
            "科幻",
            "动画",
            "纪录片"
        ]

    # 每次随机选一个陌生领域
    chosen = random.choice(
        unfamiliar[:5]
    )

    page = max(
        1,
        st.session_state.movie_page
    )

    try:

        candidates = (
            tmdb_discover_movie(

                genre_id=
                    all_genres[
                        chosen
                    ],

                sort_by=
                    "vote_average.desc",

                page=
                    page
            )
        )

    except Exception:

        candidates = []


    candidates = clean_movie_candidates(
        candidates
    )

    context = f"""
用户当前阅读领域：

{json.dumps(
    profile.get(
        "category_distribution",
        {}
    ),
    ensure_ascii=False
)}

本次希望主动探索的陌生领域：

{chosen}
"""

    ranked = rank_movies_for_user(

        candidates,

        context,

        f"🌱 越界推荐：用户平时接触较少的{chosen}领域，但要保证电影本身值得尝试。"
    )

    lookup = {

        movie["id"]:
            movie

        for movie in candidates
    }

    result = []

    for item in ranked:

        movie = lookup.get(
            item.get(
                "id"
            )
        )

        if movie:

            movie["match_score"] = safe_int(
                item.get(
                    "score",
                    65
                )
            )

            movie["reason"] = item.get(
                "reason",
                f"这是一部来自{chosen}领域的探索性推荐。"
            )

            result.append(
                movie
            )

    if not result:

        for movie in candidates[:3]:

            movie["match_score"] = 60

            movie["reason"] = (
                f"你平时较少接触{chosen}类型，"
                "这部电影适合作为一次小幅度的阅读兴趣迁移。"
            )

            result.append(
                movie
            )

    return result


# ============================================================
# 25. Book -> Movie
# ============================================================

def recommend_movie_from_book(
    book
):

    title = book.get(
        "title",
        "未知"
    )

    author = book.get(
        "author",
        ""
    )

    category = book.get(
        "category",
        "其他"
    )

    # --------------------------------------------------------
    # 第一步：根据书的标题找可能相关的电影
    # --------------------------------------------------------

    candidates = []

    try:

        candidates.extend(
            tmdb_search_movie(
                title,
                page=1
            )
        )

        # 第二页作为扩充
        candidates.extend(
            tmdb_search_movie(
                title,
                page=2
            )
        )

    except Exception:

        pass


    # --------------------------------------------------------
    # 如果同名/相关搜索不足
    # 根据书的类型去 Discover
    # --------------------------------------------------------

    if len(candidates) < 5:

        genre_id = None

        for keyword, gid in BOOK_CATEGORY_TO_MOVIE.items():

            if keyword in str(
                category
            ):

                genre_id = gid

                break

        if genre_id:

            try:

                candidates.extend(
                    tmdb_discover_movie(

                        genre_id=
                            genre_id,

                        sort_by=
                            "vote_average.desc",

                        page=1
                    )
                )

                candidates.extend(
                    tmdb_discover_movie(

                        genre_id=
                            genre_id,

                        sort_by=
                            "popularity.desc",

                        page=2
                    )
                )

            except Exception:

                pass


    # --------------------------------------------------------
    # 最终兜底
    # --------------------------------------------------------

    if len(candidates) < 3:

        try:

            candidates.extend(
                tmdb_discover_movie(
                    sort_by=
                        "popularity.desc",
                    page=1
                )
            )

        except Exception:

            pass


    candidates = clean_movie_candidates(
        candidates
    )

    context = f"""
用户选择的书：

《{title}》

作者：
{author}

微信读书分类：
{category}

用户阅读人格：
{st.session_state.personality.get(
    "code",
    ""
)}

用户整体阅读领域：
{json.dumps(
    st.session_state.profile.get(
        "category_distribution",
        {}
    ),
    ensure_ascii=False
)}
"""

    ranked = rank_movies_for_user(

        candidates,

        context,

        "📖→🎬 从一本书出发：优先寻找类型、主题、地区或审美气质上有联系的电影；不要求同名，也不要求完美匹配。"
    )

    lookup = {

        movie["id"]:
            movie

        for movie in candidates
    }

    result = []

    for item in ranked:

        movie = lookup.get(
            item.get(
                "id"
            )
        )

        if movie:

            movie["match_score"] = safe_int(
                item.get(
                    "score",
                    70
                )
            )

            movie["reason"] = item.get(
                "reason",
                "这部电影与这本书存在一定主题或气质上的联系。"
            )

            result.append(
                movie
            )

    # --------------------------------------------------------
    # 必须保证有结果
    # --------------------------------------------------------

    if not result:

        for index, movie in enumerate(
            candidates[:3]
        ):

            movie["match_score"] = (
                78 - index * 7
            )

            movie["reason"] = (
                f"它与《{title}》"
                "在类型或主题上存在一定关联，"
                "可以作为延伸观看。"
            )

            result.append(
                movie
            )

    return result


# ============================================================
# 26. Display Movies
# ============================================================

def display_movies(
    movies
):

    if not movies:

        st.info(
            "暂时没有拿到电影数据，请再探索一次。"
        )

        return

    for movie in movies:

        left, right = st.columns(
            [0.28, 0.72]
        )

        with left:

            if movie.get(
                "poster"
            ):

                st.image(
                    movie["poster"],
                    use_container_width=True
                )

            else:

                st.markdown(
                    "🎬"
                )

        with right:

            st.markdown(
                f"## 🎬 {movie.get('title', '未知')}"
            )

            if movie.get(
                "original_title"
            ):

                st.caption(
                    movie[
                        "original_title"
                    ]
                )

            release = movie.get(
                "release_date",
                ""
            )

            year = (
                release[:4]
                if release
                else "未知"
            )

            rating = safe_float(
                movie.get(
                    "rating",
                    0
                )
            )

            votes = safe_int(
                movie.get(
                    "vote_count",
                    0
                )
            )

            st.write(
                f"📅 {year}  ·  "
                f"⭐ {rating:.1f}  ·  "
                f"👥 {votes}人评分"
            )

            score = movie.get(
                "match_score"
            )

            if score is not None:

                st.progress(
                    min(
                        1,
                        score / 100
                    )
                )

                st.markdown(
                    f"**与你的匹配度：{score}/100**"
                )

            if movie.get(
                "reason"
            ):

                st.markdown(
                    f"""
                    <div class="movie-reason">
                    <b>为什么推荐：</b>
                    {movie["reason"]}
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            overview = movie.get(
                "overview",
                ""
            )

            if overview:

                st.write(
                    overview
                )

        st.markdown(
            "---"
        )


# ============================================================
# 27. Hero
# ============================================================

st.markdown(
    """
    <div class="hero">

    <div class="hero-title">
    📚 阅途
    </div>

    <div class="hero-subtitle">
    Personal Reading Growth Agent
    · 从你的阅读世界出发，继续探索
    </div>

    </div>
    """,
    unsafe_allow_html=True
)


# ============================================================
# 28. Connect Weread
# ============================================================

with st.expander(
    "🔑 连接微信读书",
    expanded=not st.session_state.is_ready
):

    weread_key = st.text_input(
        "微信读书 API Key",
        type="password",
        key="weread_api_key_input"
    )

    if st.button(
        "🚀 读取我的阅读世界",
        use_container_width=True,
        key="load_weread_button"
    ):

        if not weread_key.strip():

            st.error(
                "请输入微信读书 API Key。"
            )

        else:

            with st.spinner(
                "正在读取你的阅读世界……"
            ):

                try:

                    client = WereadClient(
                        weread_key
                    )

                    shelf_raw = run_async(
                        client.get_shelf()
                    )

                    stats_raw = run_async(
                        client.get_reading_stats()
                    )

                    notebooks_raw = run_async(
                        client.get_notebooks()
                    )

                    shelf_info = parse_shelf(
                        shelf_raw
                    )

                    stats_info = parse_stats(
                        stats_raw
                    )

                    notebook_info = parse_notebooks(
                        notebooks_raw
                    )

                    profile = build_profile(
                        shelf_info,
                        stats_info,
                        notebook_info
                    )

                    personality = (
                        calculate_personality(
                            profile
                        )
                    )

                    catalog = build_catalog(
                        shelf_info
                    )

                    agent = build_agent(
                        client,
                        profile,
                        catalog,
                        personality
                    )

                    st.session_state.weread_client = client

                    st.session_state.shelf = shelf_info

                    st.session_state.reading_stats = stats_info

                    st.session_state.notebooks = notebook_info

                    st.session_state.profile = profile

                    st.session_state.personality = personality

                    st.session_state.book_catalog = catalog

                    st.session_state.agent = agent

                    st.session_state.is_ready = True

                    st.session_state.movie_results = []

                    st.session_state.movie_mode = ""

                    st.session_state.movie_page = 1

                    st.session_state.messages = []

                    st.session_state.note_items = []

                    st.session_state.last_refresh = datetime.now()

                    st.success(
                        "✅ 阅读世界加载完成！"
                    )

                    st.rerun()

                except Exception as exc:

                    st.error(
                        f"❌ 加载失败：{exc}"
                    )


# ============================================================
# 29. Main
# ============================================================

if st.session_state.is_ready:

    profile = st.session_state.profile

    personality = st.session_state.personality

    catalog = st.session_state.book_catalog


    # --------------------------------------------------------
    # Header
    # --------------------------------------------------------

    st.markdown(
        f"""
        ## {personality['code']} · {personality['title']}

        > {personality['description']}

        {personality['sub']}
        """
    )


    # --------------------------------------------------------
    # Metrics
    # --------------------------------------------------------

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "📚 电子书",
        profile.get(
            "book_count",
            0
        )
    )

    c2.metric(
        "✅ 已读完",
        profile.get(
            "finished_books",
            0
        )
    )

    c3.metric(
        "⏰ 总阅读",
        format_seconds(
            profile.get(
                "total_read_time",
                0
            )
        )
    )

    c4.metric(
        "📝 笔记",
        profile.get(
            "total_notes",
            0
        )
    )


    # --------------------------------------------------------
    # Tabs
    # --------------------------------------------------------

    (
        tab_home,
        tab_personality,
        tab_notes,
        tab_goal,
        tab_books,
        tab_culture,
        tab_agent
    ) = st.tabs(

        [
            "🏠 首页",
            "🧠 阅读人格",
            "📝 我的笔记",
            "🎯 阅读计划",
            "📚 我的书架",
            "🎬 文化探索",
            "🤖 AI 阅读顾问"
        ]
    )


    # ========================================================
    # HOME
    # ========================================================

    with tab_home:

        left, right = st.columns(
            [1.4, 1]
        )

        with left:

            st.subheader(
                "🔥 今日阅读"
            )

            today_key = date.today().strftime(
                "%Y-%m-%d"
            )

            checked = (
                st.session_state.checkin_history.get(
                    today_key,
                    False
                )
            )

            streak = calculate_streak_safe(
                st.session_state.checkin_history
            )

            if checked:

                st.success(
                    f"✅ 今日已打卡"
                    f" · 连续 {streak} 天"
                )

            else:

                st.warning(
                    "今天还没有阅读打卡。"
                )

                if st.button(
                    "🔥 完成今日打卡",
                    use_container_width=True,
                    key="home_checkin"
                ):

                    st.session_state.checkin_history[
                        today_key
                    ] = True

                    st.rerun()


        with right:

            target = safe_int(
                st.session_state.annual_goal,
                50
            )

            finished = safe_int(
                profile.get(
                    "finished_books",
                    0
                )
            )

            progress = (
                finished / target
                if target
                else 0
            )

            st.subheader(
                "🎯 年度目标"
            )

            st.progress(
                min(
                    1,
                    progress
                )
            )

            st.markdown(
                f"### {finished} / {target} 本"
            )


        st.markdown(
            "---"
        )

        st.subheader(
            "🔔 阅读提醒"
        )

        reminders = get_reading_reminders(
            catalog
        )

        if reminders:

            for item in reminders:

                if item["days"] >= 30:

                    st.error(
                        f"📕《{item['title']}》"
                        f"已经 {item['days']} 天没有继续阅读。"
                    )

                else:

                    st.warning(
                        f"📖《{item['title']}》"
                        f"已经 {item['days']} 天没翻了。"
                    )

        else:

            st.success(
                "最近没有长期搁置的书。"
            )


        st.markdown(
            "---"
        )

        st.subheader(
            "📖 下一本读什么？"
        )

        if st.button(
            "🤖 让阅途决定",
            use_container_width=True,
            key="home_next_book"
        ):

            with st.spinner(
                "正在分析你的阅读轨迹……"
            ):

                try:

                    response = (
                        st.session_state.agent.invoke({

                            "messages": [

                                {
                                    "role":
                                        "user",

                                    "content":
                                        (
                                            "根据我的真实阅读数据，"
                                            "决定下一本值得读什么。"
                                            "给出1本主推荐和2本备选。"
                                        )
                                }

                            ]
                        })
                    )

                    answer = ""

                    for msg in reversed(
                        response.get(
                            "messages",
                            []
                        )
                    ):

                        if getattr(
                            msg,
                            "type",
                            None
                        ) == "ai":

                            content = getattr(
                                msg,
                                "content",
                                ""
                            )

                            if isinstance(
                                content,
                                str
                            ):

                                answer = content
                                break

                    st.markdown(
                        answer
                    )

                except Exception as exc:

                    st.error(
                        str(exc)
                    )


    # ========================================================
    # PERSONALITY
    # ========================================================

    with tab_personality:

        st.subheader(
            "🧠 我的阅读人格"
        )

        st.markdown(
            f"# {personality['code']}"
        )

        st.markdown(
            f"## {personality['title']}"
        )

        st.write(
            personality["description"]
        )

        st.caption(
            "娱乐化阅读画像，不是心理学人格诊断。"
        )

        values = [

            75
            if personality["code"][0] == "E"
            else 25,

            75
            if personality["code"][1] == "N"
            else 25,

            75
            if personality["code"][2] == "T"
            else 25,

            75
            if personality["code"][3] == "J"
            else 25
        ]

        fig = go.Figure()

        fig.add_trace(

            go.Bar(

                x=[
                    "广度",
                    "主题",
                    "分析",
                    "规划"
                ],

                y=values
            )
        )

        fig.update_layout(
            height=350,
            yaxis=dict(
                range=[0, 100]
            ),
            showlegend=False
        )

        st.plotly_chart(
            fig,
            use_container_width=True,
            key="personality_chart"
        )

        distribution = profile.get(
            "category_distribution",
            {}
        )

        if distribution:

            st.subheader(
                "📚 我的阅读地图"
            )

            fig2 = go.Figure(

                data=[
                    go.Pie(

                        labels=list(
                            distribution.keys()
                        ),

                        values=list(
                            distribution.values()
                        ),

                        hole=0.45
                    )
                ]
            )

            fig2.update_layout(
                height=420
            )

            st.plotly_chart(
                fig2,
                use_container_width=True,
                key="category_chart"
            )

        if st.button(
            "🔥 AI锐评我的阅读",
            use_container_width=True,
            key="personality_roast"
        ):

            with st.spinner(
                "正在研究你的阅读黑历史……"
            ):

                try:

                    model = get_deepseek_model()

                    prompt = f"""
请锐评这个用户的阅读行为。

人格：
{json.dumps(
    personality,
    ensure_ascii=False
)}

数据：
{json.dumps(
    profile,
    ensure_ascii=False
)}

要求：
具体、幽默、可以稍微刻薄，
但不能恶意攻击。
至少指出3个真实阅读特征。
"""

                    result = model.invoke(
                        prompt
                    )

                    st.markdown(
                        str(
                            result.content
                        )
                    )

                except Exception as exc:

                    st.error(
                        str(exc)
                    )


    # ========================================================
    # NOTES
    # ========================================================

    with tab_notes:

        st.subheader(
            "📝 我的阅读痕迹"
        )

        st.write(
            "查看真实划线与想法，再让 AI 进行分析。"
        )

        book_options = {

            f"{book.get('title', '未知')}｜{book.get('bookId', '')}":
                book.get(
                    "bookId"
                )

            for book in catalog

            if book.get(
                "bookId"
            )
        }

        if book_options:

            selected_note_key = st.selectbox(

                "选择一本书",

                list(
                    book_options.keys()
                ),

                key="notes_book_select"
            )

            selected_note_id = (
                book_options[
                    selected_note_key
                ]
            )

            if st.button(
                "📖 读取这本书的划线和想法",
                use_container_width=True,
                key="load_notes_button"
            ):

                with st.spinner(
                    "正在读取……"
                ):

                    try:

                        bookmarks_raw = run_async(
                            st.session_state.weread_client.get_bookmarks(
                                selected_note_id
                            )
                        )

                        reviews_raw = run_async(
                            st.session_state.weread_client.get_reviews(
                                selected_note_id
                            )
                        )

                        bookmarks = bookmarks_raw.get(
                            "updated",
                            []
                        )

                        reviews = reviews_raw.get(
                            "reviews",
                            []
                        )

                        if not isinstance(
                            bookmarks,
                            list
                        ):

                            bookmarks = []

                        if not isinstance(
                            reviews,
                            list
                        ):

                            reviews = []

                        chapters = {

                            str(
                                x.get(
                                    "chapterUid"
                                )
                            ):
                                x.get(
                                    "title",
                                    ""
                                )

                            for x in bookmarks_raw.get(
                                "chapters",
                                []
                            )

                            if isinstance(
                                x,
                                dict
                            )
                        }

                        items = []

                        for mark in bookmarks:

                            if not isinstance(
                                mark,
                                dict
                            ):

                                continue

                            items.append({

                                "type":
                                    "highlight",

                                "chapter":
                                    chapters.get(
                                        str(
                                            mark.get(
                                                "chapterUid"
                                            )
                                        ),
                                        ""
                                    ),

                                "text":
                                    mark.get(
                                        "markText",
                                        ""
                                    ),

                                "thought":
                                    ""
                            })


                        for item in reviews:

                            if not isinstance(
                                item,
                                dict
                            ):

                                continue

                            review = item.get(
                                "review",
                                item
                            )

                            if not isinstance(
                                review,
                                dict
                            ):

                                continue

                            items.append({

                                "type":
                                    "thought",

                                "chapter":
                                    review.get(
                                        "chapterName",
                                        ""
                                    ),

                                "text":
                                    review.get(
                                        "abstract",
                                        ""
                                    ),

                                "thought":
                                    review.get(
                                        "content",
                                        ""
                                    )
                            })


                        st.session_state.note_items = items

                    except Exception as exc:

                        st.error(
                            f"读取失败：{exc}"
                        )


            notes = (
                st.session_state.note_items
            )

            if notes:

                for idx, item in enumerate(
                    notes[:50]
                ):

                    if item["type"] == "highlight":

                        with st.expander(
                            f"📌 划线 #{idx + 1}",
                            key=f"highlight_expander_{idx}"
                        ):

                            st.markdown(
                                f"> {item['text']}"
                            )

                            if item["chapter"]:

                                st.caption(
                                    item["chapter"]
                                )

                            if st.button(
                                "🤖 AI分析",
                                key=f"highlight_ai_{idx}"
                            ):

                                with st.spinner(
                                    "AI正在分析……"
                                ):

                                    try:

                                        result = (
                                            analyze_note_with_ai(

                                                selected_note_key.split(
                                                    "｜"
                                                )[0],

                                                item["text"]
                                            )
                                        )

                                        st.markdown(
                                            "### 🤖 AI分析"
                                        )

                                        st.write(
                                            result
                                        )

                                    except Exception as exc:

                                        st.error(
                                            str(exc)
                                        )

                    else:

                        with st.expander(
                            f"💭 我的想法 #{idx + 1}",
                            key=f"thought_expander_{idx}"
                        ):

                            if item["text"]:

                                st.markdown(
                                    "**关联原文：**"
                                )

                                st.markdown(
                                    f"> {item['text']}"
                                )

                            st.markdown(
                                "**我的想法：**"
                            )

                            st.write(
                                item["thought"]
                                or "没有记录想法。"
                            )

                            if st.button(
                                "🔥 AI锐评",
                                key=f"thought_ai_{idx}"
                            ):

                                with st.spinner(
                                    "AI正在认真审视……"
                                ):

                                    try:

                                        result = (
                                            analyze_note_with_ai(

                                                selected_note_key.split(
                                                    "｜"
                                                )[0],

                                                item["text"],

                                                item["thought"]
                                            )
                                        )

                                        st.markdown(
                                            "### 🔥 AI锐评"
                                        )

                                        st.write(
                                            result
                                        )

                                    except Exception as exc:

                                        st.error(
                                            str(exc)
                                        )


    # ========================================================
    # GOALS
    # ========================================================

    with tab_goal:

        st.subheader(
            "🎯 阅读目标"
        )

        a, b = st.columns(2)

        with a:

            annual_goal = st.number_input(

                "年度读书目标",

                min_value=1,

                max_value=500,

                value=safe_int(
                    st.session_state.annual_goal,
                    50
                ),

                key="annual_goal_widget"
            )

        with b:

            monthly_goal = st.number_input(

                "月度读书目标",

                min_value=1,

                max_value=50,

                value=safe_int(
                    st.session_state.monthly_goal,
                    4
                ),

                key="monthly_goal_widget"
            )

        if st.button(
            "💾 保存目标",
            key="save_goals_button"
        ):

            st.session_state.annual_goal = int(
                annual_goal
            )

            st.session_state.monthly_goal = int(
                monthly_goal
            )

            st.success(
                "目标已保存。"
            )

        finished = safe_int(
            profile.get(
                "finished_books",
                0
            )
        )

        target = safe_int(
            st.session_state.annual_goal,
            50
        )

        ratio = (
            finished / target
            if target
            else 0
        )

        st.progress(
            min(
                1,
                ratio
            )
        )

        st.markdown(
            f"### {finished} / {target} 本"
        )

        st.markdown(
            "---"
        )

        streak = calculate_streak_safe(
            st.session_state.checkin_history
        )

        st.metric(
            "🔥 连续阅读",
            f"{streak} 天"
        )

        today_key = date.today().strftime(
            "%Y-%m-%d"
        )

        if st.session_state.checkin_history.get(
            today_key,
            False
        ):

            st.success(
                "✅ 今天已经打卡"
            )

        else:

            if st.button(
                "🔥 今天打卡",
                key="goal_checkin"
            ):

                st.session_state.checkin_history[
                    today_key
                ] = True

                st.rerun()

        st.subheader(
            "📅 最近30天"
        )

        cols = st.columns(
            10
        )

        for i in range(30):

            d = (
                date.today()
                -
                timedelta(
                    days=29 - i
                )
            )

            key = d.strftime(
                "%Y-%m-%d"
            )

            with cols[
                i % 10
            ]:

                if st.session_state.checkin_history.get(
                    key,
                    False
                ):

                    st.success(
                        d.strftime(
                            "%m/%d"
                        )
                    )

                else:

                    st.caption(
                        d.strftime(
                            "%m/%d"
                        )
                    )


    # ========================================================
    # BOOKS
    # ========================================================

    with tab_books:

        st.subheader(
            "📚 我的书架"
        )

        search_text = st.text_input(

            "搜索书名 / 作者",

            key="bookshelf_search"
        )

        display_books = catalog

        if search_text.strip():

            q = search_text.strip().lower()

            display_books = [

                book

                for book in catalog

                if (
                    q
                    in str(
                        book.get(
                            "title",
                            ""
                        )
                    ).lower()

                    or

                    q
                    in str(
                        book.get(
                            "author",
                            ""
                        )
                    ).lower()
                )
            ]

        st.caption(
            f"显示 {len(display_books)} 本"
        )

        for start in range(
            0,
            min(
                len(display_books),
                36
            ),
            3
        ):

            row = display_books[
                start:start + 3
            ]

            cols = st.columns(
                len(row)
            )

            for col, book in zip(
                cols,
                row
            ):

                with col:

                    cover = book.get(
                        "cover",
                        ""
                    )

                    if cover:

                        try:

                            st.image(
                                cover,
                                use_container_width=True
                            )

                        except Exception:

                            pass

                    st.markdown(
                        f"### "
                        f"{book.get('title', '未知')}"
                    )

                    st.caption(
                        book.get(
                            "author",
                            "未知作者"
                        )
                    )

                    if safe_int(
                        book.get(
                            "finishReading",
                            0
                        )
                    ) == 1:

                        st.success(
                            "✅ 已读完"
                        )

                    else:

                        st.warning(
                            "📖 未读完"
                        )


    # ========================================================
    # CULTURE
    # ========================================================

    with tab_culture:

        st.subheader(
            "🎬 文化探索"
        )

        st.caption(
            "从你的阅读世界出发，探索电影。"
        )

        mode = st.radio(

            "选择探索模式",

            [
                "❤️ 共鸣推荐",
                "🌱 越界推荐",
                "📖→🎬 从一本书出发"
            ],

            horizontal=True,

            key="culture_mode"
        )


        # ----------------------------------------------------
        # Similar
        # ----------------------------------------------------

        if mode == "❤️ 共鸣推荐":

            st.markdown(
                "### ❤️ 你可能会喜欢"
            )

            st.write(
                "主要根据你的阅读类型、语言与兴趣寻找电影。"
            )

            if st.button(
                "🎬 换一批",
                use_container_width=True,
                key="similar_movie_button"
            ):

                if not TMDB_API_TOKEN:

                    st.error(
                        "没有配置 TMDB_API_TOKEN。"
                    )

                else:

                    st.session_state.movie_page += 1

                    with st.spinner(
                        "正在寻找另一批电影……"
                    ):

                        try:

                            results = (
                                recommend_similar_movies()
                            )

                            st.session_state.movie_results = results

                            st.session_state.movie_mode = mode

                        except Exception as exc:

                            st.error(
                                f"推荐失败：{exc}"
                            )


            if (
                st.session_state.movie_mode
                == mode
            ):

                display_movies(
                    st.session_state.movie_results
                )


        # ----------------------------------------------------
        # Explore
        # ----------------------------------------------------

        elif mode == "🌱 越界推荐":

            st.markdown(
                "### 🌱 离开你的舒适区"
            )

            st.write(
                "故意找你平时较少接触的电影类型。"
            )

            if st.button(
                "🌱 换一个陌生领域",
                use_container_width=True,
                key="explore_movie_button"
            ):

                if not TMDB_API_TOKEN:

                    st.error(
                        "没有配置 TMDB_API_TOKEN。"
                    )

                else:

                    st.session_state.movie_page += 1

                    with st.spinner(
                        "正在寻找新的领域……"
                    ):

                        try:

                            results = (
                                recommend_explore_movies()
                            )

                            st.session_state.movie_results = results

                            st.session_state.movie_mode = mode

                        except Exception as exc:

                            st.error(
                                f"推荐失败：{exc}"
                            )


            if (
                st.session_state.movie_mode
                == mode
            ):

                display_movies(
                    st.session_state.movie_results
                )


        # ----------------------------------------------------
        # Book -> Movie
        # ----------------------------------------------------

        else:

            st.markdown(
                "### 📖 → 🎬 从一本书出发"
            )

            st.write(
                "先识别书的类型，再寻找有共鸣的电影。"
            )

            movie_book_options = {

                f"{book.get('title', '未知')}｜{book.get('bookId', '')}":
                    book

                for book in catalog

            }

            if movie_book_options:

                selected_movie_book = st.selectbox(

                    "选择一本书",

                    list(
                        movie_book_options.keys()
                    ),

                    key="movie_source_book_select"
                )

                if st.button(
                    "🎬 从这本书出发",
                    use_container_width=True,
                    key="book_movie_button"
                ):

                    if not TMDB_API_TOKEN:

                        st.error(
                            "没有配置 TMDB_API_TOKEN。"
                        )

                    else:

                        with st.spinner(
                            "正在理解这本书……"
                        ):

                            try:

                                results = (
                                    recommend_movie_from_book(

                                        movie_book_options[
                                            selected_movie_book
                                        ]
                                    )
                                )

                                st.session_state.movie_results = results

                                st.session_state.movie_mode = mode

                                st.session_state.movie_source_book = (
                                    selected_movie_book
                                )

                            except Exception as exc:

                                st.error(
                                    f"推荐失败：{exc}"
                                )


                if (
                    st.session_state.movie_mode
                    == mode
                ):

                    display_movies(
                        st.session_state.movie_results
                    )

            else:

                st.info(
                    "当前没有书籍。"
                )


    # ========================================================
    # AGENT
    # ========================================================

    with tab_agent:

        st.subheader(
            "🤖 与阅途对话"
        )

        st.caption(
            "推荐、锐评、笔记、阅读成果检验，都可以直接聊天。"
        )

        q1, q2, q3, q4 = st.columns(4)

        if q1.button(
            "📖 下一本读什么？",
            use_container_width=True,
            key="chat_next"
        ):

            st.session_state.quick_query = (
                "根据我的真实阅读数据，帮我决定下一本读什么。"
            )

        if q2.button(
            "🔥 锐评我的书架",
            use_container_width=True,
            key="chat_roast"
        ):

            st.session_state.quick_query = (
                "请锐评我的书架和阅读习惯。"
            )

        if q3.button(
            "🧠 阅读人格",
            use_container_width=True,
            key="chat_mbti"
        ):

            st.session_state.quick_query = (
                "分析我的阅读人格和阅读盲区。"
            )

        if q4.button(
            "🎓 检验阅读成果",
            use_container_width=True,
            key="chat_test"
        ):

            st.session_state.quick_query = (
                "我想检验自己是否真的读懂了一本书。"
                "请选择一本书，然后一次问我一个问题。"
            )


        for message in st.session_state.messages:

            with st.chat_message(
                message["role"]
            ):

                st.markdown(
                    message["content"]
                )


        prompt = st.chat_input(

            "告诉阅途你正在想什么……",

            key="main_agent_chat"
        )


        if (
            not prompt
            and
            st.session_state.quick_query
        ):

            prompt = (
                st.session_state.quick_query
            )

            st.session_state.quick_query = ""


        if prompt:

            st.session_state.messages.append({

                "role":
                    "user",

                "content":
                    prompt
            })

            with st.chat_message(
                "user"
            ):

                st.markdown(
                    prompt
                )

            with st.chat_message(
                "assistant"
            ):

                with st.spinner(
                    "阅途正在思考……"
                ):

                    try:

                        history = (
                            st.session_state.messages[
                                -12:
                            ]
                        )

                        response = (
                            st.session_state.agent.invoke({

                                "messages":
                                    history
                            })
                        )

                        answer = (
                            "暂时没有得到有效回答。"
                        )

                        for msg in reversed(
                            response.get(
                                "messages",
                                []
                            )
                        ):

                            if getattr(
                                msg,
                                "type",
                                None
                            ) != "ai":

                                continue

                            content = getattr(
                                msg,
                                "content",
                                ""
                            )

                            if isinstance(
                                content,
                                str
                            ) and content.strip():

                                answer = content

                                break

                        st.markdown(
                            answer
                        )

                        st.session_state.messages.append({

                            "role":
                                "assistant",

                            "content":
                                answer
                        })

                    except Exception as exc:

                        st.error(
                            f"❌ Agent调用失败：{exc}"
                        )

        if st.button(
            "🗑️ 清空对话",
            key="clear_chat"
        ):

            st.session_state.messages = []

            st.rerun()


else:

    st.info(
        "👆 请先连接微信读书。"
    )


# ============================================================
# 30. Footer
# ============================================================

st.markdown(
    "---"
)

st.caption(
    "阅途 · Personal Reading Growth Agent "
    "· LangChain + DeepSeek + 微信读书 + TMDB"
)
