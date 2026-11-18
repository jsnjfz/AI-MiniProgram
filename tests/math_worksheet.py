"""独立验算每种题型和实际组卷结果。用法：python3 tests/math_worksheet.py [HTML 路径]"""
import json
import re
import subprocess
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

PAGE = (Path(sys.argv[1]) if len(sys.argv) > 1 else
        Path(__file__).resolve().parents[1] / "工具" / "小学数学自动出题器.html")
SAMPLES = 1000
PAPERS = 20
# 读取网页中的实际出题函数，固定随机种子；预期答案由 Python Fraction 独立计算。
DRIVER = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(process.argv[1], 'utf8');
const ids = [...html.matchAll(/<input[^>]+type="checkbox"[^>]+id="([^"]+)"/g)].map(m => m[1]);
const body = html.slice(html.indexOf('function generateUniqueQuestions('), html.indexOf('function createQuestionElement('));
if (!ids.length || !body.includes('function formatMixedFraction(')) throw Error('原版函数或题型未取到');
const seed = 20261118;
const context = vm.createContext({ console: {warn() {}}, seed });
vm.runInContext('var state=seed; Math.random=()=>((state=(Math.imul(state,1664525)+1013904223)>>>0)/4294967296);'+body,context);
for (const id of ids) {
  vm.runInContext("state=seed",context);
  const option={id};
  const items=Array.from({length:Number(process.argv[2])},()=>context.generateQuestion(option));
  const papers=Array.from({length:Number(process.argv[3])},()=>{
    const rows=context.generateUniqueQuestions([option],50);
    const text = html => html.replace(/<[^>]*>/g, ' ');
    const zero = /(?:^|[^.0-9])0(?:[^.0-9]|$)/;
    return {
      count: rows.length,
      unique: new Set(rows.map(x=>x.question)).size,
      zero: rows.filter(x=>zero.test(text(x.question)) || x.answer === '0').length,
      operandDigit: rows.filter(x=>text(x.question).includes('0')).length,
      digit: rows.filter(x=>(text(x.question)+text(x.answer)).includes('0')).length
    };
  });
  process.stdout.write(JSON.stringify({id,items,papers})+'\n');
}
"""
FRAC_MARKUP = re.compile(r'<span class="fraction"><span class="numerator">(\d+)</span><span class="denominator">(\d+)</span></span>')
TOKEN = re.compile(r'\d+/\d+|\d+(?:\.\d+)?|[+×÷-]')


def flatten(value):
    return FRAC_MARKUP.sub(r'\1/\2', value).strip()


def read_question(value):
    source = value.removesuffix('=').strip()
    tokens = TOKEN.findall(source)
    if ''.join(tokens) != source.replace(' ', ''):
        raise ValueError(value)
    nums = [Fraction(s) for s in tokens[::2]]
    ops = tokens[1::2]
    # 先乘除后加减，同级从左到右；所有计算都用有理数。
    terms = [nums[0]]
    for op, num in zip(ops, nums[1:]):
        if op == '×':
            terms[-1] *= num
        elif op == '÷':
            terms[-1] /= num
        else:
            terms.append(num if op == '+' else -num)
    return nums, ops, sum(terms)


def read_answer(s):
    sign = -1 if s.startswith('-') else 1
    return sign * sum(Fraction(t) for t in s.lstrip('-').split())


def detect(id_, nums, ops, exact, answer, answer_text):
    a, b = nums[:2]
    if exact != answer:
        yield '答案正负相反' if exact < 0 < answer else '答案只是近似值' if abs(exact-answer) <= Fraction(1, 200) else '其他错误答案'
    if id_ in ('grade5-down-fracsub', 'grade5-down-fracmix') and exact < 0:
        yield '小学分数减法出现负结果'
    if id_.startswith('preschool-') and not 0 <= exact <= 10:
        yield '超出10以内'
    if id_ == 'grade1-up-11to20' and not 11 <= exact <= 20:
        yield '结果超过20' if exact > 20 else '结果小于11'
    if id_ == 'grade1-up-20carry' and (a % 10 + b % 10 < 10):
        yield '标进位却无需进位'
    if id_.startswith('grade2-up-') and '100' in id_ and not 0 <= exact <= 100:
        yield '结果超出100以内'
    if id_ == 'grade3-up-sub2d' and b < 10:
        yield '减数只有一位'
    if id_ in ('grade3-down-div2d1d','grade3-down-div3d1d'):
        lo, hi = (10,99) if 'div2d' in id_ else (100,999)
        if not lo <= a <= hi:
            yield '被除数位数错误'
    if id_ in ('grade2-down-muldiv','grade3-down-div3d') and exact.denominator != 1:
        yield '低年级连乘除出现非整商'
    if id_ == 'grade3-down-mul3d' and not all(10 <= n <= 99 for n in nums):
        yield '连乘因数位数与两位数示例不一致'
    if id_ == 'grade5-down-fracsub' and ops != ['-']:
        yield '减法题型出现加号'
    if id_ == 'grade2-up-mix100' and len(ops) != 1:
        yield '双数加或减的示例实际是三数混合'
    if id_ == 'grade5-down-intdivfrac' and exact.denominator != 1 and answer.denominator != 1 and '.' in answer_text:
        yield '要求变分数却显示小数'


proc = subprocess.run(['node','-e',DRIVER,str(PAGE),str(SAMPLES),str(PAPERS)], capture_output=True, text=True, check=True)
SMALL_POOLS = {'preschool-add','preschool-sub','grade1-up-20carry','grade1-down-add10','grade1-down-sub10'}
checked = 0
totals = Counter()
problems = {}
for line in proc.stdout.splitlines():
    data = json.loads(line)
    key = data['id']
    checked += 1
    issues = Counter()
    first = {}
    for item in data['items']:
        question = flatten(item['question'])
        shown = flatten(item['answer'])
        nums, ops, exact = read_question(question)
        for issue in detect(key, nums, ops, exact, read_answer(shown), shown):
            issues[issue] += 1
            first.setdefault(issue, f'{question} {shown}')
    for paper in data['papers']:
        totals['papers'] += 1
        totals['questions'] += paper['count']
        totals['zero'] += paper['zero']
        totals['digit'] += paper['digit']
        if key not in ('grade1-down-add10','grade1-down-sub10','grade1-down-mix10'):
            totals['ordinary'] += paper['count']
            totals['ordinaryDigit'] += paper['digit']
            totals['ordinaryOperandDigit'] += paper['operandDigit']
        expected_count = 45 if key in SMALL_POOLS else 50
        if paper['count'] != expected_count or paper['unique'] != paper['count']:
            issues['题量或卷内去重'] += 1
        if paper['zero'] > 1:
            issues['单卷独立零项或零答案超过一道'] += 1
    if issues:
        problems[key] = {'counts': dict(issues), 'examples': first}

if checked != 51:
    raise AssertionError(f'题型覆盖异常：{checked}')
if totals['ordinaryDigit'] > 0.10 * totals['ordinary']:
    problems['zeroDigits'] = '普通题型含数字 0 的题目超过 10%'
print(json.dumps(dict(types=checked, samples=checked*SAMPLES, **totals, failures=problems),
                 ensure_ascii=False, indent=2))
sys.exit(int(bool(problems)))
