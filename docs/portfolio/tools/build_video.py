"""Build a 5-minute subtitled MP4 from unaltered public-demo screenshots.

No browser numbers are replaced. The right rail and captions are editorial annotations.
Requires Pillow and a free FFmpeg build with libx264; video output stays outside Git.
"""
import argparse
import json
import math
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Seconds, actual screenshot, chapter, heading, editorial notes, sentence-by-sentence narration.
SCENES = [
    (15, '01-home', '01 / 项目介绍', '把运营工作连成一条线', ['公开 Synthetic 模拟数据', '真实 Edge 页面素材', '截图剪辑 · 中文字幕 · 无配音'], [
        '这是跨境电商智能经营监控系统V2.1，一个面向数据运营岗位的个人技术作品集。',
        '视频采用真实线上页面截图剪辑，演示全部使用Synthetic模拟数据，不代表真实企业收益。']),
    (10, '02-baseline', '01 / 项目介绍', '先核查，再分析，再汇报', ['Python / Pandas', 'SQL / SQLite / Streamlit', '质量 → 指标 → 预警 → 修订 → 日报'], [
        '系统使用Python、Pandas、SQL、SQLite和Streamlit，将质量检查、经营分析、预警、人工修订和日报连接起来。']),
    (8, '03-workbench', '02 / 订单质量治理', '先看有效样本', ['有效订单 71 笔', '折后销售额 1,364 USD', '初始全期：9月1日至14日'], [
        '工作台初始有71笔有效订单，销售额1364美元。这里统计的是通过现有规则的有效样本。']),
    (8, '04-quality-summary', '02 / 订单质量治理', '异常条数不等于订单数', ['待核实异常 3 条', '受影响记录 2 条', '两条金额规则命中同一订单'], [
        '质量检查显示3条待核实异常，只影响2条记录。异常条数不能直接当成错误订单数量，更不是损失金额。']),
    (10, '05-negative-price', '02 / 订单质量治理', 'SYNTH-BAD：负价订单', ['unit_price = -10 USD', 'invalid_price', '原记录72 · 源文件第73行'], [
        'SYNTH-BAD的单价是负十美元。系统识别invalid_price，保留原始值、批次和源文件行号，并隔离整张订单。']),
    (7, '07-discount-rule', '02 / 订单质量治理', '规则指出错误，不猜正确值', ['invalid_discount 同时命中', '负价导致优惠金额关系不合法', '正确价格仍需凭证核实'], [
        '同一负单价还触发优惠关系检查。系统知道数据不合法，但正确单价必须由人工核对凭证。']),
    (12, '08-unknown-cost', '02 / 订单质量治理', '收入有效，利润未知', ['SYNTH-UNKNOWN / SKU999', '20 USD 收入保留', '未知成本不填0'], [
        '另一张SYNTH-UNKNOWN有20美元收入，但SKU999没有匹配成本。',
        '系统保留收入，只隔离利润计算，避免把未知成本填零而虚增利润。']),
    (20, '09-sku001', '03 / 商品经营分析', 'SKU001：主要毛利来源', ['同一窗口：9月1日至14日', '销售 924 USD · 49笔', '商品毛利 532 USD', '暂估贡献 178 USD'], [
        '在经营分析中保持9月1日至14日，选择SKU001。页面显示销售924美元、49笔订单、毛利532美元。',
        '暂估贡献是178美元。运营人员可以按同一范围比较商品，而不用反复复制透视表和匹配成本。']),
    (20, '10-sku002', '03 / 商品经营分析', 'SKU002：缺数据不能当零', ['销售 420 USD · 21笔', '商品毛利 126 USD', '贡献与ROAS：数据不足', '成本覆盖不等于费用完整'], [
        '切换SKU002，销售420美元、毛利126美元，但贡献和ROAS显示数据不足。',
        '这不是零贡献，也不能据此判定商品不值得经营。还要补齐广告费用和归因信息，再比较盈利能力。']),
    (10, '12-alert-run', '04 / 智能经营预警', '手动检测，复用同周期待办', ['参考日 2026-10-21', '本次触发 22 项', '新增 0 条待办'], [
        '以10月21日为参考日运行规则检测，触发22项、新增零待办，因为相同周期的待办已经存在。']),
    (17, '13-alert-evidence', '04 / 智能经营预警', 'Amazon退款率上升', ['前期 2.38% → 本期 17.86%', '上升 15.48 个百分点', '阈值：5 个百分点', '9/1—9/7 对比 9/8—9/14'], [
        'Amazon退款订单率由前一周的2.38%升至后一周的17.86%，增加15.48个百分点，超过5个百分点阈值。',
        '这提示需要优先核查退款凭证和成熟订单队列，不能直接认定是商品质量或物流造成的。']),
    (13, '14-alert-handled', '04 / 智能经营预警', '留下调查进度', ['填写模拟处理说明', '待处理 → 处理中', '没有直接确认根因'], [
        '我填写模拟核查说明，把状态改为处理中。系统保存处理日志，供后续跟进，而不是替运营人员作出经营决定。']),
    (10, '15-revision-form', '05 / 修订与指标重算', '申请纠正，不覆盖原始行', ['SYNTH-BAD / unit_price', '-10 → 20 USD', '原因与模拟凭证引用必填'], [
        '核对模拟凭证后，在数据修订中选择SYNTH-BAD，把单价从负十申请改为二十，并填写原因和凭证引用。']),
    (8, '16-revision-submitted', '05 / 修订与指标重算', '待审核不进入计算', ['申请已提交', '审批前指标不变', '申请与生效分开'], [
        '提交申请后，页面提示审批前指标不变。未经批准的建议值不会直接进入经营汇总。']),
    (8, '17-approval-form', '05 / 修订与指标重算', '模拟审批有说明', ['审核结论：已批准', '记录审核说明', '演示身份不是生产权限'], [
        '填写模拟审核说明并批准。这里展示审批流程，但同一访客可以申请和批准，不代表已有生产级权限。']),
    (10, '18-revision-approved', '05 / 修订与指标重算', '原值、凭证与审批可追溯', ['原值 -10 仍然保留', '批准后的有效值 20', '版本链与审批历史'], [
        '批准后，系统保留原值、新值、凭证引用和审批历史，按有效版本重新质检，而不是无痕覆盖原始记录。']),
    (12, '19-recomputed', '05 / 修订与指标重算', '核对每一项变化', ['销售 1,364 → 1,384 USD', '订单 71 → 72 笔', '毛利 658 → 670 USD', '贡献 262 → 272 USD'], [
        '全期销售变为1384美元，订单72笔，毛利670美元，暂估贡献272美元。',
        '销售只增加20美元而不是30，因为原先负价订单根本没有进入有效汇总。']),
    (7, '20-inventory-difference', '05 / 修订与指标重算', '修好订单，不等于全链路正确', ['新增库存与订单一致性异常', 'SKU001 / 2026-09-14', '不能为了全绿而强行放行'], [
        '重新质检又发现SKU001库存出库与有效订单数量不一致。修复订单并不代表上下游数据全部正确。']),
    (5, '21-inventory-source', '05 / 修订与指标重算', '继续核对库存凭证', ['原库存出库数量仍为2', '订单有效样本已改变', '差异不等于仓库一定出错'], [
        '原库存出库仍为两件，需要继续核查履约和库存凭证，不能直接归责仓库。']),
    (7, '22-daily-dates', '06 / 经营日报与汇报', '明确经营日与观察日', ['D：2026-09-14', 'H：2026-10-21', 'H只影响退款观察队列'], [
        '日报选择9月14日，退款观察截止日为10月21日。H不是全部数据的历史截断日期。']),
    (10, '11-daily-before', '06 / 经营日报与汇报', '回看修订前的日报', ['此画面为修订前留存', '销售 92 USD · 贡献 -8 USD', '销售增长不等于利润增长'], [
        '先回看修订前留存的日报：当日销售92美元，暂估贡献负8美元。未知成本收入增加，不代表已知样本利润增加。']),
    (14, '23-daily-after', '06 / 经营日报与汇报', '修订后的经营日报', ['销售 112 USD · 6笔订单', '毛利 40 USD · 贡献 2 USD', 'ROAS仍为0.56', '这是纠错后的重算结果'], [
        '批准修订后的日报，销售为112美元、6笔订单、毛利40美元、暂估贡献2美元，ROAS仍是0.56。',
        '这些变化包含数据纠错，不应说成新经营动作带来的增长。']),
    (9, '24-daily-limits', '06 / 经营日报与汇报', '把限制一起交给店长', ['成本覆盖率 82.14%', '未知成本订单仍有1笔', '暂估贡献不是财务净利润'], [
        '当日成本覆盖率仍只有82.14%，还有一笔未知成本订单。暂估贡献没有覆盖完整财务费用，不能当成净利润。']),
    (8, '25-daily-guidance', '06 / 经营日报与汇报', '建议是核查方向', ['核对成本、库存与退款证据', '历史预警不等于最新检测', '修订后预警需另行运行'], [
        '报告保留历史预警和核查建议。历史触发不代表当前仍触发，修订后还应重新运行规则检测。']),
    (7, '26-daily-download', '06 / 经营日报与汇报', '下载可离线复核的日报', ['六项KPI与D−1比较', '样本限制及核查建议', 'HTML可离线打开'], [
        '点击下载HTML日报，即可离线查看指标、前日比较、限制和核查建议，减少手工制作日报。']),
    (15, '27-ending', '07 / 总结与边界', '展示数据运营的完整工作', ['质量检测 → 异常隔离', '经营分析 → 风险预警', '审核修订 → 日报生成'], [
        '这个项目展示的能力，是把质量检测、异常隔离、经营指标、风险预警、审核修订和日报连接成可追溯流程。',
        '员工减少重复汇总，把时间用于核实事实、解释原因和推动处理。']),
    (20, None, '07 / 总结与边界', '明确实现，也明确边界', ['个人技术作品集 / Synthetic', '尚未验证真实企业生产数据', '无自动平台同步与生产权限', '不是生产级SaaS或财务系统'], [
        '目前使用模拟数据，没有真实平台自动同步和生产级身份权限，也没有完整财务费用体系。',
        '它是一套个人技术作品集，不是生产级SaaS，不能替代完整财务系统。欢迎打开在线演示，按业务案例复现。']),
]


def timestamp(sec, srt=False):
    ms = round(sec * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}' if srt else f'{h*60+m:02}:{s:02}'


def wrap(draw, text, font, width):
    lines, line = [], ''
    for char in text:
        if char == '\n' or draw.textlength(line + char, font=font) > width:
            lines.append(line)
            line = '' if char == '\n' else char
        else:
            line += char
    if line:
        lines.append(line)
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--capture', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--ffmpeg', required=True)
    ap.add_argument('--font', default=str(Path(os.environ.get('WINDIR', '.')) / 'Fonts' / 'msyh.ttc'))
    ap.add_argument('--docs', type=Path, default=Path(__file__).resolve().parent.parent)
    args = ap.parse_args()
    assert sum(s[0] for s in SCENES) == 300
    args.out.mkdir(parents=True, exist_ok=True)
    frames = args.out / 'frames'
    frames.mkdir(exist_ok=True)
    fonts = {n: ImageFont.truetype(args.font, n) for n in (18, 20, 22, 25, 28, 30, 34, 42, 58)}
    cues, chapters, timeline = [], [], []
    elapsed = 0.0
    for duration, shot, chapter, heading, notes, narration in SCENES:
        if not chapters or chapters[-1]['title'] != chapter:
            chapters.append({'start': elapsed, 'title': chapter})
        base = Image.new('RGB', (1920, 1080), '#0b1425')
        d = ImageDraw.Draw(base)
        d.text((26, 20), '跨境电商经营监控 V2.1', font=fonts[30], fill='white')
        d.text((600, 27), chapter, font=fonts[25], fill='#72d9ca')
        d.rounded_rectangle((1530, 16, 1895, 64), radius=12, fill='#173b45')
        d.text((1550, 25), 'Synthetic 模拟 · 线上实操', font=fonts[25], fill='#b8fff1')
        if shot:
            source = Image.open(args.capture / f'{shot}.png').convert('RGB')
            source.thumbnail((1344, 840), Image.Resampling.LANCZOS)
            x, y = 24 + (1344-source.width)//2, 94 + (840-source.height)//2
            d.rounded_rectangle((20, 90, 1372, 938), radius=10, fill='white')
            base.paste(source, (x, y))
            d.text((1400, 100), '讲解标注 / 不改页面数据', font=fonts[20], fill='#8da8bf')
            yy = 150
            for line in wrap(d, heading, fonts[34], 480):
                d.text((1400, yy), line, font=fonts[34], fill='white'); yy += 50
            d.line((1400, yy+16, 1888, yy+16), fill='#2b475c', width=2)
            yy += 55
            for note in notes:
                d.ellipse((1400, yy+12, 1408, yy+20), fill='#6de0ce')
                for line in wrap(d, note, fonts[28], 452):
                    d.text((1420, yy), line, font=fonts[28], fill='#dbe7f2'); yy += 44
                yy += 20
            d.text((1400, 810), '真实 Edge 页面截图剪辑', font=fonts[22], fill='#8da8bf')
            d.text((1400, 846), '2026-10-26 / USD', font=fonts[22], fill='#8da8bf')
            d.text((1400, 882), f'{timestamp(elapsed)}—{timestamp(elapsed+duration)}', font=fonts[22], fill='#8da8bf')
        else:
            d.text((90, 130), '从发现错误，到交付可信日报', font=fonts[58], fill='white')
            d.text((90, 220), '流程示意（讲解） · 不是新增系统页面', font=fonts[25], fill='#8da8bf')
            labels = ['质量检测', '异常隔离', '经营分析', '风险预警', '审核修订', '日报生成']
            for i, label in enumerate(labels):
                x = 80 + (i % 3)*610; y = 320+(i//3)*180
                d.rounded_rectangle((x, y, x+550, y+125), radius=18, fill='#153b4a')
                d.text((x+35,y+35), f'0{i+1}  {label}', font=fonts[42], fill='#c3fff0')
            d.text((90, 735), '模拟作品集 · 未验证真实企业生产数据', font=fonts[34], fill='white')
            d.text((90, 800), '无自动平台同步 / 无生产级权限 / 不替代完整财务系统', font=fonts[30], fill='#b1c7dc')
        sentence_duration = duration / len(narration)
        for line_no, sentence in enumerate(narration):
            start = elapsed + line_no*sentence_duration
            end = elapsed + (line_no+1)*sentence_duration
            frame = base.copy(); fd = ImageDraw.Draw(frame)
            fd.rectangle((0, 952, 1920, 1080), fill='#040a13')
            subtitle_lines = wrap(fd, sentence, fonts[30], 1760)
            assert len(subtitle_lines) <= 2, sentence
            y = 976 if len(subtitle_lines) == 2 else 995
            for line in subtitle_lines:
                width = fd.textlength(line, font=fonts[30])
                fd.text(((1920-width)/2, y), line, font=fonts[30], fill='white'); y += 43
            fd.rectangle((0, 1074, int(1920*end/300), 1079), fill='#53d4bf')
            image_name = f'frame-{len(cues)+1:03}.png'
            frame.save(frames/image_name)
            cues.append({'start': start, 'end': end, 'text': sentence, 'frame': image_name})
        timeline.append({'start': elapsed, 'end': elapsed+duration, 'shot': shot, 'chapter': chapter, 'heading': heading, 'narration': narration})
        elapsed += duration

    srt = '\n\n'.join(f'{i+1}\n{timestamp(c["start"], True)} --> {timestamp(c["end"], True)}\n{c["text"]}' for i,c in enumerate(cues)) + '\n'
    (args.out/'demo.zh-CN.srt').write_text(srt, encoding='utf-8')
    (args.docs/'DEMO.zh-CN.srt').write_text(srt, encoding='utf-8')
    (args.out/'timeline.json').write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding='utf-8')
    doc = ['# 5分钟演示：完整分镜与逐句中文讲稿', '', '> 实际视频为1920×1080中文字幕MP4，使用真实Playwright + Edge线上页面截图剪辑；无配音、无背景音乐、非连续录屏。右侧是独立讲解标注，未修改页面数字。所有经营数据为Synthetic。', '', '[在线体验](https://ecommerce-business-analysis-izcmrhydxddnasxqdbdxxr.streamlit.app/) · [面试案例](INTERVIEW_CASE.md) · [展示成果](SHOWCASE.md)', '', '## 七段时间轴', '', '|时间|内容|', '|---|---|']
    for i, chapter in enumerate(chapters):
        end = chapters[i+1]['start'] if i+1 < len(chapters) else 300
        doc.append(f'|{timestamp(chapter["start"])}—{timestamp(end)}|{chapter["title"]}|')
    doc += ['', '## 分镜与逐句讲稿', '', '以下每句均对应视频中文字幕，可直接录制真人配音。素材编号对应capture-manifest和截图文件名；回看修订前日报已明确标记，不与修订后画面混淆。', '']
    for scene in timeline:
        doc += [f'### {timestamp(scene["start"])}—{timestamp(scene["end"])}｜{scene["heading"]}', '', f'**画面：** {scene["shot"] or "讲解流程示意卡"}；{scene["chapter"]}。', '']
        for c in cues:
            if scene['start'] <= c['start'] < scene['end']:
                doc.append(f'- {timestamp(c["start"])}—{timestamp(c["end"])}：“{c["text"]}”')
        doc.append('')
    doc += ['## 复现与发布', '', '1. 使用已有Node 20+、Playwright及Microsoft Edge，运行[采集脚本](tools/capture_demo.cjs)。只允许固定公开Synthetic网址；脚本会在独立演示会话填写模拟预警和修订，不连接本地业务库。', '2. 使用Pillow与免费FFmpeg运行[视频构建脚本](tools/build_video.py)，通过参数指定素材和输出目录，输出目录应位于仓库之外。', '3. 构建脚本同时生成逐句SRT、时间轴和视频。缺失素材或数值不符时应停止，不修改截图数字。', '4. [独立字幕文件](DEMO.zh-CN.srt)与[可复现命令](SHOWCASE.md)随文档提供。MP4不提交到Git；本轮未上传托管，发布由作者决定。', '']
    (args.docs/'VIDEO_SCRIPT.md').write_text('\n'.join(doc), encoding='utf-8')
    concat = []
    for c in cues:
        concat.extend([f"file 'frames/{c['frame']}'", f"duration {c['end']-c['start']:.6f}"])
    concat.append(f"file 'frames/{cues[-1]['frame']}'")
    (args.out/'frames.ffconcat').write_text('\n'.join(concat)+'\n', encoding='utf-8')
    output = args.out/'ecommerce-v21-demo-zh-CN.mp4'
    command = [args.ffmpeg, '-hide_banner', '-y', '-f', 'concat', '-safe', '0', '-i', 'frames.ffconcat', '-vf', 'fps=24,tpad=stop_mode=clone:stop_duration=10', '-frames:v', '7200', '-c:v', 'libx264', '-preset', 'fast', '-crf', '21', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an', output.name]
    with (args.out/'encode.log').open('w', encoding='utf-8') as log:
        subprocess.run(command, cwd=args.out, stdout=log, stderr=subprocess.STDOUT, check=True)
    metadata = {'video': output.name, 'durationSeconds': 300, 'width': 1920, 'height': 1080, 'fps': 24, 'audio': False, 'bytes': output.stat().st_size, 'type': 'real-online-screenshot-edit', 'subtitleCues': len(cues), 'chapters': chapters}
    (args.out/'video-metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == '__main__':
    main()
