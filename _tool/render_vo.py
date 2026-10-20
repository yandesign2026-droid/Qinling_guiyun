#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
秦岭归云 · 台词库 v3 批量配音渲染

edge-tts 合成 → afconvert 转 24k → 后期 DSP（区分三个老年男）→ 归一化 → 44.1k wav

    python3 _tool/render_vo.py            # 全量
    python3 _tool/render_vo.py --limit 8  # 只渲染前 8 条做样本
"""
import os, sys, json, wave, array, math, random, subprocess, shutil
from concurrent.futures import ThreadPoolExecutor

ROOT = "/Users/home/游戏 秦岭归云"
LIST = os.path.join(ROOT, "_tool/vo_list_v3.json")
TMP  = "/tmp/qlyy_vo"
OUT  = os.path.join(ROOT, "配音_v3")

random.seed(1986)

# ── DSP ────────────────────────────────────────────────────────────

def _lp(sig, sr, fc):
    """一阶低通（递归），返回新 array"""
    a = 1.0 - math.exp(-2.0 * math.pi * fc / sr)
    out = array.array('d', [0.0]) * len(sig)
    y = 0.0
    for i in range(len(sig)):
        y += a * (sig[i] - y)
        out[i] = y
    return out

def _hp(sig, sr, fc):
    """一阶高通"""
    a = 1.0 / (1.0 + 2.0 * math.pi * fc / sr)
    out = array.array('d', [0.0]) * len(sig)
    y = 0.0
    x1 = 0.0
    for i in range(len(sig)):
        x = sig[i]
        y = a * (y + x - x1)
        out[i] = y
        x1 = x
    return out

def _softclip(sig, th=0.55):
    """软削波，给嗓音加砂砾感"""
    out = array.array('d', [0.0]) * len(sig)
    for i in range(len(sig)):
        x = sig[i]
        ax = abs(x)
        if ax <= th:
            out[i] = x
        else:
            s = 1.0 if x > 0 else -1.0
            e = ax - th
            out[i] = s * (th + e / (1.0 + e / (1.0 - th)))
    return out

def _addnoise(sig, amt, sr, lp=3000):
    """电流声。底噪必须先过一次低通——宽带白噪听着是"嘶嘶"，
    19 米波段的底噪是闷的。爆音同理，做成 8ms 的衰减脉冲。"""
    n = len(sig)
    noise = array.array('d', [random.uniform(-amt, amt) for _ in range(n)])
    noise = _lp(noise, sr, lp)
    noise = _lp(noise, sr, lp)
    step = int(0.4 * sr)
    bl = max(1, int(0.008 * sr))
    for i in range(0, n, step):
        if random.random() < 0.55:
            j = i + random.randint(0, max(0, step - bl - 1))
            amp = random.choice((-1, 1)) * amt * 4.0
            for k in range(min(bl, n - j)):
                env = 1.0 - k / bl
                noise[j + k] += amp * env * env
    out = array.array('d', sig)
    for i in range(n):
        out[i] += noise[i]
    return out


def _trim(sig, sr, th=0.004, pad_ms=60):
    """裁掉 edge-tts 的前导/尾随静音。短句不裁会拖慢节奏。"""
    n = len(sig)
    pad = int(sr * pad_ms / 1000)
    a, b = 0, n
    for i in range(n):
        if abs(sig[i]) > th:
            a = max(0, i - pad)
            break
    for i in range(n - 1, -1, -1):
        if abs(sig[i]) > th:
            b = min(n, i + pad)
            break
    if b <= a:
        return sig
    out = array.array('d', sig[a:b])
    # 首尾 20ms 淡入淡出，避免咔哒
    f = int(sr * 0.02)
    m = min(f, len(out))
    for i in range(m):
        out[i] *= i / m
        out[len(out) - 1 - i] *= i / m
    return out


def _rms_norm(sig, target=0.13, ceiling=0.95):
    """按响度归一化（峰值归一只治标）。超出 ceiling 则回落。"""
    n = len(sig)
    if n == 0:
        return sig
    cur = math.sqrt(sum(x * x for x in sig) / n)
    if cur < 1e-6:
        return sig
    g = target / cur
    peak = max(abs(x) for x in sig) * g
    if peak > ceiling:
        g *= ceiling / peak
    return array.array('d', [x * g for x in sig])

def _room(sig, sr):
    """极轻房间感：三次延迟叠加，模拟土坯房"""
    d1, d2, d3 = int(0.013 * sr), int(0.021 * sr), int(0.037 * sr)
    out = array.array('d', sig)
    n = len(sig)
    for d, g in ((d1, 0.22), (d2, 0.14), (d3, 0.08)):
        for i in range(d, n):
            out[i] += sig[i - d] * g
    return out

def _gain(sig, db):
    g = 10.0 ** (db / 20.0)
    return array.array('d', [x * g for x in sig])

def _normalize(sig, target=0.79):
    peak = 0.0
    for x in sig:
        ax = abs(x)
        if ax > peak:
            peak = ax
    if peak < 1e-6:
        return sig
    g = target / peak
    return array.array('d', [x * g for x in sig])


def post_process(sig, sr, kind):
    """后期处理主线。三个老年男在这里被拉开。"""
    if kind == "radio":
        # 周教授 / 邪修：19 米波段。窄带 + 轻失真（噪声在归一化之后单独加）
        s = _hp(sig, sr, 320)
        s = _lp(s, sr, 3300)
        s = _lp(s, sr, 3300)
        s = _softclip(s, 0.6)
        s = _hp(s, sr, 200)
        return s
    if kind == "gravel":
        # 赵铁柱 / 孙明远：猎人，几十年山风。砂砾 + 沉
        s = _lp(sig, sr, 4200)
        s = _softclip(s, 0.48)
        s = _lp(s, sr, 3600)
        return s
    if kind == "room":
        # 林援朝：土坯房里说话，有墙。轻微房间感，不加噪
        s = _room(sig, sr)
        s = _lp(s, sr, 5200)
        return s
    if kind == "weaken":
        # 陈素心：从三十年的深处挤出来。闷、虚、气声
        s = _lp(sig, sr, 4500)
        s = _lp(s, sr, 4500)
        s = _hp(s, sr, 110)
        s = _gain(s, -3.0)
        return s
    if kind == "quiet":
        # 旁白 / 环境句
        s = _lp(sig, sr, 7000)
        s = _gain(s, -4.0)
        return s
    return sig


# ── IO ─────────────────────────────────────────────────────────────

def read_wav(path):
    with wave.open(path) as w:
        n = w.getnframes()
        sr = w.getframerate()
        raw = w.readframes(n)
    a = array.array('h')
    a.frombytes(raw)
    return array.array('d', [x / 32768.0 for x in a]), sr

def write_wav(path, sig, sr):
    out = array.array('h', [max(-32768, min(32767, int(x * 32767))) for x in sig])
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(out.tobytes())

def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


# ── 主流程 ─────────────────────────────────────────────────────────

def tts(item):
    """阶段 1：edge-tts 合成（网络 IO 密集，用线程并行）"""
    mp3 = os.path.join(TMP, item["id"] + ".mp3")
    if os.path.exists(mp3) and os.path.getsize(mp3) > 1000:
        return item["id"], True
    cmd = (f'edge-tts -v {item["voice"]} --rate={item["rate"]} '
           f'--pitch={item["pitch"]} -t {json.dumps(item["text"], ensure_ascii=False)} '
           f'--write-media "{mp3}"')
    r = sh(cmd)
    ok = os.path.exists(mp3) and os.path.getsize(mp3) > 1000
    if not ok:
        print("  TTS FAIL", item["id"], r.stderr[:120])
    return item["id"], ok

def convert(item):
    """阶段 2+3+4：mp3 → 24k wav → DSP → 归一化 → 44.1k wav"""
    oid = item["id"]
    mp3 = os.path.join(TMP, oid + ".mp3")
    w24 = os.path.join(TMP, oid + "_24.wav")
    w44 = os.path.join(OUT, f'{oid}_{item["speaker"]}.wav')
    if os.path.exists(w44):
        return oid, True
    r = sh(f'afconvert -f WAVE -d LEI16@24000 -c 1 "{mp3}" "{w24}"')
    if not os.path.exists(w24):
        return oid, False
    sig, sr = read_wav(w24)
    sig = _trim(sig, sr)                       # 1 裁掉前导/尾随静音
    sig = _normalize(sig, 0.90)                # 2 先按峰值对齐
    sig = post_process(sig, sr, item["post"])  # 3 音色
    tgt = 0.09 if item["tier"] in ("env", "inscription") else 0.13
    sig = _rms_norm(sig, tgt, 0.95)            # 4 先定响度
    if item["post"] == "radio":                # 5 电流声：绝对量，必须在定完响度之后加
        sig = _addnoise(sig, 0.004, sr)        #   否则会被 rms 归一化一起放大成白噪
    sig = _rms_norm(sig, tgt, 0.95)            # 5 按响度对齐
    sig = _normalize(sig, 0.95)                # 6 峰值安全阀
    write_wav(w24, sig, 24000)
    sh(f'afconvert -f WAVE -d LEI16@44100 -c 1 "{w24}" "{w44}"')
    return oid, os.path.exists(w44)


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    data = json.load(open(LIST, encoding="utf-8"))
    lines = [x for x in data["lines"] if x["tier"] not in ("skip", "inscription")]
    if limit:
        # 样本模式下优先取每个角色的一条 + 全部金句
        seen, sample = set(), []
        for x in lines:
            if x["tier"] == "gold":
                sample.append(x)
                continue
            if x["speaker"] not in seen:
                seen.add(x["speaker"])
                sample.append(x)
        lines = sample[:limit] if limit else sample
    else:
        lines = lines

    os.makedirs(TMP, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    print(f"渲染 {len(lines)} 条 → {OUT}")
    print("阶段 1/2：edge-tts 合成…")
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(tts, lines))
    ok = sum(1 for _, b in res if b)
    print(f"  合成成功 {ok}/{len(lines)}")

    print("阶段 2/2：转码 + 后期 + 归一化…")
    with ThreadPoolExecutor(max_workers=6) as ex:
        res2 = list(ex.map(convert, [x for x, b in zip(lines, [r[1] for r in res]) if b]))
    ok2 = sum(1 for _, b in res2 if b)
    print(f"  输出成功 {ok2}/{ok}")

    # manifest
    man = []
    for x in lines:
        man.append({
            "id": x["id"], "speaker": x["speaker"], "text": x["text"],
            "tier": x["tier"], "src": x["src"], "n": x["n"],
            "file": f'{x["id"]}_{x["speaker"]}.wav',
            "voice": x["voice"], "rate": x["rate"], "pitch": x["pitch"], "post": x["post"],
        })
    json.dump(man, open(os.path.join(ROOT, "_tool/vo_manifest_v3.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"manifest: {len(man)} 条")

if __name__ == "__main__":
    main()
