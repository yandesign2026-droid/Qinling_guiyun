#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音乐后期：响度分层 + 环境层无缝循环 + 首尾淡

响度阶梯（相对配音 rms 0.13）：
    环境 AMB  rms 0.055  —— 比台词低 8dB，永远当背景，不得盖过任何一句对白
    音乐 MUS  rms 0.105  —— 与台词相当，但它出场时通常没有对白
    钉音 STG  peak 0.88  —— 要的是冲击，不按响度管
"""
import wave, array, math, os, glob, sys

D = "/Users/home/游戏 秦岭归云/音频/音乐"
SR = 44100

def load(p):
    with wave.open(p) as w:
        n = w.getnframes(); sr = w.getframerate(); ch = w.getnchannels()
        raw = w.readframes(n)
    a = array.array('h'); a.frombytes(raw)
    if ch == 2:
        L = array.array('d', [x / 32768.0 for x in a[0::2]])
        R = array.array('d', [x / 32768.0 for x in a[1::2]])
    else:
        L = array.array('d', [x / 32768.0 for x in a]); R = array.array('d', L)
    return L, R, sr

def save(p, L, R, sr):
    buf = array.array('h')
    for i in range(len(L)):
        buf.append(max(-32768, min(32767, int(L[i] * 32767))))
        buf.append(max(-32768, min(32767, int(R[i] * 32767))))
    with wave.open(p, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(buf.tobytes())

def rms(s):
    return math.sqrt(sum(x * x for x in s) / len(s))

def set_rms(s, target, ceiling=0.95):
    cur = rms(s)
    if cur < 1e-9: return s
    g = target / cur
    pk = max(abs(x) for x in s) * g
    if pk > ceiling: g *= ceiling / pk
    return array.array('d', [x * g for x in s])

def set_peak(s, target):
    pk = max(abs(x) for x in s) or 1.0
    g = target / pk
    return array.array('d', [x * g for x in s])

def fade(s, sr, fin=0.0, fout=0.0):
    n = len(s)
    a = int(fin * sr); b = int(fout * sr)
    out = array.array('d', s)
    for i in range(min(a, n)):
        out[i] *= i / a
    for i in range(min(b, n)):
        out[n - 1 - i] *= i / b
    return out

def seamless(s, sr, xf=1.6):
    """把 s 变成首尾可无限循环的一段：尾部 xf 秒交叉淡入到开头。"""
    n = len(s)
    x = int(xf * sr)
    if n <= 2 * x:
        return s
    out = array.array('d', s[:n - x])
    m = len(out)
    for i in range(x):
        w = i / x
        out[m - x + i] = s[m - x + i] * (1 - w) + s[i] * w
    return out

def main():
    for p in sorted(glob.glob(os.path.join(D, "*.wav"))):
        name = os.path.basename(p)
        L, R, sr = load(p)
        kind = name[:3]

        if kind == "AMB":
            L = seamless(L, sr); R = seamless(R, sr)
            L = set_rms(L, 0.055); R = set_rms(R, 0.055)
            tag = "环境 rms→0.055 无缝循环"
        elif kind == "MUS":
            L = fade(L, sr, 0.30, 2.2); R = fade(R, sr, 0.30, 2.2)
            L = set_rms(L, 0.105); R = set_rms(R, 0.105)
            tag = "音乐 rms→0.105 首尾淡"
        else:
            L = fade(L, sr, 0.004, 0.35); R = fade(R, sr, 0.004, 0.35)
            L = set_peak(L, 0.88); R = set_peak(R, 0.88)
            tag = "钉音 peak→0.88"

        save(p, L, R, sr)
        print(f"{name:<26}{len(L)/sr:>6.1f}s  rms={rms(L):.3f}  {tag}")

    # 循环接缝体检：把尾巴接回头，看跳变
    print("\n── 循环接缝体检（尾→头跳变，<0.05 为无感）──")
    for p in sorted(glob.glob(os.path.join(D, "AMB*.wav"))):
        L, R, sr = load(p)
        jump = abs(L[-1] - L[0])
        # 再看尾部 50ms 的平均斜率是否平滑
        print(f"  {os.path.basename(p):<24}跳变 {jump:.4f}")

if __name__ == "__main__":
    main()
