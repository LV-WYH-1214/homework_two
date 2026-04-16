def main():
    filename = "text_test.txt"
    chars = 0      # 字符总数
    words = 0      # 单词总数
    lines = 0      # 行数
    in_word = False # 标记是否在单词中
    last_char = ""  # 记录最后一个字符，用于处理末行无换行符场景

    try:
        # Mac 上推荐显式指定 encoding='utf-8'
        with open(filename, 'r', encoding='utf-8') as fp:
            # 分块读取，避免大文件一次性读入内存
            while True:
                chunk = fp.read(8192)
                if not chunk:
                    break

                for ch in chunk:
                    last_char = ch
                    chars += 1        # 统计每个字符

                    if ch == '\n':
                        lines += 1    # 遇到换行符，行数加1

                    # 判断是否为字母（在 Python 中 isalpha() 对英文字母同样生效）
                    if ch.isalpha():
                        if not in_word:   # 之前不在单词中，现在进入单词
                            in_word = True
                            words += 1    # 新单词开始，单词数加1
                    else:
                        in_word = False   # 非字母字符，表示单词结束

    except FileNotFoundError:
        print(f"错误：无法打开文件 {filename}")
        return

    # 处理最后一行没有换行符的情况（包括单行与多行）
    if chars > 0 and last_char != '\n':
        lines += 1

    # 输出统计结果
    print(f"文件 {filename} 统计结果：")
    print(f"字符数：{chars}")
    print(f"单词数：{words}")
    print(f"行数：{lines}")

if __name__ == "__main__":
    main()