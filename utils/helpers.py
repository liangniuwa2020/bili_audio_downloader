import re
import os

def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符，避免 Windows/Linux 路径报错。"""
    if not name:
        return "unnamed"
    cleaned = re.sub(r'[\x00-\x1f\\/:*?"<>|]', '_', name)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip('. ')
    return cleaned if cleaned else "unnamed"

def parse_timestamp(time_str: str) -> float:
    """
    解析 'HH:MM:SS', 'MM:SS', 'MM:SS.xxx' 格式的时间字符串为秒数(float)。
    """
    time_str = time_str.strip('[]()【】 ')
    parts = time_str.split(':')
    try:
        if len(parts) == 3:
            h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            return h * 3600 + m * 60 + s
        elif len(parts) == 2:
            m, s = float(parts[0]), float(parts[1])
            return m * 60 + s
        elif len(parts) == 1:
            return float(parts[0])
    except ValueError:
        pass
    return 0.0

def format_time(seconds: float) -> str:
    """将秒数格式化为 'HH:MM:SS' 或 'MM:SS'。"""
    seconds = max(0, seconds)
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def format_lrc_time(seconds: float) -> str:
    """将秒数格式化为 LRC 歌词时间戳格式 [mm:ss.xx]。"""
    seconds = max(0, seconds)
    m, s = divmod(seconds, 60)
    return f"[{int(m):02d}:{s:05.2f}]"

def parse_description_chapters(description: str, total_duration: float = 0.0) -> list:
    """
    解析视频简介/评论/置顶评论/手动输入框中的时间轴，支持多种主流格式：
    1. 时间戳在开头: 00:00 歌曲A, 40:09雨在风中, [00:00:00] 歌曲B, 01. 03:45 歌曲C, 00:00 ~ 03:45 歌曲D
    2. 时间戳在末尾: 歌曲A 00:00, 1. 歌曲B 03:45, 歌曲C [01:23:45]
    返回包含 title, raw_title, start_time, end_time 的字典列表。
    """
    if not description:
        return []

    lines = description.splitlines()
    chapters = []

    # 模式1：开头带有时间戳 (如 00:00 歌名, 40:09歌名, [01:23] 歌名, 01. 00:00 歌名)
    # 注意：序号后必须接点、空格、顿号或连接符 ([\.\s_、\-]+)，防止将 40:09 中的 4 误识别为序号
    pattern_head = re.compile(
        r'^(?:[0-9]{1,3}[\.\s_、\-]+)?'                # 序号 01. 或 1、 (必须跟分隔符)
        r'(?:\[|\(|【)?'                                  # 左括号
        r'((?:\d{1,2}:)?\d{1,2}:\d{2})'                   # 时间戳1 (HH:MM:SS 或 MM:SS)
        r'(?:\]|\)|】)?'                                  # 右括号
        r'(?:\s*[-~→—_:\s]\s*(?:\d{1,2}:)?\d{1,2}:\d{2})?' # 时间轴区间末尾
        r'\s*[-:\s_—|]*\s*'                               # 连接符
        r'(.+)$'                                          # 歌名/标题
    )

    # 模式2：末尾带有时间戳 (如 歌名 00:00, 1. 歌名 03:45)
    pattern_tail = re.compile(
        r'^(?:[0-9]{1,3}[\.\s_、\-]+)?'                # 序号 01.
        r'(.+?)'                                          # 歌名/标题
        r'\s*[-:\s_—|]*\s*'                               # 连接符
        r'(?:\[|\(|【)?'                                  # 左括号
        r'((?:\d{1,2}:)?\d{1,2}:\d{2})'                   # 时间戳
        r'(?:\]|\)|】)?$'                                 # 右括号
    )

    for line in lines:
        line = line.strip()
        if not line:
            continue

        match_head = pattern_head.match(line)
        match_tail = pattern_tail.match(line)

        time_str = None
        title = None

        if match_head:
            time_str = match_head.group(1)
            title = match_head.group(2).strip()
        elif match_tail:
            title = match_tail.group(1).strip()
            time_str = match_tail.group(2)

        if time_str and title:
            # 清理标题残留的序号与符号
            title = re.sub(r'^[0-9]{1,3}[\.\s_、\-]+', '', title).strip()
            title = re.sub(r'^[-:\s_—|]+|[-:\s_—|]+$', '', title).strip()
            
            start_sec = parse_timestamp(time_str)
            if title and start_sec >= 0:
                chapters.append({
                    "title": sanitize_filename(title),
                    "raw_title": title,
                    "start_time": start_sec,
                    "end_time": 0.0
                })

    # 按开始时间升序排列
    chapters.sort(key=lambda x: x["start_time"])

    # 过滤重复起点
    unique_chapters = []
    for c in chapters:
        if not unique_chapters or abs(c["start_time"] - unique_chapters[-1]["start_time"]) > 1.0:
            unique_chapters.append(c)

    # 计算各章节终点
    for i in range(len(unique_chapters)):
        if i < len(unique_chapters) - 1:
            unique_chapters[i]["end_time"] = unique_chapters[i + 1]["start_time"]
        else:
            unique_chapters[i]["end_time"] = total_duration if total_duration > 0 else 0.0

    return unique_chapters
