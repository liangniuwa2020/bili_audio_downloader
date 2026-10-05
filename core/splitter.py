import os
import subprocess
from utils.helpers import sanitize_filename, format_time
from core.metadata import embed_metadata
from core.lyrics import slice_lrc_for_chapter

def split_audio_file(master_mp3_path: str, chapters: list, output_dir: str, artist: str = "Bilibili", album: str = "", cover_url: str = None, cover_data: bytes = None, master_lrc: str = "", progress_callback=None) -> list:
    """
    使用 FFmpeg 根据章节时间轴切割 MP3 音频文件，并保存为独立歌曲 MP3 与对应 .lrc 歌词。
    """
    if not os.path.exists(master_mp3_path) or not chapters:
        return []

    os.makedirs(output_dir, exist_ok=True)
    generated_files = []
    total = len(chapters)

    for idx, chapter in enumerate(chapters, start=1):
        title = chapter.get("title", f"Track_{idx}")
        start_time = chapter.get("start_time", 0.0)
        end_time = chapter.get("end_time", 0.0)

        safe_title = sanitize_filename(title)
        filename = f"{idx:02d}. {safe_title}.mp3"
        output_mp3 = os.path.join(output_dir, filename)

        if progress_callback:
            progress_callback(f"正在切分轨迹 ({idx}/{total}): {safe_title} [{format_time(start_time)} -> {format_time(end_time)}]")

        # 构造正确的 FFmpeg 切片命令: -i 输入文件 -ss 起点 [-to 终点] -c copy 输出文件
        cmd = [
            "ffmpeg",
            "-y",
            "-i", master_mp3_path,
            "-ss", str(start_time)
        ]
        
        if end_time > start_time:
            cmd.extend(["-to", str(end_time)])
            
        cmd.extend([
            "-c", "copy", # 秒级无损复制切片
            output_mp3
        ])

        try:
            # 隐藏 CMD 窗口 (Windows)
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags)

            # 生成对应的子歌词 .lrc
            sliced_lrc = ""
            if master_lrc:
                sliced_lrc = slice_lrc_for_chapter(master_lrc, start_time, end_time)
                if sliced_lrc.strip():
                    lrc_path = os.path.join(output_dir, f"{idx:02d}. {safe_title}.lrc")
                    with open(lrc_path, "w", encoding="utf-8") as f:
                        f.write(sliced_lrc)

            # 写入 ID3 标签 (封面、歌名、UP主)
            embed_metadata(
                mp3_path=output_mp3,
                title=chapter.get("raw_title", title),
                artist=artist,
                album=album if album else safe_title,
                cover_url=cover_url,
                cover_data=cover_data,
                lyrics=sliced_lrc if sliced_lrc else master_lrc
            )

            generated_files.append(output_mp3)
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.decode('utf-8', errors='ignore')
            print(f"FFmpeg 切割错误 ({title}): {err_msg}")
        except Exception as e:
            print(f"切分处理异常 ({title}): {e}")

    return generated_files
