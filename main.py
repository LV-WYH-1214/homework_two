from collections.abc import Generator
from dataclasses import dataclass, field
import math
import unicodedata


# 读取与统计配置
CHUNK_SIZE = 8192
MAX_WORD_LEN = 50
SENTENCE_TERMINATORS = ".!?"

# 报告格式配置
REPORT_LABEL_WIDTH = 20
REPORT_LINE_WIDTH = 52

# 默认输入输出配置
INPUT_FILENAME = "text_test.txt"
REPORT_FILENAME = "text_report.txt"
TFIDF_COMPARE_FILENAME = "test_cases/test_alnum_words.txt"
KEYWORD_TOP_K = 5


@dataclass
class TextStats:
    """统一管理基础统计结果。"""

    char_count: int = 0
    word_count: int = 0
    line_count: int = 0
    sentence_count: int = 0
    avg_word_length: float = 0.0
    truncated_word_count: int = 0


@dataclass
class Term:
    """词项：词频、TF、IDF、TF-IDF。"""

    word: str
    count: int = 0
    tf: float = 0.0
    idf: float = 0.0
    tfidf: float = 0.0


@dataclass
class Document:
    """文档：文件名、词项集合、总词数。"""

    filename: str
    terms: dict[str, Term] = field(default_factory=dict)
    total_words: int = 0


@dataclass
class AnalysisResult:
    """单文件分析结果。"""

    stats: TextStats
    word_frequency: dict[str, int]
    letter_frequency: list[int]
    total_letters: int
    longest_word: str
    longest_word_len: int


def is_word_char(ch: str) -> bool:
    """单词字符口径：ASCII 字母或数字（等价 isalnum）。"""

    return ch.isascii() and ch.isalnum()


def _display_width(text: str) -> int:
    """计算字符串显示宽度（全角/宽字符计为 2）。"""

    width = 0
    for ch in str(text):
        width += 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1
    return width


def _pad_display(text: str, width: int = REPORT_LABEL_WIDTH) -> str:
    """按显示宽度左对齐补空格（等价 %-Ns 的终端对齐效果）。"""

    text_value = str(text)
    pad_size = width - _display_width(text_value)
    if pad_size <= 0:
        return text_value
    return text_value + (" " * pad_size)


def _format_io_error(action: str, filename: str, exc: Exception | None = None) -> str:
    """统一 I/O 错误提示模板。"""

    if exc is None:
        return f"错误：{action}文件失败：{filename}"
    return f"错误：{action}文件失败：{filename}（{exc}）"


def iter_words(fp, warning_stats: dict[str, int] | None = None) -> Generator[str, None, None]:
    """状态机分词：连续分隔符不会重复计数。"""

    in_word = False
    current_word_chars: list[str] = []
    current_word_truncated = False

    def commit_word():
        nonlocal current_word_chars, current_word_truncated
        if not current_word_chars:
            return None

        word = "".join(current_word_chars)
        if current_word_truncated and warning_stats is not None:
            warning_stats["truncated"] = warning_stats.get("truncated", 0) + 1

        current_word_chars = []
        current_word_truncated = False
        return word

    while True:
        chunk = fp.read(CHUNK_SIZE)
        if not chunk:
            break

        for ch in chunk:
            if is_word_char(ch):
                if not in_word:
                    in_word = True
                    current_word_chars = []
                    current_word_truncated = False

                if len(current_word_chars) < MAX_WORD_LEN:
                    current_word_chars.append(ch.lower())
                else:
                    current_word_truncated = True
            else:
                if in_word:
                    word = commit_word()
                    if word is not None:
                        yield word
                    in_word = False

    if in_word:
        word = commit_word()
        if word is not None:
            yield word


def scan_character_level(filepath: str):
    """字符层扫描：字符数、行数、句子数、字母频率。"""

    char_count = 0
    line_count = 0
    sentence_count = 0
    last_char = ""
    prev_is_terminator = False

    letter_frequency = [0] * 26
    total_letters = 0

    with open(filepath, "r", encoding="utf-8") as fp:
        while True:
            chunk = fp.read(CHUNK_SIZE)
            if not chunk:
                break

            char_count += len(chunk)
            line_count += chunk.count("\n")
            last_char = chunk[-1]

            for ch in chunk:
                if ch in SENTENCE_TERMINATORS:
                    if not prev_is_terminator:
                        sentence_count += 1
                    prev_is_terminator = True
                else:
                    prev_is_terminator = False

                if ch.isascii() and ch.isalpha():
                    index = ord(ch.lower()) - ord("a")
                    letter_frequency[index] += 1
                    total_letters += 1

    if char_count > 0 and (line_count == 0 or last_char != "\n"):
        line_count += 1

    return char_count, line_count, sentence_count, letter_frequency, total_letters


def scan_word_level(filepath: str):
    """单词层扫描：词数、平均词长、词频、最长词、超长截断计数。"""

    warning_stats = {"truncated": 0}
    word_count = 0
    total_word_len = 0
    word_frequency: dict[str, int] = {}
    longest_word = ""
    longest_word_len = 0

    with open(filepath, "r", encoding="utf-8") as fp:
        for word in iter_words(fp, warning_stats=warning_stats):
            word_count += 1
            word_len = len(word)
            total_word_len += word_len
            word_frequency[word] = word_frequency.get(word, 0) + 1

            if word_len > longest_word_len:
                longest_word_len = word_len
                longest_word = word

    avg_word_length = (total_word_len / word_count) if word_count > 0 else 0.0
    truncated_word_count = warning_stats["truncated"]

    return (
        word_count,
        avg_word_length,
        truncated_word_count,
        word_frequency,
        longest_word,
        longest_word_len,
    )


def is_empty_file(filepath: str) -> bool:
    """前置判断文件是否为空。"""

    with open(filepath, "rb") as fp:
        fp.seek(0, 2)
        return fp.tell() == 0


def analyze_file(filepath: str) -> AnalysisResult:
    """执行单文件分析。"""

    if is_empty_file(filepath):
        return AnalysisResult(
            stats=TextStats(),
            word_frequency={},
            letter_frequency=[0] * 26,
            total_letters=0,
            longest_word="",
            longest_word_len=0,
        )

    (
        char_count,
        line_count,
        sentence_count,
        letter_frequency,
        total_letters,
    ) = scan_character_level(filepath)

    (
        word_count,
        avg_word_length,
        truncated_word_count,
        word_frequency,
        longest_word,
        longest_word_len,
    ) = scan_word_level(filepath)

    stats = TextStats(
        char_count=char_count,
        word_count=word_count,
        line_count=line_count,
        sentence_count=sentence_count,
        avg_word_length=avg_word_length,
        truncated_word_count=truncated_word_count,
    )

    return AnalysisResult(
        stats=stats,
        word_frequency=word_frequency,
        letter_frequency=letter_frequency,
        total_letters=total_letters,
        longest_word=longest_word,
        longest_word_len=longest_word_len,
    )


def extract_terms(filepath: str) -> Document:
    """提取文档词项并计算 TF。"""

    terms: dict[str, Term] = {}
    total_words = 0

    with open(filepath, "r", encoding="utf-8") as fp:
        for word in iter_words(fp):
            total_words += 1
            term = terms.get(word)
            if term is None:
                terms[word] = Term(word=word, count=1)
            else:
                term.count += 1

    if total_words > 0:
        for term in terms.values():
            term.tf = term.count / total_words

    return Document(filename=filepath, terms=terms, total_words=total_words)


def build_document_from_word_frequency(filename: str, word_frequency: dict[str, int]) -> Document:
    """由已统计词频构建 Document，避免重复扫描同一文本。"""

    total_words = sum(word_frequency.values())
    terms: dict[str, Term] = {}

    if total_words > 0:
        for word, count in word_frequency.items():
            terms[word] = Term(word=word, count=count, tf=(count / total_words))

    return Document(filename=filename, terms=terms, total_words=total_words)


def compute_idf(documents: list[Document]) -> None:
    """按作业公式 IDF=log(N/(df+1)) 计算 IDF 与 TF-IDF。"""

    doc_count = len(documents)
    if doc_count == 0:
        return

    doc_freq: dict[str, int] = {}
    for doc in documents:
        for word in doc.terms:
            doc_freq[word] = doc_freq.get(word, 0) + 1

    for doc in documents:
        for term in doc.terms.values():
            term.idf = math.log(doc_count / (doc_freq[term.word] + 1))
            term.tfidf = term.tf * term.idf


def compute_cosine_similarity(doc_a: Document, doc_b: Document) -> float:
    """计算两个文档 TF-IDF 向量的余弦相似度。"""

    if not doc_a.terms or not doc_b.terms:
        return 0.0

    all_words = set(doc_a.terms.keys()) | set(doc_b.terms.keys())
    dot_product = 0.0
    norm_a = 0.0
    norm_b = 0.0

    for word in all_words:
        value_a = doc_a.terms[word].tfidf if word in doc_a.terms else 0.0
        value_b = doc_b.terms[word].tfidf if word in doc_b.terms else 0.0

        dot_product += value_a * value_b
        norm_a += value_a * value_a
        norm_b += value_b * value_b

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot_product / math.sqrt(norm_a * norm_b)


def extract_top_keywords(document: Document, top_k: int = 5) -> list[Term]:
    """按 TF-IDF 值提取 TopK 关键词（并列按词典序）。"""

    ranked_terms = sorted(document.terms.values(), key=lambda term: (-term.tfidf, term.word))
    return ranked_terms[:top_k]


def _build_keyword_block(title: str, keywords: list[Term]) -> list[str]:
    """构建关键词列表块。"""

    lines = [title]
    if not keywords:
        lines.append("无有效关键词。")
        return lines

    lines.append(
        _pad_display("排名", 6)
        + _pad_display("关键词", 24)
        + _pad_display("TF-IDF", 14)
        + "词频"
    )
    for index, term in enumerate(keywords, start=1):
        lines.append(
            _pad_display(index, 6)
            + _pad_display(term.word, 24)
            + _pad_display(f"{term.tfidf:.6f}", 14)
            + str(term.count)
        )

    return lines


def build_tfidf_section(doc_a: Document, doc_b: Document, similarity: float, top_k: int = 5) -> str:
    """构建 TF-IDF 相似度与关键词提取段落。"""

    top_keywords_a = extract_top_keywords(doc_a, top_k=top_k)
    top_keywords_b = extract_top_keywords(doc_b, top_k=top_k)

    lines = [
        "TF-IDF 文本相似度分析",
        "-" * REPORT_LINE_WIDTH,
        f"{_pad_display('比较文档A：')}{doc_a.filename}",
        f"{_pad_display('比较文档B：')}{doc_b.filename}",
        f"{_pad_display('余弦相似度：')}{similarity:.6f}",
        f"{_pad_display('IDF公式：')}log(N/(df+1))",
        "说明：文档数量较少时，TF-IDF 可能出现 0 或负值。",
        "-" * REPORT_LINE_WIDTH,
        "",
    ]

    if not any(abs(term.tfidf) > 1e-12 for doc in (doc_a, doc_b) for term in doc.terms.values()):
        lines.append("提示：当前样本中 TF-IDF 接近全 0，关键词区分度有限。")
        lines.append("")

    lines.extend(_build_keyword_block(f"文档A Top{top_k} 关键词：", top_keywords_a))
    lines.append("")
    lines.extend(_build_keyword_block(f"文档B Top{top_k} 关键词：", top_keywords_b))
    lines.append("-" * REPORT_LINE_WIDTH)

    return "\n".join(lines)


def analyze_tfidf(
    doc_a_path: str,
    doc_b_path: str,
    top_k: int = 5,
    doc_a_word_frequency: dict[str, int] | None = None,
) -> str:
    """执行两文档 TF-IDF 分析并返回报告段落文本。"""

    if top_k <= 0:
        raise ValueError("top_k 必须为正整数")

    if doc_a_word_frequency is None:
        doc_a = extract_terms(doc_a_path)
    else:
        doc_a = build_document_from_word_frequency(doc_a_path, doc_a_word_frequency)

    doc_b = extract_terms(doc_b_path)
    compute_idf([doc_a, doc_b])
    similarity = compute_cosine_similarity(doc_a, doc_b)
    return build_tfidf_section(doc_a, doc_b, similarity, top_k=top_k)


def _build_section(title: str, body_lines: list[str]) -> str:
    """统一构建“标题-分隔线-内容-分隔线”格式段落。"""

    lines = [title, "-" * REPORT_LINE_WIDTH]
    lines.extend(body_lines)
    lines.append("-" * REPORT_LINE_WIDTH)
    return "\n".join(lines)


def build_word_frequency_section(word_frequency: dict[str, int]) -> str:
    """构建单词频率段落。"""

    title = "单词频率统计（不区分大小写）"
    body_lines: list[str] = []

    if not word_frequency:
        body_lines.append("无有效单词。")
        return _build_section(title, body_lines)

    ranked = sorted(word_frequency.items(), key=lambda item: (-item[1], item[0]))
    body_lines.append(_pad_display("单词", 24) + "出现次数")
    for word, count in ranked:
        body_lines.append(_pad_display(word, 24) + str(count))

    return _build_section(title, body_lines)


def build_letter_frequency_section(letter_frequency: list[int], total_letters: int) -> str:
    """构建字母频率段落。"""

    title = "字母频率统计（a-z，不区分大小写）"
    body_lines: list[str] = []

    if total_letters == 0:
        body_lines.append("无有效英文字母。")
        return _build_section(title, body_lines)

    body_lines.append(_pad_display("字母", 8) + _pad_display("出现次数", 10) + "频率")
    for index, count in enumerate(letter_frequency):
        letter = chr(ord("a") + index)
        frequency = count / total_letters
        body_lines.append(_pad_display(letter, 8) + _pad_display(count, 10) + f"{frequency:.2f}")

    body_lines.append(f"{_pad_display('总字母数：')}{total_letters}")
    return _build_section(title, body_lines)


def build_longest_word_section(longest_word: str, longest_word_len: int) -> str:
    """构建最长单词段落。"""

    title = "最长单词统计"
    body_lines: list[str] = []

    if longest_word_len == 0:
        body_lines.append("无有效单词。")
        return _build_section(title, body_lines)

    body_lines.append(f"{_pad_display('最长单词：')}{longest_word}")
    body_lines.append(f"{_pad_display('长度：')}{longest_word_len}")
    return _build_section(title, body_lines)


def build_notice_section(title: str, message: str) -> str:
    """构建提示信息段落。"""

    return _build_section(title, [message])


def build_report_text(filename: str, analysis: AnalysisResult, extra_sections: list[str] | None = None) -> str:
    """构建完整格式化报告文本。"""

    stats = analysis.stats
    summary_items = [
        ("文件名：", filename),
        ("总字符数(含空格标点)：", str(stats.char_count)),
        ("总单词数：", str(stats.word_count)),
        ("总行数：", str(stats.line_count)),
        ("总句子数：", str(stats.sentence_count)),
        ("平均单词长度：", f"{stats.avg_word_length:.2f}"),
    ]
    summary_label_width = max(
        REPORT_LABEL_WIDTH,
        max(_display_width(label) for label, _ in summary_items),
    ) + 1

    lines = [
        "文本分析报告",
        "-" * REPORT_LINE_WIDTH,
    ]

    for label, value in summary_items:
        lines.append(_pad_display(label, summary_label_width) + value)

    lines.append("-" * REPORT_LINE_WIDTH)

    if stats.char_count == 0:
        lines.append("提示：检测到空文件，统计结果均为 0。")

    if stats.truncated_word_count > 0:
        lines.append(
            f"警告：检测到 {stats.truncated_word_count} 个超过 {MAX_WORD_LEN} 字符的单词，已截断后统计。"
        )

    core_sections = [
        build_word_frequency_section(analysis.word_frequency),
        build_letter_frequency_section(analysis.letter_frequency, analysis.total_letters),
        build_longest_word_section(analysis.longest_word, analysis.longest_word_len),
    ]

    for section in core_sections:
        lines.append("")
        lines.extend(section.splitlines())

    if extra_sections:
        for section in extra_sections:
            normalized = section.strip("\n")
            if not normalized:
                continue
            lines.append("")
            lines.extend(normalized.splitlines())

    return "\n".join(lines) + "\n"


def save_report(report_filename: str, report_text: str) -> None:
    """写入报告文件。"""

    with open(report_filename, "w", encoding="utf-8") as out_fp:
        out_fp.write(report_text)

    print(f"报告已保存：{report_filename}")


def main() -> None:
    """程序入口：保留作业核心功能，去除过度扩展逻辑。"""

    filename = INPUT_FILENAME
    compare_filename = TFIDF_COMPARE_FILENAME

    try:
        analysis = analyze_file(filename)
    except FileNotFoundError:
        print(_format_io_error("读取", filename))
        return
    except (PermissionError, UnicodeDecodeError, OSError) as exc:
        print(_format_io_error("读取", filename, exc))
        return

    extra_sections = []
    try:
        tfidf_section = analyze_tfidf(
            filename,
            compare_filename,
            top_k=KEYWORD_TOP_K,
            doc_a_word_frequency=analysis.word_frequency,
        )
        extra_sections.append(tfidf_section)
    except FileNotFoundError as exc:
        extra_sections.append(
            build_notice_section(
                "TF-IDF 模块提示",
                f"比较文档不存在：{exc.filename}，已跳过该模块。",
            )
        )
    except (PermissionError, UnicodeDecodeError, OSError, ValueError) as exc:
        extra_sections.append(
            build_notice_section("TF-IDF 模块提示", f"TF-IDF 分析失败：{exc}，已跳过该模块。")
        )

    report_text = build_report_text(filename, analysis, extra_sections=extra_sections)
    print(report_text, end="")

    try:
        save_report(REPORT_FILENAME, report_text)
    except (PermissionError, OSError) as exc:
        print(_format_io_error("保存", REPORT_FILENAME, exc))


if __name__ == "__main__":
    main()
