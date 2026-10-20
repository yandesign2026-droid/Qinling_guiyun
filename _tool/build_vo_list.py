#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从《秦岭归云_台词库_v3_小说原文版.md》抽取全部台词，生成可直接渲染的配音清单。"""
import re, json, os

MD = "/Users/home/游戏 秦岭归云/秦岭归云_台词库_v3_小说原文版.md"

# ── 角色 → 声轨参数 ───────────────────────────────────────────────
# 8 个 zh-CN 音色里，男声只有 3 个可用（Yunyang / Yunjian / Yunxi）。
# 三个老年男全部由 Yunjian 派生，靠 rate/pitch/后期三段拉开。
SPEAKERS = {
# rate 只影响时长，pitch 才决定年龄感。老年音色的 rate 不能压过 -20%，
# 否则 30 字长句会拖到 10 秒以上，游戏节奏直接崩。
    "旁白":   {"voice": "zh-CN-YunyangNeural", "rate": "-8%",  "pitch": "-4Hz",  "post": "quiet",   "note": "环境句声轨，比沈怀谷更慢更轻"},
    "沈怀谷": {"voice": "zh-CN-YunyangNeural", "rate": "-2%",  "pitch": "-2Hz",  "post": "none",    "note": "与旁白同音色，只差语速"},
    "老板娘": {"voice": "zh-CN-XiaoxiaoNeural","rate": "+8%",  "pitch": "-4Hz",  "post": "none",    "note": "泉水·清冽·吐字完整，全片最好听的一条嗓子"},
    "陈素心": {"voice": "zh-CN-XiaoxiaoNeural","rate": "-8%",  "pitch": "-24Hz", "post": "weaken",  "note": "与老板娘同一张脸，句尾一律往下掉"},
    "赵铁柱": {"voice": "zh-CN-YunjianNeural", "rate": "-18%", "pitch": "-52Hz", "post": "gravel",  "note": "猎人·独眼·六十出头·山里的寒"},
    "林援朝": {"voice": "zh-CN-YunjianNeural", "rate": "-12%", "pitch": "-34Hz", "post": "room",    "note": "拾骨人·守了三十年·旧年月味·绕"},
    "周教授": {"voice": "zh-CN-YunjianNeural", "rate": "-6%",  "pitch": "-18Hz", "post": "radio",   "note": "只存在于收音机里，强制过 19 米波段滤波"},
    "孙明远": {"voice": "zh-CN-YunyangNeural","rate": "-10%", "pitch": "-15Hz", "post": "none",    "note": "村口黑褂老头·正常老年男声（占位，后期换真人）"},
    "商人":   {"voice": "zh-CN-YunxiNeural",   "rate": "+6%",  "pitch": "+8Hz",  "post": "none",    "note": "急·算盘子响·自保"},
    "摄影师": {"voice": "zh-CN-YunxiNeural",   "rate": "-6%",  "pitch": "-6Hz",  "post": "none",    "note": "全片一句台词"},
    "邪修":   {"voice": "zh-CN-YunjianNeural", "rate": "-20%", "pitch": "-60Hz", "post": "radio",   "note": "刻字·文物感，井底传来"},
}

# 章 → 说话人
CHAPTER_SPEAKER = {
    "2": "陈素心", "3": "老板娘", "4": "赵铁柱", "5": "林援朝",
    "6": "周教授", "7": "商人",   "8": "孙明远", "8.5": "沈怀谷",
    "9": "邪修",   "10": "旁白",
}

def parse():
    text = open(MD, encoding="utf-8").read()
    lines = text.split("\n")
    cur_ch = None
    cur_speaker = None
    rows = []

    for ln in lines:
        m = re.match(r"^##\s+([\d.]+)\s+(.*)", ln)
        if m:
            cur_ch = m.group(1).rstrip(".")
            cur_speaker = CHAPTER_SPEAKER.get(cur_ch)
            continue
        # 主角线：章 7 之后插入的沈怀谷对白由显式标记给出
        if "沈怀谷" in ln and ln.startswith("|") is False:
            pass
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if cells[0] in ("#", "编号", "角色", "项") or set(cells[0]) <= set("-: "):
            continue
        # 四列台词表： # | 台词 | 出处 | 字数
        if len(cells) >= 4 and cells[3].isdigit():
            idx, line, src, n = cells[0], cells[1], cells[2], int(cells[3])
            # 邪修章：刻字，不做对白音轨
            speaker = cur_speaker
            # 老板娘章内"42/43/44"终局三句仍归老板娘
            tier = "normal"
            if re.search(r"\*\*V\d+\*\*", line):
                tier = "gold"
            elif "配音" in src or tier == "gold":
                pass
            clean = re.sub(r"\*\*V\d+\*\*\s*", "", line).strip()
            clean = clean.strip("。. ")
            rows.append({
                "id": f"Q{idx}",
                "speaker": speaker,
                "text": line.replace("**", ""),
                "clean": clean,
                "src": src,
                "tier": tier,
                "n": n,
            })
        elif len(cells) == 3 and cells[2].isdigit():
            # 三列表格分两种：编号开头的台词表 / 角色名开头的兜底表
            if cells[0].isdigit():
                rows.append({
                    "id": f"Q{cells[0]}",
                    "speaker": cur_speaker,
                    "text": cells[1],
                    "clean": cells[1],
                    "src": "终局三句",
                    "tier": "normal",
                    "n": int(cells[2]),
                })
            else:
                rows.append({
                    "id": f"F{len(rows)+1:02d}",
                    "speaker": cells[0],
                    "text": cells[1],
                    "clean": cells[1],
                    "src": "兜底",
                    "tier": "fallback",
                    "n": int(cells[2]),
                })
    return rows

rows = parse()

# Q67「他站在那儿，没有倒下」是小说叙述句，不是赵铁柱台词 → 走旁白声轨
for _r in rows:
    if _r["id"] == "Q67":
        _r["speaker"] = "旁白"

# 去重（同一句在不同章重复出现）
seen = set()
out = []
for r in rows:
    k = (r["speaker"], r["clean"])
    if k in seen:
        continue
    seen.add(k)
    out.append(r)

for r in out:
    sp = SPEAKERS.get(r["speaker"], SPEAKERS["旁白"])
    r["voice"] = sp["voice"]
    r["rate"] = sp["rate"]
    r["pitch"] = sp["pitch"]
    r["post"] = sp["post"]

# 环境句 / 口诀 / 刻字 做层级标记（金句优先，不被覆盖）
for r in out:
    if r["speaker"] == "旁白" and r["tier"] != "gold":
        r["tier"] = "env"
    if "子时三刻" in r["text"]:
        r["tier"] = "spell"
    if r["speaker"] == "邪修":
        r["tier"] = "inscription"
    if r["id"] == "Q144":          # 「我确定」是打字，不出声
        r["tier"] = "skip"

os.makedirs("/Users/home/游戏 秦岭归云/_tool", exist_ok=True)
dst = "/Users/home/游戏 秦岭归云/_tool/vo_list_v3.json"
json.dump({"speakers": SPEAKERS, "lines": out}, open(dst, "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

from collections import Counter
print(f"总条数 {len(out)}")
print("按角色:", dict(Counter(r['speaker'] for r in out)))
print("按层级:", dict(Counter(r['tier'] for r in out)))
for r in out:
    if r['tier'] == 'gold':
        print(f"  {r['id']} [{r['speaker']}] {r['text'][:40]} ({r['n']}字)")
print("→", dst)
