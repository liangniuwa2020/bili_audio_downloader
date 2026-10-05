import os
import re
import json
import subprocess
import requests
import yt_dlp
from utils.helpers import sanitize_filename, parse_description_chapters, format_time
from core.lyrics import fetch_and_save_lyrics
from core.splitter import split_audio_file
from core.metadata import embed_metadata

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com/',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
}

class BiliAudioDownloader:
    def __init__(self):
        pass

    def parse_url_ids(self, url: str) -> dict:
        """从 B站 链接中解析 BVID、AVID 及 P 页码。"""
        url = url.strip()
        
        # 处理 short link 还原 (b23.tv)
        if "b23.tv" in url:
            try:
                resp = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=8)
                url = resp.url
            except Exception:
                pass

        bvid_match = re.search(r'BV[a-zA-Z0-9]{10}', url)
        p_match = re.search(r'[?&]p=(\d+)', url)

        bvid = bvid_match.group(0) if bvid_match else None
        p_index = int(p_match.group(1)) if p_match else 1

        return {"bvid": bvid, "p": p_index, "raw_url": url}

    def inspect_url(self, url: str) -> dict:
        """
        解析 B站 链接元数据。优先使用 B站 官方 API，若失败则降级至 yt-dlp。
        """
        ids = self.parse_url_ids(url)
        bvid = ids.get("bvid")

        if bvid:
            api_res = self._inspect_via_bili_api(bvid, ids.get("p", 1), url)
            if api_res.get("success"):
                return api_res

        # 降级尝试 yt-dlp
        return self._inspect_via_ytdlp(url)

    def _inspect_via_bili_api(self, bvid: str, current_p: int, raw_url: str) -> dict:
        """使用 B站 Web API 获取精确数据。"""
        api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        try:
            resp = requests.get(api_url, headers=HEADERS, timeout=10)
            data = resp.json()
            if data.get("code") != 0:
                return {"success": False, "error": f"B站 API 错误: {data.get('message')}"}

            info = data.get("data", {})
            title = info.get("title", "")
            uploader = info.get("owner", {}).get("name", "Unknown Uploader")
            description = info.get("desc", "")
            thumbnail = info.get("pic", "")
            duration = info.get("duration", 0)
            pages = info.get("pages", [])

            aid = info.get("aid")
            cid = info.get("cid")
            if pages and current_p <= len(pages):
                cid = pages[current_p - 1].get("cid", cid)
                
            subtitles = self._get_subtitles_via_api(aid, cid)

            # 抓取分轨章节优先级:
            # 1. 置顶评论 / 热门评论 (内容最全，通常包含 歌名 - 歌手)
            chapters = self._get_pinned_comment_chapters(aid, duration)

            # 2. 视频简介 (desc)
            if not chapters:
                chapters = parse_description_chapters(description, total_duration=duration)

            # 3. 官方打点章节 (view_points)
            if not chapters:
                chapters = self._get_view_points_via_api(aid, cid, duration)

            # 解析多P列表
            multi_p_list = []
            if len(pages) > 1:
                for p in pages:
                    multi_p_list.append({
                        "index": p.get("page", 1),
                        "title": p.get("part", f"P{p.get('page')}"),
                        "duration": p.get("duration", 0),
                        "cid": p.get("cid"),
                        "url": f"https://www.bilibili.com/video/{bvid}?p={p.get('page')}"
                    })

            return {
                "success": True,
                "bvid": bvid,
                "aid": aid,
                "cid": cid,
                "title": title,
                "uploader": uploader,
                "description": description,
                "thumbnail": thumbnail,
                "duration": duration,
                "duration_str": format_time(duration),
                "chapters": chapters,
                "multi_p_list": multi_p_list,
                "has_subtitles": bool(subtitles),
                "subtitles": subtitles,
                "raw_info": info
            }
        except Exception as e:
            return {"success": False, "error": f"API 解析失败: {str(e)}"}

    def _get_pinned_comment_chapters(self, aid, duration: float = 0.0) -> list:
        """从 B站 视频评论区抓取 UP 主置顶评论或热门评论中的时间轴歌单。"""
        if not aid:
            return []
        try:
            url = f"https://api.bilibili.com/x/v2/reply/main?type=1&oid={aid}"
            resp = requests.get(url, headers=HEADERS, timeout=8)
            data = resp.json().get("data", {})

            candidate_texts = []

            # 1. UP 主置顶评论
            upper_msg = data.get("top", {}).get("upper", {}).get("content", {}).get("message")
            if upper_msg:
                candidate_texts.append(upper_msg)

            # 2. 置顶回复/热门回复
            for tr in data.get("top_replies", []) or []:
                msg = tr.get("content", {}).get("message")
                if msg:
                    candidate_texts.append(msg)

            # 3. 前排评论
            for rep in data.get("replies", []) or []:
                msg = rep.get("content", {}).get("message")
                if msg:
                    candidate_texts.append(msg)

            # 匹配包含时间轴的评论
            for text in candidate_texts:
                chapters = parse_description_chapters(text, total_duration=duration)
                if len(chapters) > 1:
                    return chapters

            return []
        except Exception as e:
            print(f"获取置顶评论异常: {e}")
            return []

    def _get_view_points_via_api(self, aid, cid, duration: float = 0.0) -> list:
        """从 B站 player wbi v2 API 获取视频打点/章节信息 (view_points)。"""
        if not aid or not cid:
            return []
        try:
            url = f"https://api.bilibili.com/x/player/wbi/v2?aid={aid}&cid={cid}"
            resp = requests.get(url, headers=HEADERS, timeout=8)
            data = resp.json()
            vp_list = data.get("data", {}).get("view_points", []) or []
            chapters = []
            for vp in vp_list:
                title = vp.get("content") or vp.get("title") or ""
                from_sec = float(vp.get("from", 0.0))
                to_sec = float(vp.get("to", 0.0))
                if title:
                    chapters.append({
                        "title": sanitize_filename(title),
                        "raw_title": title,
                        "start_time": from_sec,
                        "end_time": to_sec if to_sec > from_sec else duration
                    })
            return chapters
        except Exception as e:
            print(f"获取 view_points 异常: {e}")
            return []

    def _get_subtitles_via_api(self, aid, cid) -> dict:
        """从 B站 player API 获取字幕文件列表。"""
        if not aid or not cid:
            return {}
        try:
            url = f"https://api.bilibili.com/x/player/v2?aid={aid}&cid={cid}"
            resp = requests.get(url, headers=HEADERS, timeout=8)
            data = resp.json()
            subs_list = data.get("data", {}).get("subtitle", {}).get("subtitles", [])
            subs_dict = {}
            if subs_list:
                subs_dict["zh"] = []
                for s in subs_list:
                    sub_url = s.get("subtitle_url", "")
                    if sub_url:
                        if sub_url.startswith("//"):
                            sub_url = "https:" + sub_url
                        subs_dict["zh"].append({"url": sub_url, "ext": "json", "lan": s.get("lan")})
            return subs_dict
        except Exception:
            return {}

    def _inspect_via_ytdlp(self, url: str) -> dict:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'http_headers': HEADERS
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return {"success": False, "error": "无法解析链接信息"}

                title = info.get("title", "Unknown Title")
                uploader = info.get("uploader", "Unknown Uploader")
                description = info.get("description", "")
                thumbnail = info.get("thumbnail", "")
                duration = info.get("duration", 0)

                chapters = parse_description_chapters(description, total_duration=duration)
                subtitles = info.get("subtitles") or info.get("automatic_captions") or {}

                return {
                    "success": True,
                    "title": title,
                    "uploader": uploader,
                    "description": description,
                    "thumbnail": thumbnail,
                    "duration": duration,
                    "duration_str": format_time(duration),
                    "chapters": chapters,
                    "multi_p_list": [],
                    "has_subtitles": bool(subtitles),
                    "subtitles": subtitles,
                    "raw_info": info
                }
        except Exception as e:
            return {"success": False, "error": f"yt-dlp 解析失败: {str(e)}"}

    def download(self, url: str, output_dir: str, bitrate: str = "320", auto_split: bool = True, auto_lrc: bool = True, custom_chapters: list = None, status_callback=None) -> dict:
        """
        下载音轨，提取最高音质 MP3，并自动处理歌词与分轨。
        支持传入自定义/界面编辑的章节分轨列表 custom_chapters。
        """
        os.makedirs(output_dir, exist_ok=True)

        def log(msg):
            if status_callback:
                status_callback({"type": "log", "message": msg})

        def progress_hook(d):
            if status_callback and d.get('status') == 'downloading':
                percent_str = d.get('_percent_str', '0%').strip()
                speed_str = d.get('_speed_str', 'N/A').strip()
                eta_str = d.get('_eta_str', 'N/A').strip()
                status_callback({
                    "type": "progress",
                    "percent": percent_str,
                    "speed": speed_str,
                    "eta": eta_str,
                    "filename": d.get('filename', '')
                })

        log(f"🔍 正在初始化解析: {url}")

        info_res = self.inspect_url(url)
        if not info_res.get("success"):
            log(f"❌ 链接解析失败: {info_res.get('error')}")
            return {"success": False, "error": info_res.get("error")}

        video_title = sanitize_filename(info_res["title"])
        uploader = info_res["uploader"]
        cover_url = info_res["thumbnail"]
        # 优先使用界面自定义/编辑的章节清单，没有则使用自动抓取的置顶评论/打点章节
        chapters = custom_chapters if custom_chapters else info_res["chapters"]
        multi_p_list = info_res["multi_p_list"]
        subtitles = info_res["subtitles"]
        description = info_res["description"]
        bvid = info_res.get("bvid")

        log(f"🎵 目标视频: {video_title} (UP主: {uploader}, 时长: {info_res['duration_str']})")

        # 多 P 处理
        if len(multi_p_list) > 1 and "?p=" not in url:
            log(f"📚 检测到多P视频，共包含 {len(multi_p_list)} 个分集，开始逐集下载...")
            created_files = []
            for p_item in multi_p_list:
                p_url = p_item.get("url") or f"https://www.bilibili.com/video/{bvid}?p={p_item['index']}"
                p_title = sanitize_filename(f"P{p_item['index']:02d}_{p_item['title']}")
                log(f"\n▶ 正在下载 {p_title} ...")

                res = self._download_single_audio(
                    p_url, output_dir, p_title, uploader, bitrate, cover_url, subtitles, description, auto_split, auto_lrc, progress_hook, log, bvid=bvid, cid=p_item.get("cid")
                )
                if res.get("success"):
                    created_files.extend(res.get("files", []))
            return {"success": True, "files": created_files}
        else:
            return self._download_single_audio(
                url, output_dir, video_title, uploader, bitrate, cover_url, subtitles, description, auto_split, auto_lrc, progress_hook, log, chapters, bvid=bvid, cid=info_res.get("cid")
            )

    def _download_single_audio(self, url, output_dir, title, uploader, bitrate, cover_url, subtitles, description, auto_split, auto_lrc, progress_hook, log, chapters=None, bvid=None, cid=None):
        mp3_path = os.path.join(output_dir, f"{title}.mp3")
        lrc_path = os.path.join(output_dir, f"{title}.lrc")

        # 尝试通过 B站 API 直接提取 DASH 音频流并用 FFmpeg 转码
        download_success = False
        if bvid and cid:
            download_success = self._download_audio_via_bili_api(bvid, cid, mp3_path, bitrate, log, progress_hook)

        # 如果 API 提取未成功，降级使用 yt-dlp
        if not download_success:
            download_success = self._download_audio_via_ytdlp(url, output_dir, title, bitrate, log, progress_hook)

        if not download_success or not os.path.exists(mp3_path):
            log("❌ 音频下载或转换失败。")
            return {"success": False, "error": "下载失败"}

        log("✅ 高保真 MP3 音频生成成功！")

        # 处理歌词
        master_lrc = ""
        if auto_lrc:
            log("📝 正在抓取/转换歌词字幕...")
            master_lrc = fetch_and_save_lyrics(subtitles, description, lrc_path)
            if master_lrc:
                log(f"✅ 歌词获取成功，已保存至: {os.path.basename(lrc_path)}")

        # 写入 MP3 ID3 标签
        embed_metadata(
            mp3_path=mp3_path,
            title=title,
            artist=uploader,
            album=title,
            cover_url=cover_url,
            lyrics=master_lrc
        )

        created_files = [mp3_path]
        if os.path.exists(lrc_path):
            created_files.append(lrc_path)

        # 检查时间轴分轨
        if auto_split and chapters and len(chapters) > 1:
            log(f"✂ 检测到 {len(chapters)} 个时间轴章节/曲目，开始自动分轨切片...")
            split_sub_dir = os.path.join(output_dir, title)

            def split_progress(msg):
                log(f"   ↳ {msg}")

            split_files = split_audio_file(
                master_mp3_path=mp3_path,
                chapters=chapters,
                output_dir=split_sub_dir,
                artist=uploader,
                album=title,
                cover_url=cover_url,
                master_lrc=master_lrc,
                progress_callback=split_progress
            )
            log(f"🎉 成功拆分为 {len(split_files)} 首独立歌曲 MP3，已保存至文件夹: {title}/")
            created_files.extend(split_files)

        return {"success": True, "files": created_files}

    def _download_audio_via_bili_api(self, bvid: str, cid: int, target_mp3: str, bitrate: str, log, progress_hook) -> bool:
        """通过 B站 官方 PlayURL API 直接拿到 DASH 音频流，流式下载并转换。"""
        try:
            api_url = f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&fnval=16"
            resp = requests.get(api_url, headers=HEADERS, timeout=10)
            data = resp.json()

            audio_url = None
            dash = data.get("data", {}).get("dash", {})
            if dash and dash.get("audio"):
                audio_streams = sorted(dash.get("audio"), key=lambda x: x.get("bandwidth", 0), reverse=True)
                audio_url = audio_streams[0].get("baseUrl") or audio_streams[0].get("backupUrl", [None])[0]

            if not audio_url:
                return False

            log("🚀 使用 B站 高清直连通道下载音频流...")
            
            temp_m4a = target_mp3 + ".tmp.m4a"
            res = requests.get(audio_url, headers=HEADERS, stream=True, timeout=30)
            total_size = int(res.headers.get('content-length', 0))

            downloaded = 0
            with open(temp_m4a, 'wb') as f:
                for chunk in res.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0 and progress_hook:
                            percent = (downloaded / total_size) * 100
                            progress_hook({'status': 'downloading', '_percent_str': f"{percent:.1f}%"})

            log("🎵 正在转换为 MP3...")
            cmd = [
                "ffmpeg", "-y", "-i", temp_m4a,
                "-b:a", f"{bitrate}k",
                "-id3v2_version", "3",
                target_mp3
            ]
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags)

            if os.path.exists(temp_m4a):
                os.remove(temp_m4a)
            return True
        except Exception as e:
            log(f"⚠️ API 直连下载回退: {e}")
            return False

    def _download_audio_via_ytdlp(self, url: str, output_dir: str, title: str, bitrate: str, log, progress_hook) -> bool:
        out_template = os.path.join(output_dir, f"{title}.%(ext)s")
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': out_template,
            'progress_hooks': [progress_hook],
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': bitrate,
            }],
            'quiet': True,
            'no_warnings': True,
            'http_headers': HEADERS
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                log("📥 使用 yt-dlp 引擎下载并转码 MP3...")
                ydl.download([url])
            return True
        except Exception as e:
            log(f"❌ yt-dlp 下载失败: {e}")
            return False
