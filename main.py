#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bilibili 音频高保真下载 & 智能分轨/歌词助手
主程序入口
"""

import sys
import os

# 将当前项目根目录添加到 python 搜索路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.app import BiliAudioApp

def main():
    app = BiliAudioApp()
    app.mainloop()

if __name__ == "__main__":
    main()
