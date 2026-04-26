from collections.abc import Generator  # 用于给 iter_words 生成器函数标注返回类型
from dataclasses import dataclass, field  # dataclass 自动生成数据类样板代码；field 用于设置默认可变值（如空字典）
import math  # 提供 math.log（计算 IDF）和 math.sqrt（计算余弦相似度的模长）
import os  # 文件路径拼接、目录扫描、文件大小查询等所有与操作系统交互的文件系统操作
import sys  # 检测 sys.frozen（判断是否为 PyInstaller 打包的可执行文件）和 sys.executable（获取 exe 路径）
import unicodedata  # 判断字符的东亚显示宽度（east_asian_width），用于中文报告标签对齐


# 读取与统计配置
CHUNK_SIZE = 8192  # 每次读取的文件块大小，默认 8KB
MAX_WORD_LEN = 50  # 单词最大长度，超过将被截断
SENTENCE_TERMINATORS = ".!?"  # 句子终止符，用于统计句子数量

# 报告格式配置
REPORT_LABEL_WIDTH = 20  # 报告左侧标签的默认对齐宽度
REPORT_LINE_WIDTH = 52  # 报告分隔线的默认长度

# 默认分析配置
KEYWORD_TOP_K = 5  # 默认提取的 Top K 关键词数量


@dataclass # Python 标准库中的装饰器，作用是自动生成数据类的样板代码
class TextStats:
    """统一管理基础统计结果。"""

    char_count: int = 0  # 字符总数（包含空白和标点）
    word_count: int = 0  # 单词总数
    line_count: int = 0  # 总行数
    sentence_count: int = 0  # 句子总数
    avg_word_length: float = 0.0  # 平均单词长度
    truncated_word_count: int = 0  # 被截断的超长单词数


@dataclass # Python 标准库中的装饰器，作用是自动生成数据类的样板代码
class Term:
    """词项:词频、TF、IDF、TF-IDF。"""

    word: str  # 词项本身
    count: int = 0  # 在当前文档中出现的次数
    tf: float = 0.0  # 词频 (Term Frequency)
    idf: float = 0.0  # 逆文档频率 (Inverse Document Frequency)
    tfidf: float = 0.0  # TF-IDF 值


@dataclass # Python 标准库中的装饰器，作用是自动生成数据类的样板代码
class Document:
    """文档：文件名、词项集合、总词数。"""

    filename: str  # 文档来源的文件名或路径
    terms: dict[str, Term] = field(default_factory=dict)  # 文档包含的词项字典
    total_words: int = 0  # 文档的总词数


@dataclass # Python 标准库中的装饰器，作用是自动生成数据类的样板代码
class AnalysisResult:
    """单文件分析结果。"""

    stats: TextStats  # 基础统计数据（字数、词数等）
    word_frequency: dict[str, int]  # 各单词出现的频率映射
    letter_frequency: list[int]  # 各字母频率统计列表（固定长度26）
    total_letters: int  # 字母总数
    longest_word: str  # 出现的最长单词
    longest_word_len: int  # 最长单词的字符长度


def is_word_char(ch: str) -> bool:
    """单词字符口径:ASCII 字母或数字（等价 isalnum)。"""
    # 检查字符是否是英文字符（isascii）并且是字母或数字（isalnum）。
    # 为啥不直接用 isalnum ：因为 isalnum 可能会对某些中文和希腊字母返回 True，而我们只想统计 ASCII 范围内的英文字母和数字。
    return ch.isascii() and ch.isalnum()


def _display_width(text: str) -> int:
    """计算字符串显示宽度（全角/宽字符计为 2）。"""
    width = 0  # 初始化宽度为0
    for ch in str(text):  # 遍历字符串中的每一个字符
        # unicodedata.east_asian_width 用来判断字符是不是全角字符（比如中文字符在屏幕上占的位置比英文字母宽）
        # 如果是 "W" (Wide 宽) 或 "F" (Fullwidth 全角)，就认为显示宽度是2，否则是1
        width += 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1
    return width  # 返回计算出的总显示宽度


def _pad_display(text: str, width: int = REPORT_LABEL_WIDTH) -> str:
    """按显示宽度左对齐补空格（等价 %-Ns 的终端对齐效果）。"""
    text_value = str(text)  # 把输入强制转换为字符串类型
    pad_size = width - _display_width(text_value)  # 计算需要补充的空格数量 = 目标宽度 - 实际显示宽度
    if pad_size <= 0:  # 如果实际宽度已经达到或超过了目标宽度
        return text_value  # 就不需要补空格，直接返回原字符串
    return text_value + (" " * pad_size)  # 在字符串右边拼接对应数量的空格来实现左对齐排版


def _format_io_error(action: str, filename: str, exc: Exception | None = None) -> str:
    """统一 I/O 错误提示模板。"""
    if exc is None:  # 如果没有携带具体的系统异常信息
        return f"错误：{action}文件失败：{filename}"  # 返回一个基础的错误提示字符串
    # 如果有异常信息（exc），把它也一并格式化到提示语里，方便定位问题出在哪
    return f"错误：{action}文件失败：{filename}（{exc}）"


def iter_words(fp, warning_stats: dict[str, int] | None = None) -> Generator[str, None, None]:
    """状态机分词：连续分隔符不会重复计数。这是一个生成器函数，可以逐个产出单词，节省内存。"""
    in_word = False  # 状态标记：记录当前是否正在读取一个单词的过程中（状态机思想）
    current_word_chars: list[str] = []  # 列表：用来临时收集属于当前正在读取的单词的各个字符
    current_word_truncated = False  # 标记：当前单词是否因为长度超过限制而被强行截断了

    def commit_word():
        """内部帮助函数：把收集到的零散字符拼接成一个完整单词并返回，然后重置状态。"""
        nonlocal current_word_chars, current_word_truncated  # 声明使用外层函数的变量，允许在此修改它们
        if not current_word_chars:  # 如果没收集到任何字符，直接返回空
            return None

        word = "".join(current_word_chars)  # 把字符列表无缝拼接成一个完整的字符串（单词）
        if current_word_truncated and warning_stats is not None:  # 如果单词被截断过，并且调用方传了统计字典进来
            # 给字典里的截断次数记录 +1，这样外部就能知道发生过截断
            warning_stats["truncated"] = warning_stats.get("truncated", 0) + 1

        current_word_chars = []  # 清空字符收集列表，为读取下一个单词做准备
        current_word_truncated = False  # 重置截断标记为否
        return word  # 返回拼好的完整单词

    while True:  # 无限循环，直到文件数据全被读完
        chunk = fp.read(CHUNK_SIZE)  # 每次从文件中读取 CHUNK_SIZE (默认 8KB) 大小的数据块，防止直接把内存撑爆
        if not chunk:  # 如果读到的内容为空，说明文件已经彻底读到了末尾（EOF）
            break  # 退出整体的无限循环

        for ch in chunk:  # 遍历这次读到的 8KB 数据块里的每一个字符
            if is_word_char(ch):  # 判断如果这个字符是字母或数字（属于单词的一部分）
                if not in_word:  # 如果程序之前不在单词状态中，说明现在遇到了一个新单词的开头
                    in_word = True  # 切换状态：程序进入单词中了
                    current_word_chars = []  # 初始化收集列表
                    current_word_truncated = False  # 初始化截断标记

                if len(current_word_chars) < MAX_WORD_LEN:  # 如果当前收集的单词长度还没超标
                    current_word_chars.append(ch.lower())  # 把字符转成小写后，加入收集列表
                else:  # 如果单词长度已经达到最大限制
                    current_word_truncated = True  # 标记为已截断，后续属于这个单词的字符将被抛弃
            else:  # 如果这个字符不是字母或数字（比如遇到了空格、标点符号、换行符等）
                if in_word:  # 如果程序之前还在单词状态中，说明一个单词刚刚结束了
                    word = commit_word()  # 调用内部函数，把刚刚收集完的单词打包出来
                    if word is not None:  # 如果打包出了有效的单词
                        yield word  # 重点：使用 yield 把单词“吐”给调用者，并暂停函数等待下次需要单词时再继续运行
                    in_word = False  # 切换状态：程序现在不在单词中了

    if in_word:  # 当文件全部读完跳出 while 循环后，如果最后还卡在一个单词的状态里没结束（比如文件没以标点结尾）
        word = commit_word()  # 把最后收集到的残留单词也打包出来
        if word is not None:
            yield word  # 把最后一个单词也“吐”出去


def scan_character_level(filepath: str):
    """字符层扫描：字符数、行数、句子数、字母频率。"""
    char_count = 0  # 初始化累计总字符数
    line_count = 0  # 初始化累计总行数
    sentence_count = 0  # 初始化累计总句子数
    last_char = ""  # 记录上一次读到的最后一个字符，用来处理末尾行的特殊情况
    prev_is_terminator = False  # 标记前一个字符是不是句号感叹号等，防止连用的标点导致把一个句子算成多个

    letter_frequency = [0] * 26  # 初始化一个包含26个数字0的列表，分别对应 a-z 各字母出现的次数
    total_letters = 0  # 初始化累计总的英文字母个数

    with open(filepath, "r", encoding="utf-8") as fp:  # 使用 utf-8 编码以只读("r")模式打开文件，with 语法会在结束时自动关闭文件
        while True:  # 循环分块读取文件
            chunk = fp.read(CHUNK_SIZE)  # 每次读一块规定大小的数据块
            if not chunk:  # 如果没读到数据，说明到文件尾了
                break  # 退出循环

            char_count += len(chunk)  # 将当前这块数据的字符数量直接累加到总字符数里
            line_count += chunk.count("\n")  # 数一下当前这块数据里有几个换行符 '\n'，直接累加到总行数里
            last_char = chunk[-1]  # 更新记录这块数据的最后一个字符

            for ch in chunk:  # 逐一遍历当前数据块里的每一个字符
                if ch in SENTENCE_TERMINATORS:  # 如果字符是预设的句子终止符（如 . ! ?）
                    if not prev_is_terminator:  # 并且它的前一个字符不是终止符（比如遇到 "..." ，只有第一个点算句子结束，后面不算）
                        sentence_count += 1  # 发现了新句子的结尾，句子总数加1
                    prev_is_terminator = True  # 标记当前碰到了终止符，防连击
                else:  # 如果字符不是终止符
                    prev_is_terminator = False  # 重置标记，说明可以接受下一个句子的终结了

                if ch.isascii() and ch.isalpha():  # 如果这个字符是标准的英文纯字母
                    index = ord(ch.lower()) - ord("a")  # 把字母转成小写，然后计算它在 0-25 之间的位置索引（a算出来是0，b是1...）
                    letter_frequency[index] += 1  # 对应索引位置的字母频次 +1
                    total_letters += 1  # 英文纯字母总数 +1

    # 【经典边界情况处理】：如果文件里面确实有内容，但是通过上面的逻辑行数为0（文件连一行都没填满就结束了），
    # 或者文件末尾最后一行没有敲回车键（最后一个字符不是换行符）
    if char_count > 0 and (line_count == 0 or last_char != "\n"):
        line_count += 1  # 那么即使没有换行符，这也应该被算作独立的一行，行数强制补加1

    return char_count, line_count, sentence_count, letter_frequency, total_letters  # 将所有计算结果一次性打包返回


def scan_word_level(filepath: str):
    """单词层扫描：词数、平均词长、词频、最长词、超长截断计数。"""
    warning_stats = {"truncated": 0}  # 创建字典传给 iter_words，这样里面修改了字典内容，外面也能拿到截断的次数
    word_count = 0  # 初始化累计总单词数
    total_word_len = 0  # 初始化所有单词加起来的总长度，为了后面算平均长度
    word_frequency: dict[str, int] = {}  # 初始化空字典，用来记录“单词”对应的“出现次数”
    longest_word = ""  # 初始化用来记录出现的最长单词的变量
    longest_word_len = 0  # 初始化最长单词的长度记录

    with open(filepath, "r", encoding="utf-8") as fp:  # 以只读模式打开文件
        for word in iter_words(fp, warning_stats=warning_stats):  # 使用我们写的 iter_words 生成器函数，逐个拿单词
            word_count += 1  # 每拿到一个单词，总单词数+1
            word_len = len(word)  # 计算当前单词的字符长度
            total_word_len += word_len  # 把当前单词的长度加到总长度里
            
            # 从字典获取当前单词的次数，如果没有就默认给0，然后+1。这一行实现了词频统计。
            word_frequency[word] = word_frequency.get(word, 0) + 1

            if word_len > longest_word_len:  # 如果当前单词的长度大于已记录的最长单词长度
                longest_word_len = word_len  # 更新最长单词的长度记录
                longest_word = word  # 把当前单词记为最长的单词（由于是 > 号而不是 >=，保证了同长度取第一个）

    # 计算平均单词长度：如果单词数大于0就是总长度除以个数，否则就是0.0（防除以0报错）
    avg_word_length = (total_word_len / word_count) if word_count > 0 else 0.0
    truncated_word_count = warning_stats["truncated"]  # 从字典里拿出最终的截断次数

    return ( # 返回一个元组，把所有的计算结果打包交出去
        word_count,
        avg_word_length,
        truncated_word_count,
        word_frequency,
        longest_word,
        longest_word_len,
    )


def is_empty_file(filepath: str) -> bool:
    """前置判断文件是否为空。"""
    return os.path.getsize(filepath) == 0  # 直接向操作系统查询文件大小元数据，为0即空文件，无需打开文件


def analyze_file(filepath: str) -> AnalysisResult:
    """执行单文件分析，把前面的字符级和单词级扫描组合起来。"""
    if is_empty_file(filepath):  # 如果提前检测到是空文件
        # 直接返回一个全都是默认空值或0的数据包，不需要去白费力气扫描了
        return AnalysisResult(
            stats=TextStats(),
            word_frequency={},
            letter_frequency=[0] * 26,
            total_letters=0,
            longest_word="",
            longest_word_len=0,
        )

    # 第一步：调用字符层扫描，并将返回的元组拆解赋值给对应的变量
    (
        char_count,
        line_count,
        sentence_count,
        letter_frequency,
        total_letters,
    ) = scan_character_level(filepath)

    # 第二步：调用单词层扫描，并将返回的元组拆解赋值给对应的变量
    (
        word_count,
        avg_word_length,
        truncated_word_count,
        word_frequency,
        longest_word,
        longest_word_len,
    ) = scan_word_level(filepath)

    # 第三步：将基础的统计数据包装进 TextStats 这个专属的结构里
    stats = TextStats(
        char_count=char_count,
        word_count=word_count,
        line_count=line_count,
        sentence_count=sentence_count,
        avg_word_length=avg_word_length,
        truncated_word_count=truncated_word_count,
    )

    # 第四步：将所有分析数据最终包装进 AnalysisResult 数据类对象中并返回给调用者
    return AnalysisResult(
        stats=stats,
        word_frequency=word_frequency,
        letter_frequency=letter_frequency,
        total_letters=total_letters,
        longest_word=longest_word,
        longest_word_len=longest_word_len,
    )


def extract_terms(filepath: str) -> Document:
    """提取文档词项并计算 TF (单个词在文档中出现的频率)。"""
    terms: dict[str, Term] = {}  # 创建空字典，用来存：单词字符串 -> Term对象的映射关系
    total_words = 0  # 初始化当前文档的总词数

    with open(filepath, "r", encoding="utf-8") as fp:  # 打开文件
        for word in iter_words(fp):  # 逐个获取文件里的单词
            total_words += 1  # 文档总词数+1
            term = terms.get(word)  # 尝试从字典中获取当前单词对应的 Term 对象
            if term is None:  # 如果字典里还没有这个单词（第一次出现）
                terms[word] = Term(word=word, count=1)  # 创建一个新的 Term 对象存进去，初始计数设为1
            else:  # 如果已经存在了
                term.count += 1  # 直接让这个单词的计数+1

    if total_words > 0:  # 如果文档里有词
        for term in terms.values():  # 遍历字典里的每一个 Term 对象
            term.tf = term.count / total_words  # 计算并赋值 TF 值公式：该词的次数 / 文档总词数

    return Document(filename=filepath, terms=terms, total_words=total_words)  # 包装成 Document 对象返回


def build_document_from_word_frequency(filename: str, word_frequency: dict[str, int]) -> Document:
    """由已经统计好的词频字典直接构建 Document，避免为了算 TF-IDF 把同一个文件又扫描一遍。"""
    total_words = sum(word_frequency.values())  # 把字典里所有的词频次数加起来，就是文档总词数
    terms: dict[str, Term] = {}  # 创建空字典存 Term 对象

    if total_words > 0:  # 如果文档不是空的
        for word, count in word_frequency.items():  # 遍历已有的词频字典 (单词, 次数)
            # 直接创建 Term 对象，并一步到位计算出 TF 值
            terms[word] = Term(word=word, count=count, tf=(count / total_words))

    return Document(filename=filename, terms=terms, total_words=total_words)  # 包装成 Document 对象返回


def compute_idf(documents: list[Document]) -> None:
    """按作业公式 IDF=log(N/(df+1)) 计算多篇文档中各个词的 IDF 与最终的 TF-IDF 权重。"""
    doc_count = len(documents)  # 获取参与对比的总文档数量 (即公式里的 N)
    if doc_count == 0:  # 如果没传文档进来
        return  # 什么都不干，直接结束

    doc_freq: dict[str, int] = {}  # 创建字典存 df（Document Frequency 即包含某个词的文档数量）
    for doc in documents:  # 遍历每一篇文档
        for word in doc.terms:  # 遍历文档里出现的每一个词（不需要管出现了几次，只要出现了就算1）
            doc_freq[word] = doc_freq.get(word, 0) + 1  # 让这个词所在的文档总数+1

    for doc in documents:  # 再次遍历每一篇文档
        for term in doc.terms.values():  # 遍历文档里的每一个 Term 对象
            # 计算 IDF = log( 总文档数 / (包含该词的文档数 + 1) )，+1是为了防止万一分母为0报错
            term.idf = math.log(doc_count / (doc_freq[term.word] + 1))
            # 计算 TF-IDF 最终权重值 = TF * IDF
            term.tfidf = term.tf * term.idf


def compute_cosine_similarity(doc_a: Document, doc_b: Document) -> float:
    """计算两个文档 TF-IDF 向量的余弦相似度（用来判断两篇文章在内容上的相似程度）。"""
    if not doc_a.terms or not doc_b.terms:  # 如果其中有一个文档是空的（没有词）
        return 0.0  # 相似度直接是 0.0（完全不相关）

    # 用集合操作（| 取并集）把两篇文章出现过的所有不同的词合并成一个全集
    all_words = set(doc_a.terms.keys()) | set(doc_b.terms.keys())
    dot_product = 0.0  # 初始化：记录两个向量的内积（分子部分）
    norm_a = 0.0  # 初始化：记录文档A向量的模长平方（分母部分 A）
    norm_b = 0.0  # 初始化：记录文档B向量的模长平方（分母部分 B）

    for word in all_words:  # 遍历词汇全集里的每一个词
        # 获取这个词在A文档和B文档里的 TF-IDF 值，如果某篇文档里没这个词，就当 0.0 处理
        value_a = doc_a.terms[word].tfidf if word in doc_a.terms else 0.0
        value_b = doc_b.terms[word].tfidf if word in doc_b.terms else 0.0

        dot_product += value_a * value_b  # 累加向量内积 (对应位置相乘)
        norm_a += value_a * value_a  # 累加文档A的特征值的平方
        norm_b += value_b * value_b  # 累加文档B的特征值的平方

    if norm_a == 0.0 or norm_b == 0.0:  # 如果某篇文档全集词的权重都是0（通常是因为没提取出有效词）
        return 0.0  # 防止后续计算除以0导致程序崩溃，直接返回相似度0

    # 余弦相似度核心公式 = 向量内积 / (向量A模长 * 向量B模长)
    return dot_product / math.sqrt(norm_a * norm_b)


def extract_top_keywords(document: Document, top_k: int = 5) -> list[Term]:
    """按 TF-IDF 权重值提取排名靠前的 TopK 关键词（如果分数一样，就按字母顺序排）。"""
    # 使用 Python 内置的 sorted 函数进行排序。
    # key=lambda 定义了排序规则：默认是从小到大排，所以在 term.tfidf 前加了负号变成从大到小。
    # 当 tfidf 分数一模一样时，按照 term.word 的字母顺序排列。
    ranked_terms = sorted(document.terms.values(), key=lambda term: (-term.tfidf, term.word))
    return ranked_terms[:top_k]  # 利用切片语法 [:top_k]，只返回排在最前面的 top_k 个元素


def _build_keyword_block(title: str, keywords: list[Term]) -> list[str]:
    """构建用于报告显示的“关键词列表”文本块。"""
    lines = [title]  # 先把小标题放进列表里
    if not keywords:  # 如果没有提供任何关键词
        lines.append("无有效关键词。")  # 补一句友好的提示
        return lines

    # 添加列表的表头，调用了我们写的左对齐排版工具 _pad_display 保证格式整齐
    lines.append(
        _pad_display("排名", 6)
        + _pad_display("关键词", 24)
        + _pad_display("TF-IDF", 14)
        + "词频"
    )
    for index, term in enumerate(keywords, start=1):  # 遍历关键词集合，并利用 enumerate 自动带上序号(从1开始)
        lines.append(
            _pad_display(index, 6)  # 显示序号
            + _pad_display(term.word, 24)  # 显示单词本身
            + _pad_display(f"{term.tfidf:.6f}", 14)  # 显示 TFIDF 值，格式化保留小数点后6位
            + str(term.count)  # 显示这个词在文档中出现的总次数
        )

    return lines  # 返回生成的文本行列表


def build_tfidf_section(doc_a: Document, doc_b: Document, similarity: float, top_k: int = 5) -> str:
    """把 TF-IDF 相关的相似度数据和关键词排版合并成一个大的文本段落。"""
    top_keywords_a = extract_top_keywords(doc_a, top_k=top_k)  # 提取文档A的Top关键词
    top_keywords_b = extract_top_keywords(doc_b, top_k=top_k)  # 提取文档B的Top关键词

    lines = [  # 构建报告段落头部的基本信息
        "TF-IDF 文本相似度分析",
        "-" * REPORT_LINE_WIDTH,  # 画一条等宽的横向分割线
        f"{_pad_display('比较文档A：')}{os.path.basename(doc_a.filename)}",  # 只显示文件名部分，避免打印过长的绝对路径
        f"{_pad_display('比较文档B：')}{os.path.basename(doc_b.filename)}",  # 只显示文件名部分，避免打印过长的绝对路径
        f"{_pad_display('余弦相似度：')}{similarity:.6f}",  # 相似度保留6位小数
        f"{_pad_display('IDF公式：')}log(N/(df+1))",
        "说明：文档数量较少时，TF-IDF 可能出现 0 或负值。",
        "-" * REPORT_LINE_WIDTH,  # 画一条等宽的横向分割线
        "",  # 空一行
    ]

    # 如果两篇文档所有词的 tfidf 都在非常接近0的区间内（极小值）
    if not any(abs(term.tfidf) > 1e-12 for doc in (doc_a, doc_b) for term in doc.terms.values()):
        lines.append("提示：当前样本中 TF-IDF 接近全 0，关键词区分度有限。")
        lines.append("")

    lines.extend(_build_keyword_block(f"文档A Top{top_k} 关键词：", top_keywords_a))  # 把A的关键词拼装进列表
    lines.append("")  # 空一行
    lines.extend(_build_keyword_block(f"文档B Top{top_k} 关键词：", top_keywords_b))  # 把B的关键词拼装进列表
    lines.append("-" * REPORT_LINE_WIDTH)  # 结尾再画一条分割线

    return "\n".join(lines)  # 把列表里的所有行，用换行符 "\n" 连成一整个大字符串返回


def analyze_tfidf(
    doc_a_path: str,
    doc_b_path: str,
    top_k: int = 5,
    doc_a_word_frequency: dict[str, int] | None = None,
) -> str:
    """对外暴露的主功能接口：执行两篇文档的 TF-IDF 分析，并返回排版好的报告段落文本。"""
    if top_k <= 0:  # 安全检查：TopK 不能是负数或0
        raise ValueError("top_k 必须为正整数")

    if doc_a_word_frequency is None:  # 如果没有传文档A现成的词频数据进来
        doc_a = extract_terms(doc_a_path)  # 那就老老实实去扫描文件A提取词频
    else:  # 如果有数据传进来，说明主流程前面已经扫描过了
        # 直接用现成的数据构建文档，免去重复读取文件的性能开销！
        doc_a = build_document_from_word_frequency(doc_a_path, doc_a_word_frequency)

    doc_b = extract_terms(doc_b_path)  # 扫描提取比较用的文档B的词频数据
    compute_idf([doc_a, doc_b])  # 将文档A和文档B打包成列表传进去，计算整个集合范围的 IDF 权重
    similarity = compute_cosine_similarity(doc_a, doc_b)  # 核心：计算相似度
    return build_tfidf_section(doc_a, doc_b, similarity, top_k=top_k)  # 将所有计算结果排版成报告文本返回


def _build_section(title: str, body_lines: list[str]) -> str:
    """统一构建“标题-分隔线-内容-分隔线”格式段落。"""
    # 初始化一个列表，先把小标题放进去，然后再跟一条长度固定的横线
    lines = [title, "-" * REPORT_LINE_WIDTH]
    lines.extend(body_lines)  # 把传进来的主体内容行（列表形式）全部追加进去
    lines.append("-" * REPORT_LINE_WIDTH)  # 结尾再画一条横线收尾
    return "\n".join(lines)  # 把这所有的行用回车符串起来，变成一个大字符串返回


def build_word_frequency_section(word_frequency: dict[str, int]) -> str:
    """构建单词频率段落。"""
    title = "单词频率统计（不区分大小写）"  # 设定该段落的固定标题
    body_lines: list[str] = []  # 准备一个空列表装主体文字

    if not word_frequency:  # 如果传进来的词频字典是空的
        body_lines.append("无有效单词。")  # 就塞一句话提示
        return _build_section(title, body_lines)  # 调用通用方法打包返回

    # 排序：word_frequency.items() 返回 (单词, 次数) 元组
    # key=lambda item: (-item[1], item[0]) 意思是：先按照次数(item[1])从大到小排(加了负号)，次数一样的话按单词字母(item[0])从小到大排
    ranked = sorted(word_frequency.items(), key=lambda item: (-item[1], item[0]))
    
    # 打印表头，调用对齐工具
    body_lines.append(_pad_display("单词", 24) + "出现次数")
    for word, count in ranked:  # 遍历排好序的单词和次数
        body_lines.append(_pad_display(word, 24) + str(count))  # 一行一行格式化加进列表

    return _build_section(title, body_lines)  # 调用通用方法打包返回


def build_letter_frequency_section(letter_frequency: list[int], total_letters: int) -> str:
    """构建字母频率段落。"""
    title = "字母频率统计（a-z，不区分大小写）"  # 设定固定标题
    body_lines: list[str] = []  # 准备列表装内容

    if total_letters == 0:  # 如果整篇文章连一个英文字母都没有
        body_lines.append("无有效英文字母。")
        return _build_section(title, body_lines)

    # 打印表头
    body_lines.append(_pad_display("字母", 8) + _pad_display("出现次数", 10) + "频率")
    
    for index, count in enumerate(letter_frequency):  # enumerate 可以同时获取索引(0-25)和对应的次数
        letter = chr(ord("a") + index)  # ord("a")拿到a的ASCII码，加上索引后再用chr转回字母
        frequency = count / total_letters  # 计算这个字母出现的频率百分比
        # 格式化组装这一行，频率保留2位小数( f"{frequency:.2f}" )
        body_lines.append(_pad_display(letter, 8) + _pad_display(count, 10) + f"{frequency:.2f}")

    body_lines.append(f"{_pad_display('总字母数：')}{total_letters}")  # 最后补上总字母数的统计
    return _build_section(title, body_lines)  # 调用通用方法打包返回


def build_longest_word_section(longest_word: str, longest_word_len: int) -> str:
    """构建最长单词段落。"""
    title = "最长单词统计"
    body_lines: list[str] = []

    if longest_word_len == 0:  # 如果最长单词长度是0，说明没遇到正常单词
        body_lines.append("无有效单词。")
        return _build_section(title, body_lines)

    # 正常组装出两行信息
    body_lines.append(f"{_pad_display('最长单词：')}{longest_word}")
    body_lines.append(f"{_pad_display('长度：')}{longest_word_len}")
    return _build_section(title, body_lines)


def build_notice_section(title: str, message: str) -> str:
    """构建单行的提示信息段落（比如报错提示）。"""
    return _build_section(title, [message])  # 直接把信息装进单元素列表，交给通用打包函数处理


def build_report_text(filename: str, analysis: AnalysisResult, extra_sections: list[str] | None = None) -> str:
    """构建完整格式化报告文本（把上面散装的段落全拼起来）。"""
    stats = analysis.stats  # 提取基础统计包
    summary_items = [  # 把要展示的基础信息整理成一个个 (标签名, 值) 的元组列表
        ("文件名：", filename),
        ("总字符数(含空格标点)：", str(stats.char_count)),
        ("总单词数：", str(stats.word_count)),
        ("总行数：", str(stats.line_count)),
        ("总句子数：", str(stats.sentence_count)),
        ("平均单词长度：", f"{stats.avg_word_length:.2f}"),  # 保留两位小数
    ]
    
    # 动态计算标签需要对齐的宽度，为了适应不同长度的标题，找所有标签里最长的那个，再加上1个空格缓冲
    summary_label_width = max(
        REPORT_LABEL_WIDTH,
        max(_display_width(label) for label, _ in summary_items),
    ) + 1

    lines = [  # 报告的最开头大标题
        "文本分析报告",
        "-" * REPORT_LINE_WIDTH,
    ]

    for label, value in summary_items:  # 循环把基础信息带上对齐塞进列表
        lines.append(_pad_display(label, summary_label_width) + value)

    lines.append("-" * REPORT_LINE_WIDTH)  # 画横线结束头部

    if stats.char_count == 0:  # 如果是空文件，给个明显提示
        lines.append("提示：检测到空文件，统计结果均为 0。")

    if stats.truncated_word_count > 0:  # 如果存在被强行截断的超长单词，在这里打出警告
        lines.append(
            f"警告：检测到 {stats.truncated_word_count} 个超过 {MAX_WORD_LEN} 字符的单词，已截断后统计。"
        )

    # 把我们上面写的生成各个分块段落的函数调用起来，把生成的结果存进列表里
    core_sections = [
        build_word_frequency_section(analysis.word_frequency),
        build_letter_frequency_section(analysis.letter_frequency, analysis.total_letters),
        build_longest_word_section(analysis.longest_word, analysis.longest_word_len),
    ]

    for section in core_sections:  # 遍历这些基础的核心分块
        lines.append("")  # 分块之间加个空行
        lines.extend(section.splitlines())  # 因为 section 是一整个带换行符的字符串，所以用 splitlines() 把它按行拆散后再加入列表

    if extra_sections:  # 如果外部传进来了额外的分块（比如 TF-IDF 的结果）
        for section in extra_sections:
            normalized = section.strip("\n")  # 去掉头尾多余的换行符
            if not normalized:  # 如果是空的就不管
                continue
            lines.append("")  # 加空行
            lines.extend(normalized.splitlines())  # 拆开加进去

    return "\n".join(lines) + "\n"  # 最终，把所有收集到的行拼成一个终极字符串，并在末尾留一个空行


def save_report(report_filename: str, report_text: str, display_path: str | None = None) -> None:
    """写入报告文件。display_path 用于控制台展示，不传则回退到完整路径。"""
    # 用 utf-8 编码、"w"(覆盖写入) 模式打开指定文件。with 会帮我们自动 close 文件。
    with open(report_filename, "w", encoding="utf-8") as out_fp:
        out_fp.write(report_text)  # 把大字符串直接怼进去

    # 优先用调用方传入的展示路径（通常是相对路径），让提示信息更简洁；没传则回退到完整绝对路径
    shown = display_path if display_path is not None else report_filename
    print(f"报告已保存：{shown}")


def get_base_dir() -> str:
    """获取程序基准目录：打包为可执行文件时取 exe 所在目录，普通脚本运行时取脚本所在目录。"""
    # sys.frozen 是 PyInstaller 打包后才会存在的特殊属性，用来区分"可执行文件模式"和"普通脚本模式"
    if getattr(sys, "frozen", False):  # 如果是打包后的可执行文件（比如 .exe 或 macOS app）
        return os.path.dirname(sys.executable)  # 返回 exe 文件自身所在的目录，而不是用户当前所在的目录
    return os.path.dirname(os.path.abspath(__file__))  # 普通脚本模式：取 .py 文件所在目录的绝对路径


def discover_txt_files(base_dir: str) -> list[str]:
    """从 base_dir 出发递归收集所有 .txt 文件的绝对路径，按路径字母顺序排序后返回。"""
    result: list[str] = []  # 用来存收集到的文件绝对路径，最终会按字母顺序排好
    for dirpath, dirs, filenames in os.walk(base_dir):  # os.walk 会递归遍历 base_dir 及其全部子目录
        dirs.sort()  # 原地排序子目录名，保证不同次运行时的遍历顺序完全一致（os.walk 默认顺序不稳定）
        for filename in sorted(filenames):  # 同一目录里的文件也按文件名字母顺序处理
            # 只收集 .txt 文件，并跳过程序自动生成的 _report.txt 报告文件，防止报告出现在候选列表里造成循环分析
            if filename.lower().endswith(".txt") and not filename.lower().endswith("_report.txt"):  # 大小写均可（如 .TXT 也算）
                result.append(os.path.join(dirpath, filename))  # 把"目录路径 + 文件名"拼成完整绝对路径加入列表
    return result  # 返回排好序的全部候选文件路径列表


def display_file_menu(candidates: list[str], base_dir: str, title: str = "请选择文件") -> None:
    """把候选文件列表以编号形式打印出来，显示相对路径方便区分同名文件。"""
    print(f"\n{title}")  # 先打印菜单标题，前面空一行让版面清爽一些
    print("-" * REPORT_LINE_WIDTH)  # 打印分隔线，宽度和报告正文保持一致
    for index, filepath in enumerate(candidates, start=1):  # 从编号 1 开始逐一列出候选文件
        rel_path = os.path.relpath(filepath, base_dir)  # 计算相对于程序目录的路径，避免打印出一大串绝对路径
        file_size = os.path.getsize(filepath)  # 获取文件大小（单位：字节）
        size_str = f"{file_size / 1024:.1f} KB" if file_size >= 1024 else f"{file_size} B"  # 超过 1 KB 才换算，否则直接显示字节数
        print(f"  [{index}] {rel_path}  ({size_str})")  # 打印"编号 + 路径 + 文件大小"一行候选项
    print("-" * REPORT_LINE_WIDTH)  # 菜单底部再打印一条分隔线


def prompt_user_choice(
    candidates: list[str],
    base_dir: str,
    title: str = "请选择文件",
    exclude_path: str | None = None,
) -> str | None:
    """展示候选文件菜单，循环读取用户输入直到拿到有效选择或用户主动退出。
    exclude_path：需排除的文件路径（用于 TF-IDF 选对比文件时禁止选主文件）。
    返回选中的文件绝对路径；用户输入 q 则返回 None 表示跳过。"""
    if exclude_path is not None:  # 如果传入了需要排除的路径（比如已选的主文件）
        # 用 os.path.abspath 统一转成绝对路径再比较，防止"./a.txt"和"a.txt"被误判为不同文件
        filtered = [p for p in candidates if os.path.abspath(p) != os.path.abspath(exclude_path)]
        if not filtered:  # 排除后列表变空了，说明没有其他文件可选
            print("提示：没有其他可用的 .txt 文件可供对比。")
            return None
    else:
        filtered = candidates  # 没有排除需求，直接用完整候选列表

    display_file_menu(filtered, base_dir, title)  # 把过滤后的候选列表打印成带编号的菜单

    while True:  # 持续循环，直到收到合法输入或用户主动退出
        try:
            raw = input("请输入序号（输入 q 跳过/退出）：").strip()  # 读取用户输入，去除首尾多余空格
        except (EOFError, KeyboardInterrupt):  # 用户按 Ctrl+D（EOF）或 Ctrl+C（中断）时优雅退出
            print("\n已退出。")
            return None

        if raw.lower() == "q":  # 用户主动输入 q 表示跳过或退出
            return None

        if raw.isdigit():  # 只有纯数字才进入编号验证，过滤掉字母、符号等非法输入
            index = int(raw)
            if 1 <= index <= len(filtered):  # 编号必须在 1 到列表长度的有效范围内
                return filtered[index - 1]  # 列表下标从 0 开始，所以编号要减 1

        print(f"输入无效，请输入 1 到 {len(filtered)} 之间的数字，或输入 q 跳过。")  # 输入不合法，提示后继续循环


def main() -> None:
    """程序入口：程序的真正起点，负责调度上面的各种功能模块，组织成一个完整的流水线。"""
    # 第零步：确定程序基准目录。后续的文件扫描和报告保存都以此为基础，不再依赖外部的"当前工作目录"
    base_dir = get_base_dir()  # 获取程序自身（.py 脚本或打包后的 exe）所在的目录
    print(f"扫描目录：{base_dir}")  # 告知用户当前扫描的是哪个目录，方便排查"找不到文件"之类的问题

    # 第一步：递归扫描基准目录下所有 .txt 文件，组成候选列表供后续选择
    candidates = discover_txt_files(base_dir)  # 递归发现所有 .txt 文件，按路径字母顺序排好
    if not candidates:  # 如果整个目录树里一个 .txt 文件都没有，直接报错退出
        print("错误：当前目录下未找到任何 .txt 文件，程序退出。")
        return

    # 第二步：让用户从候选列表中选择要分析的主文件
    if len(candidates) == 1:  # 只有一个候选文件时，不用弹菜单，直接自动选中
        filename = candidates[0]
        print(f"\n检测到唯一 .txt 文件，已自动选中：{os.path.relpath(filename, base_dir)}")
    else:  # 有多个候选文件，显示带编号的菜单让用户手动选择
        filename = prompt_user_choice(candidates, base_dir, title="选择要分析的主文件")
        if filename is None:  # 用户输入了 q 表示不想继续，退出程序
            print("已退出程序。")
            return

    # 第三步：对选中的主文件执行核心文本分析，得到各项统计数据
    try:
        analysis = analyze_file(filename)  # 调用单文件分析功能，拿到包含各种统计数据的结果包
    except FileNotFoundError:  # 文件不存在（理论上不会发生，因为是从真实扫描结果里选的）
        print(_format_io_error("读取", filename))
        return
    except (PermissionError, UnicodeDecodeError, OSError) as exc:  # 没有读取权限、编码不对或其他系统级错误
        print(_format_io_error("读取", filename, exc))
        return

    # 第四步：询问用户是否需要进行 TF-IDF 文本相似度对比（可选的增强分析模块）
    extra_sections = []  # 准备一个空列表，用来装 TF-IDF 这类附加的报告段落
    try:
        tfidf_choice = input("\n是否需要进行 TF-IDF 文本相似度对比分析？(y/n)：").strip().lower()
    except (EOFError, KeyboardInterrupt):  # 非交互环境（管道输入）或用户中断时，默认跳过 TF-IDF 模块
        tfidf_choice = "n"

    if tfidf_choice == "y":  # 用户选择进行对比分析
        if len(candidates) < 2:  # 整个目录树里只有 1 个 .txt 文件，根本没有第二个文件可以用来对比
            print("提示：当前目录下只有一个 .txt 文件，无法进行对比，已跳过 TF-IDF 模块。")
        else:
            compare_filename = prompt_user_choice(  # 再弹一次菜单，让用户选择对比文件
                candidates,
                base_dir,
                title="选择用于 TF-IDF 对比的文件（不能与主文件相同）",
                exclude_path=filename,  # 把已选的主文件排除出候选，避免"自己和自己对比"
            )
            if compare_filename is not None:  # 用户选了对比文件（没有输入 q 跳过）
                try:
                    tfidf_section = analyze_tfidf(
                        filename,
                        compare_filename,
                        top_k=KEYWORD_TOP_K,
                        doc_a_word_frequency=analysis.word_frequency,  # 复用主文件已算好的词频，避免重复扫描文件
                    )
                    extra_sections.append(tfidf_section)  # 把生成的 TF-IDF 报告段落塞进附加列表
                except (PermissionError, UnicodeDecodeError, OSError, ValueError) as exc:  # 对比模块出错，不退出程序，在报告里加一条提示即可
                    extra_sections.append(
                        build_notice_section("TF-IDF 模块提示", f"TF-IDF 分析失败：{exc}，已跳过该模块。")
                    )

    # 第五步：排版生成完整报告文本，把统计数据和所有附加段落拼成一份可读性强的长文本
    display_name = os.path.relpath(filename, base_dir)  # 把绝对路径转成相对路径，让报告里的文件名字段更简洁易读
    report_text = build_report_text(display_name, analysis, extra_sections=extra_sections)
    print(report_text, end="")  # 把报告打印到终端供即时查看（end="" 防止末尾多出一个多余的空行）

    # 第六步：把报告保存到与主文件相同的目录下，文件名格式为"原文件名_report.txt"
    input_stem = os.path.splitext(os.path.basename(filename))[0]  # 取主文件的文件名，去掉 .txt 扩展名部分
    report_filename = os.path.join(os.path.dirname(filename), f"{input_stem}_report.txt")  # 拼出报告文件的完整保存路径
    try:
        # 传入相对路径作为展示名，让终端提示信息与报告头中的文件名风格保持一致
        save_report(report_filename, report_text, display_path=os.path.relpath(report_filename, base_dir))
    except (PermissionError, OSError) as exc:  # 如果目录没有写入权限或者磁盘满了之类的情况
        print(_format_io_error("保存", report_filename, exc))  # 提示用户文件算完了但没能存下来

if __name__ == "__main__":  # 这是 Python 语言经典的约定俗成写法
    # 意思是：只有当你直接运行这个 python 脚本文件时，才会触发里面的 main() 函数。
    # 如果这个脚本是被其他人的代码使用 `import main` 导入去当工具库用的，这里的 main() 就不会自动运行。
    main()
