import json
import os
import re
import requests
from utils.helpers import format_lrc_time, parse_timestamp

def convert_bcc_to_lrc(bcc_data: dict) -> str:
    """
    将 B站 BCC / JSON 格式字幕转换为标准的 .lrc 歌词字符串。
    BCC 结构: {"body": [{"from": 0.5, "to": 3.2, "content": "歌词内容"}, ...]}
    """
    if not isinstance(bcc_data, dict) or "body" not in bcc_data:
        return ""

    lrc_lines = []
    for item in bcc_data.get("body", []):
        start_sec = float(item.get("from", 0.0))
        content = item.get("content", "").strip()
        if content:
            time_tag = format_lrc_time(start_sec)
            lrc_lines.append(f"{time_tag}{content}")

    return "\n".join(lrc_lines)

def convert_vtt_srt_to_lrc(sub_text: str) -> str:
    """
    将 VTT / SRT 文本字幕转换为 .lrc 歌词格式。
    """
    if not sub_text:
        return ""

    lrc_lines = []
    # 匹配时间戳 00:01:23.450 --> 00:01:25.000 或 00:01:23,450 --> 00:01:25,000
    pattern = re.compile(r'((?:\d{2}:)?\d{2}:\d{2}[\.,]\d{3})\s*-->\s*(?:\d{2}:)?\d{2}:\d{2}[\.,]\d{3}')

    lines = sub_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = pattern.search(line)
        if match:
            time_str = match.group(1).replace(',', '.')
            sec = parse_timestamp(time_str)
            time_tag = format_lrc_time(sec)
            
            # 读取接下来的文本行
            i += 1
            content_lines = []
            while i < len(lines) and lines[i].strip() and not pattern.search(lines[i]):
                text = lines[i].strip()
                # 过滤 VTT 标签像 <v ...> 等
                text = re.sub(r'<[^>]+>', '', text)
                if text:
                    content_lines.append(text)
                i += 1
            if content_lines:
                lrc_lines.append(f"{time_tag}{' '.join(content_lines)}")
            continue
        i += 1

    return "\n".join(lrc_lines)

def slice_lrc_for_chapter(master_lrc: str, start_time: float, end_time: float) -> str:
    """
    根据章节起止时间，裁剪主 LRC 歌词，并将时间轴重置为从 00:00 开始。
    """
    if not master_lrc:
        return ""

    sliced_lines = []
    # 匹配 [mm:ss.xx]歌词内容
    lrc_pattern = re.compile(r'^\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)$')

    for line in master_lrc.splitlines():
        line = line.strip()
        match = lrc_pattern.match(line)
        if match:
            m, s, ms, content = match.groups()
            sec = int(m) * 60 + int(s) + float(f"0.{ms}")

            # 检查时间是否属于该章节
            if start_time <= sec <= (end_time if end_time > 0 else 999999):
                rel_sec = sec - start_time
                new_tag = format_lrc_time(rel_sec)
                sliced_lines.append(f"{new_tag}{content}")

    return "\n".join(sliced_lines)

def fetch_and_save_lyrics(subtitles_info: dict, description: str, output_lrc_path: str) -> str:
    """
    尝试从字幕或简介中获取歌词，并保存为 .lrc 文件。
    返回完整的 LRC 歌词文本。
    """
    lrc_text = ""

    # 1. 尝试从 yt-dlp 抓取的字幕中转换
    if subtitles_info:
        for lang, sub_list in subtitles_info.items():
            for sub in sub_list:
                url = sub.get("url")
                ext = sub.get("ext")
                if not url:
                    continue
                try:
                    resp = requests.get(url, timeout=10)
                    if resp.status_code == 200:
                        if ext == "json" or "json" in url:
                            lrc_text = convert_bcc_to_lrc(resp.json())
                        elif ext in ["vtt", "srt"] or "vtt" in url or "srt" in url:
                            lrc_text = convert_vtt_srt_to_lrc(resp.text)
                        
                        if lrc_text.strip():
                            break
                except Exception as e:
                    print(f"下载字幕失败 ({url}): {e}")
            if lrc_text.strip():
                break

    # 2. 如果字幕不存在，检查简介中是否有歌词文本
    if not lrc_text.strip() and description:
        # 简单提取简介中的文字作为 txt/lrc 歌词
        lrc_text = f"[00:00.00]{description.strip()}"

    if lrc_text.strip() and output_lrc_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_lrc_path)), exist_ok=True)
        with open(output_lrc_path, "w", encoding="utf-8") as f:
            f.write(lrc_text)

    return lrc_text
