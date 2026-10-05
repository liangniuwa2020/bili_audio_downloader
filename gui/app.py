import os
import sys
import io
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
import requests
from PIL import Image

from core.downloader import BiliAudioDownloader
from utils.helpers import format_time, parse_description_chapters

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class BiliAudioApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Bilibili 音频下载 & 智能分轨/歌词助手")
        self.geometry("1020x800")
        self.minsize(940, 720)

        self.downloader = BiliAudioDownloader()
        self.current_info = None
        self.is_downloading = False

        self.create_widgets()

    def create_widgets(self):
        # 主网格布局
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ================= 顶部：URL 输入区 =================
        top_frame = ctk.CTkFrame(self, corner_radius=10)
        top_frame.grid(row=0, column=0, padx=15, pady=(15, 10), sticky="ew")
        top_frame.grid_columnconfigure(1, weight=1)

        title_label = ctk.CTkLabel(top_frame, text="🎵 B站音频下载 & 智能分轨歌词助手", font=ctk.CTkFont(size=18, weight="bold"))
        title_label.grid(row=0, column=0, columnspan=4, padx=15, pady=(10, 5), sticky="w")

        url_label = ctk.CTkLabel(top_frame, text="B站视频网址:", font=ctk.CTkFont(size=13))
        url_label.grid(row=1, column=0, padx=(15, 5), pady=10, sticky="w")

        self.entry_url = ctk.CTkEntry(top_frame, placeholder_text="例如: https://www.bilibili.com/video/BV1xx411c7mD...", font=ctk.CTkFont(size=13))
        self.entry_url.grid(row=1, column=1, padx=5, pady=10, sticky="ew")

        self.btn_paste = ctk.CTkButton(top_frame, text="粘贴", width=70, fg_color="#3B82F6", hover_color="#2563EB", command=self.paste_url)
        self.btn_paste.grid(row=1, column=2, padx=5, pady=10)

        self.btn_inspect = ctk.CTkButton(top_frame, text="解析页面", width=100, fg_color="#8B5CF6", hover_color="#7C3AED", command=self.start_inspect)
        self.btn_inspect.grid(row=1, column=3, padx=(5, 15), pady=10)

        # ================= 中部：左右分栏 =================
        main_content = ctk.CTkFrame(self, fg_color="transparent")
        main_content.grid(row=1, column=0, padx=15, pady=5, sticky="nsew")
        main_content.grid_columnconfigure(0, weight=1)
        main_content.grid_columnconfigure(1, weight=1)
        main_content.grid_rowconfigure(0, weight=1)

        # ----- 左侧栏：视频信息与音轨/章节预览 (可编辑) -----
        left_frame = ctk.CTkFrame(main_content, corner_radius=10)
        left_frame.grid(row=0, column=0, padx=(0, 8), pady=0, sticky="nsew")
        left_frame.grid_columnconfigure(0, weight=1)
        left_frame.grid_rowconfigure(3, weight=1)

        left_header = ctk.CTkLabel(left_frame, text="📊 视频信息与分轨时间轴", font=ctk.CTkFont(size=15, weight="bold"))
        left_header.grid(row=0, column=0, padx=15, pady=10, sticky="w")

        # 封面与元数据容器
        meta_container = ctk.CTkFrame(left_frame, fg_color="transparent")
        meta_container.grid(row=1, column=0, padx=15, pady=5, sticky="ew")

        self.lbl_cover = ctk.CTkLabel(meta_container, text="[ 封面预览 ]", width=160, height=95, fg_color="#1E293B", corner_radius=8)
        self.lbl_cover.pack(side="left", padx=(0, 10))

        info_text_frame = ctk.CTkFrame(meta_container, fg_color="transparent")
        info_text_frame.pack(side="left", fill="both", expand=True)

        self.lbl_video_title = ctk.CTkLabel(info_text_frame, text="标题: (未解析)", font=ctk.CTkFont(size=13, weight="bold"), anchor="w", wraplength=260)
        self.lbl_video_title.pack(anchor="w", pady=2)

        self.lbl_uploader = ctk.CTkLabel(info_text_frame, text="UP主: -", font=ctk.CTkFont(size=12), anchor="w", text_color="#94A3B8")
        self.lbl_uploader.pack(anchor="w", pady=2)

        self.lbl_duration = ctk.CTkLabel(info_text_frame, text="时长: - | 歌词: -", font=ctk.CTkFont(size=12), anchor="w", text_color="#94A3B8")
        self.lbl_duration.pack(anchor="w", pady=2)

        # 可编辑的分轨/章节时间轴文本框
        track_header_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        track_header_frame.grid(row=2, column=0, padx=15, pady=(10, 5), sticky="ew")
        
        ctk.CTkLabel(track_header_frame, text="✏️ 分轨时间轴 (可直接在此手动添加/修改时间戳):", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")

        self.txt_tracks = ctk.CTkTextbox(left_frame, font=ctk.CTkFont(family="Consolas", size=12), corner_radius=8)
        self.txt_tracks.grid(row=3, column=0, padx=15, pady=(0, 15), sticky="nsew")
        self.txt_tracks.insert("1.0", "格式提示 (可在此手动输入或修改分轨时间轴):\n00:00 歌曲A\n03:45 歌曲B\n07:30 歌曲C")

        # ----- 右侧栏：下载选项与运行控制台 -----
        right_frame = ctk.CTkFrame(main_content, corner_radius=10)
        right_frame.grid(row=0, column=1, padx=(8, 0), pady=0, sticky="nsew")
        right_frame.grid_columnconfigure(1, weight=1)
        right_frame.grid_rowconfigure(5, weight=1)

        ctk.CTkLabel(right_frame, text="⚙️ 下载选项", font=ctk.CTkFont(size=15, weight="bold")).grid(row=0, column=0, columnspan=2, padx=15, pady=10, sticky="w")

        # 保存路径
        ctk.CTkLabel(right_frame, text="保存目录:").grid(row=1, column=0, padx=(15, 5), pady=5, sticky="w")
        path_frame = ctk.CTkFrame(right_frame, fg_color="transparent")
        path_frame.grid(row=1, column=1, padx=(0, 15), pady=5, sticky="ew")
        path_frame.grid_columnconfigure(0, weight=1)

        default_download_dir = os.path.join(os.path.expanduser("~"), "Downloads", "BiliMusic")
        self.entry_path = ctk.CTkEntry(path_frame, font=ctk.CTkFont(size=12))
        self.entry_path.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.entry_path.insert(0, default_download_dir)

        self.btn_browse = ctk.CTkButton(path_frame, text="浏览...", width=60, command=self.browse_directory)
        self.btn_browse.grid(row=0, column=1)

        # 比特率设置
        ctk.CTkLabel(right_frame, text="MP3 音质:").grid(row=2, column=0, padx=(15, 5), pady=5, sticky="w")
        self.opt_bitrate = ctk.CTkOptionMenu(right_frame, values=["320 kbps (最高)", "256 kbps (极高)", "192 kbps (标准)"], width=180)
        self.opt_bitrate.grid(row=2, column=1, padx=(0, 15), pady=5, sticky="w")

        # 选项勾选框
        opts_frame = ctk.CTkFrame(right_frame, fg_color="transparent")
        opts_frame.grid(row=3, column=0, columnspan=2, padx=15, pady=5, sticky="w")

        self.chk_split = ctk.CTkCheckBox(opts_frame, text="自动分割时间轴章节为独立 MP3 文件")
        self.chk_split.pack(anchor="w", pady=3)
        self.chk_split.select()

        self.chk_lrc = ctk.CTkCheckBox(opts_frame, text="同步下载与自动切分 LRC 歌词文件")
        self.chk_lrc.pack(anchor="w", pady=3)
        self.chk_lrc.select()

        self.chk_tag = ctk.CTkCheckBox(opts_frame, text="自动嵌入封面与 ID3 标签到 MP3")
        self.chk_tag.pack(anchor="w", pady=3)
        self.chk_tag.select()

        # 开始下载大按钮
        self.btn_download = ctk.CTkButton(right_frame, text="🚀 开始下载并处理", font=ctk.CTkFont(size=15, weight="bold"), height=40, fg_color="#10B981", hover_color="#059669", command=self.start_download)
        self.btn_download.grid(row=4, column=0, columnspan=2, padx=15, pady=10, sticky="ew")

        # 日志控制台
        ctk.CTkLabel(right_frame, text="📝 运行日志:", font=ctk.CTkFont(size=13, weight="bold")).grid(row=5, column=0, columnspan=2, padx=15, pady=(5, 0), sticky="nw")

        self.txt_log = ctk.CTkTextbox(right_frame, font=ctk.CTkFont(family="Consolas", size=11), corner_radius=8)
        self.txt_log.grid(row=5, column=0, columnspan=2, padx=15, pady=(25, 15), sticky="nsew")
        self.txt_log.configure(state="disabled")

        # ================= 底部：进度条 =================
        bottom_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        bottom_frame.grid(row=2, column=0, padx=15, pady=(0, 15), sticky="ew")
        bottom_frame.grid_columnconfigure(0, weight=1)

        self.progress_bar = ctk.CTkProgressBar(bottom_frame, height=12)
        self.progress_bar.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.progress_bar.set(0.0)

        self.lbl_status = ctk.CTkLabel(bottom_frame, text="就绪", font=ctk.CTkFont(size=12), text_color="#94A3B8", anchor="w")
        self.lbl_status.grid(row=1, column=0, sticky="w")

    def paste_url(self):
        try:
            clipboard = self.clipboard_get()
            if clipboard:
                self.entry_url.delete(0, tk.END)
                self.entry_url.insert(0, clipboard.strip())
        except Exception:
            pass

    def browse_directory(self):
        folder = filedialog.askdirectory()
        if folder:
            self.entry_path.delete(0, tk.END)
            self.entry_path.insert(0, folder)

    def append_log(self, text: str):
        def _update():
            self.txt_log.configure(state="normal")
            self.txt_log.insert(tk.END, text + "\n")
            self.txt_log.see(tk.END)
            self.txt_log.configure(state="disabled")
        self.after(0, _update)

    def set_status(self, text: str, progress: float = None):
        def _update():
            self.lbl_status.configure(text=text)
            if progress is not None:
                self.progress_bar.set(progress)
        self.after(0, _update)

    def start_inspect(self):
        url = self.entry_url.get().strip()
        if not url:
            messagebox.showwarning("提示", "请输入有效的 B站 视频网址！")
            return

        self.btn_inspect.configure(state="disabled")
        self.set_status("正在解析视频元数据与章节信息...", 0.1)
        self.append_log(f"🔍 开始解析: {url}")

        def worker():
            res = self.downloader.inspect_url(url)
            self.after(0, lambda: self.on_inspect_complete(res))

        threading.Thread(target=worker, daemon=True).start()

    def on_inspect_complete(self, res: dict):
        self.btn_inspect.configure(state="normal")
        if not res.get("success"):
            self.set_status("解析失败", 0.0)
            self.append_log(f"❌ 解析失败: {res.get('error')}")
            messagebox.showerror("解析错误", res.get("error"))
            return

        self.current_info = res
        self.set_status("解析完成！", 1.0)
        self.append_log("✅ 页面元数据解析成功！")

        title = res["title"]
        uploader = res["uploader"]
        duration = res["duration_str"]
        has_subs = "有" if res["has_subtitles"] else "无"

        self.lbl_video_title.configure(text=f"标题: {title}")
        self.lbl_uploader.configure(text=f"UP主: {uploader}")
        self.lbl_duration.configure(text=f"时长: {duration} | 歌词字幕: {has_subs}")

        if res.get("thumbnail"):
            threading.Thread(target=self.load_cover, args=(res["thumbnail"],), daemon=True).start()

        tracks_text = ""
        multi_p = res.get("multi_p_list", [])
        chapters = res.get("chapters", [])

        if multi_p and len(multi_p) > 1:
            tracks_text += f"# 多 P 分集清单 (共 {len(multi_p)} 集)\n"
            for p in multi_p:
                dur_str = format_time(p.get("duration", 0))
                tracks_text += f"P{p['index']:02d}. {p['title']} [{dur_str}]\n"
        elif chapters:
            for ch in chapters:
                start_s = format_time(ch['start_time'])
                tracks_text += f"{start_s} {ch['raw_title']}\n"
        else:
            tracks_text += "# 未自动检测到时间轴分轨。你可以在下方直接输入时间轴，格式如:\n00:00 歌曲A\n03:45 歌曲B\n"

        self.txt_tracks.delete("1.0", tk.END)
        self.txt_tracks.insert("1.0", tracks_text.strip())

    def load_cover(self, url: str):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                img_data = resp.content
                image = Image.open(io.BytesIO(img_data))
                ctk_img = ctk.CTkImage(light_image=image, dark_image=image, size=(160, 95))
                self.after(0, lambda: self.lbl_cover.configure(image=ctk_img, text=""))
        except Exception:
            pass

    def start_download(self):
        if self.is_downloading:
            return

        url = self.entry_url.get().strip()
        if not url:
            messagebox.showwarning("提示", "请输入有效的 B站 视频网址！")
            return

        output_dir = self.entry_path.get().strip()
        if not output_dir:
            messagebox.showwarning("提示", "请选择保存目录！")
            return

        bitrate_str = self.opt_bitrate.get().split()[0]
        auto_split = self.chk_split.get() == 1
        auto_lrc = self.chk_lrc.get() == 1

        # 读取用户界面当前编辑的时间轴文本框内容
        edited_track_text = self.txt_tracks.get("1.0", tk.END).strip()
        total_duration = self.current_info.get("duration", 0.0) if self.current_info else 0.0
        custom_chapters = parse_description_chapters(edited_track_text, total_duration=total_duration)

        if custom_chapters:
            self.append_log(f"📌 解析到 {len(custom_chapters)} 个分轨时间节点，将按此进行切片处理。")

        self.is_downloading = True
        self.btn_download.configure(state="disabled", text="⏳ 正在下载中...")
        self.progress_bar.set(0.0)

        def status_callback(msg_dict):
            m_type = msg_dict.get("type")
            if m_type == "log":
                self.append_log(msg_dict.get("message"))
            elif m_type == "progress":
                percent_str = msg_dict.get("percent", "0%")
                speed_str = msg_dict.get("speed", "")
                eta_str = msg_dict.get("eta", "")
                
                try:
                    p_val = float(percent_str.replace('%', '')) / 100.0
                except ValueError:
                    p_val = 0.0
                    
                self.set_status(f"下载中: {percent_str} | 速度: {speed_str} | 剩余: {eta_str}", p_val)

        def worker():
            res = self.downloader.download(
                url=url,
                output_dir=output_dir,
                bitrate=bitrate_str,
                auto_split=auto_split,
                auto_lrc=auto_lrc,
                custom_chapters=custom_chapters,
                status_callback=status_callback
            )
            self.after(0, lambda: self.on_download_complete(res))

        threading.Thread(target=worker, daemon=True).start()

    def on_download_complete(self, res: dict):
        self.is_downloading = False
        self.btn_download.configure(state="normal", text="🚀 开始下载并处理")

        if res.get("success"):
            self.set_status("下载并分轨处理完成！", 1.0)
            self.append_log("\n🎉 所有任务处理完毕！已生成 MP3 与歌词文件。")
            messagebox.showinfo("完成", "音频下载、分轨切片与歌词处理完成！")
        else:
            self.set_status("下载出错", 0.0)
            messagebox.showerror("错误", f"下载过程出错: {res.get('error')}")

if __name__ == "__main__":
    app = BiliAudioApp()
    app.mainloop()
