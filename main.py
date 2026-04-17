from dataclasses import dataclass


# 词频统计上限：最多记录 100 个不同单词
MAX_WORDS = 100
# 单词长度上限：超过后按前 50 个字符截断，并输出告警
MAX_WORD_LEN = 50
# 分块读取大小：兼顾内存占用与读取效率
CHUNK_SIZE = 8192


@dataclass
class WordFreq:
    """保存一个标准化单词及其出现次数。"""

    word: str
    count: int


def is_english_letter(ch):
    """判断字符是否为英文大小写字母（仅 A-Z / a-z）。"""

    return ('a' <= ch <= 'z') or ('A' <= ch <= 'Z')


def _submit_word(word, was_truncated, freq, warning_stats):
    """
    提交一个完整单词到词频表。

    处理流程：
    1) 将弯撇号归一化为直撇号，并统一转小写。
    2) 若单词超长则截断，并累计截断告警次数。
    3) 若词已存在则 count + 1。
    4) 若词不存在且词表已满，则忽略并累计超上限告警次数。
    5) 否则新增词条。
    """

    normalized = word.replace('’', "'").lower()

    # 超长词统一按前 MAX_WORD_LEN 字符参与统计
    if was_truncated or len(normalized) > MAX_WORD_LEN:
        normalized = normalized[:MAX_WORD_LEN]
        warning_stats['truncated'] += 1

    # 线性查重：若已存在直接累加频次
    for item in freq:
        if item.word == normalized:
            item.count += 1
            return

    # 词条已达上限：忽略新词，但程序继续执行
    if len(freq) >= MAX_WORDS:
        warning_stats['ignored_new'] += 1
        return

    # 新词且未超上限：加入词频表
    freq.append(WordFreq(word=normalized, count=1))


def compute_word_freq(
    fp,
    freq,
    total_words,
    letter_freq=None,
    total_letters=None,
    longest_word=None,
    max_len=None,
    chars_out=None,
    lines_out=None,
):
    """
    Python 等价实现：compute_word_freq(FILE *fp, WordFreq *freq, int *total_words)

    参数：
    - fp: 已打开的文本文件对象（按字符读取）
    - freq: 词频列表（元素为 WordFreq）
    - total_words: 单元素列表，用于模拟 C 里的“输出参数”
    - letter_freq: 可选，长度为 26 的列表，统计 a-z 出现次数
    - total_letters: 可选，单元素列表，统计英文字母总数
    - longest_word: 可选，单元素列表，保存最长单词（并列时保留先出现的）
    - max_len: 可选，单元素列表，保存最长单词长度
    - chars_out: 可选，单元素列表，输出字符总数
    - lines_out: 可选，单元素列表，输出行数（含末行无换行的修正）

    返回：
    - warning_stats: {"truncated": 超长截断次数, "ignored_new": 超上限忽略新词次数}
    """

    warning_stats = {'truncated': 0, 'ignored_new': 0}

    # 状态机定义：
    # 0 = 词外
    # 1 = 词内，且上一字符是字母
    # 2 = 词内，且上一字符是撇号（等待下一个字母确认是否仍属同一词）
    word_state = 0

    # 当前正在构造的单词缓冲区（按字符追加）
    current_word_chars = []
    # 标记当前词是否发生过“超过 MAX_WORD_LEN 后继续读入”的情况
    current_word_truncated = False

    # 可选输出：基础统计信息（用于避免主流程二次扫描）
    chars_count = 0
    lines_count = 0
    last_char = ""

    def append_with_limit(ch):
        """向当前词缓冲追加字符；超过上限后只记截断标记，不再追加内容。"""

        nonlocal current_word_truncated
        if len(current_word_chars) < MAX_WORD_LEN:
            current_word_chars.append(ch)
        else:
            current_word_truncated = True

    def commit_current_word():
        """提交当前缓冲词并重置缓冲区。"""

        nonlocal current_word_chars, current_word_truncated
        if current_word_chars:
            # 最长单词统计：仅在严格更长时更新，保证并列长度保留第一个
            if longest_word is not None and max_len is not None:
                current_len = len(current_word_chars)
                if current_len > max_len[0]:
                    max_len[0] = current_len
                    longest_word[0] = ''.join(current_word_chars)

            _submit_word(''.join(current_word_chars), current_word_truncated, freq, warning_stats)
        current_word_chars = []
        current_word_truncated = False

    # 分块读取文件，避免一次性读入大文件
    while True:
        chunk = fp.read(CHUNK_SIZE)
        if not chunk:
            break

        for ch in chunk:
            chars_count += 1
            last_char = ch
            if ch == '\n':
                lines_count += 1

            if is_english_letter(ch):
                lower_ch = ch.lower()

                # 可选输出：在单词统计同时累计字母频率
                if letter_freq is not None and total_letters is not None:
                    letter_freq[ord(lower_ch) - ord('a')] += 1
                    total_letters[0] += 1

                if word_state == 0:
                    # 从词外进入词内：识别到一个新单词
                    total_words[0] += 1
                    append_with_limit(lower_ch)
                elif word_state == 1:
                    # 正常词内延续
                    append_with_limit(lower_ch)
                else:
                    # 仅当“撇号后紧跟字母”时，撇号才并入单词（don't 记为一个词）
                    append_with_limit("'")
                    append_with_limit(lower_ch)
                word_state = 1
            elif ch in ("'", '’') and word_state == 1:
                # 词内遇到撇号：先进入“待确认”状态，等待下一个字符判断
                word_state = 2
            else:
                # 遇到分隔符：若刚在词内则提交当前词
                if word_state in (1, 2):
                    commit_current_word()
                word_state = 0

    # 文件结束时，若仍在词内，需要补提交最后一个词
    if word_state in (1, 2):
        commit_current_word()

    # 对“末行无换行符”进行行数修正
    if chars_count > 0 and last_char != '\n':
        lines_count += 1

    if chars_out is not None:
        chars_out[0] = chars_count
    if lines_out is not None:
        lines_out[0] = lines_count

    return warning_stats


def main():
    """
    程序入口。

    采用“单次扫描”策略：一次遍历同时得到
    字符数、单词数、行数、词频、字母频率和最长单词。
    """

    # 输入文件名（当前按题目要求固定为 text_test.txt）
    filename = "text_test.txt"

    # 单次扫描：基础统计 + 词频 + 字母频率 + 最长单词
    freq = []
    total_words = [0]  # 通过单元素列表模拟“可写输出参数”
    letter_freq = [0] * 26  # 下标 0-25 分别对应 a-z
    total_letters = [0]  # 英文字母总数
    longest_word = [""]  # 最长单词
    max_len = [0]  # 最长单词长度
    chars_out = [0]  # 字符总数
    lines_out = [0]  # 行数
    warning_stats = {'truncated': 0, 'ignored_new': 0}

    try:
        with open(filename, 'r', encoding='utf-8') as fp:
            warning_stats = compute_word_freq(
                fp,
                freq,
                total_words,
                letter_freq=letter_freq,
                total_letters=total_letters,
                longest_word=longest_word,
                max_len=max_len,
                chars_out=chars_out,
                lines_out=lines_out,
            )
    # 统计读取异常处理
    except FileNotFoundError:
        print(f"错误：无法打开文件 {filename}")
        return
    except (PermissionError, UnicodeDecodeError, OSError) as exc:
        print(f"错误：读取文件 {filename} 失败：{exc}")
        return

    chars = chars_out[0]
    words = total_words[0]
    lines = lines_out[0]

    # 输出前排序：频次降序；同频按字母序
    sorted_freq = sorted(freq, key=lambda item: (-item.count, item.word))

    # 输出基础统计结果
    print(f"文件 {filename} 统计结果：")
    print(f"字符数：{chars}")
    print(f"单词数：{words}")
    print(f"行数：{lines}")

    # 输出词频表（不区分大小写）
    print("\n词频统计（不区分大小写）：")
    if sorted_freq:
        print(f"{'单词':<20}频次")
        for item in sorted_freq:
            print(f"{item.word:<20}{item.count}")
    else:
        print("无英文单词可统计。")

    # 输出字母频率表（a-z，不区分大小写）
    print("\n字母频率统计（a-z，不区分大小写）：")
    print(f"{'字母':<6}{'次数':<8}频率(次数/总字母数)")
    for i in range(26):
        letter = chr(ord('a') + i)
        count = letter_freq[i]
        ratio = (count / total_letters[0]) if total_letters[0] > 0 else 0.0
        print(f"{letter:<6}{count:<8}{ratio:.2f}")

    # 输出最长单词统计（并列最长时取第一个）
    print("\n最长单词统计：")
    print(f"最长单词：{longest_word[0] if max_len[0] > 0 else '无'}")
    print(f"长度：{max_len[0]}")

    # 输出告警信息（若有）
    if warning_stats['truncated'] > 0:
        print(
            f"警告：检测到 {warning_stats['truncated']} 个超过 {MAX_WORD_LEN} 字符的单词，"
            "已截断后统计。"
        )
    if warning_stats['ignored_new'] > 0:
        print(
            f"警告：不同单词超过 {MAX_WORDS} 个，"
            f"已忽略 {warning_stats['ignored_new']} 个后续新单词记录，程序已继续执行。"
        )


if __name__ == "__main__":
    main()