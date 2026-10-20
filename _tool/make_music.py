#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
秦岭归云 · 环境音乐与音景合成

核心规则（这是本片唯一的一条音乐规则）：
    邪修摄六魂，缺第七。所以全片的音乐只用 **全音阶**——
    全音阶恰好只有六个音，第七个音永远转不出来，它自己就是一个走不出去的圆。
    只有在真结局（第六盏灯灭了）才第一次出现一个不属于全音阶的音。
    那个音就是"第七个"。

    全音阶（D 起）:  D  E  F#  G#  A#  C   ← 六个音
    第七音（终局才用）:  F♮                  ← 打破全音阶的第一个音

纯 stdlib 合成，无 ffmpeg / numpy / 外部音源。
"""
import wave, array, math, random, os, struct

SR   = 44100
OUT  = "/Users/home/游戏 秦岭归云/音频/音乐"
random.seed(7)

# ── 音高表 ────────────────────────────────────────────────────────
def nt(f): return f
D2 = 73.42;  D3 = 146.83; D4 = 293.66; D5 = 587.33
# 全音阶（六音），D 起
WHOLE = [D3, 164.81, 185.00, 207.65, 233.08, 261.63]          # D3 E3 F#3 G#3 A#3 C4
WHOLE_HI = [x * 2 for x in WHOLE]                              # 高八度
SEVENTH = 349.23                                               # F♮4：终局才出现的第七音

# ── 基础工具 ──────────────────────────────────────────────────────
_SIN = array.array('d', [math.sin(2 * math.pi * i / 4096) for i in range(4096)])

def _osc(freq, n, sr=SR, phase=0.0):
    """正弦查表合成。相位累加，支持弯音。"""
    out = array.array('d', [0.0]) * n
    step = freq * 4096 / sr
    p = phase * 4096 / (2 * math.pi)
    for i in range(n):
        idx = int(p) & 4095
        out[i] = _SIN[idx]
        p += step
    return out

def _osc_glide(freq, n, bend=0.0, sr=SR):
    """起音时略高，滑到基频——古琴/埙的弯音。bend 单位：半音"""
    out = array.array('d', [0.0]) * n
    target = freq
    start = freq * (2 ** (bend / 12.0))
    p = 0.0
    for i in range(n):
        f = start + (target - start) * (i / max(1, n // 8)) if i < n // 8 else target
        p += f * 4096 / sr
        out[i] = _SIN[int(p) & 4095]
    return out

def _noise(n, seed=None):
    r = random.Random(seed if seed is not None else random.randint(0, 99999))
    return array.array('d', [r.uniform(-1, 1) for _ in range(n)])

def _lp(sig, sr, fc):
    a = 1.0 - math.exp(-2.0 * math.pi * fc / sr)
    out = array.array('d', [0.0]) * len(sig)
    y = 0.0
    for i in range(len(sig)):
        y += a * (sig[i] - y)
        out[i] = y
    return out

def _hp(sig, sr, fc):
    a = 1.0 / (1.0 + 2.0 * math.pi * fc / sr)
    out = array.array('d', [0.0]) * len(sig)
    y = 0.0; x1 = 0.0
    for i in range(len(sig)):
        x = sig[i]
        y = a * (y + x - x1)
        out[i] = y
        x1 = x
    return out

def _bp(sig, sr, f0, f1):
    return _hp(_lp(sig, sr, f1), sr, f0)

def _adsr(n, a, d, s, r, sus_lvl=0.6):
    """返回包络数组。a/d/r 单位秒"""
    A, D, R = int(a * SR), int(d * SR), int(r * SR)
    S = max(0, n - A - D - R)
    e = array.array('d', [0.0]) * n
    i = 0
    for k in range(A):
        if i < n: e[i] = k / A; i += 1
    for k in range(D):
        if i < n: e[i] = 1.0 + (sus_lvl - 1.0) * (k / D); i += 1
    for k in range(S):
        if i < n: e[i] = sus_lvl; i += 1
    for k in range(R):
        if i < n: e[i] = sus_lvl * (1.0 - k / R); i += 1
    return e

def _mix(*sigs):
    n = max(len(s) for s in sigs)
    out = array.array('d', [0.0]) * n
    for s in sigs:
        for i in range(len(s)):
            out[i] += s[i]
    return out

def _gain(sig, g):
    return array.array('d', [x * g for x in sig])

def _reverb(sig, sr=SR, taps=((0.021, .30), (0.037, .22), (0.058, .15), (0.091, .09))):
    out = array.array('d', sig)
    n = len(sig)
    for t, g in taps:
        d = int(t * sr)
        for i in range(d, n):
            out[i] += sig[i - d] * g
    return out

def _loop(core, times, xfade_sec=1.2, sr=SR):
    """把一段核心循环若干次，接缝处交叉淡入，避免周期性咔哒。"""
    xf = int(xfade_sec * sr)
    L = len(core)
    total = L + (L - xf) * (times - 1)
    out = array.array('d', [0.0]) * total
    for i in range(L):
        out[i] = core[i]
    pos = L
    for t in range(1, times):
        start = pos - xf
        for i in range(xf):
            w = i / xf
            out[start + i] = out[start + i] * (1 - w) + core[i] * w
        for i in range(xf, L):
            out[start + i] = core[i]
        pos = start + L
    return out

def _stereo(left, right):
    """两条声道合成 interleaved 输出"""
    n = max(len(left), len(right))
    L = array.array('d', left) + array.array('d', [0.0]) * (n - len(left))
    R = array.array('d', right) + array.array('d', [0.0]) * (n - len(right))
    return L, R

def _pan(sig, pos):
    """pos: 0=全左 1=全右"""
    gl = math.cos(pos * math.pi / 2)
    gr = math.sin(pos * math.pi / 2)
    return _gain(sig, gl), _gain(sig, gr)

def _norm(sig, peak=0.85):
    p = max(abs(x) for x in sig) or 1.0
    g = peak / p
    return array.array('d', [x * g for x in sig])

def write(name, L, R, sr=SR):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name + ".wav")
    n = max(len(L), len(R))
    Lp = _norm(L); Rp = _norm(R)
    buf = array.array('h')
    for i in range(n):
        buf.append(max(-32768, min(32767, int(Lp[i] * 32767))))
        buf.append(max(-32768, min(32767, int(Rp[i] * 32767))))
    with wave.open(p, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(buf.tobytes())
    return p, n / sr


# ── 乐器 ──────────────────────────────────────────────────────────
def xun(freq, dur, amp=1.0, breathy=0.10):
    """埙 / 箫：正弦基底 + 弱二次泛音 + 气声 + 慢起音"""
    n = int(dur * SR)
    base = _osc(freq, n)
    h2   = _gain(_osc(freq * 2, n), 0.22)
    h3   = _gain(_osc(freq * 3, n), 0.08)
    air  = _gain(_bp(_noise(n), SR, freq * 1.6, freq * 4.5), breathy)
    # 慢起音 + 轻微颤音
    vib = _gain(_osc(4.7, n), 0.006)
    env = _adsr(n, 0.35, 0.20, 0.72, 0.60, 0.72)
    out = array.array('d', [0.0]) * n
    for i in range(n):
        f = freq * (1 + vib[i])
        out[i] = (base[i] + h2[i] + h3[i] + air[i]) * env[i]
    return _gain(out, amp)

def guqin(freq, dur, amp=1.0):
    """古琴拨弦：泛音列 + 快速衰减 + 起音弯音"""
    n = int(dur * SR)
    parts = []
    for k, g in ((1, 1.0), (2, 0.42), (3, 0.24), (4, 0.12), (5, 0.07), (6.9, 0.04)):
        o = _osc_glide(freq * k, n, bend=0.35)
        env = _adsr(n, 0.004, dur * 0.30, 0.16, dur * 0.66, 0.16)
        parts.append(_gain(array.array('d', [o[i] * env[i] for i in range(n)]), g))
    s = _mix(*parts)
    return _gain(s, amp * 0.30)

def qing(freq, dur, amp=1.0):
    """磬：不谐和泛音比 + 极长衰减"""
    n = int(dur * SR)
    parts = []
    for k, g in ((1, 1.0), (2.76, 0.52), (5.40, 0.28), (8.93, 0.14)):
        o = _osc(freq * k, n)
        env = _adsr(n, 0.002, dur * 0.16, 0.10, dur * 0.84, 0.10)
        parts.append(_gain(array.array('d', [o[i] * env[i] for i in range(n)]), g))
    return _gain(_mix(*parts), amp * 0.26)

def strings(freq, dur, amp=1.0, low=False):
    """弦乐：锯齿近似（奇次泛音）+ 慢起音 + 颤音。low=True 更低更闷"""
    n = int(dur * SR)
    parts = []
    hmax = 6 if low else 10
    for k in range(1, hmax, 2):
        parts.append(_gain(_osc(freq * k, n), 1.0 / (k * k)))
    s = _mix(*parts)
    vib = _gain(_osc(5.2 if not low else 3.4, n), 0.010)
    env = _adsr(n, dur * 0.18, dur * 0.14, 0.62, dur * 0.34, 0.62)
    out = array.array('d', [0.0]) * n
    for i in range(n):
        out[i] = s[i] * (1 + vib[i]) * env[i]
    out = _lp(out, SR, 2600 if low else 5200)
    return _gain(out, amp * 0.20)

def drone(freq, dur, amp=1.0, movement=0.35):
    """持续低音：两个略微失谐的振荡器拍频 + 极慢起伏"""
    n = int(dur * SR)
    a = _osc(freq, n)
    b = _gain(_osc(freq * 1.006, n), 0.85)      # 拍频
    c = _gain(_osc(freq * 0.5, n), 0.55)        # 下八度
    swell = _gain(_osc(0.055, n), movement)
    env = _adsr(n, dur * 0.20, 0.0, 1.0, dur * 0.25, 1.0)
    out = array.array('d', [0.0]) * n
    for i in range(n):
        out[i] = (a[i] + b[i] + c[i]) * (1.0 + swell[i]) * env[i]
    return _gain(out, amp * 0.22)

def wind(dur, intensity=1.0, lowcut=90, hicut=1400):
    """风：带通噪声 + 缓慢起伏 + 偶发阵风"""
    n = int(dur * SR)
    nz = _bp(_noise(n), SR, lowcut, hicut)
    # 两层不同速度的起伏，制造不规律感
    m1 = _gain(_osc(0.07, n), 0.45)
    m2 = _gain(_osc(0.023, n), 0.35)
    out = array.array('d', [0.0]) * n
    for i in range(n):
        out[i] = nz[i] * (0.55 + m1[i] + m2[i])
    return _gain(_lp(out, SR, hicut), intensity * 0.55)

def waterdrop(dur, amp=1.0, times=5):
    """水滴：短促的高频正弦下滑 + 长尾混响"""
    n = int(dur * SR)
    out = array.array('d', [0.0]) * n
    for t in range(times):
        pos = random.randint(int(0.3 * SR), max(int(0.3 * SR) + 1, n - int(0.8 * SR)))
        dl = random.uniform(0.05, 0.11)
        dn = int(dl * SR)
        f0 = random.uniform(900, 1700)
        seg = array.array('d', [0.0]) * dn
        p = 0.0
        for i in range(dn):
            f = f0 * (1.0 - 0.45 * i / dn)
            p += f * 4096 / SR
            seg[i] = _SIN[int(p) & 4095]
        e = _adsr(dn, 0.001, dn / SR * 0.35, 0.25, dn / SR * 0.6, 0.25)
        for i in range(min(dn, n - pos)):
            out[pos + i] += seg[i] * e[i] * amp
    return _gain(out, 0.42)


# ══════════════════════════════════════════════════════════════════
# 环境层 AMB —— 循环音景
# ══════════════════════════════════════════════════════════════════

def AMB01_山雾():
    """秦岭的雾，是活的。低频山风 + 湿冷的空气 + 远处的闷响"""
    core = 9.0
    n = int(core * SR)
    w  = wind(core, 1.0, 70, 1200)
    w2 = _gain(wind(core, 0.55, 400, 3400), 0.7)      # 湿冷的高频空气
    d  = drone(D2, core, 0.55, 0.30)
    # 偶发远处闷响（每 ~3 秒一次，很轻）
    for k in range(3):
        pos = int((0.7 + k * 2.8) * SR)
        tn = int(0.55 * SR)
        seg = array.array('d', [0.0]) * tn
        p = 0.0
        for i in range(tn):
            f = 58 * (1 - 0.3 * i / tn)
            p += f * 4096 / SR
            seg[i] = _SIN[int(p) & 4095]
        e = _adsr(tn, 0.01, 0.12, 0.05, 0.40, 0.05)
        for i in range(min(tn, n - pos)):
            w[pos + i] += seg[i] * e[i] * 0.22
    L, R = _pan(_mix(w, w2, d), 0.32)
    L = _reverb(L); R = _reverb(R)
    return write("AMB01_山雾", *_stereo(_loop(L, 3), _loop(R, 3)))

def AMB02_客栈夜():
    """老木结构的房子在夜里自己会响。极低 drone + 木头吱呀 + 远处的风"""
    core = 9.0
    w = wind(core, 0.30, 60, 700)
    d = drone(D2 * 0.75, core, 0.75, 0.22)
    # 木头吱呀：慢速的滤波噪声脉冲，随机的音高
    for k in range(4):
        pos = int((0.5 + k * 2.3 + random.random()) * SR)
        tn = int(random.uniform(0.5, 1.1) * SR)
        seg = _bp(_noise(tn), SR, random.uniform(160, 420), random.uniform(700, 1500))
        e = _adsr(tn, tn / SR * 0.30, tn / SR * 0.20, 0.45, tn / SR * 0.45, 0.45)
        for i in range(min(tn, len(w) - pos)):
            w[pos + i] += seg[i] * e[i] * 0.30
    L, R = _pan(_mix(w, d), 0.45)
    L = _reverb(L, taps=((0.017, .18), (0.031, .12)))
    R = _reverb(R, taps=((0.019, .18), (0.033, .12)))
    return write("AMB02_客栈夜", *_stereo(_loop(L, 3), _loop(R, 3)))

def AMB03_墙内():
    """不是墙外，是墙里。极低频压迫 + 闷住的抓挠回响"""
    core = 9.0
    d = drone(D2 * 0.5, core, 1.0, 0.18)              # 36Hz 附近，胸腔共振
    d2 = drone(D2 * 0.503, core, 0.55, 0.25)          # 失谐制造不安
    # 抓挠：闷住的、不规则的短促摩擦（比 SFX01 更远、更沉）
    for k in range(7):
        pos = int((0.4 + k * 1.15 + random.uniform(0, .3)) * SR)
        tn = int(random.uniform(0.35, 0.75) * SR)
        seg = _bp(_noise(tn), SR, 200, 1500)
        e = _adsr(tn, tn / SR * 0.25, tn / SR * 0.25, 0.35, tn / SR * 0.5, 0.35)
        for i in range(min(tn, len(d) - pos)):
            d[pos + i] += seg[i] * e[i] * 0.16
    s = _mix(d, d2)
    s = _lp(s, SR, 900)                                # 全部闷住
    L, R = _pan(s, 0.5)
    return write("AMB03_墙内", *_stereo(_loop(L, 3), _loop(R, 3)))

def AMB04_井底():
    """六缕魂魄沉在底下，一层一层。巨大的空间 + 水滴 + 深"""
    core = 9.0
    d  = drone(D2 * 0.5, core, 0.85, 0.20)
    d2 = drone(D3, core, 0.30, 0.35)
    w  = _gain(wind(core, 0.22, 80, 600), 0.6)
    dp = waterdrop(core, 1.0, 6)
    s  = _mix(d, d2, w, dp)
    s  = _lp(s, SR, 2400)
    L, R = _pan(s, 0.42)
    L = _reverb(L, taps=((0.045, .42), (0.082, .30), (0.13, .20), (0.21, .12)))
    R = _reverb(R, taps=((0.051, .42), (0.089, .30), (0.14, .20), (0.23, .12)))
    return write("AMB04_井底", *_stereo(_loop(L, 3), _loop(R, 3)))

def AMB05_破庙():
    """香灰还是温的，刚有人跪过。穿堂风 + 干燥"""
    core = 9.0
    w = wind(core, 0.85, 200, 2600)
    w = _hp(w, SR, 150)                                # 干，没有低频的湿
    d = drone(D3 * 0.5, core, 0.35, 0.25)
    # 偶尔的木鱼/铃：极轻的一声金属
    for k in range(2):
        pos = int((1.2 + k * 4.0) * SR)
        seg = qing(D5 * 1.5, 1.6, 0.30)
        for i in range(min(len(seg), len(w) - pos)):
            w[pos + i] += seg[i]
    L, R = _pan(_mix(w, d), 0.55)
    L = _reverb(L, taps=((0.028, .26), (0.052, .18)))
    R = _reverb(R, taps=((0.031, .26), (0.057, .18)))
    return write("AMB05_破庙", *_stereo(_loop(L, 3), _loop(R, 3)))

def AMB06_雾散():
    """风停了。雾散尽了。秦岭的月亮第一次完整地照在这座村子上。
       全片唯一一条有调性的环境层——因为阵破了。"""
    core = 9.0
    d = drone(D3, core, 0.50, 0.18)
    # 全音阶上飘着的极轻的高音（不再是走不出去的圆，是在散开）
    for k, f in enumerate(WHOLE_HI[:4]):
        seg = _gain(xun(f, core, 0.16, breathy=0.22), 0.7)
        for i in range(len(seg)):
            d[i] += seg[i]
    w = _gain(wind(core, 0.12, 100, 900), 0.5)         # 风几乎停了
    s = _mix(d, w)
    L, R = _pan(s, 0.48)
    L = _reverb(L, taps=((0.038, .24), (0.071, .16)))
    R = _reverb(R, taps=((0.042, .24), (0.077, .16)))
    return write("AMB06_雾散", *_stereo(_loop(L, 3), _loop(R, 3)))


# ══════════════════════════════════════════════════════════════════
# 音乐层 MUS
# ══════════════════════════════════════════════════════════════════

def MUS01_归云主题():
    """埙吹四个音。全音阶，停在第六音上——不解决，悬着。"""
    seq = [WHOLE[0], WHOLE[2], WHOLE[1], WHOLE[5]]
    dur = [3.4, 2.6, 3.0, 5.0]
    L = array.array('d'); R = array.array('d')
    total = int(sum(dur) * SR) + SR
    Lb = array.array('d', [0.0]) * total
    Rb = array.array('d', [0.0]) * total
    pos = 0
    for f, d in zip(seq, dur):
        s = xun(f, d, 1.0, breathy=0.16)
        s = _reverb(s, taps=((0.043, .28), (0.079, .18)))
        l, r = _pan(s, 0.35 + random.uniform(-0.1, 0.1))
        for i in range(len(l)):
            if pos + i < total:
                Lb[pos + i] += l[i]; Rb[pos + i] += r[i]
        pos += int(d * 0.78 * SR)                      # 叠一点，呼吸不断
    # 底下垫一层极低的 drone
    dr = drone(D2, total / SR, 0.55, 0.22)
    for i in range(min(len(dr), total)):
        Lb[i] += dr[i] * 0.9; Rb[i] += dr[i] * 0.9
    return write("MUS01_归云主题", Lb, Rb)

def MUS02_陈素心():
    """被压在下头的那一缕。低弦，句尾一律往下掉——和她的声线同一个规则。"""
    total = 22.0
    n = int(total * SR)
    L = array.array('d', [0.0]) * n; R = array.array('d', [0.0]) * n
    # 三个长音，每个都往下坠（结尾频率下滑）
    for k, f in enumerate([WHOLE[0] * 0.5, WHOLE[3] * 0.5, WHOLE[1] * 0.5]):
        pos = int(k * 6.4 * SR)
        d = 7.0
        dn = int(d * SR)
        s = strings(f, d, 1.0, low=True)
        # 句尾下坠：最后 35% 音高滑下去一个全音
        tail = int(dn * 0.62)
        out = array.array('d', s)
        p = 0.0
        for i in range(tail, dn):
            k2 = (i - tail) / max(1, dn - tail)
            fq = f * (1 - 0.11 * k2)
            p += fq * 4096 / SR
            blend = k2 * 0.85
            out[i] = s[i] * (1 - blend) + _SIN[int(p) & 4095] * s[i] * 0 + s[i] * (1 - 0.55 * k2)
        out = _lp(out, SR, 1800)
        l, r = _pan(out, 0.40)
        for i in range(min(len(l), n - pos)):
            L[pos + i] += l[i]; R[pos + i] += r[i]
    dr = drone(D2 * 0.5, total, 0.42, 0.15)
    for i in range(n):
        L[i] += dr[i]; R[i] += dr[i]
    return write("MUS02_陈素心", L, R)

def MUS03_守墓人():
    """她守了快两百年。磬 + 冷 drone。完整、对称、没有情绪——正因为完整才可怕。"""
    total = 24.0
    n = int(total * SR)
    L = array.array('d', [0.0]) * n; R = array.array('d', [0.0]) * n
    for k in range(4):
        pos = int(k * 5.6 * SR)
        s = qing(WHOLE_HI[5 - k], 3.2, 1.0)
        s = _reverb(s, taps=((0.062, .34), (0.11, .22)))
        l, r = _pan(s, 0.5 + (k % 2) * 0.22 - 0.11)
        for i in range(min(len(l), n - pos)):
            L[pos + i] += l[i]; R[pos + i] += r[i]
    dr = drone(D2, total, 0.70, 0.16)
    for i in range(n):
        L[i] += dr[i]; R[i] += dr[i]
    return write("MUS03_守墓人", L, R)

def MUS04_阵眼():
    """六个红点，六处阵眼。六音循环上行——第七个音永远不出现。
       这是全片的音乐规则，也是邪修那个走不出去的圆。"""
    total = 30.0
    n = int(total * SR)
    L = array.array('d', [0.0]) * n; R = array.array('d', [0.0]) * n
    # 三轮上行，每轮六个音，每轮比上一轮紧一点
    for round_i in range(3):
        for k in range(6):
            pos = int((round_i * 9.4 + k * (1.45 - round_i * 0.16)) * SR)
            if pos >= n - SR: continue
            s = guqin(WHOLE[k], 2.2, 0.9 + round_i * 0.15)
            l, r = _pan(s, 0.18 + k * 0.13)            # 音越高越往右，像在爬
            for i in range(min(len(l), n - pos)):
                L[pos + i] += l[i]; R[pos + i] += r[i]
    dr = drone(D2, total, 0.85, 0.30)
    for i in range(n):
        L[i] += dr[i]; R[i] += dr[i]
    L = _reverb(L, taps=((0.036, .22), (0.067, .14)))
    R = _reverb(R, taps=((0.040, .22), (0.073, .14)))
    return write("MUS04_阵眼", L, R)

def MUS05_终局灯灭():
    """第六盏灯灭了。
       前八秒还是全音阶——然后第一次出现一个不属于它的音（F♮）。
       那个音就是第七个。用它，只用它一次，然后留白。"""
    total = 34.0
    n = int(total * SR)
    L = array.array('d', [0.0]) * n; R = array.array('d', [0.0]) * n
    # 前段：全音阶的下行（阵在收）
    for k, f in enumerate([WHOLE[5], WHOLE[4], WHOLE[3], WHOLE[2], WHOLE[1], WHOLE[0]]):
        pos = int(k * 1.35 * SR)
        s = guqin(f, 2.4, 0.85)
        l, r = _pan(s, 0.62 - k * 0.08)
        for i in range(min(len(l), n - pos)):
            L[pos + i] += l[i]; R[pos + i] += r[i]
    # 8.6 秒：第七音。埙吹一个不属于全音阶的 F♮，长，孤零零的一个
    pos7 = int(8.6 * SR)
    s7 = xun(SEVENTH, 9.0, 1.0, breathy=0.26)
    s7 = _reverb(s7, taps=((0.055, .38), (0.098, .26), (0.16, .16)))
    l7, r7 = _pan(s7, 0.5)
    for i in range(min(len(l7), n - pos7)):
        L[pos7 + i] += l7[i]; R[pos7 + i] += r7[i]
    # 同时底下那个走了全片的 drone 停下来
    dr = drone(D2, 9.0, 0.9, 0.25)
    for i in range(min(len(dr), n)):
        L[i] += dr[i]; R[i] += dr[i]
    # 20 秒后：只剩风，和一声磬
    pos_q = int(20.5 * SR)
    sq = qing(D4, 6.0, 0.55)
    sq = _reverb(sq, taps=((0.07, .40), (0.13, .26)))
    lq, rq = _pan(sq, 0.5)
    for i in range(min(len(lq), n - pos_q)):
        L[pos_q + i] += lq[i]; R[pos_q + i] += rq[i]
    w = _gain(wind(total, 0.30, 90, 800), 0.55)
    env = _adsr(n, 12.0, 0.0, 1.0, 6.0, 1.0)           # 风后段才进来
    for i in range(n):
        L[i] += w[i] * env[i]; R[i] += w[i] * env[i]
    return write("MUS05_终局灯灭", L, R)


# ══════════════════════════════════════════════════════════════════
# 钉音 STG
# ══════════════════════════════════════════════════════════════════

def STG01_照片特写():
    """N03 放大日期那一帧：一声极短的弦乐高音，只 0.6 秒。"""
    d = 1.6
    s = strings(WHOLE_HI[5] * 1.5, d, 1.0)
    s = _gain(_hp(s, SR, 700), 1.5)
    e = _adsr(len(s), 0.012, 0.18, 0.10, 0.9, 0.10)
    out = array.array('d', [s[i] * e[i] for i in range(len(s))])
    out = _reverb(out, taps=((0.031, .22), (0.058, .12)))
    l, r = _pan(out, 0.5)
    return write("STG01_照片特写", l, r)

def STG02_青光裂地():
    """脚下的石板裂开，缝里透出青光。低频冲击 + 金属上扬 + 长尾"""
    d = 4.0
    n = int(d * SR)
    # 低频冲击
    imp = array.array('d', [0.0]) * n
    p = 0.0
    for i in range(n):
        f = 90 * (1 - 0.55 * min(1.0, i / (0.9 * SR)))
        p += f * 4096 / SR
        imp[i] = _SIN[int(p) & 4095]
    e = _adsr(n, 0.006, 0.5, 0.12, 2.6, 0.12)
    imp = array.array('d', [imp[i] * e[i] for i in range(n)])
    # 金属上扬（青光）
    rise = array.array('d', [0.0]) * n
    p = 0.0
    for i in range(n):
        f = WHOLE_HI[2] * (1 + 0.9 * min(1.0, i / (1.4 * SR)))
        p += f * 4096 / SR
        rise[i] = _SIN[int(p) & 4095] * 0.35
    e2 = _adsr(n, 0.05, 0.6, 0.22, 2.4, 0.22)
    rise = array.array('d', [rise[i] * e2[i] for i in range(n)])
    s = _mix(imp, rise, _gain(_bp(_noise(n), SR, 300, 2600), 0.18))
    s = _reverb(s, taps=((0.048, .30), (0.093, .22), (0.15, .14)))
    l, r = _pan(s, 0.46)
    return write("STG02_青光裂地", l, r)

def STG03_门():
    """结局 A 定格：他站在门里，成了一道门。低音落定，不解决。"""
    d = 5.0
    s = qing(WHOLE[0] * 0.5, d, 1.0)
    s2 = strings(WHOLE[0] * 0.5, d, 0.55, low=True)
    dr = drone(D2 * 0.5, d, 0.7, 0.12)
    out = _mix(s, s2, dr)
    out = _lp(out, SR, 2200)
    out = _reverb(out, taps=((0.062, .34), (0.115, .22)))
    l, r = _pan(out, 0.5)
    return write("STG03_门", l, r)


# ── 主流程 ────────────────────────────────────────────────────────
JOBS = [
    ("环境", [AMB01_山雾, AMB02_客栈夜, AMB03_墙内, AMB04_井底, AMB05_破庙, AMB06_雾散]),
    ("音乐", [MUS01_归云主题, MUS02_陈素心, MUS03_守墓人, MUS04_阵眼, MUS05_终局灯灭]),
    ("钉音", [STG01_照片特写, STG02_青光裂地, STG03_门]),
]

if __name__ == "__main__":
    import sys, time
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for cat, fns in JOBS:
        if only and only != cat:
            continue
        print(f"\n── {cat} ──")
        for fn in fns:
            t = time.time()
            p, d = fn()
            print(f"  {os.path.basename(p):<28}{d:>6.1f}s  ({time.time()-t:.1f}s)")
    print("\n→", OUT)
