import os
import requests
from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, USLT, ID3NoHeaderError

def embed_metadata(mp3_path: str, title: str, artist: str = "Bilibili", album: str = "", cover_url: str = None, cover_data: bytes = None, lyrics: str = None):
    """
    为 MP3 文件写入 ID3 标签，包含标题、艺术家、专辑、封面图片与嵌入歌词。
    """
    if not os.path.exists(mp3_path):
        return False

    try:
        try:
            audio = ID3(mp3_path)
        except ID3NoHeaderError:
            audio = ID3()

        # 设置基础元数据
        audio["TIT2"] = TIT2(encoding=3, text=title)
        audio["TPE1"] = TPE1(encoding=3, text=artist)
        if album:
            audio["TALB"] = TALB(encoding=3, text=album)

        # 嵌入歌词
        if lyrics:
            audio["USLT"] = USLT(encoding=3, lang='chi', desc='Lyrics', text=lyrics)

        # 嵌入封面
        img_data = cover_data
        if not img_data and cover_url:
            try:
                resp = requests.get(cover_url, timeout=10)
                if resp.status_code == 200:
                    img_data = resp.content
            except Exception:
                pass

        if img_data:
            mime = "image/jpeg"
            if img_data.startswith(b'\x89PNG'):
                mime = "image/png"
            audio["APIC"] = APIC(
                encoding=3,
                mime=mime,
                type=3, # 3代表 Front Cover
                desc='Cover',
                data=img_data
            )

        audio.save(mp3_path)
        return True
    except Exception as e:
        print(f"嵌入元数据失败 ({mp3_path}): {e}")
        return False
