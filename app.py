"""
📚 阅途 · Personal Reading Growth Agent
主入口文件 - 已删除电影推荐功能
"""
import os
import json
import random
from datetime import datetime, date, timedelta

import streamlit as st
import plotly.graph_objects as go

from config import TMDB_API_TOKEN, DEFAULT_ANNUAL_GOAL, DEFAULT_MONTHLY_GOAL
from database import db
from utils.helpers import (
    run_async, safe_int, safe_float, format_seconds,
    calculate_streak, get_week_range
)
from core.weread_client import WereadClient
from core.parser import (
    parse_shelf, parse_stats, parse_notebooks,
    build_profile, build_catalog, get_reading_reminders
)
from core.personality import calculate_personality
from core.agent import build_agent, get_deepseek_model
from features.reading_chronotype import (
    analyze_reading_chronotype, create_chronotype_chart
)
from features.weekly_report import (
    generate_weekly_report, generate_weekly_report_text,
    create_weekly_heatmap
)
from features.shelf_organizer import organize_shelf, get_reading_priority_list
from features.daily_quote import (
    get_daily_quote_from_catalog,
    get_quote_from_specific_book,
    refresh_cache as refresh_quote_cache
)
from features.yearly_report import (
    generate_yearly_report, generate_yearly_report_text,
    create_yearly_chart
)


# ============================================================
# Page Config
# ============================================================

st.set_page_config(
    page_title="阅途 · Personal Reading Growth Agent",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# CSS
# ============================================================

st.markdown("""
<style>
.block-container { max-width: 1250px; padding-top: 2rem; padding-bottom: 4rem; }
.hero {
    padding: 2.2rem 2.5rem;
    border-radius: 28px;
    background: linear-gradient(135deg, #f4f0ff 0%, #eef7ff 50%, #fff5ec 100%);
    margin-bottom: 1.5rem;
    border: 1px solid #ececec;
}
.hero-title { font-size: 2.6rem; font-weight: 800; }
.hero-subtitle { color: #666; font-size: 1rem; margin-top: .4rem; }
.quote-card {
    padding: 1.5rem 2rem;
    background: linear-gradient(135deg, #f8f6ff 0%, #f0f4ff 100%);
    border-radius: 18px;
    border-left: 5px solid #7c6cf0;
    margin: 1rem 0;
}
.quote-card .quote-text { font-size: 1.3rem; font-weight: 500; color: #2c3e50; line-height: 1.8; }
.quote-card .quote-meta { color: #888; font-size: 0.9rem; margin-top: 0.8rem; }
.quote-card .quote-source { font-weight: 600; color: #7c6cf0; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# Session State
# ============================================================

DEFAULT_STATE = {
    "user_id": None,
    "api_key": None,
    "weread_client": None,
    "agent": None,
    "is_ready": False,
    "book_catalog": [],
    "shelf": {},
    "reading_stats": {},
    "notebooks": {},
    "profile": {},
    "personality": {},
    "note_items": [],
    "messages": [],
    "annual_goal": DEFAULT_ANNUAL_GOAL,
    "monthly_goal": DEFAULT_MONTHLY_GOAL,
    "checkin_history": {},
    "quick_query": "",
    "last_refresh": None,
    "daily_quote": None,
    "daily_quote_loaded": False,  # ✅ 新增字段
    "yearly_report": None,
    "yearly_report_year": None,
    "quote_seed": None,
    "data_loaded": False
}

for key, value in DEFAULT_STATE.items():
    if key not in st.session_state:
        if isinstance(value, dict):
            st.session_state[key] = dict(value)
        elif isinstance(value, list):
            st.session_state[key] = list(value)
        else:
            st.session_state[key] = value


# ============================================================
# 生成用户ID
# ============================================================

def generate_user_id(api_key: str) -> str:
    import hashlib
    return hashlib.md5(api_key.encode()).hexdigest()[:16]


# ============================================================
# 数据库操作
# ============================================================

def load_user_from_db(user_id: str) -> bool:
    user_data = db.get_user_data(user_id)
    if not user_data:
        return False

    st.session_state.profile = user_data.get('profile', {})
    st.session_state.personality = user_data.get('personality', {})
    st.session_state.annual_goal = user_data.get('annual_goal', DEFAULT_ANNUAL_GOAL)
    st.session_state.monthly_goal = user_data.get('monthly_goal', DEFAULT_MONTHLY_GOAL)
    st.session_state.last_refresh = user_data.get('last_refresh')

    st.session_state.checkin_history = db.get_checkin_history(user_id)
    st.session_state.messages = db.get_messages(user_id, 50)

    cached = db.get_shelf_cache(user_id)
    if cached:
        st.session_state.book_catalog = cached.get('catalog', [])
        st.session_state.shelf = cached.get('shelf_info', {})
        st.session_state.reading_stats = cached.get('reading_stats', {})
        st.session_state.notebooks = cached.get('notebooks_info', {})

    return True


def save_user_to_db(user_id: str):
    db.save_user_data(user_id, {
        'api_key': st.session_state.api_key,
        'profile': st.session_state.profile,
        'personality': st.session_state.personality,
        'annual_goal': st.session_state.annual_goal,
        'monthly_goal': st.session_state.monthly_goal,
        'last_refresh': datetime.now().strftime("%Y-%m-%d %H:%M")
    })

    for date_str, checked in st.session_state.checkin_history.items():
        db.toggle_checkin(user_id, date_str, checked)

    db.save_shelf_cache(user_id, {
        'catalog': st.session_state.book_catalog,
        'shelf_info': st.session_state.shelf,
        'reading_stats': st.session_state.reading_stats,
        'notebooks_info': st.session_state.notebooks,
    })


def sync_reading_data(user_id: str, api_key: str, force_full_scan: bool = False):
    client = WereadClient(api_key)
    shelf_raw = run_async(client.get_shelf())
    stats_raw = run_async(client.get_reading_stats())
    notebooks_raw = run_async(client.get_notebooks())

    new_shelf_info = parse_shelf(shelf_raw)
    new_stats_info = parse_stats(stats_raw)
    new_notebook_info = parse_notebooks(notebooks_raw)
    new_catalog = build_catalog(new_shelf_info)

    cached_book_ids = set()
    for book in st.session_state.book_catalog:
        book_id = book.get("bookId")
        if book_id:
            cached_book_ids.add(book_id)

    new_book_ids = set()
    for book in new_catalog:
        book_id = book.get("bookId")
        if book_id:
            new_book_ids.add(book_id)

    if force_full_scan or not st.session_state.book_catalog:
        need_full_scan = True
    else:
        new_books = new_book_ids - cached_book_ids
        total_books = max(len(cached_book_ids), 1)
        new_ratio = len(new_books) / total_books
        need_full_scan = new_ratio > 0.3

    if need_full_scan:
        profile = build_profile(new_shelf_info, new_stats_info, new_notebook_info)
        personality = calculate_personality(profile)
        catalog = new_catalog
        agent = build_agent(client, profile, catalog, personality)

        st.session_state.shelf = new_shelf_info
        st.session_state.reading_stats = new_stats_info
        st.session_state.notebooks = new_notebook_info
        st.session_state.profile = profile
        st.session_state.personality = personality
        st.session_state.book_catalog = catalog
        st.session_state.agent = agent
    else:
        existing_titles = {book.get("title"): book for book in st.session_state.book_catalog}
        for book in new_catalog:
            title = book.get("title")
            if title not in existing_titles:
                st.session_state.book_catalog.append(book)

        st.session_state.shelf = new_shelf_info
        st.session_state.reading_stats = new_stats_info
        st.session_state.notebooks = new_notebook_info

        profile = build_profile(new_shelf_info, new_stats_info, new_notebook_info)
        personality = calculate_personality(profile)
        st.session_state.profile = profile
        st.session_state.personality = personality

        agent = build_agent(client, profile, st.session_state.book_catalog, personality)
        st.session_state.agent = agent

    st.session_state.weread_client = client
    st.session_state.is_ready = True
    st.session_state.last_refresh = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_user_to_db(user_id)
    return True


# ============================================================
# Hero
# ============================================================

st.markdown("""
<div class="hero">
<div class="hero-title">📚 阅途</div>
<div class="hero-subtitle">Personal Reading Growth Agent · 从你的阅读世界出发，继续探索</div>
</div>
""", unsafe_allow_html=True)


# ============================================================
# Connect Weread
# ============================================================

if not st.session_state.data_loaded:
    if st.session_state.api_key:
        user_id = generate_user_id(st.session_state.api_key)
        if load_user_from_db(user_id):
            st.session_state.user_id = user_id
            st.session_state.is_ready = True
            st.session_state.data_loaded = True

with st.expander("🔑 连接微信读书", expanded=not st.session_state.is_ready):
    weread_key = st.text_input(
        "微信读书 API Key",
        type="password",
        key="weread_api_key_input",
        value=st.session_state.api_key or ""
    )

    col_load, col_status = st.columns([1, 2])

    with col_load:
        load_button = st.button("🚀 读取我的阅读世界", use_container_width=True)

    with col_status:
        if st.session_state.is_ready and st.session_state.last_refresh:
            st.caption(f"✅ 已连接 · 数据更新于：{st.session_state.last_refresh}")
            st.caption(f"📚 共 {len(st.session_state.book_catalog)} 本书")
        elif st.session_state.is_ready:
            st.caption("✅ 已连接")

    if load_button:
        if not weread_key.strip():
            st.error("请输入微信读书 API Key。")
        else:
            user_id = generate_user_id(weread_key)
            st.session_state.user_id = user_id
            st.session_state.api_key = weread_key

            has_cache = load_user_from_db(user_id)

            if has_cache:
                with st.spinner("📂 已加载缓存数据，正在检查新增书籍..."):
                    try:
                        sync_reading_data(user_id, weread_key, force_full_scan=False)
                        refresh_quote_cache(user_id)
                        st.session_state.daily_quote = None
                        st.session_state.daily_quote_loaded = False
                        st.session_state.data_loaded = True
                        st.success("✅ 阅读世界已更新！")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"❌ 更新失败：{exc}")
            else:
                with st.spinner("📚 首次加载，正在扫描你的阅读世界..."):
                    try:
                        sync_reading_data(user_id, weread_key, force_full_scan=True)
                        st.session_state.data_loaded = True
                        st.success("✅ 阅读世界加载完成！")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"❌ 加载失败：{exc}")


# ============================================================
# Main
# ============================================================

if st.session_state.is_ready:
    profile = st.session_state.profile
    personality = st.session_state.personality
    catalog = st.session_state.book_catalog
    user_id = st.session_state.user_id

    if not profile or not catalog:
        st.warning("📂 请点击「读取我的阅读世界」加载你的阅读数据。")
    else:
        st.markdown(f"""
        ## {personality['code']} · {personality['title']}
        > {personality['description']}
        {personality['sub']}
        """)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("📚 电子书", profile.get("book_count", 0))
        c2.metric("✅ 已读完", profile.get("finished_books", 0))
        c3.metric("⏰ 总阅读", format_seconds(profile.get("total_read_time", 0)))
        c4.metric("📝 笔记", profile.get("total_notes", 0))

        # ========================================================
        # Tabs
        # ========================================================

        tab_home, tab_personality, tab_notes, tab_goal, tab_books, tab_features, tab_agent = st.tabs([
            "🏠 首页",
            "🧠 阅读人格",
            "📝 我的笔记",
            "🎯 阅读计划",
            "📚 我的书架",
            "✨ 新功能",
            "🤖 AI 阅读顾问"
        ])


        # ========================================================
        # HOME
        # ========================================================

        with tab_home:
            left, right = st.columns([1.4, 1])

            with left:
                st.subheader("🔥 今日阅读")
                today_key = date.today().strftime("%Y-%m-%d")
                checked = st.session_state.checkin_history.get(today_key, False)
                streak = calculate_streak(st.session_state.checkin_history)

                if checked:
                    st.success(f"✅ 今日已打卡 · 连续 {streak} 天")
                else:
                    st.warning("今天还没有阅读打卡。")
                    if st.button("🔥 完成今日打卡", use_container_width=True):
                        st.session_state.checkin_history[today_key] = True
                        db.toggle_checkin(user_id, today_key, True)
                        st.rerun()

            with right:
                target = safe_int(st.session_state.annual_goal, DEFAULT_ANNUAL_GOAL)
                finished = safe_int(profile.get("finished_books", 0))
                progress = min(1, finished / target if target else 0)

                st.subheader("🎯 年度目标")
                st.progress(progress)
                st.markdown(f"### {finished} / {target} 本")

            st.markdown("---")
            st.subheader("🔔 阅读提醒")
            reminders = get_reading_reminders(catalog)
            if reminders:
                for item in reminders:
                    if item["days"] >= 30:
                        st.error(f"📕《{item['title']}》已经 {item['days']} 天没有继续阅读。")
                    else:
                        st.warning(f"📖《{item['title']}》已经 {item['days']} 天没翻了。")
            else:
                st.success("最近没有长期搁置的书。")


        # ========================================================
        # PERSONALITY
        # ========================================================

        with tab_personality:
            st.subheader("🧠 我的阅读人格")
            st.markdown(f"# {personality['code']}")
            st.markdown(f"## {personality['title']}")
            st.write(personality["description"])
            st.caption("娱乐化阅读画像，不是心理学人格诊断。")

            values = [
                75 if personality["code"][0] == "E" else 25,
                75 if personality["code"][1] == "N" else 25,
                75 if personality["code"][2] == "T" else 25,
                75 if personality["code"][3] == "J" else 25
            ]
            fig = go.Figure()
            fig.add_trace(go.Bar(x=["广度", "主题", "分析", "规划"], y=values))
            fig.update_layout(height=350, yaxis=dict(range=[0, 100]), showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

            distribution = profile.get("category_distribution", {})
            if distribution:
                st.subheader("📚 我的阅读地图")
                fig2 = go.Figure(data=[go.Pie(
                    labels=list(distribution.keys()),
                    values=list(distribution.values()),
                    hole=0.45
                )])
                fig2.update_layout(height=420)
                st.plotly_chart(fig2, use_container_width=True)

            if st.button("🔥 AI锐评我的阅读", use_container_width=True):
                with st.spinner("正在研究你的阅读黑历史……"):
                    try:
                        model = get_deepseek_model()
                        prompt = f"请锐评这个用户的阅读行为。人格：{json.dumps(personality, ensure_ascii=False)}，数据：{json.dumps(profile, ensure_ascii=False)}。要求：具体、幽默、可以稍微刻薄，至少指出3个真实阅读特征。"
                        result = model.invoke(prompt)
                        st.markdown(str(result.content))
                    except Exception as exc:
                        st.error(str(exc))


        # ========================================================
        # NOTES
        # ========================================================

        with tab_notes:
            st.subheader("📝 我的阅读痕迹")
            st.write("查看真实划线与想法。")

            book_options = {
                f"{book.get('title', '未知')}": book.get("bookId")
                for book in catalog if book.get("bookId")
            }

            if book_options:
                selected_note_key = st.selectbox("选择一本书", list(book_options.keys()), key="notes_book_select")
                selected_note_id = book_options[selected_note_key]

                if st.button("📖 读取划线和想法", use_container_width=True):
                    with st.spinner("正在读取……"):
                        try:
                            bookmarks_raw = run_async(st.session_state.weread_client.get_bookmarks(selected_note_id))
                            reviews_raw = run_async(st.session_state.weread_client.get_reviews(selected_note_id))

                            items = []
                            for mark in bookmarks_raw.get("updated", []):
                                if isinstance(mark, dict):
                                    items.append({"type": "highlight", "text": mark.get("markText", "")})
                            for item in reviews_raw.get("reviews", []):
                                if isinstance(item, dict):
                                    review = item.get("review", item)
                                    if isinstance(review, dict):
                                        items.append({"type": "thought", "text": review.get("abstract", ""), "thought": review.get("content", "")})

                            st.session_state.note_items = items
                            st.success(f"✅ 读取到 {len(items)} 条记录")
                        except Exception as exc:
                            st.error(f"读取失败：{exc}")

                notes = st.session_state.note_items
                if notes:
                    for idx, item in enumerate(notes[:30]):
                        if item["type"] == "highlight":
                            with st.expander(f"📌 划线 #{idx+1}"):
                                st.markdown(f"> {item['text']}")
                        else:
                            with st.expander(f"💭 想法 #{idx+1}"):
                                st.write(item.get("thought", "无"))


        # ========================================================
        # GOALS
        # ========================================================

        with tab_goal:
            st.subheader("🎯 阅读目标")

            a, b = st.columns(2)
            with a:
                annual_goal = st.number_input("年度目标", min_value=1, max_value=500, value=safe_int(st.session_state.annual_goal, DEFAULT_ANNUAL_GOAL))
            with b:
                monthly_goal = st.number_input("月度目标", min_value=1, max_value=50, value=safe_int(st.session_state.monthly_goal, DEFAULT_MONTHLY_GOAL))

            if st.button("💾 保存目标"):
                st.session_state.annual_goal = int(annual_goal)
                st.session_state.monthly_goal = int(monthly_goal)
                db.save_user_data(user_id, {
                    'api_key': st.session_state.api_key,
                    'profile': st.session_state.profile,
                    'personality': st.session_state.personality,
                    'annual_goal': st.session_state.annual_goal,
                    'monthly_goal': st.session_state.monthly_goal,
                    'last_refresh': st.session_state.last_refresh
                })
                st.success("目标已保存。")

            finished = safe_int(profile.get("finished_books", 0))
            target = safe_int(st.session_state.annual_goal, DEFAULT_ANNUAL_GOAL)
            st.progress(min(1, finished / target if target else 0))
            st.markdown(f"### {finished} / {target} 本")

            st.markdown("---")
            streak = calculate_streak(st.session_state.checkin_history)
            st.metric("🔥 连续阅读", f"{streak} 天")

            today_key = date.today().strftime("%Y-%m-%d")
            if not st.session_state.checkin_history.get(today_key, False):
                if st.button("🔥 今天打卡"):
                    st.session_state.checkin_history[today_key] = True
                    db.toggle_checkin(user_id, today_key, True)
                    st.rerun()
            else:
                st.success("✅ 今天已经打卡")

            st.subheader("📅 最近30天")
            cols = st.columns(10)
            for i in range(30):
                d = date.today() - timedelta(days=29-i)
                key = d.strftime("%Y-%m-%d")
                with cols[i % 10]:
                    if st.session_state.checkin_history.get(key, False):
                        st.success(d.strftime("%m/%d"))
                    else:
                        st.caption(d.strftime("%m/%d"))


        # ========================================================
        # BOOKS
        # ========================================================

        with tab_books:
            st.subheader("📚 我的书架")

            search_text = st.text_input("搜索书名 / 作者", key="bookshelf_search")
            display_books = catalog

            if search_text.strip():
                q = search_text.strip().lower()
                display_books = [b for b in catalog if q in str(b.get("title", "")).lower() or q in str(b.get("author", "")).lower()]

            st.caption(f"显示 {len(display_books)} 本")

            for start in range(0, min(len(display_books), 36), 3):
                row = display_books[start:start+3]
                cols = st.columns(len(row))
                for col, book in zip(cols, row):
                    with col:
                        if book.get("cover"):
                            try:
                                st.image(book["cover"], use_container_width=True)
                            except:
                                pass
                        st.markdown(f"### {book.get('title', '未知')}")
                        st.caption(book.get("author", "未知作者"))
                        if safe_int(book.get("finishReading", 0)) == 1:
                            st.success("✅ 已读完")
                        else:
                            st.warning("📖 未读完")


        # ========================================================
        # FEATURES
        # ========================================================

        with tab_features:
            st.subheader("✨ 阅读新功能")
            st.caption("从阅读数据中发掘更多价值")

            feature_tabs = st.tabs(["🕐 阅读生物钟", "📊 阅读周报", "📚 书架整理", "📜 每日一言", "📅 阅读年报"])

            # ===== 阅读生物钟 =====
            with feature_tabs[0]:
                st.markdown("### 🕐 你的阅读生物钟")
                if catalog:
                    chronotype_data = analyze_reading_chronotype(catalog)
                    c1, c2, c3 = st.columns(3)
                    c1.metric("🕐 生物钟类型", chronotype_data["chronotype"])
                    c2.metric("⏰ 最佳阅读时段", f"{chronotype_data['peak_hour']:02d}:00")
                    c3.metric("📊 阅读记录", f"{chronotype_data['total_reads']} 次")
                    st.info(f"💡 {chronotype_data['advice']}")
                    fig = create_chronotype_chart(chronotype_data["hour_distribution"])
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("需要更多阅读数据来生成生物钟分析。")

            # ===== 阅读周报 =====
            with feature_tabs[1]:
                st.markdown("### 📊 阅读周报")
                if catalog:
                    report = generate_weekly_report(catalog, st.session_state.checkin_history)
                    report["streak"] = calculate_streak(st.session_state.checkin_history)
                    report_text = generate_weekly_report_text(report, personality)
                    st.markdown(f"```\n{report_text}\n```")
                    fig = create_weekly_heatmap(report["daily_counts"])
                    st.plotly_chart(fig, use_container_width=True)
                    c1, c2, c3 = st.columns(3)
                    c1.metric("📖 本周阅读", f"{report['books_read_this_week']} 本")
                    c2.metric("✅ 打卡天数", f"{report['checkin_days']}/7 天")
                    c3.metric("🔥 连续阅读", f"{report['streak']} 天")
                else:
                    st.info("需要更多阅读数据来生成周报。")

            # ===== 书架整理 =====
            with feature_tabs[2]:
                st.markdown("### 📚 书架整理助手")
                if catalog:
                    organizer_data = organize_shelf(catalog)
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("📚 总藏书", organizer_data["total_books"])
                    c2.metric("✅ 已读完", organizer_data["finished_count"])
                    c3.metric("📖 未读完", organizer_data["unfinished_count"])
                    c4.metric("📊 完成率", f"{organizer_data['completion_rate']}%")
                    st.subheader("💡 整理建议")
                    for suggestion in organizer_data["suggestions"]:
                        st.info(suggestion)
                    if organizer_data["by_category"]:
                        st.subheader("📊 分类统计")
                        cat_data = sorted(organizer_data["by_category"].items(), key=lambda x: len(x[1]), reverse=True)
                        for cat, books in cat_data[:10]:
                            st.progress(len(books) / organizer_data["total_books"], text=f"{cat} ({len(books)} 本)")
                    st.subheader("🎯 阅读优先级")
                    priority_books = get_reading_priority_list(catalog)
                    for book in priority_books[:5]:
                        st.markdown(f"- 📖 《{book['title']}》 - {book['author']}")
                else:
                    st.info("需要更多书籍数据来整理书架。")

            # ===== 每日一言 =====
            with feature_tabs[3]:
                st.markdown("### 📜 每日一言")
                st.caption("从你自己划过的句子中，重温阅读时的心动瞬间")

                if not catalog:
                    st.info("请先连接微信读书。")
                else:
                    col1, col2, col3 = st.columns([2, 1, 1])

                    with col1:
                        st.markdown("**📖 今日随机书摘**")
                        st.caption("从你的书架中随机选一本书，展示一条你划过的句子")

                    with col2:
                        if st.button("🎲 换一句", use_container_width=True):
                            import random as rand_module

                            st.session_state.quote_seed = rand_module.randint(1, 999999)
                            st.session_state.daily_quote = None
                            st.session_state.daily_quote_loaded = False  # ✅ 重置加载标志
                            st.rerun()

                    with col3:
                        if st.button("🔄 刷新划线", use_container_width=True,
                                     help="重新扫描所有书籍的划线（新增划线后使用）"):
                            refresh_quote_cache(user_id)
                            st.session_state.daily_quote = None
                            st.session_state.daily_quote_loaded = False  # ✅ 重置加载标志
                            st.rerun()

                    # ✅ 修复后的加载逻辑
                    if st.session_state.daily_quote is None and not st.session_state.daily_quote_loaded:
                        with st.spinner("加载中..."):
                            seed = st.session_state.quote_seed if st.session_state.quote_seed else date.today().toordinal()
                            quote_data = get_daily_quote_from_catalog(
                                catalog,
                                st.session_state.weread_client,
                                user_id,
                                seed=seed
                            )
                            st.session_state.daily_quote = quote_data
                            st.session_state.daily_quote_loaded = True  # ✅ 标记已加载

                    # 显示每日一言
                    quote_data = st.session_state.daily_quote

                    if quote_data:
                        if quote_data.get("has_quote", False):
                            st.markdown(f"""
                            <div class="quote-card">
                                <div class="quote-text">📜 “{quote_data['quote']}”</div>
                                <div class="quote-meta">
                                    <span class="quote-source">📖 《{quote_data['book_title']}》</span>
                                    {f"· {quote_data['chapter']}" if quote_data.get('chapter') else ""}
                                    <br>
                                    ✍️ {quote_data['book_author']} 
                                    {f"· 📅 你于 {quote_data['date']} 划线" if quote_data.get('date') else ""}
                                    {f"· 📌 本书共 {quote_data['total_highlights']} 条划线" if quote_data.get('total_highlights') else ""}
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                        else:
                            st.info(quote_data.get("message", "暂无划线数据"))

                    st.markdown("---")
                    st.markdown("### 📖 从指定书籍中选一句")

                    book_list = [b.get("title", "未知") for b in catalog if b.get("title")]

                    if book_list:
                        selected_quote_book = st.selectbox(
                            "选择一本书",
                            book_list,
                            key="quote_book_select"
                        )

                        if st.button("📖 从这本书中选一句", use_container_width=True):
                            with st.spinner(f"正在从《{selected_quote_book}》中寻找..."):
                                quote_data = get_quote_from_specific_book(
                                    catalog,
                                    selected_quote_book,
                                    st.session_state.weread_client
                                )
                                if quote_data and quote_data.get("has_quote", False):
                                    st.markdown(f"""
                                    <div class="quote-card">
                                        <div class="quote-text">📜 “{quote_data['quote']}”</div>
                                        <div class="quote-meta">
                                            <span class="quote-source">📖 《{quote_data['book_title']}》</span>
                                            {f"· {quote_data['chapter']}" if quote_data.get('chapter') else ""}
                                            <br>
                                            ✍️ {quote_data['book_author']} 
                                            {f"· 📅 你于 {quote_data['date']} 划线" if quote_data.get('date') else ""}
                                            {f"· 📌 本书共 {quote_data['total_highlights']} 条划线" if quote_data.get('total_highlights') else ""}
                                        </div>
                                    </div>
                                    """, unsafe_allow_html=True)
                                else:
                                    if quote_data and quote_data.get("no_highlight"):
                                        st.warning(f"📝 你在《{quote_data['book_title']}》中还没有划线")
                                    else:
                                        st.error(quote_data.get("message", "获取划线失败"))
            # ===== 阅读年报 =====
            with feature_tabs[4]:
                st.markdown("### 📅 阅读年报")
                st.caption("回顾你一年的阅读旅程")

                if not catalog:
                    st.info("请先连接微信读书。")
                else:
                    current_year = date.today().year
                    years = [current_year, current_year - 1, current_year - 2]

                    selected_year = st.selectbox(
                        "选择年份",
                        years,
                        key="yearly_report_year_select"
                    )

                    if st.button("📊 生成年报", use_container_width=True):
                        with st.spinner(f"正在生成 {selected_year} 年阅读报告..."):
                            try:
                                report = generate_yearly_report(
                                    catalog,
                                    st.session_state.checkin_history,
                                    profile,
                                    personality,
                                    selected_year
                                )
                                st.session_state.yearly_report = report
                                st.session_state.yearly_report_year = selected_year
                                st.success(f"✅ {selected_year} 年年报生成成功！")
                                st.rerun()
                            except Exception as e:
                                st.error(f"生成失败：{e}")

                    if st.session_state.yearly_report and st.session_state.yearly_report_year == selected_year:
                        report = st.session_state.yearly_report

                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("📖 阅读书籍", report['total_books'])
                        c2.metric("✅ 读完", report['finished_books'])
                        c3.metric("📊 完成率", f"{report['completion_rate']}%")
                        c4.metric("📝 笔记", report.get('total_notes', 0))

                        c1, c2, c3 = st.columns(3)
                        c1.metric("🏷️ 最爱分类", f"{report['top_category'][0]}（{report['top_category'][1]}本）")
                        c2.metric("✍️ 最爱作者", f"{report['top_author'][0]}（{report['top_author'][1]}本）")
                        c3.metric("🔥 最长连续", f"{report['max_streak']} 天")

                        if report['category_distribution']:
                            st.subheader("📊 年度阅读分类")
                            fig = create_yearly_chart(report['category_distribution'])
                            st.plotly_chart(fig, use_container_width=True)

                        st.subheader("📝 年度总结")
                        report_text = generate_yearly_report_text(report)
                        st.markdown(f"```\n{report_text}\n```")

                        st.download_button(
                            label="📥 下载年报",
                            data=report_text,
                            file_name=f"阅途年报_{selected_year}.txt",
                            mime="text/plain"
                        )
                    else:
                        st.info("点击「生成年报」查看你的年度阅读总结")


        # ========================================================
        # AGENT
        # ========================================================

        with tab_agent:
            st.subheader("🤖 与阅途对话")
            st.caption("推荐、锐评、笔记、阅读成果检验，都可以直接聊天。")

            q1, q2, q3, q4 = st.columns(4)
            if q1.button("📖 下一本读什么？", use_container_width=True):
                st.session_state.quick_query = "根据我的真实阅读数据，帮我决定下一本读什么。"
            if q2.button("🔥 锐评我的书架", use_container_width=True):
                st.session_state.quick_query = "请锐评我的书架和阅读习惯。"
            if q3.button("🧠 阅读人格", use_container_width=True):
                st.session_state.quick_query = "分析我的阅读人格和阅读盲区。"
            if q4.button("🎓 检验阅读成果", use_container_width=True):
                st.session_state.quick_query = "我想检验自己是否真的读懂了一本书。"

            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            prompt = st.chat_input("告诉阅途你正在想什么……", key="main_agent_chat")

            if not prompt and st.session_state.quick_query:
                prompt = st.session_state.quick_query
                st.session_state.quick_query = ""

            if prompt:
                st.session_state.messages.append({"role": "user", "content": prompt})
                db.save_message(user_id, "user", prompt)

                with st.chat_message("user"):
                    st.markdown(prompt)

                with st.chat_message("assistant"):
                    with st.spinner("阅途正在思考……"):
                        try:
                            history = st.session_state.messages[-12:]
                            response = st.session_state.agent.invoke({"messages": history})

                            answer = "暂时没有得到有效回答。"
                            for msg in reversed(response.get("messages", [])):
                                if getattr(msg, "type", None) == "ai":
                                    content = getattr(msg, "content", "")
                                    if isinstance(content, str) and content.strip():
                                        answer = content
                                        break

                            st.markdown(answer)
                            st.session_state.messages.append({"role": "assistant", "content": answer})
                            db.save_message(user_id, "assistant", answer)
                        except Exception as exc:
                            st.error(f"❌ Agent调用失败：{exc}")

            if st.button("🗑️ 清空对话"):
                st.session_state.messages = []
                db.clear_messages(user_id)
                st.rerun()


else:
    st.info("👆 请先连接微信读书。")


# ============================================================
# Footer
# ============================================================

st.markdown("---")
st.caption("阅途 · Personal Reading Growth Agent · LangChain + DeepSeek + 微信读书")
